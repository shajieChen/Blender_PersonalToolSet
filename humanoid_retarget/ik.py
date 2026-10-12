"""Optional two-bone IK so a hand or foot meets the source contact point.

The body stays on the FK result. IK only rewrites the two bones of a chain
when the user turns the option on.
"""

from __future__ import annotations

import math

from mathutils import Matrix, Vector

_LEG_CHAINS = (
    ("thigh_l", "shin_l", "foot_l"),
    ("thigh_r", "shin_r", "foot_r"),
)
_ARM_CHAINS = (
    ("upperarm_l", "forearm_l", "hand_l"),
    ("upperarm_r", "forearm_r", "hand_r"),
)


def apply_contact_ik(src, tgt, pairs, scale: float, feet: bool, hands: bool) -> None:
    if not feet and not hands:
        return
    pair_map = {role: (source_name, target_name) for role, source_name, target_name in pairs}
    if "hips" not in pair_map:
        return
    chains = []
    if feet:
        chains.extend(_LEG_CHAINS)
    if hands:
        chains.extend(_ARM_CHAINS)
    for chain in chains:
        if all(role in pair_map for role in chain):
            _solve_chain(src, tgt, pair_map, scale, chain)


def _solve_chain(src, tgt, pair_map, scale: float, chain) -> None:
    _upper_role, _mid_role, end_role = chain
    src_hips = src.pose.bones[pair_map["hips"][0]]
    tgt_hips = tgt.pose.bones[pair_map["hips"][1]]
    src_end = src.pose.bones[pair_map[end_role][0]]
    tgt_upper = tgt.pose.bones[pair_map[chain[0]][1]]
    tgt_mid = tgt.pose.bones[pair_map[chain[1]][1]]

    src_world = src.matrix_world
    tgt_world = tgt.matrix_world
    src_hip_w = src_world @ src_hips.head
    src_end_w = src_world @ src_end.head
    desired = (tgt_world @ tgt_hips.head) + (src_end_w - src_hip_w) * scale

    upper_head = tgt_world @ tgt_upper.head
    upper_len = _rest_world_length(tgt, tgt_upper.name)
    mid_len = _rest_world_length(tgt, tgt_mid.name)
    if upper_len < 1e-5 or mid_len < 1e-5:
        return

    pole = tgt_world @ tgt_mid.head
    upper_dir, mid_dir = _two_bone(upper_head, upper_len, mid_len, desired, pole)
    _aim_bone(tgt, tgt_upper, upper_dir, upper_head)
    import bpy

    bpy.context.view_layer.update()
    knee = tgt.matrix_world @ tgt_upper.tail
    _aim_bone(tgt, tgt_mid, mid_dir, knee)


def _rest_world_length(obj, bone_name: str) -> float:
    bone = obj.data.bones[bone_name]
    head = obj.matrix_world @ bone.head_local
    tail = obj.matrix_world @ bone.tail_local
    return (tail - head).length


def _two_bone(root: Vector, upper_len: float, mid_len: float, target: Vector, pole: Vector):
    reach = target - root
    distance = reach.length
    maximum = upper_len + mid_len - 1e-4
    minimum = abs(upper_len - mid_len) + 1e-4
    if distance < 1e-6:
        reach = Vector((0.0, 0.0, -1.0))
        distance = 1.0
    distance = min(max(distance, minimum), maximum)
    direction = reach.normalized()
    target = root + direction * distance

    cos_angle = (upper_len * upper_len + distance * distance - mid_len * mid_len) / (2.0 * upper_len * distance)
    cos_angle = min(1.0, max(-1.0, cos_angle))
    angle = math.acos(cos_angle)

    pole_dir = pole - root
    pole_dir = pole_dir - direction * pole_dir.dot(direction)
    if pole_dir.length < max(upper_len, mid_len) * 0.02:
        pole_dir = Vector((0.0, -1.0, 0.0))
        pole_dir = pole_dir - direction * pole_dir.dot(direction)
        if pole_dir.length < 1e-6:
            pole_dir = Vector((1.0, 0.0, 0.0))
    pole_dir.normalize()

    upper_dir = (direction * math.cos(angle) + pole_dir * math.sin(angle)).normalized()
    knee = root + upper_dir * upper_len
    mid_dir = target - knee
    if mid_dir.length < 1e-6:
        mid_dir = direction
    return upper_dir, mid_dir.normalized()


def _aim_bone(obj, pose_bone, world_direction: Vector, world_head: Vector) -> None:
    arm = obj.matrix_world.inverted()
    direction = (arm.to_3x3() @ world_direction).normalized()
    head = arm @ world_head
    previous = pose_bone.matrix.copy()
    y_axis = direction
    x_axis = previous.col[0].xyz - y_axis * previous.col[0].xyz.dot(y_axis)
    if x_axis.length < 1e-6:
        x_axis = Vector((1.0, 0.0, 0.0)) - y_axis * y_axis.x
    if x_axis.length < 1e-6:
        x_axis = Vector((0.0, 1.0, 0.0))
    x_axis.normalize()
    z_axis = x_axis.cross(y_axis).normalized()
    x_axis = y_axis.cross(z_axis).normalized()
    pose_bone.matrix = Matrix((
        (x_axis.x, y_axis.x, z_axis.x, head.x),
        (x_axis.y, y_axis.y, z_axis.y, head.y),
        (x_axis.z, y_axis.z, z_axis.z, head.z),
        (0.0, 0.0, 0.0, 1.0),
    ))
