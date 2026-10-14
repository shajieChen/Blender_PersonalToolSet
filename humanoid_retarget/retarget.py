"""Bake source humanoid motion onto a target humanoid skeleton.

Rest rotation swings each target bone so the limb points the same way as
the source, measured from one mapped joint to the next in the character's
left/up/forward frame. Limb twist stays on the target bind. Hips, spine, chest
and neck also take the source twist about that chain. The head has no outgoing
chain, so its rest-relative rotation is transferred in the body frame. Current-pose reference
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
from .foot_ik import (
    FootIKSettings,
    LimbPlantState,
    LimbReference,
    PelvisReference,
    RetargetGeometry,
    geometric_foot_speeds,
    retarget_pelvis_position,
    validate_foot_ik_settings,
)
from .ik import apply_contact_ik
from .motion_space import MotionSpaceError, build_motion_space, validate_motion_space
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
        foot_ik_settings=None,
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
        if foot_ik_settings is None:
            foot_ik_settings = FootIKSettings()
        if not isinstance(foot_ik_settings, FootIKSettings):
            raise RetargetError("foot_ik_settings 必须是 FootIKSettings")
        try:
            validate_foot_ik_settings(foot_ik_settings)
        except ValueError as exc:
            raise RetargetError(str(exc))
        self.foot_ik_settings = FootIKSettings(**{
            field: getattr(foot_ik_settings, field) for field in foot_ik_settings.__dataclass_fields__
        })
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


_TORSO_TWIST_ROLES = frozenset({"hips", "spine", "chest", "neck"})


def _twist_about_chain(src, source_name, src_chain, desired, orient):
    """Add the source rest-relative twist about the posed chain. Bind stays on the right."""
    source_rest = _rot3(src.data.bones[source_name].matrix_local)
    source_delta = _rot3(src.pose.bones[source_name].matrix) @ source_rest.inverted()
    source_rotation = source_delta.to_quaternion().normalized()
    if source_rotation.w < 0.0:
        source_rotation.negate()
    chain_frame = Vector((0.0, 1.0, 0.0)).rotation_difference(src_chain.normalized())
    chain_rotation = chain_frame.inverted() @ source_rotation @ chain_frame
    twist = chain_rotation.to_swing_twist("Y")[1]
    twist = (twist + pi) % (2.0 * pi) - pi
    return Quaternion(desired.normalized(), twist).to_matrix() @ orient


def _head_orient(src, pose_bone, source_name, source_body, target_body):
    """Map the head's rest-relative rotation through the body frame onto the target rest."""
    source_rest = _rot3(src.data.bones[source_name].matrix_local)
    source_delta = _rot3(src.pose.bones[source_name].matrix) @ source_rest.inverted()
    change = source_body.inverted() @ source_delta @ source_body
    target_rest = _rot3(pose_bone.bone.matrix_local)
    return target_body @ change @ target_body.inverted() @ target_rest


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
            if role == "head" and (src_chain is None or tgt_chain is None):
                orient = _head_orient(src, pose_bone, source_name, source_body, target_body)
            elif src_chain is None or tgt_chain is None:
                continue
            else:
                desired = target_body @ (source_body.inverted() @ src_chain).normalized()
                rest_orient = pose_bone.bone.matrix_local.to_3x3()
                swing = tgt_chain.normalized().rotation_difference(desired.normalized())
                orient = swing.to_matrix() @ rest_orient
                if role in _TORSO_TWIST_ROLES:
                    orient = _twist_about_chain(src, source_name, src_chain, desired, orient)
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


def target_action_for_source_clip(source, target, source_action):
    """Return the baked target clip that matches one source clip.

    A direct bake is named ``{target}_{clip}``. The Rigify hop names the
    final clip ``{target}_{metarig}_{clip}``. Both end in the source clip
    name, and ``hr_actions`` stays in the same order as the source clips.
    """
    if source is None or target is None or source_action is None or source == target:
        return None
    stored = target.get("hr_actions")
    if not stored:
        return None
    names = [name for name in str(stored).split(ACTION_SEP) if name]
    source_actions = collect_actions(source)
    clip_names = [action.name for action in source_actions]

    def exact_tail(action_name, clip_name):
        if not action_name.endswith("_" + clip_name):
            return False
        for other in clip_names:
            if len(other) > len(clip_name) and action_name.endswith("_" + other):
                return False
        return True

    matches = [name for name in names if exact_tail(name, source_action.name)]
    if len(matches) == 1:
        return bpy.data.actions.get(matches[0])
    direct = f"{target.name}_{source_action.name}"
    if direct in matches:
        return bpy.data.actions.get(direct)
    try:
        index = source_actions.index(source_action)
    except ValueError:
        index = next(
            (i for i, action in enumerate(source_actions) if action.name == source_action.name),
            None,
        )
    if index is not None and index < len(names):
        return bpy.data.actions.get(names[index])
    if matches:
        return bpy.data.actions.get(matches[0])
    return None


