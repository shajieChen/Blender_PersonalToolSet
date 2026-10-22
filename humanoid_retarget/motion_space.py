"""Metric motion-space conversion for retarget math.

All foot-IK formulas run in a per-character metric space:
Z up, XY ground plane, Z=0 at the configured floor, units in meters.
"""

from __future__ import annotations

from dataclasses import dataclass

from mathutils import Matrix, Quaternion, Vector

_EPSILON = 1e-5


@dataclass(frozen=True)
class MotionSpace:
    axes: Matrix
    origin: Vector
    meters_per_unit: float
    object_matrix: Matrix

    def position(self, armature_position: Vector) -> Vector:
        return (
            self.axes.transposed()
            @ (armature_position.copy() - self.origin)
        ) * self.meters_per_unit

    def armature_position(self, position: Vector) -> Vector:
        return self.origin + self.axes @ (
            position / self.meters_per_unit
        )

    def world_position(self, world_position: Vector) -> Vector:
        return self.position(self.object_matrix.inverted() @ world_position)

    def rotation(self, armature_matrix: Matrix) -> Quaternion:
        rotation = armature_matrix.to_quaternion().to_matrix()
        return (
            self.axes.transposed() @ rotation
        ).to_quaternion().normalized()

    def armature_rotation(self, rotation: Quaternion) -> Matrix:
        return self.axes @ rotation.to_matrix()

    def world_rotation(self, world_matrix: Matrix) -> Quaternion:
        return self.rotation(self.object_matrix.inverted() @ world_matrix)


class MotionSpaceError(RuntimeError):
    pass


def build_motion_space(
    obj,
    anatomical_body: Matrix,
    meters_per_blender_unit: float,
    floor_height_m: float,
) -> MotionSpace:
    world = obj.matrix_world.copy()
    columns = [world.col[i].to_3d() for i in range(3)]
    lengths = [column.length for column in columns]
    if any(length <= _EPSILON for length in lengths):
        raise MotionSpaceError("armature has a degenerate scale axis")
    if max(lengths) - min(lengths) > _EPSILON * max(lengths):
        raise MotionSpaceError("armature must have uniform scale")
    for a in range(3):
        for b in range(a + 1, 3):
            if abs(columns[a].normalized().dot(columns[b].normalized())) > _EPSILON:
                raise MotionSpaceError("armature axes must stay orthogonal")
    if world.to_3x3().determinant() <= 0.0:
        raise MotionSpaceError("armature matrix is mirrored")

    uniform_scale = sum(lengths) / 3.0
    world_rotation = world.to_3x3() * (1.0 / uniform_scale)

    world_up = Vector((0.0, 0.0, 1.0))
    anatomical_left = anatomical_body.col[0].xyz.normalized()
    world_left = world_rotation @ anatomical_left
    world_left = world_left - world_up * world_left.dot(world_up)
    if world_left.length < _EPSILON:
        world_left = world_rotation.col[0].xyz
        world_left = world_left - world_up * world_left.dot(world_up)
    if world_left.length < _EPSILON:
        raise MotionSpaceError("cannot build a stable ground plane for this rig")
    world_left.normalize()
    world_forward = world_up.cross(world_left).normalized()

    world_axes = Matrix((
        (world_left.x, world_forward.x, world_up.x),
        (world_left.y, world_forward.y, world_up.y),
        (world_left.z, world_forward.z, world_up.z),
    ))
    axes = world_rotation.transposed() @ world_axes

    origin_world = world.translation.copy()
    origin_world.z = floor_height_m / meters_per_blender_unit
    origin = world.inverted() @ origin_world

    return MotionSpace(
        axes=axes.copy(),
        origin=origin.copy(),
        meters_per_unit=meters_per_blender_unit * uniform_scale,
        object_matrix=world.copy(),
    )


def validate_motion_space(obj, space: MotionSpace) -> None:
    current = obj.matrix_world
    cached = space.object_matrix
    delta = max(
        abs(current[r][c] - cached[r][c])
        for r in range(4)
        for c in range(4)
    )
    if delta > 1e-6:
        raise MotionSpaceError("armature world transform changed during bake")
