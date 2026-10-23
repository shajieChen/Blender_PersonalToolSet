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

# Accepted contact stack (coordinate-correct goals, skin feedback, knee floor,
# height-plan smoothing). Stays off unless a bake explicitly enables it, so the
# historical foot-IK path is unchanged.
_CONTACT_STACK_ENABLED = False
_CONTACT_FLOOR_TOLERANCE = -0.001
_CONTACT_MAX_CORRECTIONS = 2
_CONTACT_MAX_RAISE = None
_CONTACT_MIN_KNEE_DEG = None
_CONTACT_KNEE_SMOOTH_DEG = None
CONTACT_LOG = []
CONTACT_TRACE = []
_CORRECTION_PLAN = None
CORRECTION_PLAN_VERSION = "height-plan-v1"
_PLAN_CACHE = {}

# Experiment only (independent copy): sole-target correction and hip
# compensation. Both default off so the baseline path is unchanged.
EXP_SOLE = False
EXP_HIP = False
EXP_ROOT_DELTA = 0.0
EXP_HIP_MODE = "min"
EXP_PRE_SOLE = False
EXP_KEEP_RECHECK = True
EXP_PRE_LOG = []
EXP_LOG = []
EXP_HIP_LOG = []


def clear_correction_plan_cache():
    _PLAN_CACHE.clear()


def _p(space, world_point):
    if _CONTACT_STACK_ENABLED:
        return space.world_position(world_point)
    return space.position(world_point)


def _r(space, world_matrix):
    if _CONTACT_STACK_ENABLED:
        return space.world_rotation(world_matrix)
    return space.rotation(world_matrix)


def smooth_corrections_binomial(series):
    """Two passes of the [1, 2, 1] / 4 kernel. Ends are replicated."""
    def one_pass(values):
        out = []
        for index, value in enumerate(values):
            prev = values[index - 1] if index > 0 else value
            nxt = values[index + 1] if index + 1 < len(values) else value
            out.append((prev + value * 2.0 + nxt) * 0.25)
        return out
    return one_pass(one_pass(list(series)))


def build_height_plan(raw_series, lowest_series):
    """Add lift so the foot-low trajectory follows a smoothed target.

    The plan never reduces the raw per-frame correction.
    """
    plan = {}
    roles = sorted({role for _frame, role in raw_series})
    for role in roles:
        frames = sorted(frame for frame, item_role in raw_series if item_role == role)
        heights = [lowest_series.get((frame, role), 0.0) for frame in frames]
        smoothed = smooth_corrections_binomial(
            [Vector((0.0, 0.0, value)) for value in heights]
        )
        for frame, target in zip(frames, smoothed):
            raw = raw_series[(frame, role)]
            extra = max(
                0.0,
                max(target.z, _CONTACT_FLOOR_TOLERANCE) - lowest_series.get((frame, role), 0.0),
            )
            plan[(frame, role)] = raw + Vector((0.0, 0.0, extra))
    return plan


def skin_point_world(tgt, bind_point, influences, rest_inverses=None):
    """Linear-blend-skinned world position. Weights are normalised by their sum."""
    total = sum(weight for _name, weight in influences)
    if total <= 1e-9:
        return tgt.matrix_world @ bind_point
    if rest_inverses is None:
        rest_inverses = {}
    blended = None
    for name, weight in influences:
        if name not in rest_inverses:
            rest_inverses[name] = tgt.pose.bones[name].bone.matrix_local.inverted()
        posed = tgt.pose.bones[name].matrix @ rest_inverses[name] @ bind_point
        blended = posed * (weight / total) if blended is None else blended + posed * (weight / total)
    return tgt.matrix_world @ blended


def _skin_lowest_world(tgt, skin_points):
    rest_inverses = {}
    lowest = None
    dominant = None
    for bind_point, influences in skin_points:
        point = skin_point_world(tgt, bind_point, influences, rest_inverses)
        if lowest is None or point.z < lowest:
            lowest = point.z
            dominant = max(influences, key=lambda item: item[1])[0]
    return lowest, dominant


def _foot_lowest(tgt, limb):
    if limb.skin_points:
        return _skin_lowest_world(tgt, limb.skin_points)
    if limb.contact_local:
        pose = tgt.pose.bones[limb.target_names[2]]
        world = tgt.matrix_world
        lowest = min((world @ (pose.matrix @ point)).z for point in limb.contact_local)
        return lowest, limb.target_names[2]
    return None, None


