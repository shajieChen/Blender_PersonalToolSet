import json
from pathlib import Path

import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree


OUTPUT = Path('H:/Blender_Plugin/docs/superpowers/evidence/2026-10-23-spring-bone/followup/coverage-review')
RAY_EPSILON = 1e-6


def channel_snapshot(obj):
    return (obj, obj.location.copy(), obj.rotation_euler.copy(), obj.rotation_quaternion.copy(), tuple(obj.rotation_axis_angle), obj.scale.copy())


def restore_channels(channels):
    for obj, location, euler, quaternion, axis_angle, scale in channels:
        obj.location = location
        obj.rotation_euler = euler
        obj.rotation_quaternion = quaternion
        obj.rotation_axis_angle = axis_angle
        obj.scale = scale


def selected_vertices(obj, names):
    groups = {group.index for group in obj.vertex_groups if group.name in names}
    return {vertex.index for vertex in obj.data.vertices if sum(slot.weight for slot in vertex.groups if slot.group in groups) > 0.05}


def geometry(obj, selected, units):
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        assert len(mesh.vertices) == len(obj.data.vertices)
        mesh.calc_loop_triangles()
        points = [evaluated.matrix_world @ vertex.co * units for vertex in mesh.vertices]
        triangles = [tuple(triangle.vertices) for triangle in mesh.loop_triangles if sum(index in selected for index in triangle.vertices) >= 2]
        return points, triangles
    finally:
        evaluated.to_mesh_clear()


def capsule_distance(point, start, end, radius):
    axis = end - start
    ratio = max(0.0, min(1.0, (point - start).dot(axis) / axis.length_squared)) if axis.length_squared > 1e-16 else 0.0
    return (point - (start + axis * ratio)).length - radius


def proxy_shapes(armature, units):
    shapes = []
    for collider in armature.sb_settings.colliders:
        pose = armature.matrix_world @ armature.pose.bones[collider.bone_name].matrix
        start = pose @ (Vector(collider.head_offset_m) / units) * units
        end = pose @ (Vector(collider.tail_offset_m) / units) * units if collider.shape == 'CAPSULE' else start
        shapes.append((collider.name, start, end, float(collider.radius_m)))
    return shapes


def nearest_proxy(point, shapes):
    return min(capsule_distance(point, start, end, radius) for _name, start, end, radius in shapes)


def edge_hits(points, triangles, tree):
    edges = {tuple(sorted((triangle[index], triangle[(index + 1) % 3]))) for triangle in triangles for index in range(3)}
    hits = []
    for first, second in edges:
        start = points[first]
        delta = points[second] - start
        length = delta.length
        if length <= RAY_EPSILON * 2.0:
            continue
        position, _normal, _index, distance = tree.ray_cast(start, delta / length, length)
        if position is not None and RAY_EPSILON < distance < length - RAY_EPSILON:
            hits.append(position)
    return hits


def inspect_pose(label, armature, cloth, body, skirt_vertices, leg_vertices, skirt_names, units):
    cloth_points, cloth_triangles = geometry(cloth, skirt_vertices, units)
    body_points, body_triangles = geometry(body, leg_vertices, units)
    cloth_tree = BVHTree.FromPolygons(cloth_points, cloth_triangles, all_triangles=True)
    body_tree = BVHTree.FromPolygons(body_points, body_triangles, all_triangles=True)
    hits = edge_hits(body_points, body_triangles, cloth_tree) + edge_hits(cloth_points, cloth_triangles, body_tree)
    unique = {tuple(round(component, 5) for component in point): point for point in hits}
    shapes = proxy_shapes(armature, units)
    proxy_gaps = [nearest_proxy(point, shapes) for point in unique.values()]
    skin_gaps = [nearest_proxy(body_points[index], shapes) for index in leg_vertices]
    tails = []
    for chain in armature.sb_settings.chains:
        for item in chain.bone_names:
            point = armature.matrix_world @ armature.pose.bones[item.name].tail * units
            distance = nearest_proxy(point, shapes) - chain.hit_radius_m
            tails.append({'bone': item.name, 'distance_m': distance})
    result = {
        'label': label,
        'skirt_lowest_z_m': min(cloth_points[index].z for index in skirt_vertices),
        'ankle_z_m': {name: (armature.matrix_world @ armature.pose.bones[name].head * units).z for name in ('foot.L', 'foot.R')},
        'cloth_triangles': len(cloth_triangles),
        'leg_triangles': len(body_triangles),
        'exact_edge_triangle_crossings': len(unique),
        'crossings_outside_all_proxies': sum(gap > 1e-5 for gap in proxy_gaps),
        'maximum_crossing_outside_proxy_m': max(proxy_gaps, default=0.0),
        'leg_vertices': len(leg_vertices),
        'leg_vertices_outside_proxies': sum(gap > 1e-5 for gap in skin_gaps),
        'maximum_leg_vertex_outside_proxy_m': max(skin_gaps),
        'tail_proxy_penetrations': [row for row in tails if row['distance_m'] < -1e-5],
        'tail_minimum_signed_distance_m': min(row['distance_m'] for row in tails),
        'crossing_samples': [{'point_m': list(point), 'proxy_gap_m': nearest_proxy(point, shapes)} for point in list(unique.values())[:30]],
    }
    return result, cloth_points, body_points


