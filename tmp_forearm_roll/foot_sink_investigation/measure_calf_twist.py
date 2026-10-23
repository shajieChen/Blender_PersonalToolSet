"""Calf chain-twist facts for FK / legacy foot IK / T3 on one clip. No save."""
import math
import sys

import bpy

ADDONS = r"C:\Users\chenshajie1\AppData\Roaming\Blender Foundation\Blender\5.1\scripts\addons"
SOURCE = r"h:\SErsiko_ExtactedTool\output\c0000_突刺_wp_a_0300.glb"
TARGET = r"c:\Users\chenshajie1\Downloads\body.FBX"


def twist_y(pose_bone):
    quat = pose_bone.matrix_basis.to_quaternion()
    angle = 2.0 * math.degrees(math.atan2(quat.y, quat.w))
    if angle > 180.0:
        angle -= 360.0
    if angle < -180.0:
        angle += 360.0
    return angle


def world_twist(arm, bone_name, child_name):
    from mathutils import Quaternion, Vector

    pose_bone = arm.pose.bones[bone_name]
    rest = pose_bone.bone.matrix_local.to_3x3()
    delta = pose_bone.matrix.to_3x3() @ rest.inverted()
    quat = delta.to_quaternion()
    if quat.w < 0.0:
        quat.negate()
    axis = (arm.pose.bones[child_name].head - pose_bone.head).normalized()
    vector = Vector((quat.x, quat.y, quat.z))
    projected = axis * vector.dot(axis)
    twist = Quaternion((quat.w, projected.x, projected.y, projected.z))
    if twist.magnitude < 1e-10:
        return 0.0
    twist.normalize()
    angle = 2.0 * math.degrees(math.acos(max(-1.0, min(1.0, abs(twist.w)))))
    if Vector((twist.x, twist.y, twist.z)).dot(axis) < 0.0:
        angle = -angle
    return angle


def main():
    sys.path.insert(0, ADDONS)
    for name in list(sys.modules):
        if name == "humanoid_retarget" or name.startswith("humanoid_retarget."):
            del sys.modules[name]
    bpy.ops.wm.read_factory_settings(use_empty=True)
    from humanoid_retarget.mapping import build_pairs
    from humanoid_retarget import pipeline
    import humanoid_retarget.retarget as retarget
    from humanoid_retarget.foot_ik import FootIKSettings

    source, _ = pipeline.load_source(SOURCE)
    objects, _ = pipeline.import_model(TARGET)
    target = pipeline.pick_armature(objects)
    action = next(item for item in retarget.collect_actions(source) if item.name == "a050_300000")
    retarget._assign_action(source, action)
    retarget.collect_actions = lambda _src: [action]
    pairs = build_pairs(source, target)
    start, end = int(action.frame_range[0]), int(round(action.frame_range[1]))

    def bake(label, **overrides):
        values = dict(
            pairs=pairs, root_motion="KEEP", reference="REST",
            foot_ik=True, hand_ik=False,
            foot_ik_settings=FootIKSettings(floor_enabled=True, floor_alpha=1.0, floor_height_m=0.0),
        )
        values.update(overrides)
        retarget.bake_retarget(source, target, retarget.RetargetOptions(**values))
        result = {}
        for side in ("L", "R"):
            bone = target.pose.bones["Bip01 %s Calf" % side]
            series = {}
            for frame in range(start, end + 1):
                bpy.context.scene.frame_set(frame)
                bpy.context.view_layer.update()
                series[frame] = round(world_twist(target, "Bip01 %s Calf" % side, "Bip01 %s Foot" % side), 2)
            steps = {f: round(series[f] - series[f - 1], 2) for f in series if f > start}
            result[side] = (series, steps)
            print(label, side, "twistY", {f: series[f] for f in (0, 14, 15, 16, 17, 18, 19, 20, 24, 52)},
                  "max_abs", max(series.items(), key=lambda kv: abs(kv[1])),
                  "max_step", max(steps.items(), key=lambda kv: abs(kv[1])), flush=True)
        return result

    bake("FK", foot_ik=False)
    bake("LEGACY_IK", contact_min_knee_deg=0.0, correction_smoothing="")
    bake("T3_DEFAULT")
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
