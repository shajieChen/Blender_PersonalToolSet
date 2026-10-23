from dataclasses import dataclass
from math import cos, pi, sqrt

from mathutils import Matrix, Quaternion, Vector

LENGTH_EPSILON_M = 1e-8
DIRECTION_EPSILON = 1e-8
SCALE_EPSILON = 1e-8
FIXED_HZ = 60
FIXED_DT = 1.0 / FIXED_HZ
WORLD = "WORLD"
FOLLOW_TRANSLATION = "FOLLOW_TRANSLATION"

_AXIS_X = Vector((1.0, 0.0, 0.0))
_AXIS_Y = Vector((0.0, 1.0, 0.0))
_AXIS_Z = Vector((0.0, 0.0, 1.0))
_FALLBACK_AXES = (_AXIS_X, _AXIS_Y, _AXIS_Z)


class SpringBoneError(Exception):
    pass


@dataclass
class ChainParameters:
    stiffness: float
    drag_force: float
    gravity_power: float
    gravity_dir: Vector
    hit_radius_m: float
    weight: float
    cone_enabled: bool
    cone_angle_rad: float


@dataclass
class SegmentState:
    length_m: float
    previous_tail_m: Vector
    current_tail_m: Vector
    last_direction: Vector
    last_radial: Vector


@dataclass
class SegmentSample:
    base_pose: Matrix


@dataclass
class SphereCollider:
    center_m: Vector
    radius_m: float


@dataclass
class CapsuleCollider:
    start_m: Vector
    end_m: Vector
    radius_m: float


def direction_or_fallback(candidate, last_direction, fallback):
    for vector in (candidate, last_direction, fallback, _AXIS_Y):
        if vector is None:
            continue
        length = vector.length
        if length > DIRECTION_EPSILON:
            return vector / length
    return _AXIS_Y.copy()


def perpendicular_axis(direction):
    for axis in _FALLBACK_AXES:
        crossed = direction.cross(axis)
        if crossed.length > DIRECTION_EPSILON:
            return crossed.normalized()
    return _AXIS_X.copy()


def collision_direction(delta, reference_direction, last_radial, axis=None):
    if axis is not None and axis.length > DIRECTION_EPSILON:
        axis_normal = axis.normalized()

        def reject(vector):
            if vector is None or vector.length <= DIRECTION_EPSILON:
                return None
            tangential = vector - axis_normal * vector.dot(axis_normal)
            if tangential.length <= DIRECTION_EPSILON:
                return None
            return tangential.normalized()

        for vector in (delta, last_radial, reference_direction, *_FALLBACK_AXES):
            chosen = reject(vector)
            if chosen is not None:
                return chosen
        return perpendicular_axis(axis_normal)
    if delta is not None and delta.length > LENGTH_EPSILON_M:
        return delta.normalized()
    if last_radial is not None and last_radial.length > DIRECTION_EPSILON:
        return last_radial.normalized()
    if reference_direction is not None and reference_direction.length > DIRECTION_EPSILON:
        return reference_direction.normalized()
    return _AXIS_X.copy()


def _nearest_on_capsule(point, collider):
    axis = collider.end_m - collider.start_m
    if axis.length_squared <= LENGTH_EPSILON_M * LENGTH_EPSILON_M:
        return collider.start_m.copy(), None
    ratio = (point - collider.start_m).dot(axis) / axis.length_squared
    if ratio < 0.0:
        ratio = 0.0
    elif ratio > 1.0:
        ratio = 1.0
    return collider.start_m + axis * ratio, axis


def signed_collider_distance(point, collider, hit_radius_m):
    if isinstance(collider, SphereCollider):
        return (point - collider.center_m).length - collider.radius_m - hit_radius_m
    nearest, _axis = _nearest_on_capsule(point, collider)
    return (point - nearest).length - collider.radius_m - hit_radius_m


def push_collider(point, collider, hit_radius_m, reference_direction, last_radial):
    if isinstance(collider, SphereCollider):
        delta = point - collider.center_m
        direction = collision_direction(delta, reference_direction, last_radial, None)
        signed = delta.length - collider.radius_m - hit_radius_m
    else:
        nearest, axis = _nearest_on_capsule(point, collider)
        delta = point - nearest
        direction = collision_direction(delta, reference_direction, last_radial, axis)
        signed = delta.length - collider.radius_m - hit_radius_m
    if signed < 0.0:
        return point - direction * signed, signed
    return point.copy(), signed


