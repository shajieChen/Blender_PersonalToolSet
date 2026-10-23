"""CRSimSoftCollision-equivalent soft repulsion numerics.

Pure mathutils port of FCRSimSoftCollision::GatherForce semantics
(CRSimSoftCollision.h L23-30, CubicEaseIn falloff, cm-space inner math).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from mathutils import Vector


_SMALL_NUMBER = 1e-8


@dataclass
class SoftRepulsionSettings:
    enabled: bool = False
    minimum_distance_m: float = 0.10
    maximum_distance_m: float = 0.20
    coefficient: float = 64.0
    inverted: bool = False
    mass: float = 1.0
    linear_damping: float = 0.01
    torso_radius_m: float = 0.15
    hand_radius_m: float = 0.025
    forearm_radius_m: float = 0.035


def validate_soft_repulsion_settings(
    settings: SoftRepulsionSettings,
) -> None:
    values = (
        settings.minimum_distance_m,
        settings.maximum_distance_m,
        settings.coefficient,
        settings.mass,
        settings.linear_damping,
        settings.torso_radius_m,
        settings.hand_radius_m,
        settings.forearm_radius_m,
    )
    if not all(math.isfinite(value) for value in values):
        raise ValueError("soft repulsion parameters must be finite")
    if any(value < 0.0 for value in (
        settings.torso_radius_m,
        settings.hand_radius_m,
        settings.forearm_radius_m,
    )):
        raise ValueError("collision proxy radii must be non-negative")


def closest_point_on_segment(
    point: Vector,
    start: Vector,
    end: Vector,
) -> Vector:
    segment = end - start
    to_point = point - start
    dot1 = to_point.dot(segment)
    if dot1 <= 0.0:
        return start.copy()
    dot2 = segment.dot(segment)
    if dot2 <= dot1:
        return end.copy()
    return start + segment * (dot1 / dot2)


def _safe_normal(vector: Vector) -> Vector:
    squared_length = vector.length_squared
    if squared_length == 1.0:
        return vector.copy()
    if squared_length < _SMALL_NUMBER:
        return Vector((0.0, 0.0, 0.0))
    return vector / math.sqrt(squared_length)


def sphere_force(
    position_m: Vector,
    center_m: Vector,
    size_m: float,
    settings: SoftRepulsionSettings,
) -> Vector:
    if settings.mass <= _SMALL_NUMBER:
        return Vector((0.0, 0.0, 0.0))

    direction = (position_m - center_m) * 100.0
    distance = max(direction.length - size_m * 100.0, 0.0)

    if distance > _SMALL_NUMBER:
        direction = _safe_normal(direction)

    if settings.inverted:
        direction = -direction

    minimum = settings.minimum_distance_m * 100.0
    maximum = settings.maximum_distance_m * 100.0

    if maximum <= minimum:
        if distance < minimum:
            falloff = 0.0 if settings.inverted else 1.0
        else:
            falloff = 1.0 if settings.inverted else 0.0
    else:
        ratio = 0.0
        if distance < minimum:
            ratio = 1.0
        elif distance < maximum:
            ratio = (distance - minimum) / (maximum - minimum)
            ratio = 1.0 - min(1.0, max(0.0, ratio))
        if settings.inverted:
            ratio = 1.0 - ratio
        falloff = ratio * ratio * ratio

    return direction * (falloff * settings.coefficient * 0.01)


def integrate_verlet(
    position: Vector,
    velocity: Vector,
    force: Vector,
    mass: float,
    linear_damping: float,
    blend: float,
    dt: float,
):
    if mass <= _SMALL_NUMBER:
        return position.copy(), velocity.copy()

    weight = min(1.0, max(0.0, blend * dt))
    damping = min(1.0, max(0.0, 1.0 - linear_damping))
    new_velocity = (
        velocity + (force / mass - velocity) * weight
    ) * damping
    return position + new_velocity * dt, new_velocity


def repel_capsule_point(
    position: Vector,
    axis_start: Vector,
    axis_end: Vector,
    point_radius_m: float,
    dt: float,
    settings: SoftRepulsionSettings,
) -> Vector:
    if not settings.enabled:
        return position.copy()

    center = closest_point_on_segment(
        position, axis_start, axis_end
    )
    size = settings.torso_radius_m + point_radius_m
    force = sphere_force(position, center, size, settings)
    result, _velocity = integrate_verlet(
        position,
        Vector((0.0, 0.0, 0.0)),
        force,
        settings.mass,
        settings.linear_damping,
        1.0,
        dt,
    )
    return result
