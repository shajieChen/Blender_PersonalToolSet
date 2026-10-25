import json
import math
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from spring_bone.contact_bake import _action_token, _mesh_arrays, _mesh_token, _skin_weights
from spring_bone.skin_collision import _contact_score


def point_inside_votes(points, obstacle_points, obstacle_triangles):
    tree = BVHTree.FromPolygons([Vector(point) for point in obstacle_points], obstacle_triangles.tolist(), all_triangles=True)
    directions = [Vector(value).normalized() for value in ((1., .371, .193), (.231, 1., .419), (.157, .293, 1.))]
    extent = max(float(np.linalg.norm(np.ptp(obstacle_points, axis=0))) * 4.0, 1.0)
    rows = []
    for point in points:
        counts = []
        for direction in directions:
            origin = Vector(point)
            count = 0
            for _ in range(128):
                hit, normal, face, distance = tree.ray_cast(origin, direction, extent)
                if hit is None:
                    break
                count += 1
                origin = hit + direction * 1e-7
            counts.append(count)
        nearest = tree.find_nearest(Vector(point))
        rows.append({"ray_hits": counts, "inside_votes": sum(value % 2 for value in counts), "nearest_surface_distance": float(nearest[3]) if nearest[0] is not None else None})
    return rows


def independent_intersections(points, triangles, obstacle_points, obstacle_triangles):
    first_tree = BVHTree.FromPolygons([Vector(point) for point in points], triangles.tolist(), all_triangles=True)
    second_tree = BVHTree.FromPolygons([Vector(point) for point in obstacle_points], obstacle_triangles.tolist(), all_triangles=True)
    pairs = np.asarray(first_tree.overlap(second_tree), dtype=np.int32)
    if not len(pairs):
        return {"pairs": 0, "maximum_segment": 0.0, "garment_triangles": [], "obstacle_triangles": []}
    first, second = points[triangles[pairs[:, 0]]], obstacle_points[obstacle_triangles[pairs[:, 1]]]
    normal_first = np.cross(first[:, 1] - first[:, 0], first[:, 2] - first[:, 0])
    normal_second = np.cross(second[:, 1] - second[:, 0], second[:, 2] - second[:, 0])
    normal_first /= np.maximum(np.linalg.norm(normal_first, axis=1, keepdims=True), 1e-30)
    normal_second /= np.maximum(np.linalg.norm(normal_second, axis=1, keepdims=True), 1e-30)
    direction = np.cross(normal_first, normal_second)
    lengths = np.linalg.norm(direction, axis=1)
    direction /= np.maximum(lengths[:, None], 1e-30)

    def interval(vertices, plane_points, plane_normals):
        distances = np.einsum("nki,ni->nk", vertices - plane_points[:, :1], plane_normals)
        following = np.roll(distances, -1, axis=1)
        denominators = distances - following
        valid = (distances * following <= 0.0) & (np.abs(denominators) > 1e-14)
        fractions = np.divide(distances, denominators, out=np.zeros_like(distances), where=valid)
        cuts = vertices + fractions[:, :, None] * (np.roll(vertices, -1, axis=1) - vertices)
        projections = np.einsum("nki,ni->nk", cuts, direction)
        lower = np.where(valid, projections, np.inf).min(axis=1)
        upper = np.where(valid, projections, -np.inf).max(axis=1)
        return lower, upper

    first_lower, first_upper = interval(first, second, normal_second)
    second_lower, second_upper = interval(second, first, normal_first)
    segment = np.minimum(first_upper, second_upper) - np.maximum(first_lower, second_lower)
    hit = (lengths > 1e-8) & (segment > 1e-7)
    return {"pairs": int(hit.sum()), "maximum_segment": float(segment[hit].max()) if hit.any() else 0.0, "garment_triangles": pairs[hit, 0].tolist(), "obstacle_triangles": pairs[hit, 1].tolist()}


