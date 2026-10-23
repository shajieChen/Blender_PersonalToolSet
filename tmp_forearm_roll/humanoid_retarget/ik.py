"""Contact IK built on UE-equivalent goal, floor constraint and speed planting.

The body stays on the FK result. When foot or hand IK is on, each limb chain
gets a goal from the source chain extension ratio (not the global height
scale), feet additionally run floor + planting passes, then a two-bone
solver aims the joints at the goal.
"""

from __future__ import annotations

import bpy
from mathutils import Matrix, Quaternion, Vector

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

# Experiment log for the dual-reference anti-penetration recheck. Entries are
# (frame, role, corrections, lowest_world_z, failed). Motion-space Z equals
# world Z here because the motion space origin sits at the floor height.
CONTACT_LOG = []
_CONTACT_FLOOR_TOLERANCE = -0.001
_CONTACT_MAX_CORRECTIONS = 2
# Experimental candidate switches. None keeps the current skin-feedback scheme.
_CONTACT_MAX_RAISE = None
_CONTACT_MIN_KNEE_DEG = None
# Smooth knee preference: when set (degrees), the push toward the minimum knee
# angle fades in with a smoothstep over this band below the threshold instead
# of switching on at full strength. None keeps the hard threshold.
_CONTACT_KNEE_SMOOTH_DEG = None

# Per-iteration trace of the ground-feedback recheck:
# (frame, role, iteration, lowest_before, raise_this_iteration, knee_before).
CONTACT_TRACE = []

# Temporal-smoothing experiment: a precomputed plan mapping
# (frame, role) -> correction Vector added to the initial ankle goal before
# the safety recheck runs. Built from a full first-pass bake (see
# build_correction_plan), so it needs the whole time series and does not
# depend on evaluation order. None disables it.
_CORRECTION_PLAN = None

# Correction-plan cache. Keys are input signatures built by the bake (action
# content, frame range, rests, mapping, floor/knee/smoothing parameters and
# the algorithm version below); a plan is only reused when every input that
# can change the solve is unchanged. Bump the version on any algorithm change.
CORRECTION_PLAN_VERSION = "height-plan-v1"
_PLAN_CACHE = {}

# Scheme-A experiment: after the two-bone aim, remove the calf twist about
# the knee->ankle axis so the calf keeps the FK (bind-roll) reference instead
# of the roll composed from the two shortest-arc swings. Off by default;
# when off the solve is byte-identical to the previous behaviour.
_CALF_ROLL_FIX_ENABLED = False
# "inline" removes the roll inside every two-bone solve.
# "final" removes it after every contact pass, including the planning pass.
# "bake_lock" removes it only while a height plan is active and pins heads.
# "inherit" removes it only on the keyframe pass and leaves the foot channels
# so the foot inherits the calf rotation.
# "restore_foot" does the same, then writes the foot's local quaternion so
# its world orientation matches the pre-roll pose. Location channels stay.
_CALF_ROLL_APPLY = "inline"
# (frame, end_role, roll_before_deg, roll_after_deg) per corrected solve.
CALF_ROLL_LOG = []
# (frame, role, stage, knee_mm, ankle_mm, length_mm, pre_length_mm, chain_deg, roll_deg, bone_y_deg)
ENDPOINT_LOG = []
# (frame, role, stage, foot_deg, ankle_mm, knee_mm, length_mm, calf_loc_mm)
FOOT_POSE_LOG = []


def clear_correction_plan_cache():
    _PLAN_CACHE.clear()


def smooth_corrections_binomial(series):
    """Two passes of the [1,2,1]/4 binomial kernel over Vector series.

    Edge handling: replicate the end values (zero-slope boundary), so the
    clip start/end keep their own correction magnitude.
    """
    def one_pass(values):
        out = []
        for index, value in enumerate(values):
            prev = values[index - 1] if index > 0 else value
            nxt = values[index + 1] if index + 1 < len(values) else value
            out.append((prev + value * 2.0 + nxt) * 0.25)
        return out

    return one_pass(one_pass(list(series)))


