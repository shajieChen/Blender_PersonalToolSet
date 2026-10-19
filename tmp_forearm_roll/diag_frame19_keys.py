"""Separate source key data from swing roll at frames 18-20."""
from __future__ import annotations

import math
import sys

import bpy
from mathutils import Quaternion, Vector

COPY = r"H:\Blender_Plugin\tmp_forearm_roll"
SOURCE = r"h:\SErsiko_ExtactedTool\output\c0000_突刺_wp_a_0300.glb"
TARGET = r"c:\Users\chenshajie1\Downloads\body.FBX"
ACTION = "a050_300000"


def qdeg(a, b):
    a = a.normalized()
    b = b.normalized()
    dot = max(-1.0, min(1.0, a.dot(b)))
    return math.degrees(2.0 * math.acos(min(1.0, abs(dot))))


def twist_about(quat, axis):
    axis = axis.normalized()
    quat = quat.normalized()
    vector = Vector((quat.x, quat.y, quat.z))
    projected = axis * vector.dot(axis)
    twist = Quaternion((quat.w, projected.x, projected.y, projected.z))
    if twist.magnitude < 1e-10:
        return 0.0
    twist.normalize()
    angle = 2.0 * math.acos(max(-1.0, min(1.0, abs(twist.w))))
    if Vector((twist.x, twist.y, twist.z)).dot(axis) < 0.0:
        angle = -angle
    return math.degrees(angle)


def main():
    sys.path.insert(0, COPY)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    from humanoid_retarget.mapping import build_pairs
    from humanoid_retarget import pipeline
    import humanoid_retarget.retarget as retarget

    source, _ = pipeline.load_source(SOURCE)
    objects, _ = pipeline.import_model(TARGET)
    target = pipeline.pick_armature(objects)
    action = next(item for item in retarget.collect_actions(source) if item.name == ACTION)
    retarget._assign_action(source, action)
    pairs = build_pairs(source, target)
    roles = {role: (source_name, target_name) for role, source_name, target_name in pairs}
    bag = source.animation_data.action.layers[0].strips[0].channelbag(source.animation_data.action_slot)
    for bone in ("L_UpperArm", "L_Forearm", "L_Clavicle", "Pelvis"):
        frames = set()
        modes = set()
        for curve in bag.fcurves:
            if f'pose.bones["{bone}"].' not in curve.data_path:
                continue
            modes.add(curve.data_path.split("].")[-1])
            if "rotation_quaternion" not in curve.data_path:
                continue
            for key in curve.keyframe_points:
                if 16.0 <= key.co[0] <= 22.0:
                    frames.add(round(key.co[0], 4))
        print("KEYS", bone, "paths", sorted(modes), "frames16_22", sorted(frames))
    for bone in ("L_UpperArm", "L_Forearm"):
        print("MODE", bone, source.pose.bones[bone].rotation_mode, target.pose.bones[roles["upperarm_l" if bone == "L_UpperArm" else "forearm_l"][1]].rotation_mode)

    options = retarget.RetargetOptions(
        pairs=pairs, forearm_chain_twist=True, foot_ik=False, hand_ik=False, reference="REST",
    )
    options.forearm_roll_continuity = False
    src_roles = {role: pair[0] for role, pair in roles.items()}
    tgt_roles = {role: pair[1] for role, pair in roles.items()}
    source_body = retarget._body_matrix(source, retarget._anatomical_roles(source, src_roles))
    target_body = retarget._body_matrix(target, retarget._anatomical_roles(target, tgt_roles))
    stored = {}
    for frame in (18, 19, 20):
        bpy.context.scene.frame_set(frame)
        retarget._apply_body_orientations(source, target, pairs, options)
        stored[frame] = {}
        for role, child in (("upperarm_l", "forearm_l"), ("forearm_l", "hand_l")):
            source_name, target_name = roles[role]
            rest = (
                target.data.bones[roles[child][1]].head_local
                - target.data.bones[target_name].head_local
            ).normalized()
            src_chain = (
                source.pose.bones[roles[child][0]].head
                - source.pose.bones[source_name].head
            ).normalized()
            desired = (target_body @ (source_body.inverted() @ src_chain)).normalized()
            swing = rest.rotation_difference(desired)
            stored[frame][role] = {"swing": swing, "desired": desired, "rest": rest}
    for role in ("upperarm_l", "forearm_l"):
        for frame in (19, 20):
            previous = stored[frame - 1][role]
            current = stored[frame][role]
            delta = (current["swing"] @ previous["swing"].inverted()).normalized()
            print(
                role, frame,
                "swingStep", round(qdeg(previous["swing"], current["swing"]), 3),
                "chainStep", round(math.degrees(previous["desired"].angle(current["desired"])), 3),
                "swingRollAboutDesired", round(twist_about(delta, current["desired"]), 3),
                "restAngle", round(math.degrees(current["rest"].angle(current["desired"])), 3),
                "swingFromRest", round(math.degrees(current["swing"].angle), 3),
            )
    print("DONE")


if __name__ == "__main__":
    main()
