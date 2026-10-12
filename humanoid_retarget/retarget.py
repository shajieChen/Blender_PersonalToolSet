"""Bake source humanoid motion onto a target humanoid skeleton.

Rotation is copied in each bone's reference axes, with a correction so a
different bone roll does not twist the limb. The reference is the rest pose
unless a current pose was captured. Hip translation is scaled by the
hips-to-head height ratio and can drop horizontal travel. Optional hand and
foot IK runs after the FK pose.
"""

from __future__ import annotations

import bpy
from mathutils import Matrix, Vector

from .classify import CORE_ROLES, describe_roles, rig_height
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
    ):
        self.pairs = pairs
        self.reference = reference if reference in {"REST", "CURRENT"} else "REST"
        self.reference_data = reference_data
        self.root_motion = root_motion if root_motion in {"KEEP", "IN_PLACE"} else "KEEP"
        self.foot_ik = bool(foot_ik)
        self.hand_ik = bool(hand_ik)
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

    options = options or RetargetOptions()
    if options.reference == "CURRENT" and not options.reference_data:
        raise RetargetError("已选择当前姿势作为零点，但还没有捕获参考姿势")
    pairs = _pairs_from_options(src, tgt, options)
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
    original_frame = scene.frame_current
    try:
        for action in actions:
            _assign_action(src, action)
            start, end = _frame_range(action)
            target_action = _new_target_action(tgt, f"{tgt.name}_{action.name}")
            for frame in range(start, end + 1):
                scene.frame_set(frame)
                bpy.context.view_layer.update()
                references = {}
                for _role, src_name, tgt_name in pairs:
                    src_basis, tgt_basis, src_head, tgt_head = _reference_for(
                        src, tgt, src_name, tgt_name, options
                    )
                    references[tgt_name] = (src_head, tgt_head)
                    _rotation_onto(
                        src.pose.bones[src_name],
                        tgt.pose.bones[tgt_name],
                        src.data.bones[src_name],
                        tgt.data.bones[tgt_name],
                        src_basis,
                        tgt_basis,
                    )
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
    finally:
        scene.frame_set(original_frame)

    if baked:
        first, start, end = baked[0]
        _assign_action(tgt, first)
        _stash_nla(tgt, [action for action, _start, _end in baked[1:]])
        scene.frame_start = min(item[1] for item in baked)
        scene.frame_end = max(item[2] for item in baked)
        scene.frame_set(scene.frame_start)

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
