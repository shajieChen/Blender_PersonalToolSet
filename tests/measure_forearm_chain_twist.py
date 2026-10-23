"""Compare chain-twist formulas for L_Forearm at frame 35. Does not write the addon."""
from __future__ import annotations

import math
import sys

import bpy
from mathutils import Quaternion, Vector

ROOT = r"H:\Blender_Plugin"
SOURCE = r"h:\SErsiko_ExtactedTool\output\c0000_突刺_wp_a_0300.glb"
TARGET = r"c:\Users\chenshajie1\Downloads\body.FBX"
ACTION = "a050_300000"


def roll(rest_axis, pose_axis, rest_x, pose_x):
    swing = rest_axis.normalized().rotation_difference(pose_axis.normalized())
    carried = swing @ rest_x.normalized()
    axis = pose_axis.normalized()

    def perp(vector):
        vector = vector - axis * vector.dot(axis)
        return vector.normalized()

    carried_n = perp(carried)
    posed_n = perp(pose_x)
    return math.degrees(math.atan2(carried_n.cross(posed_n).dot(axis), carried_n.dot(posed_n)))


def chain(arm, start, end, posed):
    if posed:
        vector = arm.pose.bones[end].head - arm.pose.bones[start].head
    else:
        vector = arm.data.bones[end].head_local - arm.data.bones[start].head_local
    return vector.normalized()


def main():
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    from humanoid_retarget import pipeline
    import humanoid_retarget.retarget as retarget

    source, _ = pipeline.load_source(SOURCE)
    objects, _ = pipeline.import_model(TARGET)
    target = pipeline.pick_armature(objects)
    action = next(item for item in retarget.collect_actions(source) if ACTION in item.name)
    retarget._assign_action(source, action)
    bpy.context.scene.frame_set(35)
    bpy.context.view_layer.update()

    src_roles = {
        "forearm_l": "L_Forearm", "hand_l": "L_Hand",
        "upperarm_l": "L_UpperArm", "upperarm_r": "R_UpperArm",
        "hips": "Pelvis", "head": "Head",
    }
    tgt_roles = {
        "forearm_l": "Bip01 L Forearm", "hand_l": "Bip01 L Hand",
        "upperarm_l": "Bip01 L UpperArm", "upperarm_r": "Bip01 R UpperArm",
        "hips": "Bip01 Pelvis", "head": "Head",
    }
    source_body = retarget._body_matrix(source, src_roles)
    target_body = retarget._body_matrix(target, tgt_roles)
    rest_axis = chain(source, "L_Forearm", "L_Hand", False)
    pose_axis = chain(source, "L_Forearm", "L_Hand", True)
    target_rest = chain(target, "Bip01 L Forearm", "Bip01 L Hand", False)
    def marker(matrix, axis):
        columns = [matrix.col[i].xyz for i in range(3)]
        return max(columns, key=lambda column: abs(math.sin(column.angle(axis)))).normalized()

    source_rest_m = source.data.bones["L_Forearm"].matrix_local.to_3x3()
    source_pose_m = source.pose.bones["L_Forearm"].matrix.to_3x3()
    target_rest_m = target.data.bones["Bip01 L Forearm"].matrix_local.to_3x3()
    source_mark = marker(source_rest_m, rest_axis)
    source_mark_pose = source_pose_m @ (source_rest_m.inverted() @ source_mark)
    target_mark = marker(target_rest_m, target_rest)
    source_roll = roll(rest_axis, pose_axis, source_mark, source_mark_pose)
    print(
        "MARK_SRC", round(math.degrees(source_mark.angle(rest_axis)), 2),
        "MARK_TGT", round(math.degrees(target_mark.angle(target_rest)), 2),
    )
    desired = target_body @ (source_body.inverted() @ pose_axis).normalized()
    rest_orient = target.data.bones["Bip01 L Forearm"].matrix_local.to_3x3()
    aim = target_rest.rotation_difference(desired)
    orient = aim.to_matrix() @ rest_orient
    aim_roll = roll(target_rest, desired, target_mark, orient @ (target_rest_m.inverted() @ target_mark))
    rest_rotation = source.data.bones["L_Forearm"].matrix_local.to_3x3()
    pose_rotation = source.pose.bones["L_Forearm"].matrix.to_3x3()
    delta = (pose_rotation @ rest_rotation.inverted()).to_quaternion().normalized()
    swing = rest_axis.rotation_difference(pose_axis)
    print("SRC_ROLL", round(source_roll, 3), "AIM_ROLL", round(aim_roll, 3))
    for name, twist in {
        "swing_inv_delta": swing.inverted() @ delta,
        "delta_swing_inv": delta @ swing.inverted(),
    }.items():
        axis = twist.axis
        angle = twist.angle if axis.dot(pose_axis) >= 0 else -twist.angle
        print(name, "deg", round(math.degrees(angle), 3), "dot_pose", round(axis.dot(pose_axis), 3), "dot_rest", round(axis.dot(rest_axis), 3))
        for sign in (1, -1):
            trial = Quaternion(desired, sign * angle).to_matrix() @ orient
            rolled = roll(target_rest, desired, target_mark, trial @ (target_rest_m.inverted() @ target_mark))
            print(" ", sign, "roll", round(rolled, 3), "err", round(rolled - source_roll, 3))
    probe = desired.cross(target_mark)
    if probe.length < 1e-6:
        probe = desired.cross(Vector((0.0, 1.0, 0.0)))
    probe.normalize()
    pure = Quaternion(desired, math.radians(79.446))
    turned = pure @ probe
    turned_angle = math.degrees(math.atan2(probe.cross(turned).dot(desired), probe.dot(turned)))
    print("PURE79", round(turned_angle, 3))
    helper = retarget._twist_about_chain(source, "L_Forearm", pose_axis, desired, orient)
    helper_roll = roll(target_rest, desired, target_mark, helper @ (target_rest_m.inverted() @ target_mark))
    print("TORSO_HELPER", round(helper_roll, 3), "ERR", round(helper_roll - source_roll, 3))
    rest_helper = retarget._twist_about_chain(source, "L_Forearm", rest_axis, desired, orient)
    rest_roll = roll(target_rest, desired, target_mark, rest_helper @ (target_rest_m.inverted() @ target_mark))
    print("HELPER_ON_REST_AXIS", round(rest_roll, 3), "ERR", round(rest_roll - source_roll, 3))


if __name__ == "__main__":
    main()
