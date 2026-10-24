from dataclasses import dataclass

import numpy as np
from mathutils import Matrix, Quaternion, Vector
from mathutils.bvhtree import BVHTree


SEARCH_STEPS = (0.16, 0.08, 0.04, 0.02, 0.01)
SEARCH_AXES = tuple(Vector(axis) for axis in np.eye(3))
MAX_CORRECTION_RAD = 1.2217304764


def _segment_triangle(origins, directions, triangles):
    edge_a = triangles[:, 1] - triangles[:, 0]
    edge_b = triangles[:, 2] - triangles[:, 0]
    cross = np.cross(directions, edge_b)
    determinant = np.einsum("ij,ij->i", edge_a, cross)
    determinant_scale = np.linalg.norm(directions, axis=1) * np.linalg.norm(edge_a, axis=1) * np.linalg.norm(edge_b, axis=1)
    valid = (determinant_scale > 1e-30) & (np.abs(determinant) > determinant_scale * 1e-8)
    inverse = np.divide(1.0, determinant, out=np.zeros_like(determinant), where=valid)
    offset = origins - triangles[:, 0]
    first = np.einsum("ij,ij->i", offset, cross) * inverse
    second_cross = np.cross(offset, edge_a)
    second = np.einsum("ij,ij->i", directions, second_cross) * inverse
    distance = np.einsum("ij,ij->i", edge_b, second_cross) * inverse
    return valid & (first >= -1e-6) & (second >= -1e-6) & (first + second <= 1.000001) & (distance > 1e-5) & (distance < 0.99999)


def _triangle_tree(points, triangles):
    return BVHTree.FromPolygons([Vector(point) for point in points], triangles.tolist(), all_triangles=True)


def triangle_crossings(points, triangles, body_points, body_triangles):
    return _contact_score(points, triangles, body_points, body_triangles)[0][0]


def _contact_score(points, triangles, body_points, body_triangles, body_tree=None):
    if len(triangles) == 0 or len(body_triangles) == 0:
        return (0, 0.0), np.empty(0, dtype=np.int32)
    tree = body_tree if body_tree is not None else _triangle_tree(body_points, body_triangles)
    pairs = tree.overlap(_triangle_tree(points, triangles))
    if not pairs:
        return (0, 0.0), np.empty(0, dtype=np.int32)
    pairs = np.asarray(pairs, dtype=np.int32)
    body = body_points[body_triangles[pairs[:, 0]]]
    garment = points[triangles[pairs[:, 1]]]
    crossed = np.zeros(len(pairs), dtype=bool)
    for index in range(3):
        crossed |= _segment_triangle(body[:, index], body[:, (index + 1) % 3] - body[:, index], garment)
        crossed |= _segment_triangle(garment[:, index], garment[:, (index + 1) % 3] - garment[:, index], body)
    count = int(crossed.sum())
    if count == 0:
        return (0, 0.0), np.empty(0, dtype=np.int32)
    body, garment = body[crossed], garment[crossed]
    normal = np.cross(body[:, 1] - body[:, 0], body[:, 2] - body[:, 0])
    normal /= np.maximum(np.linalg.norm(normal, axis=1, keepdims=True), 1e-12)
    signed = np.einsum("nki,ni->nk", garment - body[:, :1], normal)
    depth = np.minimum(np.maximum(signed.max(axis=1), 0.0), np.maximum(-signed.min(axis=1), 0.0))
    return (count, round(float(depth.sum()), 9)), np.unique(triangles[pairs[crossed, 1]])


