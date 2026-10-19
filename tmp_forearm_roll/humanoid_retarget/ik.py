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

        pole_hint = transfer_source_fold_pole(
            src,
            source_space,
            tgt,
            target_space,
            limb,
            goal.position,
        )
        _solve_chain(tgt, target_space, limb, goal, pole_hint=pole_hint)


def transfer_source_fold_pole(
    src,
    source_space: MotionSpace,
    tgt,
    target_space: MotionSpace,
    reference: LimbReference,
    target_goal: Vector,
) -> Vector:
    """Map the source elbow/knee offset onto the target reach (retarget pole)."""
    src_world = src.matrix_world
    upper = source_space.position(
        src_world @ src.pose.bones[reference.source_names[0]].head
    )
    mid = source_space.position(
        src_world @ src.pose.bones[reference.source_names[1]].head
    )
    end = source_space.position(
        src_world @ src.pose.bones[reference.source_names[2]].head
    )
    src_reach = end - upper
    if src_reach.length_squared < 1e-16:
        return reference.reference_pole.copy()
    src_dir = src_reach.normalized()
    src_perp = (mid - upper) - src_dir * (mid - upper).dot(src_dir)
    tgt_world = tgt.matrix_world
    root = target_space.position(
        tgt_world @ tgt.pose.bones[reference.target_names[0]].head
    )
    tgt_dir = target_goal - root
    if tgt_dir.length_squared < 1e-16 or src_perp.length_squared < 1e-16:
        return bind_oriented_pole(
            root,
            target_goal,
            target_space.position(
                tgt_world @ tgt.data.bones[reference.target_names[0]].head_local
            ),
            target_space.position(
                tgt_world @ tgt.data.bones[reference.target_names[1]].head_local
            ),
            target_space.position(
                tgt_world @ tgt.data.bones[reference.target_names[2]].head_local
            ),
            Vector((0.0, -1.0, 0.0)),
        )
    tgt_dir = tgt_dir.normalized()
    swung = src_dir.rotation_difference(tgt_dir) @ src_perp
    return root + swung


def bind_oriented_pole(
    root: Vector,
    target: Vector,
    reference_root: Vector,
    reference_mid: Vector,
    reference_end: Vector,
    preferred_side: Vector | None = None,
) -> Vector:
    """Build an elbow/knee pole from the bind fold, swung onto the current reach.

    UE Preferred Angles / IK pole targets coerce bend side from the rest pose.
    Using the live FK mid as the pole inherits a wrong-side fold and pretzels.
    Nearly straight T/A-pose binds have tiny rest bend; then preferred_side
    should point where the joint must bend (elbows: behind, knees: forward).
    """
    rest_reach = reference_end - reference_root
    cur_reach = target - root
    if rest_reach.length_squared < 1e-16 or cur_reach.length_squared < 1e-16:
        return reference_mid.copy()
    rest_dir = rest_reach.normalized()
    cur_dir = cur_reach.normalized()
    rest_offset = reference_mid - reference_root
    rest_perp = rest_offset - rest_dir * rest_offset.dot(rest_dir)
    span = max((reference_mid - reference_root).length, 1e-4)
    if rest_perp.length < span * 0.02:
        side = (
            preferred_side.copy()
            if preferred_side is not None
            else Vector((0.0, -1.0, 0.0))
        )
        rest_perp = side - rest_dir * side.dot(rest_dir)
        if rest_perp.length_squared < 1e-16:
            rest_perp = rest_dir.cross(Vector((0.0, 0.0, 1.0)))
        if rest_perp.length_squared < 1e-16:
            rest_perp = rest_dir.cross(Vector((1.0, 0.0, 0.0)))
        if rest_perp.length_squared < 1e-16:
            return reference_mid.copy()
        rest_perp = rest_perp.normalized() * (span * 0.35)
    swing = rest_dir.rotation_difference(cur_dir)
    return root + (swing @ rest_perp)


def align_pole_to_bind_side(
    root: Vector,
    pole: Vector,
    reference_pole: Vector,
    target: Vector,
) -> Vector:
    """Keep a live pole on the same side of the reach axis as a bind-side tip."""
    reach = target - root
    if reach.length_squared < 1e-16:
        return reference_pole.copy()
    direction = reach.normalized()

    def perpendicular(point: Vector) -> Vector:
        offset = point - root
        return offset - direction * offset.dot(direction)

    mid_perp = perpendicular(pole)
    ref_perp = perpendicular(reference_pole)
    if ref_perp.length_squared < 1e-16:
        return pole.copy()
    if mid_perp.length_squared < 1e-16:
        return root + ref_perp
    if mid_perp.dot(ref_perp) < 0.0:
        return root + ref_perp.normalized() * mid_perp.length
    return pole.copy()


