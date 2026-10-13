"""Bake source humanoid motion onto a target humanoid skeleton.

Rest rotation swings each target bone so the limb points the same way as
the source, measured from one mapped joint to the next in the character's
left/up/forward frame. Twist around that limb stays on the target bind, so a
different bone roll does not spin the skinned mesh. Current-pose reference
keeps the captured target pose and adds only the change since that pose. Hip
translation is scaled by the
hips-to-head height ratio and can drop horizontal travel. Optional hand and
foot IK runs after the FK pose.
"""

from __future__ import annotations

import bpy
from math import pi
from mathutils import Matrix, Quaternion, Vector

from .classify import CORE_ROLES, classify_armature, correct_chest_pairs, correct_deform_pairs, describe_roles, rig_height
from .ik import apply_contact_ik
from .mapping import build_pairs


class RetargetError(RuntimeError):
    pass


class RetargetOptions:
    """Bake settings. Defaults keep the original rest-pose FK transfer."""

    def __init__(
        self,
        pairs=None,
        reference="REST",
        reference_data=None,
        root_motion="KEEP",
        foot_ik=False,
        hand_ik=False,
        standard_skeleton="DIRECT",
    ):
        self.pairs = pairs
        self.reference = reference if reference in {"REST", "CURRENT"} else "REST"
        self.reference_data = reference_data
        self.root_motion = root_motion if root_motion in {"KEEP", "IN_PLACE"} else "KEEP"
        self.foot_ik = bool(foot_ik)
        self.hand_ik = bool(hand_ik)
        if standard_skeleton not in {"DIRECT", "RIGIFY_HUMAN_METARIG"}:
            raise RetargetError("未知的标准人形骨架: " + str(standard_skeleton))
        self.standard_skeleton = standard_skeleton
        self.resolved_pairs = None


ACTION_SEP = "\n"


def collect_actions(arm_obj: bpy.types.Object):
    actions = []
    stored = arm_obj.get("hr_actions")
    if stored:
        for name in str(stored).split(ACTION_SEP):
            action = bpy.data.actions.get(name)
            if action is not None and action not in actions:
                actions.append(action)
    anim = arm_obj.animation_data
    if anim and anim.action and anim.action not in actions:
        actions.insert(0, anim.action)
    if anim:
        for track in anim.nla_tracks:
            for strip in track.strips:
                if strip.action and strip.action not in actions:
                    actions.append(strip.action)
    return [action for action in actions if not action.is_empty] if actions else []


def _assign_action(obj, action):
    anim = obj.animation_data or obj.animation_data_create()
    anim.action = action
    if not getattr(action, "slots", None):
        return
    chosen = None
    for slot in action.slots:
        label = getattr(slot, "name_display", None) or slot.name
        if obj.name == label or obj.name in str(label):
            chosen = slot
            break
    if chosen is None and len(action.slots):
        chosen = action.slots[0]
    if chosen is not None:
        anim.action_slot = chosen


def _new_target_action(target, name):
    action = bpy.data.actions.new(name)
    action.use_fake_user = True
    slot = None
    try:
        slot = action.slots.new(id_type="OBJECT", name=target.name)
    except TypeError:
        slot = action.slots.new("OBJECT", target.name)
    anim = target.animation_data or target.animation_data_create()
    anim.action = action
    if slot is not None:
        anim.action_slot = slot
    return action


def _basis_matrix(pose_bone):
    return pose_bone.matrix_basis.to_quaternion().to_matrix().to_4x4()


_BODY_ROLE_ORDER = (
    "hips",
    "spine",
    "chest",
    "neck",
    "head",
    "shoulder_l",
    "upperarm_l",
    "forearm_l",
    "hand_l",
    "shoulder_r",
    "upperarm_r",
    "forearm_r",
    "hand_r",
    "thigh_l",
    "shin_l",
    "foot_l",
    "toe_l",
    "thigh_r",
    "shin_r",
    "foot_r",
    "toe_r",
)


def _rot3(matrix):
    return matrix.to_3x3().to_quaternion().to_matrix()


