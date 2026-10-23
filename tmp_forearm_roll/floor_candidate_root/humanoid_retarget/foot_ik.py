"""UE-equivalent foot-IK numerics: goal, pelvis, floor, planting, spring.

Pure mathutils module: no bpy, no UI, no retarget imports.
Formulas follow UE 5.7.4 IKRig sources cited in docs/design/design_foot_ik.md.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from mathutils import Quaternion, Vector


@dataclass
class FootIKSettings:
    floor_enabled: bool = True
    floor_alpha: float = 1.0
    maintain_height_offset: float = 1.0
    falloff_start_m: float = 0.08
    falloff_distance_m: float = 0.20
    pelvis_floor_weight: float = 1.0
    source_crotch_offset_m: float = 0.0
    target_crotch_offset_m: float = 0.0
    planting_enabled: bool = True
    speed_threshold_mps: float = 0.15
    stiffness: float = 250.0
    critical_damping: float = 1.0
    contact_window_s: float = 0.08
    contact_height_tolerance_m: float = 0.02
    contact_minimum_tolerance_m: float = 0.01
    floor_height_m: float = 0.0


@dataclass
class PelvisReference:
    source_name: str
    target_name: str
    source_position: Vector
    target_position: Vector
    inverse_source_height: float
    xy_offset: Vector
    # Ground datum captured at rig registration, in armature-local terms:
    # the reference hips heights above the captured ground plane (meters).
    # source_datum_matrix/scale convert a source armature-local point to
    # its datum height. All three are None when no datum was captured;
    # the pelvis mapping then keeps the legacy motion-space formula.
    source_datum_height: float | None = None
    target_datum_height: float | None = None
    source_datum_matrix: object = None
    source_datum_scale: float = 1.0


@dataclass
class LimbReference:
    roles: tuple
    source_names: tuple
    target_names: tuple
    source_initial_length: float
    target_initial_length: float
    target_upper_length: float
    target_lower_length: float
    source_end_rotation: Quaternion
    target_end_rotation: Quaternion
    height_offset: float
    source_rest_end_height: float
    reference_pole: Vector
    contact_local: tuple = ()
    skin_points: tuple = ()


@dataclass
class IKGoal:
    position: Vector
    rotation: Quaternion


@dataclass
class VectorSpringState:
    velocity: Vector = field(default_factory=lambda: Vector((0.0, 0.0, 0.0)))
    previous_target: Vector = field(default_factory=lambda: Vector((0.0, 0.0, 0.0)))
    previous_target_valid: bool = False

    def reset(self):
        self.velocity = Vector((0.0, 0.0, 0.0))
        self.previous_target = Vector((0.0, 0.0, 0.0))
        self.previous_target_valid = False


@dataclass
class LimbPlantState:
    previous_goal: Vector
    spring: VectorSpringState = field(default_factory=VectorSpringState)


@dataclass
class RetargetGeometry:
    source_space: object
    target_space: object
    pelvis: PelvisReference
    limbs: tuple


def validate_foot_ik_settings(settings: FootIKSettings) -> None:
    numeric = (
        settings.floor_alpha,
        settings.maintain_height_offset,
        settings.falloff_start_m,
        settings.falloff_distance_m,
        settings.pelvis_floor_weight,
        settings.source_crotch_offset_m,
        settings.target_crotch_offset_m,
        settings.speed_threshold_mps,
        settings.stiffness,
        settings.critical_damping,
        settings.contact_window_s,
        settings.contact_height_tolerance_m,
        settings.contact_minimum_tolerance_m,
        settings.floor_height_m,
    )
    if not all(math.isfinite(value) for value in numeric):
        raise ValueError("foot IK parameters must be finite")
    for weight in (settings.floor_alpha, settings.maintain_height_offset, settings.pelvis_floor_weight):
        if not 0.0 <= weight <= 1.0:
            raise ValueError("foot IK blend weights must stay within 0..1")
    for length in (
        settings.falloff_start_m,
        settings.falloff_distance_m,
        settings.speed_threshold_mps,
        settings.stiffness,
        settings.critical_damping,
        settings.contact_window_s,
        settings.contact_height_tolerance_m,
        settings.contact_minimum_tolerance_m,
    ):
        if length < 0.0:
            raise ValueError("foot IK magnitudes must be non-negative")
    if settings.critical_damping > 1.0:
        raise ValueError("critical damping is capped at 1.0")


def retarget_pelvis_position(
    current: Vector,
    reference: PelvisReference,
    settings: FootIKSettings,
    in_place: bool,
    current_datum_z=None,
):
    # Datum mapping: ratio, percent and constrained height all use heights
    # above each rig's captured ground datum (armature-local, captured at
    # registration). The result is a height above the ground, which the
    # motion space then places relative to the configured floor exactly
    # once; neither the floor height nor the object transform enters here.
    if (
        reference.source_datum_height is not None
        and reference.target_datum_height is not None
        and current_datum_z is not None
    ):
        source_height = reference.source_datum_height
        target_height = reference.target_datum_height
        current_z = current_datum_z
        if abs(source_height) > 1e-9:
            ratio = target_height / source_height
        else:
            ratio = (
                reference.target_position.z
                * reference.inverse_source_height
            )
        base = current.copy()
        base.x *= ratio
        base.y *= ratio
        base.z = current_z * ratio

        if abs(settings.pelvis_floor_weight) > 1e-8:
            if current_z <= source_height:
                source_initial_crotch = (
                    source_height
                    - settings.source_crotch_offset_m
                )
                source_current_crotch = (
                    current_z - settings.source_crotch_offset_m
                )
                percent = source_current_crotch / max(
                    0.01, source_initial_crotch
                )
                constrained = (
                    (
                        target_height
                        - settings.target_crotch_offset_m
                    ) * percent
                    + settings.target_crotch_offset_m
                )
            else:
                constrained = (
                    current_z
                    + target_height
                    - source_height
                )
            base.z += (
                constrained - base.z
            ) * settings.pelvis_floor_weight

        position = base.copy()
        position.x += reference.xy_offset.x
        position.y += reference.xy_offset.y

        if in_place:
            position.x = reference.target_position.x
            position.y = reference.target_position.y

        return position, position - base

    # Legacy motion-space mapping (no captured datum): unchanged formula.
    ratio = (
        reference.target_position.z
        * reference.inverse_source_height
    )
    base = current.copy() * ratio

    if abs(settings.pelvis_floor_weight) > 1e-8:
        if current.z <= reference.source_position.z:
            source_initial_crotch = (
                reference.source_position.z
                - settings.source_crotch_offset_m
            )
            source_current_crotch = (
                current.z - settings.source_crotch_offset_m
            )
            percent = source_current_crotch / max(
                0.01, source_initial_crotch
            )
            constrained = (
                reference.target_position.z
                - settings.target_crotch_offset_m
            ) * percent + settings.target_crotch_offset_m
        else:
            constrained = (
                current.z
                + reference.target_position.z
                - reference.source_position.z
            )
        base.z += (
            constrained - base.z
        ) * settings.pelvis_floor_weight

    position = base.copy()
    position.x += reference.xy_offset.x
    position.y += reference.xy_offset.y

    if in_place:
        position.x = reference.target_position.x
        position.y = reference.target_position.y

    return position, position - base


def generate_limb_goal(
    source_start: Vector,
    source_end: Vector,
    source_end_rotation: Quaternion,
    target_start: Vector,
    reference: LimbReference,
    pelvis_delta: Vector,
) -> IKGoal:
    vector = source_end - source_start
    length = vector.length

    if length > 1e-10:
        direction = vector / length
    else:
        direction = Vector((0.0, 0.0, 0.0))

    normalized_length = length / reference.source_initial_length
    inverse_affect = Vector((0.0, 0.0, 1.0))
    correction = Vector(tuple(
        pelvis_delta[i] * inverse_affect[i]
        for i in range(3)
    ))
    start = target_start - correction
    position = start + direction * (
        normalized_length * reference.target_initial_length
    )

    delta = (
        source_end_rotation
        @ reference.source_end_rotation.inverted()
    ).normalized()
    rotation = (
        delta @ reference.target_end_rotation
    ).normalized()

    return IKGoal(position, rotation)


def constrain_goal_floor(
    goal: Vector,
    source_end_z: float,
    reference_height_offset: float,
    settings: FootIKSettings,
) -> Vector:
    result = goal.copy()
    if not settings.floor_enabled:
        return result

    height = abs(source_end_z)
    start = settings.falloff_start_m
    end = start + max(0.0, settings.falloff_distance_m)

    if height >= end:
        return result

    falloff_range = max(0.01, end - start)
    falloff = (
        1.0 if height < start
        else 1.0 - (height - start) / falloff_range
    )
    weight = falloff * settings.floor_alpha
    target_height = height + (
        reference_height_offset
        * settings.maintain_height_offset
    )
    result.z += (target_height - result.z) * weight
    return result


def inverse_exp_approx(value: float) -> float:
    return 1.0 / (
        1.0
        + 1.00746054 * value
        + 0.45053901 * value * value
        + 0.25724632 * value * value * value
    )


def spring_damper(
    current: Vector,
    velocity: Vector,
    target: Vector,
    dt: float,
    stiffness: float,
    damping: float,
):
    if dt <= 1e-8:
        return current.copy(), velocity.copy()

    frequency = math.sqrt(stiffness) / (
        2.0 * 3.1415926535897932
    )
    w = frequency * 6.28318530717

    if w < 1e-8:
        return current + velocity * dt, velocity.copy()

    error = current - target

    if damping < 1e-8:
        sine = math.sin(w * dt)
        cosine = math.cos(w * dt)
        position = target + error * cosine + (
            velocity / w
        ) * sine
        rate = velocity * cosine - error * (w * sine)
        return position, rate

    if damping > 1.0:
        wd = w * math.sqrt(damping * damping - 1.0)
        c2 = -(
            velocity + error * (w * damping - wd)
        ) / (2.0 * wd)
        c1 = error - c2
        a1 = wd - damping * w
        a2 = -(wd + damping * w)
        e1 = inverse_exp_approx(-a1 * dt)
        e2 = inverse_exp_approx(-a2 * dt)
        position = target + c1 * e1 + c2 * e2
        rate = c1 * (e1 * a1) + c2 * (e2 * a2)
        return position, rate

    if damping < 1.0:
        wd = w * math.sqrt(1.0 - damping * damping)
        a = error
        b = (velocity + error * (damping * w)) / wd
        sine = math.sin(wd * dt)
        cosine = math.cos(wd * dt)
        decay = inverse_exp_approx(damping * w * dt)
        offset = (a * cosine + b * sine) * decay
        rate = offset * (-damping * w)
        rate += (
            b * (wd * cosine) - a * (wd * sine)
        ) * decay
        return target + offset, rate

    c1 = error
    c2 = velocity + error * w
    decay = inverse_exp_approx(w * dt)
    position = target + (c1 + c2 * dt) * decay
    rate = (
        c2 - c1 * w - c2 * (w * dt)
    ) * decay
    return position, rate


def plant_goal(
    goal: Vector,
    speed: float,
    state: LimbPlantState,
    dt: float,
    settings: FootIKSettings,
) -> Vector:
    if (
        not settings.planting_enabled
        or speed < 0.0
        or speed > settings.speed_threshold_mps
    ):
        state.previous_goal = goal.copy()
        state.spring.reset()
        return goal.copy()

    position, velocity = spring_damper(
        state.previous_goal,
        state.spring.velocity,
        goal,
        dt,
        settings.stiffness,
        settings.critical_damping,
    )

    if dt > 1e-8:
        state.spring.velocity = velocity
        state.spring.previous_target = goal.copy()
        state.spring.previous_target_valid = True

    return position


def geometric_foot_speeds(
    positions: tuple,
    rest_end_height: float,
    dt: float,
    settings: FootIKSettings,
) -> tuple:
    count = len(positions)
    if count < 2:
        return tuple(-1.0 for _ in positions)

    radius = max(1, math.ceil(settings.contact_window_s / (2.0 * dt)))
    speeds = []
    for i in range(count):
        first = max(0, i - 1)
        last = min(count - 1, i + 1)
        if last == first:
            speed = 0.0
        else:
            delta = positions[last].xy - positions[first].xy
            speed = delta.length / ((last - first) * dt)

        lo = max(0, i - radius)
        hi = min(count, i + radius + 1)
        min_z = min(positions[j].z for j in range(lo, hi))

        candidate = (
            positions[i].z >= 0.0
            and positions[i].z <= rest_end_height + settings.contact_height_tolerance_m
            and positions[i].z <= min_z + settings.contact_minimum_tolerance_m
        )
        if candidate:
            speeds.append(speed)
        else:
            speeds.append(max(speed, settings.speed_threshold_mps + 1.0))
    return tuple(speeds)
