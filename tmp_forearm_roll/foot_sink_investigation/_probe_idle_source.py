import sys
from pathlib import Path

import bpy

ADDONS = Path(bpy.utils.resource_path("USER")) / "scripts" / "addons"
sys.path.insert(0, str(ADDONS))
for name in list(sys.modules):
    if name == "humanoid_retarget" or name.startswith("humanoid_retarget."):
        del sys.modules[name]

from humanoid_retarget import pipeline

for path in (r"C:\Users\chenshajie1\Downloads\Breathing Idle.fbx",
             r"C:\Users\chenshajie1\Downloads\Walking.fbx"):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    source, _ = pipeline.load_source(path)
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    print("SRC", path, "arm_loc", tuple(round(v, 3) for v in source.location),
          "scale", tuple(round(v, 4) for v in source.scale), "meshes", [m.name for m in meshes], flush=True)
    action = source.animation_data.action
    start, end = int(action.frame_range[0]), int(round(action.frame_range[1]))
    for frame in (start, (start + end) // 2, end):
        bpy.context.scene.frame_set(frame)
        bpy.context.view_layer.update()
        for side in ("L", "R"):
            foot = source.pose.bones["Bip01 " + side + " Foot"]
            head = source.matrix_world @ foot.head
            print(" frame", frame, side, "ankle_world_z_mm", round(float(head.z) * 1000, 1), flush=True)
        # Mesh lowest (source character's own skin).
        for mesh in meshes:
            deps = bpy.context.evaluated_depsgraph_get()
            ev = mesh.evaluated_get(deps)
            posed = ev.to_mesh()
            low = min((ev.matrix_world @ v.co).z for v in posed.vertices)
            ev.to_mesh_clear()
            print(" frame", frame, "mesh", mesh.name, "lowest_mm", round(float(low) * 1000, 1), flush=True)