def _body_matrix(arm, roles):
    """Armature-space basis whose columns are the character's left, up and forward."""
    hips_name = roles.get("hips")
    head_name = roles.get("head") or roles.get("neck") or roles.get("spine")
    if not hips_name or not head_name:
        return Matrix.Identity(3)
    if hips_name not in arm.data.bones or head_name not in arm.data.bones:
        return Matrix.Identity(3)
    up = arm.data.bones[head_name].head_local - arm.data.bones[hips_name].head_local
    if up.length < 1e-6:
        up = Vector((0.0, 0.0, 1.0))
    up.normalize()
    if "upperarm_l" in roles and "upperarm_r" in roles:
        left = arm.data.bones[roles["upperarm_l"]].head_local - arm.data.bones[roles["upperarm_r"]].head_local
    else:
        left = Vector((1.0, 0.0, 0.0))
    left = left - up * left.dot(up)
    if left.length < 1e-6:
        left = Vector((1.0, 0.0, 0.0))
    else:
        left.normalize()
    forward = left.cross(up)
    if forward.length < 1e-6:
        forward = Vector((0.0, -1.0, 0.0))
    else:
        forward.normalize()
    left = up.cross(forward).normalized()
    return Matrix((
        (left.x, up.x, forward.x),
        (left.y, up.y, forward.y),
        (left.z, up.z, forward.z),
    ))


def _desired_orientation(source_pose, source_ref, target_ref, source_body, target_body, absolute):
    current = _rot3(source_pose)
    if absolute:
        return target_body @ source_body.inverted() @ current
    change = source_body.inverted() @ current @ _rot3(source_ref).inverted() @ source_body
    return target_body @ change @ target_body.inverted() @ _rot3(target_ref)


_CHAIN_CHILD = {
    "hips": "spine",
    "spine": "chest",
    "chest": "neck",
    "neck": "head",
    "shoulder_l": "upperarm_l",
    "upperarm_l": "forearm_l",
    "forearm_l": "hand_l",
    "shoulder_r": "upperarm_r",
    "upperarm_r": "forearm_r",
    "forearm_r": "hand_r",
    "thigh_l": "shin_l",
    "shin_l": "foot_l",
    "foot_l": "toe_l",
    "thigh_r": "shin_r",
    "shin_r": "foot_r",
    "foot_r": "toe_r",
}


def _chain_end(arm, roles, role):
    """Next joint. A child that hangs off a different mapped bone is a swapped map."""
    bone_name = roles.get(role)
    if not bone_name or bone_name not in arm.data.bones:
        return None
    child_role = _CHAIN_CHILD.get(role)
    mapped = set(roles.values())
    if child_role and child_role in roles:
        child_name = roles[child_role]
        parent = arm.data.bones[child_name].parent if child_name in arm.data.bones else None
        foreign = parent is not None and parent.name in mapped and parent.name != bone_name
        if not foreign:
            return child_name
    children = [child.name for child in arm.data.bones[bone_name].children if child.name in mapped]
    if len(children) == 1:
        return children[0]
    return None


def _chain_vector(arm, roles, role, posed):
    """Vector from this mapped joint to the next one. Bone Y is not the chain."""
    end_name = _chain_end(arm, roles, role)
    if not end_name:
        return None
    if posed:
        start = arm.pose.bones[roles[role]].head
        end = arm.pose.bones[end_name].head
    else:
        start = arm.data.bones[roles[role]].head_local
        end = arm.data.bones[end_name].head_local
    vector = end - start
    if vector.length < 1e-6:
        return None
    return vector


def _anatomical_roles(arm, fallback):
    """Body axes follow the real left arm, even if a mapping swaps left and right."""
    found = classify_armature(arm)
    needed = ("upperarm_l", "upperarm_r", "hips", "head")
    if all(key in found and found[key] in arm.data.bones for key in needed):
        return found
    return fallback