def _solve_chain(
    tgt,
    space: MotionSpace,
    reference: LimbReference,
    goal: IKGoal,
    pole_hint: Vector | None = None,
) -> float:
    upper_name, mid_name, end_name = reference.target_names
    upper_pose = tgt.pose.bones[upper_name]
    mid_pose = tgt.pose.bones[mid_name]
    end_pose = tgt.pose.bones[end_name]

    world = tgt.matrix_world
    root = space.position(world @ upper_pose.head)
    rest_root = space.position(world @ tgt.data.bones[upper_name].head_local)
    rest_mid = space.position(world @ tgt.data.bones[mid_name].head_local)
    rest_end = space.position(world @ tgt.data.bones[end_name].head_local)
    end_role = reference.roles[2]
    # Motion space: Z up, Y along character forward. Elbows bend back (-Y),
    # knees bend forward (+Y) — Blender/UE pole conventions.
    if end_role in ("hand_l", "hand_r"):
        preferred_side = Vector((0.0, -1.0, 0.0))
    elif end_role in ("foot_l", "foot_r"):
        preferred_side = Vector((0.0, 1.0, 0.0))
    else:
        preferred_side = Vector((0.0, -1.0, 0.0))
    bind_pole = bind_oriented_pole(
        root,
        goal.position,
        rest_root,
        rest_mid,
        rest_end,
        preferred_side,
    )
    if pole_hint is not None:
        pole = align_pole_to_bind_side(
            root, pole_hint, bind_pole, goal.position
        )
    else:
        pole = bind_pole

    knee, reachable = _two_bone(
        root,
        reference.target_upper_length,
        reference.target_lower_length,
        goal.position,
        pole,
        reference.reference_pole - root,
    )
    _apply_two_bone_aim(tgt, space, upper_name, mid_name, end_name, knee, reachable)
    if _fold_opposes_bind(tgt, space, upper_name, mid_name, end_name, rest_root, rest_mid, rest_end):
        flipped = root - (pole - root)
        knee, reachable = _two_bone(
            root,
            reference.target_upper_length,
            reference.target_lower_length,
            goal.position,
            flipped,
            reference.reference_pole - root,
        )
        _apply_two_bone_aim(tgt, space, upper_name, mid_name, end_name, knee, reachable)

    _write_end_rotation(tgt, end_name, space, goal.rotation)
    bpy.context.view_layer.update()

    end_pose = tgt.pose.bones[end_name]
    final = space.position(world @ end_pose.head)
    return (final - goal.position).length


def _apply_two_bone_aim(tgt, space, upper_name, mid_name, end_name, knee, reachable):
    world = tgt.matrix_world
    root = space.position(world @ tgt.pose.bones[upper_name].head)
    _aim_joint(tgt, upper_name, mid_name, space, knee - root)
    bpy.context.view_layer.update()
    knee_now = space.position(world @ tgt.pose.bones[mid_name].head)
    _aim_joint(tgt, mid_name, end_name, space, reachable - knee_now)
    bpy.context.view_layer.update()


def _fold_opposes_bind(tgt, space, upper_name, mid_name, end_name, rest_root, rest_mid, rest_end):
    upper = space.position(tgt.matrix_world @ tgt.pose.bones[upper_name].head)
    mid = space.position(tgt.matrix_world @ tgt.pose.bones[mid_name].head)
    end = space.position(tgt.matrix_world @ tgt.pose.bones[end_name].head)
    rest_reach = rest_end - rest_root
    cur_reach = end - upper
    if rest_reach.length_squared < 1e-16 or cur_reach.length_squared < 1e-16:
        return False
    rest_dir = rest_reach.normalized()
    cur_dir = cur_reach.normalized()
    rest_perp = (rest_mid - rest_root) - rest_dir * (rest_mid - rest_root).dot(rest_dir)
    mid_perp = (mid - upper) - cur_dir * (mid - upper).dot(cur_dir)
    if rest_perp.length_squared < 1e-16 or mid_perp.length_squared < 1e-16:
        return False
    preferred = rest_dir.rotation_difference(cur_dir) @ rest_perp
    return mid_perp.dot(preferred) < 0.0


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
