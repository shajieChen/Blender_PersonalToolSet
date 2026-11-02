import bpy
import json
import pathlib
from mathutils import Matrix

HERE = pathlib.Path(__file__).resolve().parent
state = json.loads((HERE / "live-state.json").read_text(encoding="utf-8"))
snapshot = json.loads((HERE / "snapshot.json").read_text(encoding="utf-8"))
bpy.ops.wm.open_mainfile(filepath=snapshot["snapshot"], use_scripts=False)
scene = bpy.context.scene
arm = bpy.data.objects[state["armature"]["name"]]
mount = bpy.data.objects[state["mount"]["name"]]
root = bpy.data.objects[state["equipment"]["name"]]
bone_name = mount.parent_bone
meshes = [obj for obj in scene.objects if obj.type == "MESH" and any(mod.type == "ARMATURE" and mod.object == arm for mod in obj.modifiers)]
weights = []
for obj in meshes:
    group = obj.vertex_groups.get(bone_name)
    if group is None:
        continue
    vertices = []
    for vertex in obj.data.vertices:
        weight = next((item.weight for item in vertex.groups if item.group == group.index), 0)
        if weight > 0.5:
            vertices.append((vertex.index, weight))
    weights.append((obj, vertices))
rows = []
base_mount = None
base_root = None
base_mesh = {}
base_vertices = {}
for frame in range(scene.frame_start, scene.frame_end + 1):
    scene.frame_set(frame)
    deps = bpy.context.evaluated_depsgraph_get()
    evaluated_arm = arm.evaluated_get(deps)
    bone_world = evaluated_arm.matrix_world @ evaluated_arm.pose.bones[bone_name].matrix
    mount_world = mount.evaluated_get(deps).matrix_world.copy()
    root_world = root.evaluated_get(deps).matrix_world.copy()
    relative_mount = bone_world.inverted() @ mount_world
    relative_root = mount_world.inverted() @ root_world
    if base_mount is None:
        base_mount = relative_mount.copy()
        base_root = relative_root.copy()
    difference = lambda a, b: max(abs(a[r][c] - b[r][c]) for r in range(4) for c in range(4))
    row = {"frame": frame, "mount_bone_relative_error": difference(relative_mount, base_mount), "weapon_mount_relative_error": difference(relative_root, base_root), "bone_head": list(bone_world.translation), "mount_position": list(mount_world.translation), "mesh_relative_errors": {}, "hand_vertices": {}}
    for obj in root.children_recursive:
        if obj.type != "MESH":
            continue
        local = root_world.inverted() @ obj.evaluated_get(deps).matrix_world
        base_mesh.setdefault(obj.name, local.copy())
        row["mesh_relative_errors"][obj.name] = difference(local, base_mesh[obj.name])
    for obj, vertices in weights:
        evaluated = obj.evaluated_get(deps)
        mesh = evaluated.to_mesh()
        try:
            deltas = []
            rigid_deltas = []
            nearest = None
            for index, weight in vertices:
                if index >= len(mesh.vertices):
                    continue
                world = evaluated.matrix_world @ mesh.vertices[index].co
                local = bone_world.inverted() @ world
                key = (obj.name, index)
                base_vertices.setdefault(key, local.copy())
                delta = (local - base_vertices[key]).length
                deltas.append(delta)
                if weight >= 0.999:
                    rigid_deltas.append(delta)
                distance = (world - mount_world.translation).length
                nearest = distance if nearest is None else min(nearest, distance)
            row["hand_vertices"][obj.name] = {"count_weight_over_half": len(deltas), "count_rigid": len(rigid_deltas), "max_hand_local_vertex_drift": max(deltas, default=0), "max_rigid_hand_local_vertex_drift": max(rigid_deltas, default=0), "nearest_to_mount": nearest}
        finally:
            evaluated.to_mesh_clear()
    rows.append(row)
result = {"sampled_frames": len(rows), "parent_chain": {"mount_parent": mount.parent.name, "mount_parent_type": mount.parent_type, "mount_parent_bone": mount.parent_bone, "weapon_parent": root.parent.name}, "max_mount_bone_relative_error": max(row["mount_bone_relative_error"] for row in rows), "max_weapon_mount_relative_error": max(row["weapon_mount_relative_error"] for row in rows), "max_mesh_relative_error": max((error for row in rows for error in row["mesh_relative_errors"].values()), default=0), "bone_relative_grip": [list(row) for row in base_mount], "rows": rows}
(HERE / "animation-samples.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8", newline="\r\n")
result["max_bone_head_motion"] = max(sum((row["bone_head"][axis] - rows[0]["bone_head"][axis]) ** 2 for axis in range(3)) ** 0.5 for row in rows)
print("BONE_HEAD_MOTION", result["max_bone_head_motion"])
print("SAMPLED_FRAMES", result["sampled_frames"])
print("MOUNT_BONE_RELATIVE_MAX", result["max_mount_bone_relative_error"])
print("WEAPON_MOUNT_RELATIVE_MAX", result["max_weapon_mount_relative_error"])
print("WEAPON_MESH_RELATIVE_MAX", result["max_mesh_relative_error"])
for name in {name for row in rows for name in row["hand_vertices"]}:
    points = [row["hand_vertices"][name] for row in rows]
    print("HAND_VERTICES", name, points[0]["count_weight_over_half"], "RIGID", points[0]["count_rigid"], "LOCAL_DRIFT", max(point["max_hand_local_vertex_drift"] for point in points), "RIGID_DRIFT", max(point["max_rigid_hand_local_vertex_drift"] for point in points), "NEAREST_MOUNT", min((point["nearest_to_mount"] for point in points if point["nearest_to_mount"] is not None), default=None))
