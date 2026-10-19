"""Forward recompute using the copy module, then compare with the saved bake."""
from __future__ import annotations

import importlib.util
import json
import math
import sys

import bpy
from mathutils import Quaternion

BLEND = r"H:\Blender_Plugin\tmp_forearm_roll\final_bake.blend"
MODULE = r"H:\Blender_Plugin\tmp_forearm_roll\humanoid_retarget\retarget.py"
OUT = r"H:\Blender_Plugin\tmp_forearm_roll\baked_forearm_quat.json"


def qdeg(a, b):
    a = a.normalized()
    b = b.normalized()
    return math.degrees(2.0 * math.acos(min(1.0, abs(max(-1.0, min(1.0, a.dot(b)))))))


def load_copy():
    root = r"H:\Blender_Plugin\tmp_forearm_roll"
    sys.path.insert(0, root)
    for name in list(sys.modules):
        if name == "humanoid_retarget" or name.startswith("humanoid_retarget."):
            del sys.modules[name]
    import humanoid_retarget.retarget as retarget
    return retarget


def main():
    bpy.ops.wm.open_mainfile(filepath=BLEND)
    retarget = load_copy()
    print("COPY_FILE", retarget.__file__)
    print("HAS_CONTINUITY", hasattr(retarget, "_continuous_forearm_orient"))
    source = next(obj for obj in bpy.data.objects if obj.type == "ARMATURE" and obj.animation_data and obj.animation_data.action and obj.animation_data.action.name == "a050_300000")
    target = bpy.data.objects["Bip01"]
    from humanoid_retarget.mapping import build_pairs
    pairs = build_pairs(source, target)
    roles = {role: target_name for role, _source_name, target_name in pairs}
    options = retarget.RetargetOptions(
        pairs=pairs, forearm_chain_twist=True, foot_ik=False, hand_ik=False, reference="REST",
    )
    options.forearm_roll_continuity = True
    options._forearm_roll_memory = {}
    baked = {}
    solved = {}
    record = {}
    worst = 0.0
    worst_frame = None
    for frame in range(0, 53):
        bpy.context.scene.frame_set(frame)
        baked[frame] = target.pose.bones["Bip01 L Forearm"].matrix_basis.to_quaternion().copy()
        record[str(frame)] = {
            "L": [round(v, 8) for v in target.pose.bones["Bip01 L Forearm"].matrix_basis.to_quaternion()],
            "R": [round(v, 8) for v in target.pose.bones["Bip01 R Forearm"].matrix_basis.to_quaternion()],
        }
        retarget._apply_body_orientations(source, target, pairs, options)
        solved[frame] = target.pose.bones[roles["forearm_l"]].matrix_basis.to_quaternion().copy()
        gap = qdeg(baked[frame], solved[frame])
        if gap > worst:
            worst = gap
            worst_frame = frame
    print("RECOMPUTE_MAX", round(worst, 6), "AT", worst_frame)
    print("FRAME39", round(qdeg(baked[39], solved[39]), 6))
    print("FRAME33_STEP_BAKE", round(qdeg(baked[32], baked[33]), 4))
    print("FRAME19_STEP_BAKE", round(qdeg(baked[18], baked[19]), 4))
    with open(OUT, "w", encoding="utf-8") as handle:
        json.dump(record, handle)
    print("WROTE", OUT)
    print("DONE")


if __name__ == "__main__":
    main()