def _is_contact(speed, settings):
    return speed is not None and 0.0 <= speed <= settings.speed_threshold_mps


def _sole_correct(tgt, target_space, limb, goal, pole_hint, speed, settings):
    """Raise the ankle goal until the posed foot-region lowest point is on the floor.

    Only contact-classified feet are corrected; swing feet keep their goal.
    Returns (total_raise_m, contact, lowest_before, lowest_after).
    """
    contact = _is_contact(speed, settings)
    lowest_before, _dom = _foot_lowest(tgt, limb)
    lowest = lowest_before
    total = 0.0
    if contact and lowest is not None:
        for _ in range(3):
            if lowest >= settings.floor_height_m:
                break
            amount = settings.floor_height_m - lowest
            goal.position.z += amount
            total += amount
            _solve_chain(tgt, target_space, limb, goal, pole_hint=pole_hint)
            lowest, _dom = _foot_lowest(tgt, limb)
            if lowest is None:
                break
    return total, contact, lowest_before, lowest


def _pre_sole_correct(tgt, target_space, limb, goal, speed, settings):
    """Correct the ankle goal before the first solve, from the foot contact points.

    The heel and forefoot points (limb.contact_local, in the foot bone's
    rest-local frame) are placed with the goal rotation at the goal ankle
    position; the lowest predicted point is put on the floor. Only
    contact-classified feet are corrected.
    Returns (amount_m, contact, predicted_lowest_world_z).
    """
    contact = _is_contact(speed, settings)
    if not contact or not limb.contact_local:
        return 0.0, contact, None
    armature_point = target_space.armature_position(goal.position)
    matrix = target_space.armature_rotation(goal.rotation).to_4x4()
    matrix.translation = armature_point
    world = tgt.matrix_world
    lowest = min((world @ (matrix @ point)).z for point in limb.contact_local)
    if lowest >= settings.floor_height_m:
        return 0.0, contact, lowest
    amount = settings.floor_height_m - lowest
    goal.position.z += amount
    return amount, contact, lowest


def _build_goal(src, tgt, geometry, limb, states, speeds, pelvis_delta, dt, settings):
    end_role = limb.roles[2]
    source_start_pose = src.pose.bones.get(limb.source_names[0])
    source_end_pose = src.pose.bones.get(limb.source_names[2])
    target_start_pose = tgt.pose.bones.get(limb.target_names[0])
    if not source_start_pose or not source_end_pose or not target_start_pose:
        return None
    source_space = geometry.source_space
    target_space = geometry.target_space
    source_start = _p(source_space, src.matrix_world @ source_start_pose.head)
    source_end = _p(source_space, src.matrix_world @ source_end_pose.head)
    source_end_matrix = src.matrix_world @ source_end_pose.matrix
    source_end_rotation = _r(source_space, source_end_matrix)
    target_start = _p(target_space, tgt.matrix_world @ target_start_pose.head)
    goal = generate_limb_goal(
        source_start,
        source_end,
        source_end_rotation,
        target_start,
        limb,
        pelvis_delta,
    )
    speed = speeds.get(end_role, -1.0)
    if end_role in _FOOT_ROLES:
        goal.position = constrain_goal_floor(
            goal.position,
            source_end.z,
            limb.height_offset,
            settings,
        )
        state = states.get(end_role)
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
    return goal, pole_hint, target_start_pose, speed


def _sole_estimate(tgt, limb, speed, settings):
    """Correction a contact foot would need, measured without applying it."""
    contact = _is_contact(speed, settings)
    lowest, _dom = _foot_lowest(tgt, limb)
    if not contact or lowest is None or lowest >= settings.floor_height_m:
        return 0.0, contact, lowest
    return settings.floor_height_m - lowest, contact, lowest


def _hip_delta(records, tgt, target_space):
    """Per-frame adaptive lift from the contact feet's applied sole corrections.

    "min" never straightens any leg past its uncompensated reach; "mean"
    splits the remaining knee error between two unequal contact feet.
    The result is capped by both reach bounds for every foot, swing included.
    """
    corrections = [rec[4] for rec in records if rec[5] and rec[4] > 0.0]
    if not corrections:
        return 0.0
    if EXP_HIP_MODE == "mean" and len(corrections) > 1:
        delta = sum(corrections) / len(corrections)
    else:
        delta = min(corrections)
    return _cap_delta(records, tgt, target_space, delta)


