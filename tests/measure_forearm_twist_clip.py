"""Mathematical forearm chain-twist check on a050_300000. Does not keyframe."""
from __future__ import annotations

import math
import sys

import bpy

ROOT = r"H:\Blender_Plugin"
SOURCE = r"h:\SErsiko_ExtactedTool\output\c0000_突刺_wp_a_0300.glb"
TARGET = r"c:\Users\chenshajie1\Downloads\body.FBX"
ACTION = "a050_300000"


def shortest(a, b):
    dot = max(-1.0, min(1.0, abs(a.normalized().dot(b.normalized()))))
    return math.degrees(2.0 * math.acos(dot))


def chain(arm, start, end, posed):
    if posed:
        vector = arm.pose.bones[end].head - arm.pose.bones[start].head
    else:
        vector = arm.data.bones[end].head_local - arm.data.bones[start].head_local
    return vector.normalized()


def marker(matrix, axis):
    columns = [matrix.col[index].xyz for index in range(3)]
    return max(columns, key=lambda column: abs(math.sin(column.angle(axis)))).normalized()


def roll(rest_axis, pose_axis, rest_mark, pose_mark):
    swing = rest_axis.normalized().rotation_difference(pose_axis.normalized())
    carried = swing @ rest_mark.normalized()
    axis = pose_axis.normalized()

    def perp(vector):
        vector = vector - axis * vector.dot(axis)
        return vector.normalized()

    carried_n = perp(carried)
    posed_n = perp(pose_mark)
    return math.degrees(math.atan2(carried_n.cross(posed_n).dot(axis), carried_n.dot(posed_n)))


def main():
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    from humanoid_retarget import pipeline
    from humanoid_retarget.mapping import build_pairs
    import humanoid_retarget.retarget as retarget

    source, _ = pipeline.load_source(SOURCE)
    objects, _ = pipeline.import_model(TARGET)
    target = pipeline.pick_armature(objects)
    action = next(item for item in retarget.collect_actions(source) if ACTION in item.name)
    retarget._assign_action(source, action)
    pairs = build_pairs(source, target)
    src_roles = {role: source_name for role, source_name, _name in pairs}
    tgt_roles = {role: target_name for role, _source_name, target_name in pairs}
    quats = {False: {}, True: {}}
    for enabled in (False, True):
        options = retarget.RetargetOptions(pairs=pairs, forearm_chain_twist=enabled)
        for frame in (35, 38, 39):
            bpy.context.scene.frame_set(frame)
            retarget._apply_body_orientations(source, target, pairs, options)
            for side in ("l", "r"):
                src_bone = src_roles["forearm_" + side]
                src_hand = src_roles["hand_" + side]
                tgt_bone = tgt_roles["forearm_" + side]
                tgt_hand = tgt_roles["hand_" + side]
                src_rest = chain(source, src_bone, src_hand, False)
                src_pose = chain(source, src_bone, src_hand, True)
                tgt_rest = chain(target, tgt_bone, tgt_hand, False)
                tgt_pose = chain(target, tgt_bone, tgt_hand, True)
                src_m = marker(source.data.bones[src_bone].matrix_local.to_3x3(), src_rest)
                tgt_m = marker(target.data.bones[tgt_bone].matrix_local.to_3x3(), tgt_rest)
                src_posed = source.pose.bones[src_bone].matrix.to_3x3() @ (source.data.bones[src_bone].matrix_local.to_3x3().inverted() @ src_m)
                tgt_posed = target.pose.bones[tgt_bone].matrix.to_3x3() @ (target.data.bones[tgt_bone].matrix_local.to_3x3().inverted() @ tgt_m)
                src_twist = roll(src_rest, src_pose, src_m, src_posed)
                tgt_twist = roll(tgt_rest, tgt_pose, tgt_m, tgt_posed)
                mapped = retarget._body_matrix(target, retarget._anatomical_roles(target, tgt_roles)) @ (
                    retarget._body_matrix(source, retarget._anatomical_roles(source, src_roles)).inverted() @ src_pose
                )
                dot = mapped.normalized().dot(tgt_pose.normalized())
                print(
                    "CLIP", "B" if enabled else "A", side, frame,
                    "dot", round(dot, 8),
                    "src", round(src_twist, 5),
                    "tgt", round(tgt_twist, 5),
                    "err", round(tgt_twist - src_twist, 5),
                )
            quats[enabled][frame] = {
                "src": source.pose.bones[src_roles["forearm_l"]].matrix_basis.to_quaternion().copy(),
                "tgt": target.pose.bones[tgt_roles["forearm_l"]].matrix_basis.to_quaternion().copy(),
            }
    for enabled in (False, True):
        print(
            "STEP", "B" if enabled else "A",
            "src", round(shortest(quats[enabled][38]["src"], quats[enabled][39]["src"]), 4),
            "tgt", round(shortest(quats[enabled][39]["tgt"], quats[enabled][38]["tgt"]), 4),
        )


if __name__ == "__main__":
    main()