def _apply_body_orientations(src, tgt, pairs, options):
    """Point each target limb at the source limb without taking the source roll.

    matrix_basis is parent-relative, so a spine parented to a root rotator would
    otherwise miss that rotation when the target spine hangs off the pelvis.
    Rest mode swings the bind orientation onto the source chain direction.
    Current mode adds only the orientation change since the captured pose.
    """
    src_roles = {role: source_name for role, source_name, _target_name in pairs}
    tgt_roles = {role: target_name for role, _source_name, target_name in pairs}
    source_body = _body_matrix(src, _anatomical_roles(src, src_roles))
    target_body = _body_matrix(tgt, _anatomical_roles(tgt, tgt_roles))
    absolute = options.reference != "CURRENT"
    data = options.reference_data or {}
    for _role, _source_name, target_name in pairs:
        pose_bone = tgt.pose.bones[target_name]
        pose_bone.rotation_mode = "QUATERNION"
        pose_bone.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
        pose_bone.location = (0.0, 0.0, 0.0)
    bpy.context.view_layer.update()

    order = {role: index for index, role in enumerate(_BODY_ROLE_ORDER)}

    def _depth(bone_name):
        bone = tgt.data.bones.get(bone_name)
        depth = 0
        seen = set()
        while bone is not None and bone.name not in seen and bone.parent is not None:
            seen.add(bone.name)
            depth += 1
            bone = bone.parent
        return depth

    for role, source_name, target_name in sorted(pairs, key=lambda pair: (_depth(pair[2]), order.get(pair[0], 100))):
        pose_bone = tgt.pose.bones[target_name]
        if absolute:
            src_chain = _chain_vector(src, src_roles, role, True)
            tgt_chain = _chain_vector(tgt, tgt_roles, role, False)
            if src_chain is None or tgt_chain is None:
                continue
            desired = target_body @ (source_body.inverted() @ src_chain).normalized()
            rest_orient = pose_bone.bone.matrix_local.to_3x3()
            swing = tgt_chain.normalized().rotation_difference(desired.normalized())
            orient = swing.to_matrix() @ rest_orient
            if role == "hips":
                source_rest = _rot3(src.data.bones[source_name].matrix_local)
                source_delta = _rot3(src.pose.bones[source_name].matrix) @ source_rest.inverted()
                source_rotation = source_delta.to_quaternion().normalized()
                if source_rotation.w < 0.0:
                    source_rotation.negate()
                chain_frame = Vector((0.0, 1.0, 0.0)).rotation_difference(src_chain.normalized())
                chain_rotation = chain_frame.inverted() @ source_rotation @ chain_frame
                hips_twist = chain_rotation.to_swing_twist("Y")[1]
                hips_twist = (hips_twist + pi) % (2.0 * pi) - pi
                orient = Quaternion(desired.normalized(), hips_twist).to_matrix() @ orient
        else:
            source_ref = _stored_matrix(data.get("source_matrix"), source_name, src.data.bones[source_name].matrix_local)
            target_ref = _stored_matrix(data.get("target_matrix"), target_name, tgt.data.bones[target_name].matrix_local)
            orient = _desired_orientation(
                src.pose.bones[source_name].matrix,
                source_ref,
                target_ref,
                source_body,
                target_body,
                False,
            )
        rest = _rot3(pose_bone.bone.matrix_local)
        parent = pose_bone.parent
        if parent:
            basis = rest.inverted() @ _rot3(parent.bone.matrix_local) @ _rot3(parent.matrix).inverted() @ orient
        else:
            basis = rest.inverted() @ orient
        pose_bone.rotation_quaternion = basis.to_quaternion()
        bpy.context.view_layer.update()


def _rotation_onto(src_pose, tgt_pose, src_bone, tgt_bone, src_ref_basis, tgt_ref_basis):
    align = src_bone.matrix_local.to_3x3().inverted() @ tgt_bone.matrix_local.to_3x3()
    current = src_pose.matrix_basis.to_quaternion().to_matrix()
    delta = src_ref_basis.to_3x3().inverted() @ current
    corrected = align.inverted() @ delta @ align
    result = tgt_ref_basis.to_3x3() @ corrected
    tgt_pose.rotation_mode = "QUATERNION"
    tgt_pose.rotation_quaternion = result.to_quaternion()
    tgt_pose.location = (0.0, 0.0, 0.0)


def _hips_translation(src, tgt, src_name, tgt_name, scale, src_ref_head, tgt_ref_head, in_place):
    src_pose = src.pose.bones[src_name]
    tgt_pose = tgt.pose.bones[tgt_name]
    delta = src_pose.head - src_ref_head
    world_delta = src.matrix_world.to_3x3() @ delta
    if in_place:
        world_delta = Vector((0.0, 0.0, world_delta.z))
    target_delta = tgt.matrix_world.to_3x3().inverted() @ (world_delta * scale)
    matrix = tgt_pose.matrix.copy()
    matrix.translation = tgt_ref_head + target_delta
    tgt_pose.matrix = matrix


