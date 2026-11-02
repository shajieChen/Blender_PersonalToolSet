import json
import pathlib
import sys

import bpy
from mathutils import Vector

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[3]
snapshot = json.loads((HERE / "snapshot.json").read_text(encoding="utf-8"))
bpy.ops.wm.open_mainfile(filepath=snapshot["snapshot"], use_scripts=False)
sys.path.insert(0, str(ROOT))
import humanoid_mounts
humanoid_mounts.register()
scene = bpy.context.scene
armature = next(obj for obj in scene.objects if obj.type == "ARMATURE" and "hand.R" in obj.data.bones)
mount = bpy.data.objects["Mount_hand_r"]
settings = scene.hm_settings
settings.fitting_stage = "NONE"
settings.armature = armature
settings.part = "hand_r"
settings.mount = mount
scene.frame_set(0)
before = mount.matrix_basis.copy()
assert bpy.ops.humanoid_mounts.estimate_palm() == {"FINISHED"}
after = mount.matrix_basis.copy()
assert max(abs(before[r][c] - after[r][c]) for r in range(3) for c in range(3)) < 1e-5
maximum = 0.0
for frame in range(scene.frame_start, scene.frame_end + 1):
    scene.frame_set(frame)
    deps = bpy.context.evaluated_depsgraph_get()
    evaluated = armature.evaluated_get(deps)
    hand = evaluated.pose.bones["hand.R"]
    children = [child for child in hand.children if any(token in child.name for token in ("index", "middle", "ring", "little"))]
    assert len(children) == 4
    center = sum((evaluated.matrix_world @ child.head for child in children), Vector()) / len(children)
    palm = (evaluated.matrix_world @ hand.head + center) * 0.5
    maximum = max(maximum, (mount.evaluated_get(deps).matrix_world.translation - palm).length)
assert maximum < 1e-5
print("PALM_REAL_SNAPSHOT_FRAMES", scene.frame_end - scene.frame_start + 1)
print("PALM_REAL_SNAPSHOT_MAX_ERROR", maximum)