def probe():
    scene = bpy.context.scene
    armature = scene.sb_target_armature
    cloth = bpy.data.objects['clothing']
    body = bpy.data.objects['body']
    units = scene.unit_settings.scale_length
    assert units > 0.0
    skirt_names = {bone.name for chain in armature.sb_settings.chains for bone in chain.bone_names}
    leg_names = {'upper_leg.L', 'upper_leg.R', 'lower_leg.L', 'lower_leg.R', 'foot.L', 'foot.R', 'toes.L', 'toes.R'}
    skirt_vertices = selected_vertices(cloth, skirt_names)
    leg_vertices = selected_vertices(body, leg_names)
    anim = armature.animation_data
    action = anim.action
    slot = anim.action_slot
    source = armature.sb_settings.source_action
    entry_frame, entry_subframe = scene.frame_current, scene.frame_subframe
    entry_pose = armature.data.pose_position
    channels = [channel_snapshot(armature), *[channel_snapshot(pose) for pose in armature.pose.bones]]
    test_tree = BVHTree.FromPolygons([Vector((0, 0, 0)), Vector((1, 0, 0)), Vector((0, 1, 0))], [(0, 1, 2)], all_triangles=True)
    assert test_tree.ray_cast(Vector((0.2, 0.2, 1)), Vector((0, 0, -1)), 2.0)[0] is not None
    assert test_tree.ray_cast(Vector((2, 2, 1)), Vector((0, 0, -1)), 2.0)[0] is None
    result = {'frame': 31, 'action': action.name, 'source_action': source.name, 'cloth_data': cloth.data.name}
    try:
        scene.frame_set(31)
        bpy.context.view_layer.update()
        result['dynamic'], dynamic_cloth, dynamic_body = inspect_pose('dynamic', armature, cloth, body, skirt_vertices, leg_vertices, skirt_names, units)
        armature.data.pose_position = 'REST'
        bpy.context.view_layer.update()
        result['rest'], _rest_cloth, _rest_body = inspect_pose('rest', armature, cloth, body, skirt_vertices, leg_vertices, skirt_names, units)
        result['rest']['ankle_rest_z_m'] = {name: (armature.matrix_world @ armature.data.bones[name].head_local * units).z for name in ('foot.L', 'foot.R')}
        armature.data.pose_position = 'POSE'
        anim.action = source
        anim.action_slot = source.slots[0]
        for name in skirt_names:
            pose = armature.pose.bones[name]
            pose.rotation_euler = (0.0, 0.0, 0.0)
            pose.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
            pose.rotation_axis_angle = (0.0, 0.0, 1.0, 0.0)
        scene.frame_set(31)
        bpy.context.view_layer.update()
        result['base'], base_cloth, base_body = inspect_pose('base_with_unkeyed_skirt_rotations_reset', armature, cloth, body, skirt_vertices, leg_vertices, skirt_names, units)
        result['maximum_leg_body_base_to_dynamic_delta_m'] = max((dynamic_body[index] - base_body[index]).length for index in leg_vertices)
        result['maximum_skirt_base_to_dynamic_delta_m'] = max((dynamic_cloth[index] - base_cloth[index]).length for index in skirt_vertices)
    finally:
        anim.action = action
        anim.action_slot = slot
        armature.data.pose_position = entry_pose
        scene.frame_set(entry_frame, subframe=entry_subframe)
        restore_channels(channels)
        bpy.context.view_layer.update()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / 'coverage.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    summary = {name: {key: value for key, value in result[name].items() if key not in ('crossing_samples', 'tail_proxy_penetrations')} for name in ('rest', 'base', 'dynamic')}
    summary['body_base_dynamic_delta_m'] = result['maximum_leg_body_base_to_dynamic_delta_m']
    summary['skirt_base_dynamic_delta_m'] = result['maximum_skirt_base_to_dynamic_delta_m']
    print(json.dumps(summary, ensure_ascii=True))


probe()