def capture_reference(src, tgt, pairs):
    """Snapshot both current poses. The pose itself is left unchanged."""
    source_matrix = {}
    target_matrix = {}
    source_basis = {}
    target_basis = {}
    for _role, source_name, target_name in pairs:
        if source_name in src.pose.bones:
            pose = src.pose.bones[source_name]
            source_matrix[source_name] = [list(row) for row in pose.matrix]
            source_basis[source_name] = [list(row) for row in _basis_matrix(pose)]
        if target_name in tgt.pose.bones:
            pose = tgt.pose.bones[target_name]
            target_matrix[target_name] = [list(row) for row in pose.matrix]
            target_basis[target_name] = [list(row) for row in _basis_matrix(pose)]
    return {
        "source_matrix": source_matrix,
        "target_matrix": target_matrix,
        "source_basis": source_basis,
        "target_basis": target_basis,
    }


def _stored_matrix(table, bone_name, fallback):
    raw = table.get(bone_name) if table else None
    if not raw:
        return fallback
    return Matrix(raw)


def _reference_for(src, tgt, source_name, target_name, options):
    src_bone = src.data.bones[source_name]
    tgt_bone = tgt.data.bones[target_name]
    src_rest = src_bone.matrix_local.copy()
    tgt_rest = tgt_bone.matrix_local.copy()
    identity = Matrix.Identity(4)
    if options.reference != "CURRENT":
        return identity, identity, src_bone.head_local.copy(), tgt_bone.head_local.copy()
    data = options.reference_data or {}
    if source_name not in data.get("source_basis", {}) or target_name not in data.get("target_basis", {}):
        raise RetargetError("当前姿势参考不完整，请重新捕获参考姿势")
    src_basis = _stored_matrix(data.get("source_basis"), source_name, identity)
    tgt_basis = _stored_matrix(data.get("target_basis"), target_name, identity)
    src_head = _stored_matrix(data.get("source_matrix"), source_name, src_rest).to_translation()
    tgt_head = _stored_matrix(data.get("target_matrix"), target_name, tgt_rest).to_translation()
    return src_basis, tgt_basis, src_head, tgt_head


def _pairs_from_options(src, tgt, options):
    if options.pairs:
        pairs = []
        for role, source_name, target_name in options.pairs:
            if source_name not in src.data.bones or target_name not in tgt.data.bones:
                raise RetargetError(f"映射里的骨骼不存在: {role} {source_name} -> {target_name}")
            pairs.append((role, source_name, target_name))
    else:
        pairs = build_pairs(src, tgt)
    roles = {role for role, _source_name, _target_name in pairs}
    missing = [role for role in CORE_ROLES if role not in roles]
    if missing:
        raise RetargetError("这些主骨没有同时映射到: " + ", ".join(missing))
    if not pairs:
        raise RetargetError("两侧没有可对应的骨骼")
    return pairs


def _stash_nla(target, actions):
    """Keep every baked clip on its own NLA strip without double-playing it."""
    anim = target.animation_data
    if anim is None:
        return
    while len(anim.nla_tracks):
        anim.nla_tracks.remove(anim.nla_tracks[0])
    for action in actions:
        track = anim.nla_tracks.new()
        track.name = action.name
        start = int(action.frame_range[0])
        strip = track.strips.new(action.name[:60], start, action)
        if action.slots:
            try:
                strip.action_slot = action.slots[0]
            except Exception as exc:
                print("[HumanoidRetarget] nla slot:", exc)
    anim.use_nla = False


def _frame_range(action):
    start, end = action.frame_range
    start_i = int(start)
    end_i = int(round(end))
    if end_i < start_i:
        end_i = start_i
    return start_i, end_i


def preview_action(arm_obj, action, scene, jump=True):
    """Show one source clip in the viewport and on the timeline."""
    if arm_obj is None or arm_obj.type != "ARMATURE":
        raise RetargetError("请先指定动画来源。")
    if action is None:
        raise RetargetError("来源上没有可播放的动画。")
    _assign_action(arm_obj, action)
    if arm_obj.animation_data:
        arm_obj.animation_data.use_nla = False
    start, end = _frame_range(action)
    scene.frame_start = start
    scene.frame_end = end
    if jump or scene.frame_current < start or scene.frame_current > end:
        scene.frame_set(start)
    return start, end


