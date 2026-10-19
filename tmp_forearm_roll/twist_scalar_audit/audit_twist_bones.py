"""Bone-axis and twist-bone check. Read-only, no blend save."""
import math
import sys

import bpy
from mathutils import Vector

COPY = r"H:\Blender_Plugin\tmp_forearm_roll"
SOURCE = r"h:\SErsiko_ExtactedTool\output\c0000_突刺_wp_a_0300.glb"
ACTION = "a050_300000"


def qdist(a, b):
    a = a.normalized()
    b = b.normalized()
    return math.degrees(2.0 * math.acos(min(1.0, abs(max(-1.0, min(1.0, a.dot(b)))))))


def main():
    sys.path.insert(0, COPY)
    for name in list(sys.modules):
        if name == "humanoid_retarget" or name.startswith("humanoid_retarget."):
            del sys.modules[name]
    bpy.ops.wm.read_factory_settings(use_empty=True)
    from humanoid_retarget import pipeline
    import humanoid_retarget.retarget as retarget

    source, _ = pipeline.load_source(SOURCE)
    action = next(item for item in retarget.collect_actions(source) if item.name == ACTION)
    retarget._assign_action(source, action)
    scene = bpy.context.scene
    names = ["L_Forearm", "L_ForeArmTwist", "L_ForeArmTwist1", "L_UpperArm"]
    prev = {}
    for frame in (18, 19, 20, 38, 39):
        scene.frame_set(frame)
        bone = source.pose.bones["L_Forearm"]
        child = source.pose.bones["L_Hand"]
        chain = (child.head - bone.head).normalized()
        rest = (
            source.data.bones["L_Hand"].head_local - source.data.bones["L_Forearm"].head_local
        ).normalized()
        posed = bone.matrix.to_3x3().normalized()
        print(
            "AXIS",
            frame,
            "chain_vs_rest",
            round(math.degrees(chain.angle(rest)), 4),
            "chain_vs_x",
            round(math.degrees(chain.angle(posed @ Vector((1, 0, 0)))), 4),
            "chain_vs_y",
            round(math.degrees(chain.angle(posed @ Vector((0, 1, 0)))), 4),
            "chain_vs_z",
            round(math.degrees(chain.angle(posed @ Vector((0, 0, 1)))), 4),
        )
        now = {}
        for name in names:
            pose = source.pose.bones[name]
            quat = pose.matrix.to_quaternion().normalized()
            local = pose.matrix_basis.to_quaternion().normalized()
            now[name] = (quat, local)
            if name in prev:
                print(
                    "BONE",
                    frame,
                    name,
                    "arm",
                    round(qdist(quat, prev[name][0]), 4),
                    "basis",
                    round(qdist(local, prev[name][1]), 4),
                )
        prev = now


if __name__ == "__main__":
    main()