def cone_clamp_direction(direction, axis, limit_angle):
    axis_normal = direction_or_fallback(axis, _AXIS_Y, _AXIS_Y)
    source = direction_or_fallback(direction, axis_normal, axis_normal)
    align = _AXIS_Y.rotation_difference(axis_normal)
    local = align.inverted() @ source
    cos_limit = cos(limit_angle)
    if local.y >= cos_limit:
        return source
    sin_limit = sqrt(max(0.0, 1.0 - cos_limit * cos_limit))
    horizontal_sq = local.x * local.x + local.z * local.z
    if horizontal_sq <= DIRECTION_EPSILON * DIRECTION_EPSILON:
        local = Vector((0.0, cos_limit, sin_limit))
    else:
        scale = sin_limit / sqrt(horizontal_sq)
        local = Vector((local.x * scale, cos_limit, local.z * scale))
    return (align @ local).normalized()


def swing_with_twist(reference_rotation, simulated_direction):
    reference = reference_rotation.normalized()
    reference_y = reference @ _AXIS_Y
    reference_y = direction_or_fallback(reference_y, _AXIS_Y, _AXIS_Y)
    target = direction_or_fallback(simulated_direction, reference_y, reference_y)
    dot = reference_y.dot(target)
    if dot < -1.0 + DIRECTION_EPSILON:
        swing = Quaternion(perpendicular_axis(reference_y), pi)
    else:
        swing = reference_y.rotation_difference(target)
    return (swing @ reference).normalized()


def included_tick_count(frame_span, fps, fps_base):
    span = int(frame_span)
    rate = int(fps)
    base = int(round(float(fps_base)))
    if span < 0 or rate <= 0 or base <= 0:
        raise SpringBoneError("帧跨度无效")
    return (FIXED_HZ * span * base) // rate + 1


def frame_for_tick(start_frame, tick, fps, fps_base):
    rate = float(fps)
    base = float(fps_base)
    return float(start_frame) + (float(tick) * rate) / (float(FIXED_HZ) * base)


def validate_parameters(parameters):
    names = (
        parameters.stiffness,
        parameters.drag_force,
        parameters.gravity_power,
        parameters.hit_radius_m,
        parameters.weight,
        parameters.cone_angle_rad,
    )
    if any(value != value or value in (float("inf"), float("-inf")) for value in names):
        raise SpringBoneError("参数不是有限数")
    if parameters.stiffness < 0.0 or parameters.gravity_power < 0.0 or parameters.hit_radius_m < 0.0:
        raise SpringBoneError("参数不能为负")
    if parameters.drag_force < 0.0 or parameters.drag_force > 1.0:
        raise SpringBoneError("拖曳超出范围")
    if parameters.weight < 0.0 or parameters.weight > 1.0:
        raise SpringBoneError("混合超出范围")
    if parameters.cone_enabled and (
        parameters.cone_angle_rad < 0.0 or parameters.cone_angle_rad > pi
    ):
        raise SpringBoneError("锥角超出范围")
    if parameters.gravity_dir.length <= DIRECTION_EPSILON and parameters.gravity_power > 0.0:
        raise SpringBoneError("重力方向无效")


def matrix_has_supported_scale(matrix):
    linear = matrix.to_3x3()
    columns = [linear.col[index] for index in range(3)]
    lengths = [column.length for column in columns]
    if any(length <= SCALE_EPSILON for length in lengths):
        return False
    if abs(lengths[0] - lengths[1]) > SCALE_EPSILON or abs(lengths[0] - lengths[2]) > SCALE_EPSILON:
        return False
    if abs(columns[0].normalized().dot(columns[1].normalized())) > 1e-5:
        return False
    if abs(columns[0].normalized().dot(columns[2].normalized())) > 1e-5:
        return False
    if abs(columns[1].normalized().dot(columns[2].normalized())) > 1e-5:
        return False
    return linear.determinant() > 0.0


def _place_on_length(head, candidate, length, last_direction, fallback):
    direction = direction_or_fallback(candidate - head, last_direction, fallback)
    return head + direction * length, direction


def _apply_cone(head, tail, axis, length, angle, last_direction):
    direction = cone_clamp_direction(tail - head, axis, angle)
    if direction.length <= DIRECTION_EPSILON:
        direction = direction_or_fallback(last_direction, axis, _AXIS_Y)
    return head + direction * length