def bake_retarget(src, tgt, options=None):
    if src is None or src.type != "ARMATURE":
        raise RetargetError("请先导入带骨架和动画的来源模型。")
    if tgt is None or tgt.type != "ARMATURE":
        raise RetargetError("目标不是骨架。没有骨架的网格会先自动绑定。")
    if src == tgt:
        raise RetargetError("来源和目标是同一个骨架。")

    source_anim = src.animation_data
    source_action = source_anim.action if source_anim else None
    source_slot = getattr(source_anim, "action_slot", None) if source_anim else None

    options = options or RetargetOptions()
    if options.reference == "CURRENT" and not options.reference_data:
        raise RetargetError("已选择当前姿势作为零点，但还没有捕获参考姿势")
    pairs = correct_deform_pairs(src, tgt, correct_chest_pairs(src, tgt, _pairs_from_options(src, tgt, options)))
    options.resolved_pairs = pairs
    src_roles = {role: name for role, name, _target_name in pairs}
    tgt_roles = {role: name for role, _source_name, name in pairs}

    actions = collect_actions(src)
    if not actions:
        raise RetargetError("来源骨架上没有可烘焙的动画。")

    src_height = rig_height(src, src_roles)
    scale = rig_height(tgt, tgt_roles) / src_height if src_height > 1e-6 else 1.0
    scale = min(max(scale, 0.01), 100.0)
    in_place = options.root_motion == "IN_PLACE"

    if tgt.animation_data:
        tgt.animation_data_clear()

    scene = bpy.context.scene
    baked = []
    baked_sources = []
    original_frame = scene.frame_current
    try:
        for action in actions:
            _assign_action(src, action)
            if action == source_action and source_slot is not None:
                src.animation_data.action_slot = source_slot
            start, end = _frame_range(action)
            target_action = _new_target_action(tgt, f"{tgt.name}_{action.name}")
            for frame in range(start, end + 1):
                scene.frame_set(frame)
                bpy.context.view_layer.update()
                references = {}
                for _role, src_name, tgt_name in pairs:
                    _src_basis, _tgt_basis, src_head, tgt_head = _reference_for(
                        src, tgt, src_name, tgt_name, options
                    )
                    references[tgt_name] = (src_head, tgt_head)
                _apply_body_orientations(src, tgt, pairs, options)
                bpy.context.view_layer.update()
                hip_role = next(pair for pair in pairs if pair[0] == "hips")
                src_head, tgt_head = references[hip_role[2]]
                _hips_translation(src, tgt, hip_role[1], hip_role[2], scale, src_head, tgt_head, in_place)
                bpy.context.view_layer.update()
                apply_contact_ik(src, tgt, pairs, scale, options.foot_ik, options.hand_ik)
                bpy.context.view_layer.update()
                for _role, _src_name, tgt_name in pairs:
                    pose_bone = tgt.pose.bones[tgt_name]
                    pose_bone.keyframe_insert(data_path="rotation_quaternion", frame=frame)
                    pose_bone.keyframe_insert(data_path="location", frame=frame)
            target_action.use_fake_user = True
            baked.append((target_action, start, end))
            baked_sources.append(action)
    finally:
        scene.frame_set(original_frame)

    if baked:
        selected_index = next(
            (index for index, action in enumerate(baked_sources) if action == source_action),
            0,
        )
        selected_source = baked_sources[selected_index]
        selected_target, start, end = baked[selected_index]
        _assign_action(src, selected_source)
        if selected_source == source_action and source_slot is not None:
            src.animation_data.action_slot = source_slot
        src.animation_data.use_nla = False
        _stash_nla(tgt, [
            action for index, (action, _start, _end) in enumerate(baked)
            if index != selected_index
        ])
        _assign_action(tgt, selected_target)
        scene.frame_start = start
        scene.frame_end = end
        scene.frame_set(start)

    tgt["hr_retarget_from"] = src.name
    tgt["hr_actions"] = ACTION_SEP.join(action.name for action, _start, _end in baked)
    root_label = "原地" if in_place else "保留位移"
    ik_parts = []
    if options.foot_ik:
        ik_parts.append("脚")
    if options.hand_ik:
        ik_parts.append("手")
    lines = [
        describe_roles(tgt_roles),
        f"对应 {len(pairs)} 根骨骼，身高比例 {scale:.3f}",
        f"根运动: {root_label}，参考姿势: {'当前姿势' if options.reference == 'CURRENT' else 'Rest'}",
        f"IK: {'、'.join(ik_parts) if ik_parts else '关闭'}",
        f"烘焙 {len(baked)} 个动作: " + ", ".join(action.name for action, _s, _e in baked),
        "动画已经写在目标骨架上，隐藏来源后仍可播放。",
    ]
    return "\n".join(lines), [action for action, _s, _e in baked]