@dataclass
class SkinCollisionFrame:
    parents: np.ndarray
    relative_rest: np.ndarray
    inverse_rest: np.ndarray
    rest_points: np.ndarray
    weights: np.ndarray
    armature_world: np.ndarray
    fixed_parents: np.ndarray
    locations: np.ndarray
    rotations: list
    scales: np.ndarray
    evaluated_points: np.ndarray

    def __post_init__(self):
        for name in ("parents", "relative_rest", "inverse_rest", "rest_points", "weights", "armature_world", "fixed_parents", "locations", "scales", "evaluated_points"):
            value = np.array(getattr(self, name), copy=True)
            if not np.isfinite(value).all():
                raise ValueError("蒙皮数据不是有限数")
            setattr(self, name, value)
        self.rotations = [rotation.copy() for rotation in self.rotations]
        self.homogeneous_rest = np.column_stack((self.rest_points, np.ones(len(self.rest_points))))
        self.fixed_points = self.evaluated_points - self._contributions(self.rotations)
        self.joint_weights = self.weights.copy()
        for index in range(len(self.parents) - 1, -1, -1):
            if self.parents[index] >= 0:
                self.joint_weights[:, self.parents[index]] += self.joint_weights[:, index]

    def poses(self, rotations, locations=None):
        positions = self.locations if locations is None else locations
        result = []
        for index, rotation in enumerate(rotations):
            basis = np.asarray(Matrix.LocRotScale(Vector(positions[index]), rotation, Vector(self.scales[index])), dtype=np.float64)
            parent = result[self.parents[index]] if self.parents[index] >= 0 else self.fixed_parents[index]
            result.append(parent @ self.relative_rest[index] @ basis)
        return np.asarray(result)

    def _contributions(self, rotations, locations=None):
        matrices = self.armature_world[None, :, :] @ self.poses(rotations, locations) @ self.inverse_rest
        transformed = np.einsum("bij,nj->bni", matrices, self.homogeneous_rest)[:, :, :3]
        return np.einsum("bni,nb->ni", transformed, self.weights)

    def points(self, rotations, locations=None):
        return self.fixed_points + self._contributions(rotations, locations)


@dataclass
class SkinContactPose:
    rotations: list
    locations: np.ndarray
    triangle_pairs: int


def _project_root_contacts(frame, rotations, locations, triangles, body_points, body_triangles, tree, max_offset):
    roots = np.flatnonzero(frame.parents < 0)
    weights = frame.joint_weights[:, roots]
    axes = [(frame.armature_world @ frame.fixed_parents[index] @ frame.relative_rest[index])[:3, :3] for index in roots]
    inverses = [np.linalg.inv(value) for value in axes]
    offsets = np.array([axis @ (locations[index] - frame.locations[index]) for index, axis in zip(roots, axes)])
    center = np.mean([(frame.armature_world @ frame.fixed_parents[index])[:3, 3] for index in roots], axis=0)
    extent = max(float(np.linalg.norm(np.ptp(body_points, axis=0))) * 2.0, max_offset * 4.0)
    constraint_rows, constraint_bounds = [], []
    for _iteration in range(16):
        points = frame.points(rotations, locations)
        score, involved = _contact_score(points, triangles, body_points, body_triangles, tree)
        yield SkinContactPose([value.copy() for value in rotations], locations.copy(), score[0])
        if score[0] == 0:
            return
        active = triangles[np.isin(triangles, involved).sum(axis=1) >= 2]
        edges = np.unique(np.sort(np.concatenate((active[:, (0, 1)], active[:, (1, 2)], active[:, (2, 0)])), axis=1), axis=0)
        added = 0
        queries = [(points[triangle].mean(axis=0), tuple(triangle)) for triangle in active]
        for first, second in edges:
            start = Vector(points[first])
            delta = Vector(points[second]) - start
            length = delta.length
            if length <= 1e-12:
                continue
            hit, _normal, _triangle, distance = tree.ray_cast(start, delta / length, length)
            if hit is not None and 1e-5 < distance / length < .99999:
                queries.append((np.asarray(hit), (first, second)))
        for query_index, (point, vertices) in enumerate(queries):
            if query_index and query_index % 32 == 0:
                yield None
            outward = point - center
            radial_length = float(np.linalg.norm(outward))
            if radial_length < 1e-12:
                continue
            outward /= radial_length
            outer, normal, _triangle, _distance = tree.ray_cast(Vector(point + outward * extent), Vector(-outward), extent * 2.0)
            if outer is None:
                continue
            if normal.dot(Vector(outward)) < 0.0:
                normal.negate()
            for vertex in vertices:
                influence = weights[vertex]
                reference = points[vertex] - influence @ offsets
                row = (influence[:, None] * np.array(normal)[None, :]).reshape(-1)
                if float(row @ row) <= 1e-12:
                    continue
                constraint_rows.append(row)
                constraint_bounds.append(float(normal.dot(outer - Vector(reference))) + extent * 1e-5)
                added += 1
        if not added:
            return
        rows = np.array(constraint_rows)
        bounds = np.array(constraint_bounds)
        values = offsets.reshape(-1).copy()
        denominators = np.einsum("ni,ni->n", rows, rows)
        for _sweep in range(24):
            for row, bound, denominator in zip(rows, bounds, denominators):
                deficit = float(bound - row @ values)
                if deficit > 0.0:
                    values += row * (deficit / denominator)
            pairs = values.reshape(-1, 3)
            norms = np.linalg.norm(pairs, axis=1)
            pairs *= np.minimum(1.0, max_offset / np.maximum(norms, 1e-12))[:, None]
            yield None
        offsets[:] = values.reshape(-1, 3)
        for ordinal, index in enumerate(roots):
            locations[index] = frame.locations[index] + inverses[ordinal] @ offsets[ordinal]