def _cap_delta(records, tgt, target_space, delta):
    """Cap a root lift so every frozen foot goal stays inside both reach bounds.

    Upper bound keeps at least 15 degrees of knee flexion from straight.
    Lower bound keeps the interior knee angle at or above 15 degrees, so a
    folded leg (ankle near or above the hip) is not folded further.
    """
    import math

    flexion = math.radians(15.0)
    for limb, goal, _pole, _start_pose, _corr, _contact in records:
        root = _p(target_space, tgt.matrix_world @ tgt.pose.bones[limb.target_names[0]].head)
        upper = limb.target_upper_length
        lower = limb.target_lower_length
        limit_max = math.sqrt(max(
            upper * upper + lower * lower + 2.0 * upper * lower * math.cos(flexion), 1e-12
        ))
        limit_min = math.sqrt(max(
            upper * upper + lower * lower - 2.0 * upper * lower * math.cos(flexion), 1e-12
        ))
        while delta > 0.0:
            raised = root + Vector((0.0, 0.0, delta))
            reach = (goal.position - raised).length
            if limit_min <= reach <= limit_max:
                break
            delta -= 0.0005
    return max(delta, 0.0)


def _raise_pelvis(tgt, geometry, target_space, delta):
    pelvis_pose = tgt.pose.bones[geometry.pelvis.target_name]
    current = _p(target_space, tgt.matrix_world @ pelvis_pose.head)
    raised = current + Vector((0.0, 0.0, delta))
    matrix = pelvis_pose.matrix.copy()
    matrix.translation = target_space.armature_position(raised)
    pelvis_pose.matrix = matrix
    bpy.context.view_layer.update()


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
    hip_done = set()
    if EXP_HIP and EXP_SOLE and _CORRECTION_PLAN is not None:
        target_space = geometry.target_space
        records = []
        for limb in geometry.limbs:
            if limb.roles[2] not in _FOOT_ROLES:
                continue
            built = _build_goal(src, tgt, geometry, limb, states, speeds, pelvis_delta, dt, settings)
            if built is None:
                continue
            goal, pole_hint, target_start_pose, speed = built
            _solve_chain(tgt, target_space, limb, goal, pole_hint=pole_hint)
            if _CONTACT_STACK_ENABLED and (limb.skin_points or limb.contact_local):
                _recheck_foot_contact(tgt, target_space, limb, goal, pole_hint, target_start_pose)
            total, contact, low0, low1 = _sole_correct(
                tgt, target_space, limb, goal, pole_hint, speed, settings
            )
            EXP_LOG.append((
                bpy.context.scene.frame_current, limb.roles[2], bool(contact),
                round(total * 1000.0, 3),
                None if low0 is None else round(low0 * 1000.0, 3),
                None if low1 is None else round(low1 * 1000.0, 3),
                round(goal.position.z * 1000.0, 3),
            ))
            records.append((limb, goal, pole_hint, target_start_pose, total, contact))
            hip_done.add(limb.roles[2])
        if EXP_ROOT_DELTA > 0.0:
            delta = _cap_delta(records, tgt, target_space, EXP_ROOT_DELTA)
        else:
            delta = _hip_delta(records, tgt, target_space)
        EXP_HIP_LOG.append((
            bpy.context.scene.frame_current,
            round(delta * 1000.0, 3),
            {rec[0].roles[2]: round(rec[4] * 1000.0, 3) for rec in records},
            {rec[0].roles[2]: bool(rec[5]) for rec in records},
        ))
        if delta > 1e-6:
            _raise_pelvis(tgt, geometry, target_space, delta)
        for limb, goal, pole_hint, target_start_pose, _total, _contact in records:
            # Frozen corrected goals: the ankle and sole stay where the sole
            # correction put them; only the leg extension changes.
            _solve_chain(tgt, target_space, limb, goal, pole_hint=pole_hint)

    for limb in geometry.limbs:
        end_role = limb.roles[2]
        if end_role in hip_done:
            continue
        source_start_pose = src.pose.bones.get(limb.source_names[0])
        source_end_pose = src.pose.bones.get(limb.source_names[2])
        target_start_pose = tgt.pose.bones.get(limb.target_names[0])
        if not source_start_pose or not source_end_pose or not target_start_pose:
            continue

        source_space = geometry.source_space
        target_space = geometry.target_space

        source_start = _p(source_space, src.matrix_world @ source_start_pose.head)
        source_end = _p(source_space, src.matrix_world @ source_end_pose.head)
        source_end_matrix = src.matrix_world @ source_end_pose.matrix
        source_end_rotation = _r(source_space, source_end_matrix)
        target_start = _p(target_space, tgt.matrix_world @ target_start_pose.head)

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

        if EXP_PRE_SOLE and _CORRECTION_PLAN is not None and end_role in _FOOT_ROLES:
            amount, contact, predicted = _pre_sole_correct(
                tgt, target_space, limb, goal,
                speeds.get(end_role, -1.0), settings,
            )
            EXP_PRE_LOG.append((
                bpy.context.scene.frame_current, end_role, bool(contact),
                round(amount * 1000.0, 3),
                None if predicted is None else round(predicted * 1000.0, 3),
                round(goal.position.z * 1000.0, 3),
            ))

        pole_hint = transfer_source_fold_pole(
            src,
            source_space,
            tgt,
            target_space,
            limb,
            goal.position,
        )
        _solve_chain(tgt, target_space, limb, goal, pole_hint=pole_hint)

        if _CONTACT_STACK_ENABLED and (EXP_KEEP_RECHECK or not EXP_PRE_SOLE) and end_role in _FOOT_ROLES and (limb.skin_points or limb.contact_local):
            _recheck_foot_contact(tgt, target_space, limb, goal, pole_hint, target_start_pose)

        if EXP_SOLE and _CORRECTION_PLAN is not None and end_role in _FOOT_ROLES and (limb.skin_points or limb.contact_local):
            total, contact, low0, low1 = _sole_correct(
                tgt, target_space, limb, goal, pole_hint,
                speeds.get(end_role, -1.0), settings,
            )
            EXP_LOG.append((
                bpy.context.scene.frame_current, end_role, bool(contact),
                round(total * 1000.0, 3),
                None if low0 is None else round(low0 * 1000.0, 3),
                None if low1 is None else round(low1 * 1000.0, 3),
                round(goal.position.z * 1000.0, 3),
            ))


