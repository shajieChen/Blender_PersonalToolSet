import math
import sys
from pathlib import Path

import bpy

ADDONS = Path(bpy.utils.resource_path("USER")) / "scripts" / "addons"
sys.path.insert(0, str(ADDONS))
for name in list(sys.modules):
    if name == "humanoid_retarget" or name.startswith("humanoid_retarget."):
        del sys.modules[name]

from humanoid_retarget import pipeline

for path, frame in ((r"C:\Users\chenshajie1\Downloads\Breathing Idle.fbx", 139),
                    (r"C:\Users\chenshajie1\Downloads\Walking.fbx", 16)):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    source, _ = pipeline.load_source(path)
    bpy.context.scene.frame_set(frame)
    bpy.context.view_layer.update()
    pelvis = source.matrix_world @ source.pose.bones["Bip01 Pelvis"].head
    print("SRC", Path(path).name, "pelvis_z_mm", round(float(pelvis.z) * 1000, 1), flush=True)
    for side in ("L", "R"):
        thigh = source.matrix_world @ source.pose.bones["Bip01 " + side + " Thigh"].head
        knee = source.matrix_world @ source.pose.bones["Bip01 " + side + " Calf"].head
        ankle = source.matrix_world @ source.pose.bones["Bip01 " + side + " Foot"].head
        angle = math.degrees((thigh - knee).angle(ankle - knee))
        print(" ", side, "knee_deg", round(angle, 2), "ankle_z_mm", round(float(ankle.z) * 1000, 1),
              "pelvis_to_ankle_mm", round(float((pelvis - ankle).length) * 1000, 1), flush=True)
    # Rest pelvis height.
    rest = source.data.bones["Bip01 Pelvis"].head_local
    rest_world = source.matrix_world @ rest
    print("  rest_pelvis_z_mm", round(float(rest_world.z) * 1000, 1), flush=True)