def preview_source_and_target(source, target, action, scene, jump=True):
    """Show one source clip, and the matching baked clip on the target."""
    preview_action(source, action, scene, jump=jump)
    baked = target_action_for_source_clip(source, target, action)
    if baked is None:
        return
    _assign_action(target, baked)
    if target.animation_data:
        target.animation_data.use_nla = False


_IK_CHAIN_ROLES = (
    ("thigh_l", "shin_l", "foot_l"),
    ("thigh_r", "shin_r", "foot_r"),
    ("upperarm_l", "forearm_l", "hand_l"),
    ("upperarm_r", "forearm_r", "hand_r"),
)


def _prepare_retarget_geometry(src, tgt, pairs, options, scene):
    src_roles = {role: name for role, name, _t in pairs}
    tgt_roles = {role: name for role, _s, name in pairs}
    if "hips" not in src_roles or "hips" not in tgt_roles:
        raise RetargetError("重定向需要 hips 映射。")

    seen = set()
    for _role, src_name, tgt_name in pairs:
        if src_name in seen or tgt_name in seen:
            raise RetargetError("映射中存在重复骨骼，无法准备 IK 几何。")
        seen.add(src_name)
        seen.add(tgt_name)

    meters_per_unit = scene.unit_settings.scale_length or 1.0
    settings = options.foot_ik_settings
    source_body = _body_matrix(src, _anatomical_roles(src, src_roles))
    target_body = _body_matrix(tgt, _anatomical_roles(tgt, tgt_roles))
    try:
        source_space = build_motion_space(src, source_body, meters_per_unit, settings.floor_height_m)
        target_space = build_motion_space(tgt, target_body, meters_per_unit, settings.floor_height_m)
    except MotionSpaceError as exc:
        raise RetargetError(f"脚 IK 空间构建失败: {exc}")

    def reference_matrices(arm, roles, names):
        matrices = {}
        for name in names:
            pose = arm.pose.bones.get(name)
            if pose is None:
                continue
            if options.reference == "CURRENT" and options.reference_data:
                table = options.reference_data.get(
                    "source_matrix" if arm == src else "target_matrix"
                )
                raw = table.get(name) if table else None
                if raw:
                    matrices[name] = Matrix(raw)
                    continue
                raise RetargetError(f"当前姿势参考缺少 {name} 的矩阵，请重新捕获参考。")
            matrices[name] = arm.data.bones[name].matrix_local.copy()
        return matrices

    src_hips_name = src_roles["hips"]
    tgt_hips_name = tgt_roles["hips"]
    hips_matrices = reference_matrices(src, src_roles, [src_hips_name])
    tgt_hips_matrices = reference_matrices(tgt, tgt_roles, [tgt_hips_name])

    def head_world(arm, matrix, space):
        return space.position(arm.matrix_world @ matrix.translation)

    source_hips_pos = head_world(src, hips_matrices[src_hips_name], source_space)
    target_hips_pos = head_world(tgt, tgt_hips_matrices[tgt_hips_name], target_space)
    source_height = source_hips_pos.z
    if source_height < 1e-6:
        source_height = 0.01
    xy_offset = Vector((
        target_hips_pos.x - source_hips_pos.x,
        target_hips_pos.y - source_hips_pos.y,
        0.0,
    ))

    pelvis = PelvisReference(
        source_name=src_hips_name,
        target_name=tgt_hips_name,
        source_position=source_hips_pos,
        target_position=target_hips_pos,
        inverse_source_height=1.0 / source_height,
        xy_offset=xy_offset,
    )

    limbs = []
    wanted = []
    if options.foot_ik:
        wanted.extend(_IK_CHAIN_ROLES[:2])
    if options.hand_ik:
        wanted.extend(_IK_CHAIN_ROLES[2:])
    for roles in wanted:
        if not all(role in src_roles and role in tgt_roles for role in roles):
            print(f"[HumanoidRetarget] 跳过未完整映射的链: {roles[0]}")
            continue
        src_names = tuple(src_roles[role] for role in roles)
        tgt_names = tuple(tgt_roles[role] for role in roles)
        src_mats = reference_matrices(src, src_roles, [src_names[0], src_names[2]])
        tgt_mats = reference_matrices(tgt, tgt_roles, list(tgt_names))

        src_start = head_world(src, src_mats[src_names[0]], source_space)
        src_end = head_world(src, src_mats[src_names[2]], source_space)
        tgt_start = head_world(tgt, tgt_mats[tgt_names[0]], target_space)
        tgt_mid = head_world(tgt, tgt_mats[tgt_names[1]], target_space)
        tgt_end = head_world(tgt, tgt_mats[tgt_names[2]], target_space)

        source_initial = (src_end - src_start).length
        target_initial = (tgt_end - tgt_start).length
        if source_initial < 1e-6 or target_initial < 1e-6:
            print(f"[HumanoidRetarget] 跳过参考长度为零的链: {roles[0]}")
            continue

        upper_len = (tgt_mid - tgt_start).length
        lower_len = (tgt_end - tgt_mid).length

        def rest_head_world(arm, name, space):
            return space.position(arm.matrix_world @ arm.data.bones[name].head_local)

        tgt_rest_start = rest_head_world(tgt, tgt_names[0], target_space)
        tgt_rest_mid = rest_head_world(tgt, tgt_names[1], target_space)
        tgt_rest_end = rest_head_world(tgt, tgt_names[2], target_space)
        rest_upper = (tgt_rest_mid - tgt_rest_start).length
        rest_lower = (tgt_rest_end - tgt_rest_mid).length
        if abs(rest_upper - upper_len) > 1e-4 or abs(rest_lower - lower_len) > 1e-4:
            raise RetargetError(f"目标链 {roles[0]} 的 CURRENT 参考关节距离与 rest 不一致。")

        src_end_matrix = src.matrix_world @ src_mats[src_names[2]]
        tgt_end_matrix = tgt.matrix_world @ tgt_mats[tgt_names[2]]
        source_end_rotation = source_space.rotation(src_end_matrix)
        target_end_rotation = target_space.rotation(tgt_end_matrix)

        src_rest_end = rest_head_world(src, src_names[2], source_space)

        limbs.append(LimbReference(
            roles=roles,
            source_names=src_names,
            target_names=tgt_names,
            source_initial_length=source_initial,
            target_initial_length=target_initial,
            target_upper_length=rest_upper,
            target_lower_length=rest_lower,
            source_end_rotation=source_end_rotation,
            target_end_rotation=target_end_rotation,
            height_offset=tgt_end.z - src_end.z,
            source_rest_end_height=src_rest_end.z,
            reference_pole=tgt_mid,
        ))

    return RetargetGeometry(
        source_space=source_space,
        target_space=target_space,
        pelvis=pelvis,
        limbs=tuple(limbs),
    )