def _recheck_foot_contact(tgt, target_space, limb, goal, pole_hint, target_start_pose):
    """Skin-lowest recheck, optional knee-angle push, optional precomputed lift."""
    import math

    def measure():
        if limb.skin_points:
            return _skin_lowest_world(tgt, limb.skin_points)
        pose = tgt.pose.bones[limb.target_names[2]]
        world = tgt.matrix_world
        lowest = min((world @ (pose.matrix @ point)).z for point in limb.contact_local)
        return lowest, limb.target_names[2]

    def knee_deg():
        world = tgt.matrix_world
        upper, mid, end = (world @ tgt.pose.bones[name].head for name in limb.target_names)
        first = upper - mid
        second = end - mid
        if first.length < 1e-9 or second.length < 1e-9:
            return 180.0
        return math.degrees(first.angle(second))

    corrections = 0
    raised = 0.0
    lowest, dominant = measure()
    knee = knee_deg()
    if _CORRECTION_PLAN is not None:
        planned = _CORRECTION_PLAN.get((bpy.context.scene.frame_current, limb.roles[2]))
        if planned is not None and planned.length > 1e-12:
            CONTACT_TRACE.append((
                bpy.context.scene.frame_current, limb.roles[2], -1,
                round(float(lowest), 4), round(float(planned.z), 4), round(float(knee), 3),
            ))
            goal.position = goal.position + planned
            raised += planned.z
            _solve_chain(tgt, target_space, limb, goal, pole_hint=pole_hint)
            lowest, dominant = measure()
            knee = knee_deg()
    while corrections < _CONTACT_MAX_CORRECTIONS and (
        lowest < _CONTACT_FLOOR_TOLERANCE
        or (_CONTACT_MIN_KNEE_DEG is not None and knee < _CONTACT_MIN_KNEE_DEG)
    ):
        amount = 0.0
        if lowest < _CONTACT_FLOOR_TOLERANCE:
            amount = _CONTACT_FLOOR_TOLERANCE - lowest
            if _CONTACT_MAX_RAISE is not None:
                amount = min(amount, max(0.0, _CONTACT_MAX_RAISE - raised))
            goal.position.z += amount
            raised += amount
        CONTACT_TRACE.append((
            bpy.context.scene.frame_current, limb.roles[2], corrections,
            round(float(lowest), 4), round(float(amount), 4), round(float(knee), 3),
        ))
        if _CONTACT_MIN_KNEE_DEG is not None and knee < _CONTACT_MIN_KNEE_DEG:
            root = _p(target_space, tgt.matrix_world @ target_start_pose.head)
            reach = goal.position - root
            if reach.length > 1e-9:
                upper_len = limb.target_upper_length
                lower_len = limb.target_lower_length
                needed_sq = (
                    upper_len * upper_len + lower_len * lower_len
                    - 2.0 * upper_len * lower_len * math.cos(math.radians(_CONTACT_MIN_KNEE_DEG))
                )
                needed = math.sqrt(max(needed_sq, 1e-12))
                if reach.length < needed:
                    goal.position = root + reach.normalized() * needed
        _solve_chain(tgt, target_space, limb, goal, pole_hint=pole_hint)
        corrections += 1
        lowest, dominant = measure()
        knee = knee_deg()
    CONTACT_LOG.append((
        bpy.context.scene.frame_current, limb.roles[2], corrections,
        round(float(lowest), 4), bool(lowest < _CONTACT_FLOOR_TOLERANCE), dominant,
        round(float(raised), 4), round(float(knee), 3),
    ))


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
    upper = _p(source_space, 
        src_world @ src.pose.bones[reference.source_names[0]].head
    )
    mid = _p(source_space, 
        src_world @ src.pose.bones[reference.source_names[1]].head
    )
    end = _p(source_space, 
        src_world @ src.pose.bones[reference.source_names[2]].head
    )
    src_reach = end - upper
    if src_reach.length_squared < 1e-16:
        return reference.reference_pole.copy()
    src_dir = src_reach.normalized()
    src_perp = (mid - upper) - src_dir * (mid - upper).dot(src_dir)
    tgt_world = tgt.matrix_world
    root = _p(target_space, 
        tgt_world @ tgt.pose.bones[reference.target_names[0]].head
    )
    tgt_dir = target_goal - root
    if tgt_dir.length_squared < 1e-16 or src_perp.length_squared < 1e-16:
        return bind_oriented_pole(
            root,
            target_goal,
            _p(target_space, 
                tgt_world @ tgt.data.bones[reference.target_names[0]].head_local
            ),
            _p(target_space, 
                tgt_world @ tgt.data.bones[reference.target_names[1]].head_local
            ),
            _p(target_space, 
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
    root = _p(space, world @ upper_pose.head)
    rest_root = _p(space, world @ tgt.data.bones[upper_name].head_local)
    rest_mid = _p(space, world @ tgt.data.bones[mid_name].head_local)
    rest_end = _p(space, world @ tgt.data.bones[end_name].head_local)
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
    final = _p(space, world @ end_pose.head)
    return (final - goal.position).length


def _apply_two_bone_aim(tgt, space, upper_name, mid_name, end_name, knee, reachable):
    world = tgt.matrix_world
    root = _p(space, world @ tgt.pose.bones[upper_name].head)
    _aim_joint(tgt, upper_name, mid_name, space, knee - root)
    bpy.context.view_layer.update()
    knee_now = _p(space, world @ tgt.pose.bones[mid_name].head)
    _aim_joint(tgt, mid_name, end_name, space, reachable - knee_now)
    bpy.context.view_layer.update()


def _fold_opposes_bind(tgt, space, upper_name, mid_name, end_name, rest_root, rest_mid, rest_end):
    upper = _p(space, tgt.matrix_world @ tgt.pose.bones[upper_name].head)
    mid = _p(space, tgt.matrix_world @ tgt.pose.bones[mid_name].head)
    end = _p(space, tgt.matrix_world @ tgt.pose.bones[end_name].head)
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
