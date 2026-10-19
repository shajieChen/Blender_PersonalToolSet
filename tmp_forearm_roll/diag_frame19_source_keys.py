"""Source quaternion steps at the actual key times around frame 19."""
from __future__ import annotations

import math

import bpy
from mathutils import Quaternion

SOURCE = r"h:\SErsiko_ExtactedTool\output\c0000_突刺_wp_a_0300.glb"
ACTION = "a050_300000"


def qdeg(a, b):
    a = a.normalized()
    b = b.normalized()
    dot = max(-1.0, min(1.0, a.dot(b)))
    return math.degrees(2.0 * math.acos(min(1.0, abs(dot)))), dot


def main():
    sys_path = r"H:\Blender_Plugin\tmp_forearm_roll"
    import sys
    sys.path.insert(0, sys_path)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    from humanoid_retarget import pipeline
    import humanoid_retarget.retarget as retarget

    source, _ = pipeline.load_source(SOURCE)
    action = next(item for item in retarget.collect_actions(source) if item.name == ACTION)
    retarget._assign_action(source, action)
    bag = source.animation_data.action.layers[0].strips[0].channelbag(source.animation_data.action_slot)

    def quat_at(bone, frame):
        values = [None] * 4
        for curve in bag.fcurves:
            if f'pose.bones["{bone}"].rotation_quaternion' not in curve.data_path:
                continue
            values[curve.array_index] = curve.evaluate(frame)
        return Quaternion(values)

    def key_times(bone):
        times = set()
        for curve in bag.fcurves:
            if f'pose.bones["{bone}"].rotation_quaternion' not in curve.data_path or curve.array_index != 0:
                continue
            for key in curve.keyframe_points:
                if 14.0 <= key.co[0] <= 24.0:
                    times.add(round(key.co[0], 4))
                    print(
                        "HANDLE", bone, round(key.co[0], 4),
                        "interp", key.interpolation,
                        "left", tuple(round(v, 4) for v in key.handle_left),
                        "co", tuple(round(v, 4) for v in key.co),
                        "right", tuple(round(v, 4) for v in key.handle_right),
                    )
        return sorted(times)

    for bone in ("L_UpperArm", "L_Forearm"):
        times = key_times(bone)
        print("STEPS", bone)
        previous = None
        previous_time = None
        for time in times:
            quat = quat_at(bone, time)
            if previous is not None:
                step, dot = qdeg(previous, quat)
                print(f"  {previous_time:.1f}->{time:.1f} step {step:.3f} dot {dot:.4f}")
            previous = quat
            previous_time = time
        print("INTEGER", bone)
        previous = None
        for frame in range(16, 23):
            quat = quat_at(bone, frame)
            if previous is not None:
                step, dot = qdeg(previous, quat)
                print(f"  {frame - 1}->{frame} step {step:.3f} dot {dot:.4f}")
            previous = quat
    print("DONE")


if __name__ == "__main__":
    main()
