"""A/B forearm chain twist on the real stab clip. Does not keyframe."""
from __future__ import annotations

import math
import sys

import bpy
from mathutils import Quaternion

ROOT = r"H:\Blender_Plugin"
SOURCE = r"h:\SErsiko_ExtactedTool\output\c0000_突刺_wp_a_0300.glb"
TARGET = r"c:\Users\chenshajie1\Downloads\body.FBX"
ACTION = "a050_300000"
FRAMES = list(range(30, 40))


def degrees(radians):
    return math.degrees(radians)


def shortest_quat(a, b):
    dot = max(-1.0, min(1.0, abs(a.normalized().dot(b.normalized()))))
    return degrees(2.0 * math.acos(dot))


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
    return degrees(math.atan2(carried_n.cross(posed_n).dot(axis), carried_n.dot(posed_n)))


def bone_y(quat):
    swing, twist = quat.normalized().to_swing_twist("Y")
    twist = (twist + math.pi) % (2.0 * math.pi) - math.pi
    return degrees(swing.angle), degrees(twist), degrees(quat.angle)


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
    src_roles = {role: source_name for role, source_name, _target_name in pairs}
    tgt_roles = {role: target_name for role, _source_name, target_name in pairs}
    print("PAIRS", [(role, src_roles[role], tgt_roles[role]) for role in ("forearm_l", "hand_l", "upperarm_l")])

    source_body = retarget._body_matrix(source, retarget._anatomical_roles(source, src_roles))
    target_body = retarget._body_matrix(target, retarget._anatomical_roles(target, tgt_roles))
    src_name = src_roles["forearm_l"]
    hand_name = src_roles["hand_l"]
    tgt_name = tgt_roles["forearm_l"]
    tgt_hand = tgt_roles["hand_l"]
    src_rest_m = source.data.bones[src_name].matrix_local.to_3x3()
    tgt_rest_m = target.data.bones[tgt_name].matrix_local.to_3x3()
    src_rest_axis = chain(source, src_name, hand_name, False)
    tgt_rest_axis = chain(target, tgt_name, tgt_hand, False)
    src_mark = marker(src_rest_m, src_rest_axis)
    tgt_mark = marker(tgt_rest_m, tgt_rest_axis)
    print(
        "AXIS_SRC",
        [round(degrees(src_rest_m.col[index].xyz.angle(src_rest_axis)), 2) for index in range(3)],
        "AXIS_TGT",
        [round(degrees(tgt_rest_m.col[index].xyz.angle(tgt_rest_axis)), 2) for index in range(3)],
    )

    stored = {False: {}, True: {}}
    for enabled in (False, True):
        options = retarget.RetargetOptions(pairs=pairs, forearm_chain_twist=enabled)
        print("MODE", "B" if enabled else "A")
        for frame in FRAMES:
            bpy.context.scene.frame_set(frame)
            retarget._apply_body_orientations(source, target, pairs, options)
            src_pose_axis = chain(source, src_name, hand_name, True)
            tgt_pose_axis = chain(target, tgt_name, tgt_hand, True)
            src_pose_m = source.pose.bones[src_name].matrix.to_3x3()
            tgt_pose_m = target.pose.bones[tgt_name].matrix.to_3x3()
            src_roll = roll(src_rest_axis, src_pose_axis, src_mark, src_pose_m @ (src_rest_m.inverted() @ src_mark))
            tgt_roll = roll(tgt_rest_axis, tgt_pose_axis, tgt_mark, tgt_pose_m @ (tgt_rest_m.inverted() @ tgt_mark))
            src_body_axis = (source_body.inverted() @ src_pose_axis).normalized()
            tgt_body_axis = (target_body.inverted() @ tgt_pose_axis).normalized()
            y_swing, y_twist, total = bone_y(target.pose.bones[tgt_name].rotation_quaternion)
            hand_q = target.pose.bones[tgt_hand].rotation_quaternion
            upper_q = target.pose.bones[tgt_roles["upperarm_l"]].rotation_quaternion.copy()
            forearm_q = target.pose.bones[tgt_name].rotation_quaternion.copy()
            stored[enabled][frame] = forearm_q
            print(
                f"F{frame}",
                "src_swing", round(degrees(src_rest_axis.angle(src_pose_axis)), 3),
                "src_twist", round(src_roll, 3),
                "tgt_swing", round(degrees(tgt_rest_axis.angle(tgt_pose_axis)), 3),
                "tgt_twist", round(tgt_roll, 3),
                "dir_dot", round(src_body_axis.dot(tgt_body_axis), 6),
                "roll_err", round(tgt_roll - src_roll, 3),
                "boneY_swing", round(y_swing, 3),
                "boneY_twist", round(y_twist, 3),
                "bone_total", round(total, 3),
                "hand_deg", round(degrees(hand_q.angle), 3),
            )
            if frame == 35 and enabled:
                stored[enabled]["upper35"] = upper_q
        if not enabled:
            bpy.context.scene.frame_set(35)
            retarget._apply_body_orientations(source, target, pairs, options)
            stored[False]["upper35"] = target.pose.bones[tgt_roles["upperarm_l"]].rotation_quaternion.copy()

    for enabled in (False, True):
        q38 = stored[enabled][38]
        q39 = stored[enabled][39]
        raw = degrees(2.0 * math.acos(max(-1.0, min(1.0, q38.normalized().dot(q39.normalized())))))
        print("STEP", "B" if enabled else "A", "shortest", round(shortest_quat(q38, q39), 3), "raw_acos_dot", round(raw, 3), "dot", round(q38.normalized().dot(q39.normalized()), 4))

    upper_delta = shortest_quat(stored[False]["upper35"], stored[True]["upper35"])
    print("UPPERARM_AB_DEG", round(upper_delta, 4))

    options = retarget.RetargetOptions(pairs=pairs, forearm_chain_twist=True)
    bpy.context.scene.frame_set(35)
    retarget._apply_body_orientations(source, target, pairs, options)
    for side in ("l", "r"):
        src_bone = src_roles[f"forearm_{side}"]
        src_hand = src_roles[f"hand_{side}"]
        tgt_bone = tgt_roles[f"forearm_{side}"]
        tgt_hand_name = tgt_roles[f"hand_{side}"]
        src_rest = chain(source, src_bone, src_hand, False)
        src_pose = chain(source, src_bone, src_hand, True)
        tgt_rest = chain(target, tgt_bone, tgt_hand_name, False)
        tgt_pose = chain(target, tgt_bone, tgt_hand_name, True)
        src_m = marker(source.data.bones[src_bone].matrix_local.to_3x3(), src_rest)
        tgt_m = marker(target.data.bones[tgt_bone].matrix_local.to_3x3(), tgt_rest)
        src_posed = source.pose.bones[src_bone].matrix.to_3x3() @ (source.data.bones[src_bone].matrix_local.to_3x3().inverted() @ src_m)
        tgt_posed = target.pose.bones[tgt_bone].matrix.to_3x3() @ (target.data.bones[tgt_bone].matrix_local.to_3x3().inverted() @ tgt_m)
        print(
            "SIDE", side,
            "roll_err", round(roll(tgt_rest, tgt_pose, tgt_m, tgt_posed) - roll(src_rest, src_pose, src_m, src_posed), 4),
            "dir_dot", round((source_body.inverted() @ src_pose).normalized().dot((target_body.inverted() @ tgt_pose).normalized()), 6),
        )

    twist_names = [bone.name for bone in source.data.bones if "Twist" in bone.name and bone.name.startswith("L_Fore")]
    print("SRC_TWIST_BONES", twist_names)
    for name in twist_names:
        bone = source.data.bones[name]
        pose = source.pose.bones[name]
        delta = (pose.matrix.to_3x3() @ bone.matrix_local.to_3x3().inverted()).to_quaternion()
        print(
            "TWIST", name,
            "parent", bone.parent.name if bone.parent else None,
            "len", round(bone.length, 5),
            "mode", pose.rotation_mode,
            "armature_deg", round(degrees(delta.angle), 3),
            "children", [child.name for child in bone.children],
        )
    hand_parent = source.data.bones[hand_name].parent
    hand_pose = source.pose.bones[hand_name]
    hand_delta = (hand_pose.matrix.to_3x3() @ source.data.bones[hand_name].matrix_local.to_3x3().inverted()).to_quaternion()
    print(
        "HAND_PARENT", hand_parent.name if hand_parent else None,
        "HAND_MODE", hand_pose.rotation_mode,
        "HAND_ARMATURE_DEG", round(degrees(hand_delta.angle), 3),
        "HAND_BASIS_DEG", round(degrees(hand_pose.matrix_basis.to_quaternion().angle), 3),
    )
    tgt_twist = [bone.name for bone in target.data.bones if "twist" in bone.name.lower() or "Twist" in bone.name]
    print("TGT_TWIST_BONES", tgt_twist)
    print("TGT_FOREARM_CHILDREN", [child.name for child in target.data.bones[tgt_name].children])

    for obj in objects:
        if obj.type != "MESH":
            continue
        group = obj.vertex_groups.get(tgt_name)
        if group is None:
            print("SKIN", obj.name, "NO_GROUP", tgt_name)
            continue
        weights = []
        for vertex in obj.data.vertices:
            for item in vertex.groups:
                if item.group == group.index and item.weight > 1e-4:
                    weights.append(item.weight)
        print("SKIN", obj.name, "verts", len(obj.data.vertices), "forearm_weighted", len(weights), "max", round(max(weights) if weights else 0.0, 4))


if __name__ == "__main__":
    main()
