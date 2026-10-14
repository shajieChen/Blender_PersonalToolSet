"""Contact IK built on UE-equivalent goal, floor constraint and speed planting.

The body stays on the FK result. When foot or hand IK is on, each limb chain
gets a goal from the source chain extension ratio (not the global height
scale), feet additionally run floor + planting passes, then a two-bone
solver aims the joints at the goal.
"""

from __future__ import annotations

import bpy
from mathutils import Matrix, Vector

from .foot_ik import (
    IKGoal,
    LimbReference,
    RetargetGeometry,
    FootIKSettings,
    LimbPlantState,
    constrain_goal_floor,
    generate_limb_goal,
    plant_goal,
)
from .motion_space import MotionSpace

_LEG_CHAINS = (
    ("thigh_l", "shin_l", "foot_l"),
    ("thigh_r", "shin_r", "foot_r"),
)
_ARM_CHAINS = (
    ("upperarm_l", "forearm_l", "hand_l"),
    ("upperarm_r", "forearm_r", "hand_r"),
)
_FOOT_ROLES = frozenset({"foot_l", "foot_r"})


def apply_contact_ik(
    src,
    tgt,
    geometry: RetargetGeometry,
    settings: FootIKSettings,
    states: dict,
    speeds: dict,
    pelvis_delta: Vector,
    dt: float,
) -> None:
    for limb in geometry.limbs:
        end_role = limb.roles[2]
        source_start_pose = src.pose.bones.get(limb.source_names[0])
        source_end_pose = src.pose.bones.get(limb.source_names[2])
        target_start_pose = tgt.pose.bones.get(limb.target_names[0])
        if not source_start_pose or not source_end_pose or not target_start_pose:
            continue

        source_space = geometry.source_space
        target_space = geometry.target_space

        source_start = source_space.position(src.matrix_world @ source_start_pose.head)
        source_end = source_space.position(src.matrix_world @ source_end_pose.head)
        source_end_matrix = src.matrix_world @ source_end_pose.matrix
        source_end_rotation = source_space.rotation(source_end_matrix)
        target_start = target_space.position(tgt.matrix_world @ target_start_pose.head)

        goal = generate_limb_goal(
            source_start,
            source_end,
            source_end_rotation,
            target_start,
            limb,
            pelvis_delta,
        )

        if end_role in _FOOT_ROLES:
            goal.position = constrain_goal_floor(
                goal.position,
                source_end.z,
                limb.height_offset,
                settings,
            )
            state = states.get(end_role)
            speed = speeds.get(end_role, -1.0)
            if state is not None:
                goal.position = plant_goal(
                    goal.position,
                    speed,
                    state,
                    dt,
                    settings,
                )

        _solve_chain(tgt, target_space, limb, goal)


def _solve_chain(tgt, space: MotionSpace, reference: LimbReference, goal: IKGoal) -> float:
    upper_name, mid_name, end_name = reference.target_names
    upper_pose = tgt.pose.bones[upper_name]
    mid_pose = tgt.pose.bones[mid_name]
    end_pose = tgt.pose.bones[end_name]

    world = tgt.matrix_world
    root = space.position(world @ upper_pose.head)
    pole = space.position(world @ mid_pose.head)
    if (pole - root).length < 1e-6:
        pole = reference.reference_pole

    knee, reachable = _two_bone(
        root,
        reference.target_upper_length,
        reference.target_lower_length,
        goal.position,
        pole,
        reference.reference_pole - root,
    )

    _aim_joint(tgt, upper_name, mid_name, space, knee - root)
    bpy.context.view_layer.update()

    upper_pose = tgt.pose.bones[upper_name]
    mid_pose = tgt.pose.bones[mid_name]
    knee_now = space.position(world @ mid_pose.head)
    root_now = space.position(world @ upper_pose.head)
    _aim_joint(tgt, mid_name, end_name, space, reachable - knee_now)
    bpy.context.view_layer.update()

    _write_end_rotation(tgt, end_name, space, goal.rotation)
    bpy.context.view_layer.update()

    end_pose = tgt.pose.bones[end_name]
    final = space.position(world @ end_pose.head)
    return (final - goal.position).length


def _aim_joint(obj, start_name: str, end_name: str, space: MotionSpace, desired_direction: Vector) -> None:
    start_pose = obj.pose.bones[start_name]
    end_pose = obj.pose.bones[end_name]

    current_arm = end_pose.head - start_pose.head
    if current_arm.length < 1e-9:
        raise RuntimeError(f"degenerate joint segment {start_name}->{end_name}")
    desired_arm = space.axes @ desired_direction
    if desired_arm.length < 1e-9:
        raise RuntimeError(f"degenerate aim direction at {start_name}")

    swing = current_arm.normalized().rotation_difference(desired_arm.normalized())

    matrix = start_pose.matrix.copy()
    rotation = swing.to_matrix().to_4x4()
    rotated = rotation @ matrix
    rotated.translation = matrix.translation
    start_pose.matrix = rotated


def _two_bone(
    root: Vector,
    upper_len: float,
    lower_len: float,
    target: Vector,
    pole: Vector,
    fallback_direction: Vector,
):
    reach = target - root
    distance = reach.length
    epsilon = min(1e-6, 0.01 * min(upper_len, lower_len))
    maximum = upper_len + lower_len - epsilon
    minimum = abs(upper_len - lower_len) + epsilon
    if distance < 1e-10:
        direction = fallback_direction.normalized()
        distance = minimum
    else:
        direction = reach.normalized()
        distance = min(max(distance, minimum), maximum)

    import math

    cos_angle = (upper_len * upper_len + distance * distance - lower_len * lower_len) / (2.0 * upper_len * distance)
    cos_angle = min(1.0, max(-1.0, cos_angle))
    angle = math.acos(cos_angle)

    pole_dir = pole - root
    pole_dir = pole_dir - direction * pole_dir.dot(direction)
    if pole_dir.length < max(upper_len, lower_len) * 0.02:
        axes = (Vector((1.0, 0.0, 0.0)), Vector((0.0, 1.0, 0.0)), Vector((0.0, 0.0, 1.0)))
        pole_dir = min(axes, key=lambda axis: abs(direction.dot(axis)))
        pole_dir = pole_dir - direction * pole_dir.dot(direction)
        if pole_dir.length < 1e-6:
            pole_dir = direction.cross(Vector((0.0, 0.0, 1.0)))
            if pole_dir.length < 1e-6:
                pole_dir = direction.cross(Vector((1.0, 0.0, 0.0)))
    pole_dir.normalize()

    upper_direction = (direction * math.cos(angle) + pole_dir * math.sin(angle)).normalized()
    knee = root + upper_direction * upper_len
    reachable_end = root + direction * distance
    return knee, reachable_end


def _write_end_rotation(obj, end_name, space: MotionSpace, rotation) -> None:
    pose_bone = obj.pose.bones[end_name]
    translation = pose_bone.matrix.translation.copy()
    matrix = space.armature_rotation(rotation).to_4x4()
    matrix.translation = translation
    pose_bone.matrix = matrix
