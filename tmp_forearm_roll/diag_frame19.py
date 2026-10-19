"""Read-only frame-19 jump diagnosis. Does not save a blend."""
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
    return math.degrees(2.0 * math.acos(min(1.0, abs(dot)))), dot


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
    print("ROLES")
    for role in (
        "hips", "spine", "chest", "shoulder_l", "upperarm_l", "forearm_l", "hand_l",
        "shoulder_r", "upperarm_r", "forearm_r",
    ):
        print(role, roles.get(role))

    def constraints(arm, bone_name):
        bone = arm.pose.bones[bone_name]
        return [(item.type, item.mute, item.influence) for item in bone.constraints]

    for side in ("l", "r"):
        for role in (f"shoulder_{side}", f"upperarm_{side}", f"forearm_{side}", f"hand_{side}"):
            if role not in roles:
                continue
            print("SRC_CONSTRAINT", role, constraints(source, roles[role][0]))
            print("TGT_CONSTRAINT", role, constraints(target, roles[role][1]))

    def fcurve_quat(arm, bone_name, frame):
        anim = arm.animation_data
        if anim is None or anim.action is None:
            return None
        bag = anim.action.layers[0].strips[0].channelbag(anim.action_slot)
        values = [None, None, None, None]
        keyed = False
        for curve in bag.fcurves:
            if f'pose.bones["{bone_name}"].rotation_quaternion' not in curve.data_path:
                continue
            values[curve.array_index] = curve.evaluate(frame)
            for key in curve.keyframe_points:
                if abs(key.co[0] - frame) < 1e-4:
                    keyed = True
        if any(value is None for value in values):
            return None
        quat = Quaternion(values)
        return quat, keyed

    options = retarget.RetargetOptions(
        pairs=pairs, forearm_chain_twist=True, foot_ik=False, hand_ik=False, reference="REST",
    )
    options.forearm_roll_continuity = False
    src_roles = {role: pair[0] for role, pair in roles.items()}
    tgt_roles = {role: pair[1] for role, pair in roles.items()}
    source_body = retarget._body_matrix(source, retarget._anatomical_roles(source, src_roles))
    target_body = retarget._body_matrix(target, retarget._anatomical_roles(target, tgt_roles))
    watched = [role for role in (
        "hips", "spine", "chest", "shoulder_l", "upperarm_l", "forearm_l", "hand_l",
        "shoulder_r", "upperarm_r", "forearm_r", "hand_r",
    ) if role in roles]
    frames = list(range(16, 23))
    rows = {}
    for frame in frames:
        bpy.context.scene.frame_set(frame)
        rows[frame] = {}
        for role in watched:
            source_name, target_name = roles[role]
            source_basis = source.pose.bones[source_name].matrix_basis.to_quaternion().copy()
            source_pose = retarget._rot3(source.pose.bones[source_name].matrix).to_quaternion()
            curve = fcurve_quat(source, source_name, frame)
            rows[frame][role] = {
                "source_basis": source_basis,
                "source_pose": source_pose,
                "source_curve": None if curve is None else curve[0],
                "source_keyed": None if curve is None else curve[1],
            }
        retarget._apply_body_orientations(source, target, pairs, options)
        bpy.context.view_layer.update()
        for role in watched:
            source_name, target_name = roles[role]
            bone = target.pose.bones[target_name]
            child = retarget._CHAIN_CHILD.get(role)
            rest_chain = None
            desired = None
            posed_chain = None
            if child in roles:
                rest_chain = (
                    target.data.bones[roles[child][1]].head_local
                    - target.data.bones[target_name].head_local
                )
                if rest_chain.length > 1e-8:
                    rest_chain.normalize()
                    src_chain = (
                        source.pose.bones[roles[child][0]].head
                        - source.pose.bones[source_name].head
                    ).normalized()
                    desired = (target_body @ (source_body.inverted() @ src_chain)).normalized()
                    posed_chain = (bone.tail - bone.head)
                    end = target.pose.bones[roles[child][1]].head
                    posed_chain = (end - bone.head).normalized()
            rows[frame][role].update({
                "target_basis": bone.matrix_basis.to_quaternion().copy(),
                "target_pose": retarget._rot3(bone.matrix).to_quaternion(),
                "rest_chain": None if rest_chain is None else rest_chain.copy(),
                "desired": None if desired is None else desired.copy(),
                "posed_chain": None if posed_chain is None else posed_chain.copy(),
            })

    print("FRAME role srcBasis srcDot tgtBasis tgtDot srcPose tgtPose restToDesired chainDelta swingDelta curveKeyed")
    for frame in range(17, 23):
        for role in watched:
            previous = rows[frame - 1][role]
            current = rows[frame][role]
            src_step, src_dot = qdeg(previous["source_basis"], current["source_basis"])
            tgt_step, tgt_dot = qdeg(previous["target_basis"], current["target_basis"])
            src_pose, _ = qdeg(previous["source_pose"], current["source_pose"])
            tgt_pose, _ = qdeg(previous["target_pose"], current["target_pose"])
            rest_deg = ""
            chain_delta = ""
            swing_delta = ""
            if current["rest_chain"] is not None and current["desired"] is not None:
                rest_deg = f"{math.degrees(current['rest_chain'].angle(current['desired'])):.3f}"
                chain_delta = f"{math.degrees(previous['desired'].angle(current['desired'])):.3f}"
                swing_prev = previous["rest_chain"].rotation_difference(previous["desired"])
                swing_now = current["rest_chain"].rotation_difference(current["desired"])
                swing_step, _ = qdeg(swing_prev, swing_now)
                swing_delta = f"{swing_step:.3f}"
            curve_step = ""
            if previous["source_curve"] is not None and current["source_curve"] is not None:
                step, dot = qdeg(previous["source_curve"], current["source_curve"])
                curve_step = f"{step:.3f}/{dot:.4f}/keyed={current['source_keyed']}"
            if frame in (18, 19, 20) or tgt_step > 40.0 or src_step > 40.0:
                print(
                    frame, role,
                    f"src {src_step:.3f} dot {src_dot:.4f}",
                    f"tgt {tgt_step:.3f} dot {tgt_dot:.4f}",
                    f"srcPose {src_pose:.3f}",
                    f"tgtPose {tgt_pose:.3f}",
                    f"rest {rest_deg}",
                    f"chain {chain_delta}",
                    f"swing {swing_delta}",
                    f"curve {curve_step}",
                )
    print("DONE")


if __name__ == "__main__":
    main()