def search_skin_pose(frame, triangles, body_points, body_triangles, previous_corrections=None, previous_world_offsets=None, max_angle=MAX_CORRECTION_RAD, max_offset=0.04):
    if not np.isfinite(max_angle) or max_angle < 0.0:
        raise ValueError("骨骼修正角度无效")
    if not np.isfinite(max_offset) or max_offset < 0.0:
        raise ValueError("根部位移上限无效")
    if previous_corrections is not None and len(previous_corrections) != len(frame.rotations):
        raise ValueError("骨骼修正数量不匹配")
    body_tree = _triangle_tree(body_points, body_triangles)
    original = [rotation.copy() for rotation in frame.rotations]
    rotations = [rotation.copy() for rotation in original]
    locations = frame.locations.copy()
    roots = np.flatnonzero(frame.parents < 0)
    root_axes = {index: (frame.armature_world @ frame.fixed_parents[index] @ frame.relative_rest[index])[:3, :3] for index in roots}
    inverse_axes = {index: np.linalg.inv(axes) for index, axes in root_axes.items()}

    def measure(values, positions):
        return _contact_score(frame.points(values, positions), triangles, body_points, body_triangles, body_tree)

    def proposal():
        return SkinContactPose([value.copy() for value in rotations], locations.copy(), best[0])

    best, involved = measure(rotations, locations)
    yield proposal()
    if best[0] == 0:
        return
    if previous_corrections is not None:
        candidate = [(base @ correction).normalized() for base, correction in zip(original, previous_corrections)]
        candidate_locations = frame.locations.copy()
        if previous_world_offsets is not None:
            for index in roots:
                offset = np.array(previous_world_offsets[index], copy=True)
                offset *= min(1.0, max_offset / max(float(np.linalg.norm(offset)), 1e-12))
                candidate_locations[index] += inverse_axes[index] @ offset
        if all(base.rotation_difference(value).angle <= max_angle for base, value in zip(original, candidate)):
            count, candidate_involved = measure(candidate, candidate_locations)
            if count <= best:
                rotations, locations, best, involved = candidate, candidate_locations, count, candidate_involved
            yield proposal()
    saved, saved_locations, saved_score = [value.copy() for value in rotations], locations.copy(), best
    if max_offset > 0.0 and best[0] > 0:
        for projected in _project_root_contacts(frame, rotations, locations.copy(), triangles, body_points, body_triangles, body_tree, max_offset):
            if projected is None:
                yield SkinContactPose([value.copy() for value in saved], saved_locations.copy(), saved_score[0])
                continue
            count, candidate_involved = measure(projected.rotations, projected.locations)
            if count < saved_score:
                saved, saved_locations, saved_score = projected.rotations, projected.locations.copy(), count
                involved = candidate_involved
            yield SkinContactPose([value.copy() for value in saved], saved_locations.copy(), saved_score[0])
        rotations, locations, best = [value.copy() for value in saved], saved_locations.copy(), saved_score
    for seed in (None, 0.5, 0.0):
        if best[0] == 0:
            break
        if seed is not None:
            candidate = [Quaternion().slerp(value, seed).normalized() for value in original]
            if any(base.rotation_difference(value).angle > max_angle for base, value in zip(original, candidate)):
                continue
            rotations = candidate
            locations = frame.locations.copy()
            best, involved = measure(rotations, locations)
            yield proposal()
        for _cycle in range(3):
            cycle_before = best
            for fraction in (0.2, 0.1, 0.05):
                if best[0] == 0 or max_offset == 0.0:
                    break
                for _sweep in range(6 if fraction == 0.2 else 3):
                    before = best
                    movable = {index for index in roots if frame.joint_weights[involved, index].sum() > 1e-8}
                    for index in sorted(movable):
                        start = root_axes[index] @ (locations[index] - frame.locations[index])
                        chosen = locations[index].copy()
                        for axis in np.eye(3):
                            for sign in (-1.0, 1.0):
                                offset = start + axis * max_offset * fraction * sign
                                if np.linalg.norm(offset) > max_offset:
                                    continue
                                locations[index] = frame.locations[index] + inverse_axes[index] @ offset
                                count, candidate_involved = measure(rotations, locations)
                                if count < best:
                                    chosen, best, involved = locations[index].copy(), count, candidate_involved
                                current = locations[index].copy()
                                locations[index] = chosen
                                yield proposal()
                                locations[index] = current
                        locations[index] = chosen
                        if best[0] == 0:
                            break
                    if best[0] == 0 or before == best:
                        break
            for step in SEARCH_STEPS:
                if best[0] == 0:
                    break
                for _sweep in range(2):
                    before = best
                    movable = np.flatnonzero(frame.joint_weights[involved].sum(axis=0) > 1e-8)
                    for index in movable:
                        start = rotations[index].copy()
                        chosen = start.copy()
                        for axis in SEARCH_AXES:
                            for sign in (-1.0, 1.0):
                                candidate = (start @ Quaternion(axis, step * sign)).normalized()
                                if original[index].rotation_difference(candidate).angle > max_angle:
                                    continue
                                rotations[index] = candidate
                                count, candidate_involved = measure(rotations, locations)
                                if count < best:
                                    chosen, best, involved = candidate.copy(), count, candidate_involved
                                current = rotations[index]
                                rotations[index] = chosen
                                yield proposal()
                                rotations[index] = current
                        rotations[index] = chosen
                        if best[0] == 0:
                            break
                    if best[0] == 0 or before == best:
                        break
                if best[0] == 0:
                    break
            if best[0] == 0 or best == cycle_before:
                break
        if best < saved_score:
            saved, saved_locations, saved_score = [value.copy() for value in rotations], locations.copy(), best
    rotations, locations, best = saved, saved_locations, saved_score
    if best[0] == 0:
        corrected = [value.copy() for value in rotations]
        corrected_locations = locations.copy()
        safe = 0.0
        blocked = 1.0
        for _attempt in range(7):
            amount = (safe + blocked) * 0.5
            candidate = [value.slerp(base, amount).normalized() for value, base in zip(corrected, original)]
            candidate_locations = corrected_locations * (1.0 - amount) + frame.locations * amount
            count, _involved = measure(candidate, candidate_locations)
            if count[0] == 0:
                safe = amount
                rotations = candidate
                locations = candidate_locations
            else:
                blocked = amount
            yield proposal()
    yield proposal()
