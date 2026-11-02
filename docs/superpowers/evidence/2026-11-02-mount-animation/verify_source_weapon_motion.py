import bpy
import pathlib
import json
import math

HERE = pathlib.Path(__file__).resolve().parent
snapshot = json.loads((HERE / "snapshot.json").read_text(encoding="utf-8"))
bpy.ops.wm.open_mainfile(filepath=snapshot["snapshot"], use_scripts=False)
scene = bpy.context.scene
source = bpy.data.objects["Armature"]
names = ("R_Hand", "R_Weapon", "WP_A_0300")
base = {}
maximum = dict.fromkeys(names, 0.0)
for frame in range(scene.frame_start, scene.frame_end + 1):
    scene.frame_set(frame)
    evaluated = source.evaluated_get(bpy.context.evaluated_depsgraph_get())
    for name in names:
        rotation = evaluated.pose.bones[name].matrix_basis.to_quaternion()
        base.setdefault(name, rotation.copy())
        angle = math.degrees(base[name].rotation_difference(rotation).angle)
        maximum[name] = max(maximum[name], min(angle, 360 - angle))
result = {"sampled_frames": scene.frame_end - scene.frame_start + 1, "max_local_rotation_change_degrees": maximum}
(HERE / "source-weapon-motion.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
print(json.dumps(result))