def audit_contacts(folder, action_names=None, step=1.0, label="round-1", garment_name=None, include_fixed_faces=True, repair_quaternions=False, independent=False):
    from spring_bone.operators import active_session

    if active_session() is not None:
        raise RuntimeError("停止当前插件作业后再审计")
    scene = bpy.context.scene
    armature = scene.sb_target_armature
    settings = armature.sb_settings
    garment = bpy.data.objects[garment_name] if garment_name else settings.contact_garment
    body = settings.contact_body
    anim = armature.animation_data
    entry_action, entry_slot = anim.action, anim.action_slot
    entry_frame = scene.frame_current, scene.frame_subframe
    entry_poses = [(pose.name, pose.matrix_basis.copy()) for pose in armature.pose.bones]
    names = [item.name for chain in settings.chains for item in chain.bone_names]
    collider_names = {item.bone_name for item in settings.colliders}
    region_names = sorted({bone.name for name in collider_names for bone in (armature.data.bones[name], *armature.data.bones[name].children_recursive)})
    foot_names = [name for name in region_names if "foot" in name.lower() or "toe" in name.lower() or "ankle" in name.lower()]
    meshes = [obj for obj in scene.objects if obj.type == "MESH" and not obj.hide_get() and any(mod.type == "ARMATURE" and mod.object == armature and mod.show_viewport for mod in obj.modifiers)]
    topology, weights, tokens = {}, {}, {}
    inventory = []
    for obj in meshes:
        points, normals, triangles = _mesh_arrays(obj)
        spring = _skin_weights(obj, armature, names).sum(axis=1)
        region = _skin_weights(obj, armature, region_names).sum(axis=1)
        foot = _skin_weights(obj, armature, foot_names).sum(axis=1)
        topology[obj.name] = triangles
        weights[obj.name] = spring, region, foot
        tokens[obj.name] = _mesh_token(obj).hex()
        inventory.append({"object": obj.name, "vertices": len(points), "triangles": len(triangles), "spring_vertices": int((spring > 1e-8).sum()), "region_vertices": int((region > 1e-8).sum()), "foot_vertices": int((foot > 1e-8).sum()), "materials": [slot.name for slot in obj.material_slots], "region_triangles": int(((region[triangles] > 1e-8).any(axis=1) & ~(spring[triangles] > 1e-8).any(axis=1)).sum())})
    garment_triangles = topology[garment.name]
    garment_weights = weights[garment.name][0]
    strict_garment = garment_triangles if include_fixed_faces else garment_triangles[(garment_weights[garment_triangles] > 1e-8).any(axis=1)]
    legacy_garment = garment_triangles[(garment_weights[garment_triangles] > .05).sum(axis=1) >= 2]
    legacy_body = topology[body.name][(weights[body.name][1][topology[body.name]] > .05).sum(axis=1) >= 2]
    obstacles = []
    for obj in meshes:
        spring, region, foot = weights[obj.name]
        triangles = topology[obj.name]
        fixed = ~(spring[triangles] > 1e-8).any(axis=1)
        for part, mask in (("leg", region), ("foot", foot)):
            selected = triangles[(mask[triangles] > 1e-8).any(axis=1) & fixed]
            if len(selected):
                obstacles.append((obj, part, selected))
    actions = [bpy.data.actions[name] for name in (action_names or [entry_action.name])]
    action_tokens = {action.name: _action_token(action, action.slots[0]).hex() for action in actions}
    result = {"label": label, "blender": bpy.app.version_string, "entry_action": entry_action.name, "scene_range": [scene.frame_start, scene.frame_end], "step": step, "units_m": scene.unit_settings.scale_length, "all_garment_faces": include_fixed_faces, "repair_quaternions": repair_quaternions, "independent": independent, "inventory": inventory, "garment_triangles": {"legacy": len(legacy_garment), "expanded": len(strict_garment)}, "region_bones": region_names, "foot_bones": foot_names, "actions": []}
    owned = []
    try:
        for action in actions:
            evaluated_action = action
            if repair_quaternions:
                from spring_bone.animation import align_quaternion_key_signs
                evaluated_action = action.copy()
                owned.append(evaluated_action)
                align_quaternion_key_signs(evaluated_action, evaluated_action.slots[0])
            anim.action, anim.action_slot = evaluated_action, evaluated_action.slots[0]
            first, last = map(float, action.frame_range)
            frames = np.arange(max(0.0, first), last + step * .25, step)
            rows = []
            for frame in frames:
                scene.frame_set(math.floor(frame), subframe=float(frame - math.floor(frame)))
                bpy.context.view_layer.update()
                arrays = {obj.name: _mesh_arrays(obj)[0] for obj in meshes if obj == garment or obj == body or any(obj == item[0] for item in obstacles)}
                points = arrays[garment.name]
                legacy = _contact_score(points, legacy_garment, arrays[body.name], legacy_body)[0]
                hits = []
                for obj, part, triangles in obstacles:
                    if independent:
                        measured = independent_intersections(points, strict_garment, arrays[obj.name], triangles)
                        if measured["pairs"]:
                            hits.append({"object": obj.name, "part": part, "pairs": measured["pairs"], "maximum_intersection_m": measured["maximum_segment"] * scene.unit_settings.scale_length, "garment_vertices": np.unique(strict_garment[measured["garment_triangles"]]).tolist()})
                        continue
                    score, involved = _contact_score(points, strict_garment, arrays[obj.name], triangles)
                    if score[0]:
                        hits.append({"object": obj.name, "part": part, "pairs": score[0], "depth_sum_m": score[1] * scene.unit_settings.scale_length, "garment_vertices": involved.tolist()})
                rows.append({"frame": float(frame), "legacy_pairs": legacy[0], "hits": hits})
            result["actions"].append({"action": action.name, "meta": {key: repr(value) for key, value in action.items()}, "range": [first, last], "checked_frames": len(rows), "legacy_hit_frames": sum(row["legacy_pairs"] > 0 for row in rows), "expanded_hit_frames": sum(bool(row["hits"]) for row in rows), "maximum_pairs": max((sum(hit["pairs"] for hit in row["hits"] if hit["part"] == "leg") for row in rows), default=0), "rows": rows})
    finally:
        anim.action, anim.action_slot = entry_action, entry_slot
        scene.frame_set(entry_frame[0], subframe=entry_frame[1])
        for name, basis in entry_poses:
            armature.pose.bones[name].matrix_basis = basis
        bpy.context.view_layer.update()
        for action in owned:
            bpy.data.actions.remove(action)
    result["geometry_unchanged"] = all(_mesh_token(bpy.data.objects[name]).hex() == token for name, token in tokens.items())
    result["actions_unchanged"] = all(_action_token(bpy.data.actions[name], bpy.data.actions[name].slots[0]).hex() == token for name, token in action_tokens.items())
    result["entry_restored"] = anim.action == entry_action and anim.action_slot == entry_slot and (scene.frame_current, scene.frame_subframe) == entry_frame
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / (label + ".json")).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"label": label, "inventory": inventory, "actions": [{key: value for key, value in action.items() if key != "rows"} for action in result["actions"]], "restored": result["entry_restored"]}, ensure_ascii=True))
    assert result["geometry_unchanged"] and result["actions_unchanged"] and result["entry_restored"]
    return result