def reference_pose(index, samples, parent_base, parent_solved, solved_parent):
    base = samples[index].base_pose
    if index == 0:
        return parent_solved @ parent_base.inverted_safe() @ base
    previous = samples[index - 1].base_pose
    return solved_parent @ previous.inverted_safe() @ base


def solved_pose_matrix(world_rotation, reference_object, armature_world):
    object_rotation = armature_world.to_quaternion().inverted() @ world_rotation
    return Matrix.LocRotScale(
        reference_object.to_translation(),
        object_rotation.normalized(),
        reference_object.to_scale(),
    )


def step_chain(
    states,
    samples,
    parent_base,
    parent_solved,
    armature_world,
    scale_length,
    parameters,
    colliders,
    translation_delta_m=None,
    solved_bones=None,
):
    validate_parameters(parameters)
    if scale_length <= 0.0 or scale_length != scale_length:
        raise SpringBoneError("场景单位比例无效")
    if translation_delta_m is not None:
        for state in states:
            state.previous_tail_m = state.previous_tail_m + translation_delta_m
            state.current_tail_m = state.current_tail_m + translation_delta_m
    gravity = parameters.gravity_dir
    gravity_dir = Vector((0.0, 0.0, 0.0)) if gravity.length <= DIRECTION_EPSILON else gravity.normalized()
    solved_parent = parent_solved.copy()
    rotations = []
    for index, state in enumerate(states):
        reference = reference_pose(index, samples, parent_base, parent_solved, solved_parent)
        world = armature_world @ reference
        head = world.to_translation() * scale_length
        reference_rotation = world.to_quaternion().normalized()
        reference_direction = direction_or_fallback(reference_rotation @ _AXIS_Y, _AXIS_Y, _AXIS_Y)
        if parameters.weight <= 0.0:
            tail = head + reference_direction * state.length_m
            state.previous_tail_m = tail.copy()
            state.current_tail_m = tail.copy()
            state.last_direction = reference_direction.copy()
            rotation = reference_rotation
        else:
            previous = state.current_tail_m.copy()
            inertia = (state.current_tail_m - state.previous_tail_m) * (1.0 - parameters.drag_force)
            stiffness = reference_direction * FIXED_DT * parameters.stiffness
            external = gravity_dir * FIXED_DT * parameters.gravity_power
            candidate = state.current_tail_m + inertia + stiffness + external
            tail, state.last_direction = _place_on_length(
                head, candidate, state.length_m, state.last_direction, reference_direction
            )
            if parameters.cone_enabled:
                tail = _apply_cone(
                    head, tail, reference_direction, state.length_m, parameters.cone_angle_rad, state.last_direction
                )
                state.last_direction = direction_or_fallback(tail - head, state.last_direction, reference_direction)
            for collider in colliders:
                before = tail.copy()
                tail, signed = push_collider(
                    tail, collider, parameters.hit_radius_m, reference_direction, state.last_radial
                )
                if signed < 0.0:
                    state.last_radial = direction_or_fallback(tail - before, state.last_radial, reference_direction)
                tail, state.last_direction = _place_on_length(
                    head, tail, state.length_m, state.last_direction, reference_direction
                )
                if parameters.cone_enabled:
                    tail = _apply_cone(
                        head,
                        tail,
                        reference_direction,
                        state.length_m,
                        parameters.cone_angle_rad,
                        state.last_direction,
                    )
                    state.last_direction = direction_or_fallback(
                        tail - head, state.last_direction, reference_direction
                    )
            state.previous_tail_m = previous
            state.current_tail_m = tail.copy()
            simulated = swing_with_twist(reference_rotation, state.last_direction)
            if parameters.weight >= 1.0:
                rotation = simulated
            else:
                rotation = reference_rotation.slerp(simulated, parameters.weight).normalized()
        rotations.append(rotation)
        if 0.0 < parameters.weight < 1.0:
            mixed_direction = direction_or_fallback(rotation @ _AXIS_Y, state.last_direction, reference_direction)
            state.current_tail_m = head + mixed_direction * state.length_m
            state.last_direction = mixed_direction
        parent_matrix = solved_parent
        solved_parent = solved_pose_matrix(rotation, reference, armature_world)
        if solved_bones is not None:
            solved_bones.append((solved_parent, parent_matrix))
    return rotations
