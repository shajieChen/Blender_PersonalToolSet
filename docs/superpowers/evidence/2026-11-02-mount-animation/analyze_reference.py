import bpy
import json
import pathlib
import numpy as np
from mathutils import Matrix, Vector

HERE = pathlib.Path(__file__).resolve().parent
state = json.loads((HERE / "reference-state.json").read_text(encoding="utf-8"))
snapshot = json.loads((HERE / "snapshot.json").read_text(encoding="utf-8"))
bpy.ops.wm.open_mainfile(filepath=snapshot["snapshot"], use_scripts=False)
scene = bpy.context.scene
source = bpy.data.objects[state["settings"]["source"]]
target = bpy.data.objects[state["settings"]["target"]]
root = bpy.data.objects["GripRoot_WP_A_0300"]
source_mesh = next(obj for obj in source.children if obj.type == "MESH")
weapon_mesh = next(obj for obj in root.children_recursive if obj.type == "MESH")
weapon_bones = {"WP_A_0300"} | {bone.name for bone in source.data.bones["WP_A_0300"].children_recursive}
groups = {group.index for group in source_mesh.vertex_groups if group.name in weapon_bones}
indices = [vertex.index for vertex in source_mesh.data.vertices if sum(item.weight for item in vertex.groups if item.group in groups) > 0.5]
xs = np.array([list(root.matrix_world.inverted() @ weapon_mesh.matrix_world @ vertex.co) for vertex in weapon_mesh.data.vertices], dtype=np.float64)
assert len(indices) == len(xs) and len(xs) > 0
xcenter = xs.mean(axis=0)
x = xs - xcenter
body = next(obj for obj in target.children if obj.type == "MESH" and obj.vertex_groups.get("hand.R"))
hand_group = body.vertex_groups["hand.R"].index
palm_indices = [v.index for v in body.data.vertices if any(item.group == hand_group and item.weight >= 0.999 for item in v.groups)]
assert palm_indices
rows = []
base_local = None
base_grip_local = None
base_palm = None
base_source_weapon_local = None
base_source_hand_basis = None
base_target_hand_basis = None
for frame in range(scene.frame_start, scene.frame_end + 1):
    scene.frame_set(frame)
    deps = bpy.context.evaluated_depsgraph_get()
    evaluated = source_mesh.evaluated_get(deps)
    mesh = evaluated.to_mesh()
    try:
        ys = np.array([list(evaluated.matrix_world @ mesh.vertices[index].co) for index in indices], dtype=np.float64)
    finally:
        evaluated.to_mesh_clear()
    center = ys.mean(axis=0)
    y = ys - center
    u, singular, v = np.linalg.svd(x.T @ y)
    rotation = v.T @ u.T
    if np.linalg.det(rotation) < 0:
        v[-1] *= -1
        rotation = v.T @ u.T
    scale = np.sum((x @ rotation.T) * y) / np.sum(x * x)
    residual = np.linalg.norm(scale * x @ rotation.T - y, axis=1)
    transform = Matrix(rotation.tolist()).to_4x4()
    transform.translation = Vector((center - rotation @ xcenter).tolist())
    source_eval = source.evaluated_get(deps)
    target_eval = target.evaluated_get(deps)
    source_hand = source_eval.matrix_world @ source_eval.pose.bones["R_Hand"].matrix
    target_hand = target_eval.matrix_world @ target_eval.pose.bones["hand.R"].matrix
    source_grip = source_eval.matrix_world @ source_eval.pose.bones["R_Weapon"].matrix
    source_grip_local = transform.inverted() @ source_grip.translation
    object_rotation = target_eval.matrix_world.to_quaternion() @ source_eval.matrix_world.to_quaternion().inverted()
    wanted_rotation = object_rotation @ transform.to_quaternion()
    wanted_local = target_hand.to_quaternion().inverted() @ wanted_rotation
    body_eval = body.evaluated_get(deps)
    mesh = body_eval.to_mesh()
    try:
        palm_world = sum((body_eval.matrix_world @ mesh.vertices[index].co for index in palm_indices), Vector()) / len(palm_indices)
    finally:
        body_eval.to_mesh_clear()
    palm_local = target_hand.inverted() @ palm_world
    if base_local is None:
        base_local = wanted_local.copy()
        base_grip_local = source_grip_local.copy()
        base_palm = palm_local.copy()
    source_weapon_local = source_hand.to_quaternion().inverted() @ transform.to_quaternion()
    source_hand_basis = source_eval.pose.bones["R_Hand"].matrix_basis.to_quaternion()
    target_hand_basis = target_eval.pose.bones["hand.R"].matrix_basis.to_quaternion()
    if base_source_weapon_local is None:
        base_source_weapon_local = source_weapon_local.copy()
        base_source_hand_basis = source_hand_basis.copy()
        base_target_hand_basis = target_hand_basis.copy()
    degrees = lambda a, b: min(float(np.degrees(a.rotation_difference(b).angle)), 360 - float(np.degrees(a.rotation_difference(b).angle)))
    source_relative_change = degrees(base_source_weapon_local, source_weapon_local)
    source_wrist_change = degrees(base_source_hand_basis, source_hand_basis)
    target_wrist_change = degrees(base_target_hand_basis, target_hand_basis)
    error = (target_hand.to_quaternion() @ base_local).rotation_difference(wanted_rotation).angle
    error = min(error, 2 * np.pi - error)
    rows.append({"frame": frame, "rigid_fit_rms": float(np.sqrt(np.mean(residual ** 2))), "scale": float(scale), "constant_mount_rotation_error_degrees": float(np.degrees(error)), "source_weapon_relative_hand_angle_change": source_relative_change, "source_wrist_basis_angle_change": source_wrist_change, "target_wrist_basis_angle_change": target_wrist_change, "source_weapon_grip_local_drift": (source_grip_local - base_grip_local).length, "target_palm_local_drift": (palm_local - base_palm).length})
result = {"frames": len(rows), "matched_vertices": len(xs), "max_constant_mount_rotation_error_degrees": max(row["constant_mount_rotation_error_degrees"] for row in rows), "max_source_rigid_fit_rms": max(row["rigid_fit_rms"] for row in rows), "max_source_grip_local_drift": max(row["source_weapon_grip_local_drift"] for row in rows), "target_palm_rigid_vertices": len(palm_indices), "target_palm_bone_local": list(base_palm), "weapon_model_grip_local": list(base_grip_local), "rotation_in_target_hand": list(base_local), "rows": rows}
(HERE / "reference-alignment-analysis.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({key: value for key, value in result.items() if key != "rows"}, ensure_ascii=True))
print("SOURCE_WEAPON_RELATIVE_HAND_ANGLE_CHANGE", max(row["source_weapon_relative_hand_angle_change"] for row in rows))
print("SOURCE_WRIST_ROTATION_CHANGE", max(row["source_wrist_basis_angle_change"] for row in rows))
print("TARGET_WRIST_ROTATION_CHANGE", max(row["target_wrist_basis_angle_change"] for row in rows))