def _hips_translation_with_floor(src, tgt, geometry, settings, in_place):
    pelvis = geometry.pelvis
    src_pose = src.pose.bones[pelvis.source_name]
    current = geometry.source_space.position(src.matrix_world @ src_pose.head)

    position, pelvis_delta = retarget_pelvis_position(
        current, pelvis, settings, in_place
    )

    tgt_pose = tgt.pose.bones[pelvis.target_name]
    matrix = tgt_pose.matrix.copy()
    matrix.translation = geometry.target_space.armature_position(position)
    tgt_pose.matrix = matrix
    return pelvis_delta


def _sample_foot_motion(src, action, frame_range, geometry, settings, in_place, scene):
    start, end = frame_range
    count = end - start + 1
    if count < 2:
        return {}
    fps = scene.render.fps
    fps_base = scene.render.fps_base
    if fps <= 0 or fps_base <= 0:
        raise RetargetError("场景帧率无效，无法进行接触采样。")
    dt = fps_base / fps

    foot_roles = [limb.roles[2] for limb in geometry.limbs if limb.roles[2] in ("foot_l", "foot_r")]
    hips_name = geometry.pelvis.source_name
    hips_ref = geometry.pelvis.source_position

    samples = {role: [] for role in foot_roles}
    anim = src.animation_data
    original_use_nla = anim.use_nla if anim else None
    if anim:
        anim.use_nla = False
    original_frame = scene.frame_current
    try:
        for frame in range(start, end + 1):
            scene.frame_set(frame)
            bpy.context.view_layer.update()
            validate_motion_space(src, geometry.source_space)
            src_pose_hips = src.pose.bones.get(hips_name)
            if src_pose_hips is not None:
                hips_now = geometry.source_space.position(src.matrix_world @ src_pose_hips.head)
            else:
                hips_now = geometry.pelvis.source_position.copy()
            for role in foot_roles:
                limb = next(item for item in geometry.limbs if item.roles[2] == role)
                foot_pose = src.pose.bones.get(limb.source_names[2])
                if foot_pose is None:
                    samples[role].append(None)
                    continue
                pos = geometry.source_space.position(src.matrix_world @ foot_pose.head)
                if in_place:
                    pos = Vector((
                        pos.x - hips_now.x + hips_ref.x,
                        pos.y - hips_now.y + hips_ref.y,
                        pos.z,
                    ))
                samples[role].append(pos.copy())
    finally:
        if anim is not None and original_use_nla is not None:
            anim.use_nla = original_use_nla
        scene.frame_set(original_frame)

    speeds = {}
    for role in foot_roles:
        positions = tuple(p for p in samples[role] if p is not None)
        if len(positions) != count:
            speeds[role] = tuple(-1.0 for _ in range(count))
            continue
        limb = next(item for item in geometry.limbs if item.roles[2] == role)
        speeds[role] = geometric_foot_speeds(
            positions, limb.source_rest_end_height, dt, settings
        )
    return speeds


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

    use_foot_ik = options.foot_ik
    use_hand_ik = options.hand_ik
    ik_geometry = None
    if use_foot_ik or use_hand_ik:
        try:
            ik_geometry = _prepare_retarget_geometry(src, tgt, pairs, options, bpy.context.scene)
        except MotionSpaceError as exc:
            raise RetargetError(f"脚 IK 空间构建失败: {exc}")
    ik_settings = options.foot_ik_settings
    planting_on = (
        use_foot_ik
        and ik_geometry is not None
        and ik_settings.planting_enabled
    )

    if tgt.animation_data:
        tgt.animation_data_clear()

    scene = bpy.context.scene
    baked = []
    baked_sources = []
    original_frame = scene.frame_current
    original_start = scene.frame_start
    original_end = scene.frame_end
    try:
        for action in actions:
            _assign_action(src, action)
            if action == source_action and source_slot is not None:
                src.animation_data.action_slot = source_slot
            start, end = _frame_range(action)
            target_action = _new_target_action(tgt, f"{tgt.name}_{action.name}")

            speeds = {}
            plant_states = {}
            dt = scene.render.fps_base / scene.render.fps if scene.render.fps else 1.0
            if planting_on:
                speeds = _sample_foot_motion(
                    src, action, (start, end), ik_geometry, ik_settings, in_place, scene
                )
                for limb in ik_geometry.limbs:
                    end_role = limb.roles[2]
                    if end_role in ("foot_l", "foot_r"):
                        plant_states[end_role] = LimbPlantState(
                            previous_goal=limb.reference_pole.copy()
                        )
            if ik_geometry is not None:
                for limb in ik_geometry.limbs:
                    end_role = limb.roles[2]
                    if end_role in ("foot_l", "foot_r") and end_role not in plant_states and planting_on:
                        plant_states[end_role] = LimbPlantState(
                            previous_goal=limb.reference_pole.copy()
                        )

            for frame in range(start, end + 1):
                scene.frame_set(frame)
                bpy.context.view_layer.update()
                if ik_geometry is not None:
                    validate_motion_space(src, ik_geometry.source_space)
                    validate_motion_space(tgt, ik_geometry.target_space)
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
                pelvis_delta = Vector((0.0, 0.0, 0.0))
                if use_foot_ik and ik_geometry is not None:
                    pelvis_delta = _hips_translation_with_floor(
                        src, tgt, ik_geometry, ik_settings, in_place
                    )
                else:
                    _hips_translation(src, tgt, hip_role[1], hip_role[2], scale, src_head, tgt_head, in_place)
                bpy.context.view_layer.update()
                if ik_geometry is not None:
                    frame_speeds = {}
                    frame_index = frame - start
                    for role, values in speeds.items():
                        if 0 <= frame_index < len(values):
                            frame_speeds[role] = values[frame_index]
                        else:
                            frame_speeds[role] = -1.0
                    apply_contact_ik(
                        src, tgt, ik_geometry, ik_settings, plant_states, frame_speeds, pelvis_delta, dt
                    )
                bpy.context.view_layer.update()
                for _role, _src_name, tgt_name in pairs:
                    pose_bone = tgt.pose.bones[tgt_name]
                    pose_bone.keyframe_insert(data_path="rotation_quaternion", frame=frame)
                    pose_bone.keyframe_insert(data_path="location", frame=frame)
            target_action.use_fake_user = True
            baked.append((target_action, start, end))
            baked_sources.append(action)
    finally:
        scene.frame_start = original_start
        scene.frame_end = original_end
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
        f"IK: {'、'.join(ik_parts) if ik_parts else '关闭'}"
        + ("（地面约束+速度植步）" if use_foot_ik and ik_geometry is not None else ""),
        f"烘焙 {len(baked)} 个动作: " + ", ".join(action.name for action, _s, _e in baked),
        "动画已经写在目标骨架上，隐藏来源后仍可播放。",
    ]
    return "\n".join(lines), [action for action, _s, _e in baked]
