"""PBIK-equivalent joint angle limits: FREE/LIMITED/LOCKED per axis.

Pure mathutils port of FJointConstraint limit semantics
(PBIKConstraint.cpp L111-239, IKRigFullBodyIK.h L67-100).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum

from mathutils import Quaternion, Vector


_SMALL_NUMBER = 1e-8
_KINDA_SMALL_NUMBER = 1e-4


class LimitType(str, Enum):
    FREE = "FREE"
    LIMITED = "LIMITED"
    LOCKED = "LOCKED"


@dataclass
class AxisAngleLimit:
    kind: LimitType = LimitType.FREE
    minimum: float = 0.0
    maximum: float = 0.0


@dataclass
class BoneAngleLimits:
    role: str = ""
    x: AxisAngleLimit = field(default_factory=AxisAngleLimit)
    y: AxisAngleLimit = field(default_factory=AxisAngleLimit)
    z: AxisAngleLimit = field(default_factory=AxisAngleLimit)
    rotation_stiffness: float = 0.0


@dataclass
class JointLimitSettings:
    enabled: bool = False
    iterations: int = 20
    max_angle_degrees: float = 30.0
    bones: tuple = ()


@dataclass
class JointBody:
    rotation: Quaternion
    initial_rotation: Quaternion
    settings: BoneAngleLimits
    inverse_mass: float = 1.0
    sub_solve_locked: bool = False


@dataclass
class JointRotationConstraint:
    parent: JointBody
    child: JointBody
    reference_rotation: Quaternion


def validate_joint_limit_settings(
    settings: JointLimitSettings,
) -> None:
    if not isinstance(settings.iterations, int):
        raise ValueError("joint iterations must be an integer")
    if settings.iterations < 0:
        raise ValueError("joint iterations must be non-negative")
    if (
        not math.isfinite(settings.max_angle_degrees)
        or settings.max_angle_degrees < 0.0
    ):
        raise ValueError("maximum rotation increment must be finite and non-negative")

    seen = set()
    for bone in settings.bones:
        if not bone.role or bone.role in seen:
            raise ValueError("joint limit roles must be nonempty and unique")
        seen.add(bone.role)
        if (
            not math.isfinite(bone.rotation_stiffness)
            or not 0.0 <= bone.rotation_stiffness <= 1.0
        ):
            raise ValueError("rotation stiffness must stay within 0..1")
        for axis in (bone.x, bone.y, bone.z):
            if axis.kind not in tuple(LimitType):
                raise ValueError("unknown joint limit type")
            if not all(math.isfinite(value) for value in (
                axis.minimum, axis.maximum
            )):
                raise ValueError("joint angle limits must be finite")


def _inverse(q: Quaternion) -> Quaternion:
    return Quaternion((q.w, -q.x, -q.y, -q.z))


def _scale(q: Quaternion, factor: float) -> Quaternion:
    return Quaternion(tuple(value * factor for value in q))


def normalize_rotation(q: Quaternion) -> Quaternion:
    squared_length = sum(value * value for value in q)
    if squared_length < _SMALL_NUMBER:
        return Quaternion((1.0, 0.0, 0.0, 0.0))
    return _scale(q, 1.0 / math.sqrt(squared_length))


def _rotate(q: Quaternion, vector: Vector) -> Vector:
    xyz = Vector((q.x, q.y, q.z))
    first = xyz.cross(vector)
    return vector + (first * q.w + xyz.cross(first)) * 2.0


def _safe_normal(vector: Vector) -> Vector:
    squared_length = vector.length_squared
    if squared_length == 1.0:
        return vector.copy()
    if squared_length < _SMALL_NUMBER:
        return Vector((0.0, 0.0, 0.0))
    return vector / math.sqrt(squared_length)


def _axis_rotation(axis: Vector, degrees: float) -> Quaternion:
    half = math.radians(degrees) * 0.5
    sine = math.sin(half)
    return Quaternion((
        math.cos(half),
        axis.x * sine,
        axis.y * sine,
        axis.z * sine,
    ))


def _find_between(a: Vector, b: Vector) -> Quaternion:
    norm_ab = math.sqrt(a.length_squared * b.length_squared)
    w = norm_ab + a.dot(b)
    if w >= 1e-6 * norm_ab:
        xyz = a.cross(b)
    else:
        w = 0.0
        if abs(a.x) > abs(a.y) and abs(a.x) > abs(a.z):
            basis = Vector((0.0, 1.0, 0.0))
        else:
            basis = Vector((-1.0, 0.0, 0.0))
        xyz = a.cross(basis)
    return normalize_rotation(
        Quaternion((w, xyz.x, xyz.y, xyz.z))
    )


def _signed_angle(
    start: Vector,
    end: Vector,
    axis: Vector,
) -> float:
    value = min(1.0, max(-1.0, start.dot(end)))
    angle = math.degrees(math.acos(value))
    return angle if start.cross(end).dot(axis) >= 0.0 else -angle


def _joint_axes(joint: JointRotationConstraint):
    reference = joint.reference_rotation
    original = tuple(_rotate(reference, axis) for axis in (
        Vector((1.0, 0.0, 0.0)),
        Vector((0.0, 1.0, 0.0)),
        Vector((0.0, 0.0, 1.0)),
    ))
    parent_delta = (
        joint.parent.rotation @ _inverse(joint.parent.initial_rotation)
    )
    child_delta = (
        joint.child.rotation @ _inverse(joint.child.initial_rotation)
    )
    parent_axes = tuple(_rotate(parent_delta, axis) for axis in original)
    child_axes = tuple(_rotate(child_delta, axis) for axis in original)
    return parent_axes, child_axes


def decompose_rotation_angles(joint: JointRotationConstraint):
    parent_axes, child_axes = _joint_axes(joint)
    xa, ya, za = parent_axes
    _xb, yb, zb = child_axes

    projected_x = _safe_normal(zb - xa * zb.dot(xa))
    projected_y = _safe_normal(zb - ya * zb.dot(ya))
    projected_z = _safe_normal(yb - za * yb.dot(za))

    angles = (
        _signed_angle(za, projected_x, xa),
        -_signed_angle(za, projected_y, ya),
        _signed_angle(ya, projected_z, za),
    )
    return (
        angles,
        (xa, -ya, za),
        (projected_x, projected_y, projected_z),
        (za, za, ya),
    )


def _rotation_locked(body: JointBody) -> bool:
    return (
        body.sub_solve_locked
        or body.inverse_mass <= _SMALL_NUMBER
        or abs(body.settings.rotation_stiffness - 1.0) <= _SMALL_NUMBER
    )


def _apply_rotation_delta(
    body: JointBody,
    delta: Quaternion,
    max_angle_degrees: float,
) -> None:
    if _rotation_locked(body):
        return

    maximum = math.radians(max_angle_degrees)
    magnitude = math.sqrt(sum(value * value for value in delta))
    if magnitude > maximum:
        delta = _scale(delta, maximum / magnitude)

    change = _scale(delta @ body.rotation, 0.5)
    body.rotation = Quaternion(tuple(
        body.rotation[i] + change[i] for i in range(4)
    ))


def _apply_rotation_correction(
    joint: JointRotationConstraint,
    delta: Quaternion,
    max_angle_degrees: float,
) -> None:
    _apply_rotation_delta(
        joint.parent,
        _scale(delta, 1.0 - joint.parent.settings.rotation_stiffness),
        max_angle_degrees,
    )
    _apply_rotation_delta(
        joint.child,
        _scale(delta, -(1.0 - joint.child.settings.rotation_stiffness)),
        max_angle_degrees,
    )


def _align_axes(
    joint: JointRotationConstraint,
    axis_a: Vector,
    axis_b: Vector,
    final: bool,
    max_angle_degrees: float,
) -> None:
    if final:
        joint.child.rotation = (
            _find_between(axis_b, axis_a) @ joint.child.rotation
        )
        return

    cross = axis_a.cross(axis_b)
    magnitude = cross.length
    direction = (
        cross / magnitude
        if magnitude > _SMALL_NUMBER
        else Vector((0.0, 0.0, 0.0))
    )
    effective_inverse_mass = direction.dot(direction)
    if effective_inverse_mass < _KINDA_SMALL_NUMBER:
        return

    push = direction * (magnitude / effective_inverse_mass)
    delta = Quaternion((0.0, push.x, push.y, push.z))
    _apply_rotation_correction(joint, delta, max_angle_degrees)


def update_joint_limits(
    joint: JointRotationConstraint,
    final: bool,
    max_angle_degrees: float,
) -> None:
    axes = (
        joint.child.settings.x,
        joint.child.settings.y,
        joint.child.settings.z,
    )
    if all(axis.kind == LimitType.FREE for axis in axes):
        return

    for axis in axes:
        if axis.maximum < axis.minimum:
            axis.maximum = axis.minimum + 1.0

    locked = tuple(
        axis.kind == LimitType.LOCKED
        or (
            axis.kind == LimitType.LIMITED
            and axis.maximum - axis.minimum < 2.0
        )
        for axis in axes
    )

    if all(locked):
        original = (
            joint.parent.initial_rotation
            @ _inverse(joint.child.initial_rotation)
        )
        current = (
            joint.parent.rotation @ _inverse(joint.child.rotation)
        )
        delta = original @ _inverse(current)

        if final:
            joint.child.rotation = (
                _inverse(delta) @ joint.child.rotation
            )
        else:
            _apply_rotation_correction(
                joint,
                Quaternion((0.0, delta.x, delta.y, delta.z)),
                max_angle_degrees,
            )
        return

    hinge = next((
        index for index in range(3)
        if not locked[index]
        and all(locked[other] for other in range(3) if other != index)
    ), None)

    if hinge is not None:
        parent_axes, child_axes = _joint_axes(joint)
        _align_axes(
            joint,
            parent_axes[hinge],
            child_axes[hinge],
            final,
            max_angle_degrees,
        )

    limited = tuple(
        axis.kind == LimitType.LIMITED and not locked[index]
        for index, axis in enumerate(axes)
    )
    if not any(limited):
        return

    angles, rotation_axes, current_vectors, reference_vectors = (
        decompose_rotation_angles(joint)
    )
    for index, axis in enumerate(axes):
        if not limited[index]:
            continue

        angle = angles[index]
        if angle < axis.minimum:
            target_angle = axis.minimum
        elif angle > axis.maximum:
            target_angle = axis.maximum
        else:
            continue

        target_vector = _rotate(
            _axis_rotation(rotation_axes[index], target_angle),
            reference_vectors[index],
        )
        _align_axes(
            joint,
            target_vector,
            current_vectors[index],
            final,
            max_angle_degrees,
        )


def run_rotation_limit_pass(
    joints: tuple,
    final: bool,
    max_angle_degrees: float,
) -> None:
    for joint in joints:
        if final:
            if joint.child.sub_solve_locked:
                continue
            update_joint_limits(joint, True, max_angle_degrees)
            continue

        if (
            joint.parent.sub_solve_locked
            and joint.child.sub_solve_locked
        ):
            continue
        if abs(
            joint.parent.inverse_mass + joint.child.inverse_mass
        ) <= _SMALL_NUMBER:
            continue

        update_joint_limits(joint, False, max_angle_degrees)
        joint.parent.rotation = normalize_rotation(joint.parent.rotation)
        joint.child.rotation = normalize_rotation(joint.child.rotation)
