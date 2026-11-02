import bpy
import json
import math
import pathlib
from mathutils import Matrix, Vector

HERE = pathlib.Path(__file__).resolve().parent
snapshot = json.loads((HERE / "snapshot.json").read_text(encoding="utf-8"))
fit = json.loads((HERE / "reference-fit.json").read_text(encoding="utf-8"))
contact = json.loads((HERE / "hand-contact-review.json").read_text(encoding="utf-8"))
state = json.loads((HERE / "reference-state.json").read_text(encoding="utf-8"))
bpy.ops.wm.open_mainfile(filepath=snapshot["snapshot"], use_scripts=False)
scene = bpy.context.scene
scene.frame_set(fit["frame"])
source = bpy.data.objects[state["settings"]["source"]]
target = bpy.data.objects[state["settings"]["target"]]
mount = bpy.data.objects["Mount_hand_r"]
root = bpy.data.objects["GripRoot_WP_A_0300"]
assert root.parent == mount and mount.parent == target and mount.parent_bone == "hand.R"
deps = bpy.context.evaluated_depsgraph_get()
target_eval = target.evaluated_get(deps)
source_eval = source.evaluated_get(deps)
hand = target_eval.pose.bones["hand.R"]
hand_world = target_eval.matrix_world @ hand.matrix
finger_names = ("index_proximal.R", "middle_proximal.R", "ring_proximal.R", "little_proximal.R")
finger_center = sum((target_eval.matrix_world @ target_eval.pose.bones[name].head for name in finger_names), Vector()) / len(finger_names)
palm_world = (hand_world.translation + finger_center) * 0.5
anchor = Vector(contact["weapon_contacts"]["nearby_weapon_center_in_model"])
reference_rotation = Matrix(fit["ordered_fit"]["rotation"]).to_quaternion()
character_delta = target_eval.matrix_world.to_quaternion() @ source_eval.matrix_world.to_quaternion().inverted()
wanted_rotation = character_delta @ reference_rotation
desired = wanted_rotation.to_matrix().to_4x4()
desired.translation = palm_world - desired.to_3x3() @ anchor
old_basis = mount.matrix_basis.copy()
parent_world = mount.matrix_world @ mount.matrix_basis.inverted()
mount.matrix_basis = parent_world.inverted() @ desired
bpy.context.view_layer.update()
print("MAXERROR", max(abs(mount.matrix_world[r][c] - desired[r][c]) for r in range(4) for c in range(4)))
assert max(abs(mount.matrix_world[r][c] - desired[r][c]) for r in range(4) for c in range(4)) < 5e-4
assert (root.matrix_world @ anchor - palm_world).length < 5e-4
weapon_base = (source_eval.matrix_world @ source_eval.pose.bones["R_Weapon"].matrix).to_quaternion()
reference_offset = weapon_base.inverted() @ reference_rotation
rows = []
for frame in range(scene.frame_start, scene.frame_end + 1):
    scene.frame_set(frame)
    deps = bpy.context.evaluated_depsgraph_get()
    se = source.evaluated_get(deps)
    te = target.evaluated_get(deps)
    expected_rotation = te.matrix_world.to_quaternion() @ se.matrix_world.to_quaternion().inverted() @ (se.matrix_world @ se.pose.bones["R_Weapon"].matrix).to_quaternion() @ reference_offset
    actual_rotation = root.evaluated_get(deps).matrix_world.to_quaternion()
    angle = math.degrees(actual_rotation.rotation_difference(expected_rotation).angle)
    angle = min(angle, 360 - angle)
    hand_world = te.matrix_world @ te.pose.bones["hand.R"].matrix
    fingers = sum((te.matrix_world @ te.pose.bones[name].head for name in finger_names), Vector()) / len(finger_names)
    palm = (hand_world.translation + fingers) * 0.5
    grip = root.evaluated_get(deps).matrix_world @ anchor
    rows.append({"frame": frame, "rotation_error_degrees": angle, "grip_to_palm": (grip - palm).length})
result = {"frame": fit["frame"], "old_mount_basis": [list(row) for row in old_basis], "new_mount_basis": [list(row) for row in mount.matrix_basis], "desired_world_at_reference": [list(row) for row in desired], "weapon_grip_local": list(anchor), "palm_world_at_reference": list(palm_world), "max_grip_to_palm": max(row["grip_to_palm"] for row in rows), "max_rotation_error_degrees": max(row["rotation_error_degrees"] for row in rows), "rows": rows}
(HERE / "candidate-grip-alignment.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
print(json.dumps({key:value for key,value in result.items() if key != "rows"}))