def smooth_corrections_constrained(series, lam):
    """Joint solve: minimise sum(c-raw)^2 + lam * sum(c_t - c_{t-1})^2.

    The Z component is additionally constrained to c_z >= raw_z (never plan
    less ground correction than the per-frame feedback required); solved by
    an active-set loop over the tridiagonal normal equations. X/Y follow the
    unconstrained solve. lam is in frame^2 units.
    """
    import math

    count = len(series)
    if count == 0:
        return []

    def solve_unconstrained(raw, fixed):
        # Tridiagonal system (I + lam * D^T D) c = raw with some rows fixed.
        a = [0.0] * count
        b = [0.0] * count
        c_ = [0.0] * count
        d = [float(v) for v in raw]
        for i in range(count):
            diag = 1.0 + lam * (2.0 if 0 < i < count - 1 else 1.0)
            if count == 1:
                diag = 1.0
            a[i] = -lam if i > 0 else 0.0
            c_[i] = -lam if i < count - 1 else 0.0
            b[i] = diag
        for i in range(count):
            if i in fixed:
                a[i] = 0.0
                c_[i] = 0.0
                b[i] = 1.0
                d[i] = fixed[i]
        # Thomas algorithm.
        cp = [0.0] * count
        dp = [0.0] * count
        denom = b[0]
        cp[0] = c_[0] / denom if count > 1 else 0.0
        dp[0] = d[0] / denom
        for i in range(1, count):
            denom = b[i] - a[i] * cp[i - 1]
            cp[i] = c_[i] / denom if i < count - 1 else 0.0
            dp[i] = (d[i] - a[i] * dp[i - 1]) / denom
        out = [0.0] * count
        out[-1] = dp[-1]
        for i in range(count - 2, -1, -1):
            out[i] = dp[i] - cp[i] * out[i + 1]
        return out

    raw_z = [value.z for value in series]
    fixed = {}
    solved_z = solve_unconstrained(raw_z, fixed)
    for _ in range(count):
        violated = [i for i in range(count) if solved_z[i] < raw_z[i] - 1e-12 and i not in fixed]
        if not violated:
            break
        for i in violated:
            fixed[i] = raw_z[i]
        solved_z = solve_unconstrained(raw_z, fixed)
    solved_x = solve_unconstrained([v.x for v in series], {})
    solved_y = solve_unconstrained([v.y for v in series], {})
    from mathutils import Vector as _Vector

    return [_Vector((solved_x[i], solved_y[i], solved_z[i])) for i in range(count)]


def build_height_plan(raw_series, lowest_series):
    """Plan = raw correction + extra lift from a smoothed foot-height target.

    The desired lowest-point trajectory is the per-frame feedback result
    smoothed with the same binomial kernel, floored at the ground tolerance;
    wherever the smoothed target sits above the raw result, the difference
    is added to the correction Z (1:1 in ankle-goal Z while reachable).
    Corrections are never reduced, so ground safety is preserved.
    """
    from mathutils import Vector as _Vector

    plan = {}
    roles = sorted({role for _frame, role in raw_series})
    for role in roles:
        frames = sorted(frame for frame, r in raw_series if r == role)
        heights = [lowest_series.get((frame, role), 0.0) for frame in frames]
        smoothed = smooth_corrections_binomial(
            [_Vector((0.0, 0.0, value)) for value in heights]
        )
        for frame, target in zip(frames, smoothed):
            raw = raw_series[(frame, role)]
            extra = max(0.0, max(target.z, _CONTACT_FLOOR_TOLERANCE) - lowest_series.get((frame, role), 0.0))
            plan[(frame, role)] = raw + _Vector((0.0, 0.0, extra))
    return plan


def build_correction_plan(raw_series, mode, lam=4.0):
    """raw_series: {(frame, role): Vector correction}. Returns plan dict."""
    plan = {}
    roles = sorted({role for _frame, role in raw_series})
    for role in roles:
        frames = sorted(frame for frame, r in raw_series if r == role)
        series = [raw_series[(frame, role)] for frame in frames]
        if mode == "B":
            smoothed = smooth_corrections_binomial(series)
        elif mode == "C":
            smoothed = smooth_corrections_constrained(series, lam)
        else:
            raise ValueError(f"unknown correction smoothing mode {mode!r}")
        for frame, value in zip(frames, smoothed):
            plan[(frame, role)] = value
    return plan


def _contact_lowest_world(tgt, end_name, contact_local):
    pose = tgt.pose.bones[end_name]
    world = tgt.matrix_world
    return min((world @ (pose.matrix @ point)).z for point in contact_local)


def skin_point_world(tgt, bind_point, influences, rest_inverses=None):
    """Linear-blend-skinned world position of one bind vertex.

    Weights are normalised by their sum, matching the armature deform.
    rest_inverses optionally caches bone rest inverses by bone name.
    """
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
    """Lowest LBS world Z and the dominant bone of that vertex."""
    rest_inverses = {}
    lowest = None
    dominant = None
    for bind_point, influences in skin_points:
        point = skin_point_world(tgt, bind_point, influences, rest_inverses)
        if lowest is None or point.z < lowest:
            lowest = point.z
            dominant = max(influences, key=lambda item: item[1])[0]
    return lowest, dominant


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

        source_start = source_space.world_position(src.matrix_world @ source_start_pose.head)
        source_end = source_space.world_position(src.matrix_world @ source_end_pose.head)
        source_end_matrix = src.matrix_world @ source_end_pose.matrix
        source_end_rotation = source_space.world_rotation(source_end_matrix)
        target_start = target_space.world_position(tgt.matrix_world @ target_start_pose.head)

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

        if end_role in _FOOT_ROLES and (limb.skin_points or limb.contact_local):
            def measure():
                if limb.skin_points:
                    value, dominant = _skin_lowest_world(tgt, limb.skin_points)
                    return value, dominant
                return _contact_lowest_world(tgt, limb.target_names[2], limb.contact_local), limb.target_names[2]

            def knee_deg():
                world = tgt.matrix_world
                upper, mid, end = (world @ tgt.pose.bones[name].head for name in limb.target_names)
                first = upper - mid
                second = end - mid
                if first.length < 1e-9 or second.length < 1e-9:
                    return 180.0
                import math
                return math.degrees(first.angle(second))

            corrections = 0
            raised = 0.0
            lowest, dominant = measure()
            knee = knee_deg()
            if _CORRECTION_PLAN is not None:
                planned = _CORRECTION_PLAN.get(
                    (bpy.context.scene.frame_current, end_role)
                )
                if planned is not None and planned.length > 1e-12:
                    CONTACT_TRACE.append((
                        bpy.context.scene.frame_current, end_role, -1,
                        round(float(lowest), 4), round(float(planned.z), 4),
                        round(float(knee), 3),
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
                    bpy.context.scene.frame_current, end_role, corrections,
                    round(float(lowest), 4), round(float(amount), 4),
                    round(float(knee), 3),
                ))
                if _CONTACT_MIN_KNEE_DEG is not None and knee < _CONTACT_MIN_KNEE_DEG:
                    import math
                    root = target_space.world_position(tgt.matrix_world @ target_start_pose.head)
                    reach = goal.position - root
                    if reach.length > 1e-9:
                        upper_len = limb.target_upper_length
                        lower_len = limb.target_lower_length
                        target_deg = _CONTACT_MIN_KNEE_DEG
                        if _CONTACT_KNEE_SMOOTH_DEG:
                            deficit = _CONTACT_MIN_KNEE_DEG - knee
                            blend = min(1.0, max(0.0, deficit / _CONTACT_KNEE_SMOOTH_DEG))
                            blend = blend * blend * (3.0 - 2.0 * blend)
                            target_deg = knee + blend * deficit
                        needed_sq = (
                            upper_len * upper_len + lower_len * lower_len
                            - 2.0 * upper_len * lower_len * math.cos(math.radians(target_deg))
                        )
                        needed = math.sqrt(max(needed_sq, 1e-12))
                        if reach.length < needed:
                            goal.position = root + reach.normalized() * needed
                _solve_chain(tgt, target_space, limb, goal, pole_hint=pole_hint)
                corrections += 1
                lowest, dominant = measure()
                knee = knee_deg()
            CONTACT_LOG.append((
                bpy.context.scene.frame_current,
                end_role,
                corrections,
                round(float(lowest), 4),
                bool(lowest < _CONTACT_FLOOR_TOLERANCE),
                dominant,
                round(float(raised), 4),
                round(float(knee), 3),
            ))

        if _calf_roll_final_now() and end_role in _FOOT_ROLES:
            _apply_calf_roll_final(
                tgt, target_space, limb, goal,
                lock_endpoints=(_CALF_ROLL_APPLY == "bake_lock"),
                keep_foot=(_CALF_ROLL_APPLY == "inherit"),
                restore_foot=(_CALF_ROLL_APPLY == "restore_foot"),
            )


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
    upper = source_space.world_position(
        src_world @ src.pose.bones[reference.source_names[0]].head
    )
    mid = source_space.world_position(
        src_world @ src.pose.bones[reference.source_names[1]].head
    )
    end = source_space.world_position(
        src_world @ src.pose.bones[reference.source_names[2]].head
    )
    src_reach = end - upper
    if src_reach.length_squared < 1e-16:
        return reference.reference_pole.copy()
    src_dir = src_reach.normalized()
    src_perp = (mid - upper) - src_dir * (mid - upper).dot(src_dir)
    tgt_world = tgt.matrix_world
    root = target_space.world_position(
        tgt_world @ tgt.pose.bones[reference.target_names[0]].head
    )
    tgt_dir = target_goal - root
    if tgt_dir.length_squared < 1e-16 or src_perp.length_squared < 1e-16:
        return bind_oriented_pole(
            root,
            target_goal,
            target_space.world_position(
                tgt_world @ tgt.data.bones[reference.target_names[0]].head_local
            ),
            target_space.world_position(
                tgt_world @ tgt.data.bones[reference.target_names[1]].head_local
            ),
            target_space.world_position(
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


def _chain_roll_deg(tgt, mid_name, end_name):
    """Signed twist (deg) of the mid bone about the mid->end chain axis.

    Computed on the armature-space rest-relative rotation (pose matrix
    relative to the bone rest matrix). The object transform is a similarity
    (rotation + uniform scale), so the same signed angle is obtained from
    world matrices; no local Euler/Y component is used.
    """
    import math

    mid_pose = tgt.pose.bones[mid_name]
    end_pose = tgt.pose.bones[end_name]
    axis = end_pose.head - mid_pose.head
    if axis.length < 1e-9:
        return 0.0
    axis.normalize()
    rest = mid_pose.bone.matrix_local.to_3x3()
    delta = (mid_pose.matrix.to_3x3() @ rest.inverted()).to_quaternion().normalized()
    if delta.w < 0.0:
        delta.negate()
    vector = Vector((delta.x, delta.y, delta.z))
    projected = axis * vector.dot(axis)
    twist = Quaternion((delta.w, projected.x, projected.y, projected.z))
    if twist.magnitude < 1e-10:
        return 0.0
    twist.normalize()
    angle = 2.0 * math.degrees(math.acos(max(-1.0, min(1.0, abs(twist.w)))))
    if Vector((twist.x, twist.y, twist.z)).dot(axis) < 0.0:
        angle = -angle
    return angle


def _remove_calf_roll(tgt, mid_name, end_name):
    """Rotate the mid bone about its own chain axis until its roll is zero.

    The pivot is the mid (knee) head and the rotation axis is the current
    knee->ankle direction, so neither joint position nor the chain direction
    moves; only the axial roll changes. The correction is the inverse of
    the Swing-Twist twist component of the rest-relative rotation about
    that same axis, which adds linearly to the measured roll.
    """
    mid_pose = tgt.pose.bones[mid_name]
    end_pose = tgt.pose.bones[end_name]
    axis = end_pose.head - mid_pose.head
    if axis.length < 1e-9:
        return
    axis.normalize()
    matrix = mid_pose.matrix.copy()
    rest = mid_pose.bone.matrix_local.to_3x3()
    delta = (matrix.to_3x3() @ rest.inverted()).to_quaternion().normalized()
    if delta.w < 0.0:
        delta.negate()
    vector = Vector((delta.x, delta.y, delta.z))
    projected = axis * vector.dot(axis)
    twist = Quaternion((delta.w, projected.x, projected.y, projected.z))
    if twist.magnitude < 1e-10:
        return
    twist.normalize()
    pivot = matrix.translation.copy()
    mid_pose.matrix = (
        Matrix.Translation(pivot)
        @ twist.inverted().to_matrix().to_4x4()
        @ Matrix.Translation(-pivot)
        @ matrix
    )


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
    root = space.world_position(world @ upper_pose.head)
    rest_root = space.world_position(world @ tgt.data.bones[upper_name].head_local)
    rest_mid = space.world_position(world @ tgt.data.bones[mid_name].head_local)
    rest_end = space.world_position(world @ tgt.data.bones[end_name].head_local)
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

    if _CALF_ROLL_FIX_ENABLED and _CALF_ROLL_APPLY == "inline" and end_role in _FOOT_ROLES:
        roll_before = _chain_roll_deg(tgt, mid_name, end_name)
        _remove_calf_roll(tgt, mid_name, end_name)
        bpy.context.view_layer.update()
        CALF_ROLL_LOG.append((
            bpy.context.scene.frame_current, end_role,
            round(roll_before, 3),
            round(_chain_roll_deg(tgt, mid_name, end_name), 3),
        ))

    _write_end_rotation(tgt, end_name, space, goal.rotation)
    bpy.context.view_layer.update()

    end_pose = tgt.pose.bones[end_name]
    final = space.world_position(world @ end_pose.head)
    return (final - goal.position).length


def _calf_roll_final_now():
    """True when this contact pass should deroll after the feedback loop."""
    if not _CALF_ROLL_FIX_ENABLED:
        return False
    if _CALF_ROLL_APPLY == "final":
        return True
    if _CALF_ROLL_APPLY in ("bake_lock", "inherit", "restore_foot"):
        return _CORRECTION_PLAN is not None
    return False


def _quat_deg(a, b):
    import math

    dot = abs(max(-1.0, min(1.0, a.dot(b))))
    return math.degrees(2.0 * math.acos(dot))


def _local_quaternion_for_pose_orient(pose_bone, armature_orient):
    """Local quaternion whose pose matrix matches an armature-space orientation.

    Uses the same parent and rest composition as the retarget orientation
    write. The world quaternion is not assigned to the local channel.
    """
    rest = pose_bone.bone.matrix_local.to_quaternion().to_matrix()
    parent = pose_bone.parent
    if parent is not None:
        basis = (
            rest.inverted()
            @ parent.bone.matrix_local.to_quaternion().to_matrix()
            @ parent.matrix.to_quaternion().to_matrix().inverted()
            @ armature_orient
        )
    else:
        basis = rest.inverted() @ armature_orient
    quat = basis.to_quaternion()
    if quat.w < 0.0:
        quat.negate()
    return quat


def _world_head(world, pose_bone):
    return (world @ pose_bone.head).copy()


def _chain_metrics(world, mid_pose, end_pose, knee_world, ankle_world):
    import math

    knee = _world_head(world, mid_pose)
    ankle = _world_head(world, end_pose)
    length = (ankle - knee).length
    chain_now = ankle - knee
    chain_ref = ankle_world - knee_world
    if chain_now.length < 1e-9 or chain_ref.length < 1e-9:
        chain_deg = 0.0
    else:
        chain_deg = math.degrees(chain_now.angle(chain_ref))
    bone_y = mid_pose.matrix.to_3x3() @ Vector((0.0, 1.0, 0.0))
    chain_arm = end_pose.head - mid_pose.head
    if bone_y.length < 1e-9 or chain_arm.length < 1e-9:
        bone_y_deg = 0.0
    else:
        bone_y_deg = math.degrees(bone_y.angle(chain_arm))
    return knee, ankle, length, chain_deg, bone_y_deg


def _pin_head_world(pose_bone, world, world_point):
    """Keep this bone's current orientation and put its head back on a world point."""
    matrix = pose_bone.matrix.copy()
    matrix.translation = world.inverted() @ world_point
    pose_bone.matrix = matrix


def _foot_pose_delta(world, end_pose, saved_world, saved_knee, saved_ankle, saved_calf_loc, mid_pose):
    now_world = world @ end_pose.matrix
    knee = _world_head(world, mid_pose)
    ankle = _world_head(world, end_pose)
    return (
        round(_quat_deg(now_world.to_quaternion(), saved_world.to_quaternion()), 4),
        round((ankle - saved_ankle).length * 1000.0, 4),
        round((knee - saved_knee).length * 1000.0, 4),
        round((ankle - knee).length * 1000.0, 4),
        round((mid_pose.location - saved_calf_loc).length * 1000.0, 4),
    )


def _apply_calf_roll_final(tgt, space, reference, goal, lock_endpoints=False, keep_foot=False, restore_foot=False):
    """Remove calf roll after contact IK, then put the knee and ankle back.

    The swing-twist is about the knee-to-ankle axis in armature space. The
    calf bone's local Y is not that axis, so updating the parent moves the
    foot head. Locking writes the pre-roll world knee and ankle back into
    the pose matrices without changing the rest bone length. The foot
    orientation is still the IK goal. No skin measurement or contact pass
    follows.
    """
    mid_name = reference.target_names[1]
    end_name = reference.target_names[2]
    mid_pose = tgt.pose.bones[mid_name]
    end_pose = tgt.pose.bones[end_name]
    world = tgt.matrix_world
    knee_world = _world_head(world, mid_pose)
    ankle_world = _world_head(world, end_pose)
    saved_pose = end_pose.matrix.copy()
    saved_world = (world @ end_pose.matrix).copy()
    saved_loc = end_pose.location.copy()
    saved_calf_loc = mid_pose.location.copy()
    pre_length_mm = round((ankle_world - knee_world).length * 1000.0, 4)
    roll_before = _chain_roll_deg(tgt, mid_name, end_name)
    _remove_calf_roll(tgt, mid_name, end_name)
    bpy.context.view_layer.update()
    if keep_foot or restore_foot:
        foot_deg, ankle_mm, knee_mm, length_mm, calf_loc_mm = _foot_pose_delta(
            world, end_pose, saved_world, knee_world, ankle_world, saved_calf_loc, mid_pose,
        )
        FOOT_POSE_LOG.append((
            bpy.context.scene.frame_current, reference.roles[2], "inherited",
            foot_deg, ankle_mm, knee_mm, length_mm, calf_loc_mm,
        ))
        if restore_foot:
            end_pose.rotation_mode = "QUATERNION"
            end_pose.rotation_quaternion = _local_quaternion_for_pose_orient(
                end_pose, saved_pose.to_quaternion().to_matrix(),
            )
            end_pose.location = saved_loc
            bpy.context.view_layer.update()
            foot_deg, ankle_mm, knee_mm, length_mm, calf_loc_mm = _foot_pose_delta(
                world, end_pose, saved_world, knee_world, ankle_world, saved_calf_loc, mid_pose,
            )
            FOOT_POSE_LOG.append((
                bpy.context.scene.frame_current, reference.roles[2], "restored",
                foot_deg, ankle_mm, knee_mm, length_mm, calf_loc_mm,
            ))
    elif lock_endpoints:
        _knee, _ankle, length, chain_deg, bone_y_deg = _chain_metrics(
            world, mid_pose, end_pose, knee_world, ankle_world,
        )
        ENDPOINT_LOG.append((
            bpy.context.scene.frame_current, reference.roles[2], "drift",
            round((_knee - knee_world).length * 1000.0, 4),
            round((_ankle - ankle_world).length * 1000.0, 4),
            round(length * 1000.0, 4),
            pre_length_mm,
            round(chain_deg, 4),
            round(_chain_roll_deg(tgt, mid_name, end_name), 4),
            round(bone_y_deg, 3),
        ))
        _pin_head_world(mid_pose, world, knee_world)
        bpy.context.view_layer.update()
        _write_end_rotation(tgt, end_name, space, goal.rotation)
        _pin_head_world(end_pose, world, ankle_world)
        bpy.context.view_layer.update()
        _knee, _ankle, length, chain_deg, bone_y_deg = _chain_metrics(
            world, mid_pose, end_pose, knee_world, ankle_world,
        )
        ENDPOINT_LOG.append((
            bpy.context.scene.frame_current, reference.roles[2], "locked",
            round((_knee - knee_world).length * 1000.0, 4),
            round((_ankle - ankle_world).length * 1000.0, 4),
            round(length * 1000.0, 4),
            pre_length_mm,
            round(chain_deg, 4),
            round(_chain_roll_deg(tgt, mid_name, end_name), 4),
            round(bone_y_deg, 3),
        ))
    else:
        _write_end_rotation(tgt, end_name, space, goal.rotation)
        bpy.context.view_layer.update()
    CALF_ROLL_LOG.append((
        bpy.context.scene.frame_current, reference.roles[2],
        round(roll_before, 3),
        round(_chain_roll_deg(tgt, mid_name, end_name), 3),
    ))


def _apply_two_bone_aim(tgt, space, upper_name, mid_name, end_name, knee, reachable):
    world = tgt.matrix_world
    root = space.world_position(world @ tgt.pose.bones[upper_name].head)
    _aim_joint(tgt, upper_name, mid_name, space, knee - root)
    bpy.context.view_layer.update()
    knee_now = space.world_position(world @ tgt.pose.bones[mid_name].head)
    _aim_joint(tgt, mid_name, end_name, space, reachable - knee_now)
    bpy.context.view_layer.update()


def _fold_opposes_bind(tgt, space, upper_name, mid_name, end_name, rest_root, rest_mid, rest_end):
    upper = space.world_position(tgt.matrix_world @ tgt.pose.bones[upper_name].head)
    mid = space.world_position(tgt.matrix_world @ tgt.pose.bones[mid_name].head)
    end = space.world_position(tgt.matrix_world @ tgt.pose.bones[end_name].head)
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
