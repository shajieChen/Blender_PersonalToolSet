"""Read-only check: is the frame-39 P0 forearm pose unique within tolerance?

Does not write keyframes or modify the addon. Loads the source clip in a
separate Blender process and reconstructs the current swing formula.
"""
from __future__ import annotations

import math
import sys

import bpy
from mathutils import Quaternion, Vector

ROOT = r"H:\Blender_Plugin"
SOURCE = r"h:\SErsiko_ExtactedTool\output\c0000_突刺_wp_a_0300.glb"
TARGET = r"c:\Users\chenshajie1\Downloads\body.FBX"
ACTION = "a050_300000"
DIRECTION_DOT = 1e-4
TWIST_TOLERANCE = 0.1


def qdeg(a, b):
    a = a.normalized()
    b = b.normalized()
    dot = max(-1.0, min(1.0, a.dot(b)))
    return math.degrees(2.0 * math.acos(min(1.0, abs(dot))))


def project(vector, axis):
    axis = axis.normalized()
    return (vector - axis * vector.dot(axis)).normalized()


def signed(a, b, axis):
    a = project(a, axis)
    b = project(b, axis)
    return math.atan2(a.cross(b).dot(axis.normalized()), a.dot(b))


def marker(matrix, axis):
    columns = [matrix.col[index].xyz for index in range(3)]
    return max(columns, key=lambda column: abs(math.sin(column.angle(axis)))).normalized()


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
    source_body = retarget._body_matrix(source, retarget._anatomical_roles(source, src_roles))
    target_body = retarget._body_matrix(target, retarget._anatomical_roles(target, tgt_roles))
    source_name, hand_name = "L_Forearm", "L_Hand"
    target_name, target_hand = "Bip01 L Forearm", "Bip01 L Hand"
    source_rest_m = source.data.bones[source_name].matrix_local.to_3x3()
    target_rest_m = target.data.bones[target_name].matrix_local.to_3x3()
    source_rest_chain = (source.data.bones[hand_name].head_local - source.data.bones[source_name].head_local).normalized()
    target_rest_chain = (target.data.bones[target_hand].head_local - target.data.bones[target_name].head_local).normalized()
    source_mark = marker(source_rest_m, source_rest_chain)
    target_mark = marker(target_rest_m, target_rest_chain)
    parent = target.pose.bones[target_name].parent
    rest = retarget._rot3(target.data.bones[target_name].matrix_local)
    parent_rest = retarget._rot3(parent.bone.matrix_local)

    def frame_data(frame):
        bpy.context.scene.frame_set(frame)
        chain = (source.pose.bones[hand_name].head - source.pose.bones[source_name].head).normalized()
        desired = (target_body @ (source_body.inverted() @ chain)).normalized()
        posed = source.pose.bones[source_name].matrix.to_3x3() @ (source_rest_m.inverted() @ source_mark)
        twist = signed(source_rest_chain.rotation_difference(chain) @ source_mark, posed, chain)
        parent_pose = retarget._rot3(parent.matrix).copy()
        return desired, twist, parent_pose

    def solve(desired, twist, parent_pose, reference_desired, reference_twist):
        canon = target_rest_chain.rotation_difference(desired)
        orient = Quaternion(desired, twist).to_matrix() @ canon.to_matrix() @ target_rest_m
        basis = (rest.inverted() @ parent_rest @ parent_pose.inverted() @ orient).to_quaternion()
        got_chain = (orient @ (target_rest_m.inverted() @ target_rest_chain)).normalized()
        got_mark = orient @ (target_rest_m.inverted() @ target_mark)
        measured = signed(target_rest_chain.rotation_difference(got_chain) @ target_mark, got_mark, got_chain)
        direction = max(-1.0, min(1.0, got_chain.dot(reference_desired.normalized())))
        return canon, orient.to_quaternion(), basis, math.degrees(measured - reference_twist), math.degrees(math.acos(direction))

    desired38, twist38, parent38 = frame_data(38)
    desired39, twist39, parent39 = frame_data(39)
    canon38, orient38, basis38, err38, dir38 = solve(desired38, twist38, parent38, desired38, twist38)
    canon39, orient39, basis39, err39, dir39 = solve(desired39, twist39, parent39, desired39, twist39)
    relative = (canon39 @ canon38.inverted()).normalized()
    if relative.w < 0.0:
        relative.negate()
    print("SPACE armature-local target vectors and armature-space swing quaternions")
    print(
        "STEP1",
        "swing_delta", round(qdeg(canon38, canon39), 4),
        "rel_angle", round(math.degrees(relative.angle), 4),
        "axis_dot_desired39", round(abs(relative.axis.dot(desired39.normalized())), 6),
        "rest_to_desired", round(math.degrees(target_rest_chain.angle(desired38)), 4),
        round(math.degrees(target_rest_chain.angle(desired39)), 4),
        "orient_delta", round(qdeg(orient38, orient39), 4),
        "basis_delta_fixed_parent", round(qdeg(basis38, basis39), 4),
        "self_twist_err", round(err38, 6), round(err39, 6),
        "self_dir_err", round(dir38, 6), round(dir39, 6),
    )
    for extra in (-0.1, 0.1):
        _canon, _orient, basis, twist_err, direction_err = solve(
            desired39, twist39 + math.radians(extra), parent39, desired39, twist39
        )
        print(
            "STEP2",
            "extra", extra,
            "twist_err", round(twist_err, 6),
            "dir_err", round(direction_err, 6),
            "vs39", round(qdeg(basis, basis39), 6),
            "vs38", round(qdeg(basis, basis38), 4),
        )
    direction_limit = math.acos(1.0 - DIRECTION_DOT)
    max_from_39 = 0.0
    min_from_38 = 180.0
    worst = None
    closest = None
    for radius in (0.0, 0.5 * direction_limit, direction_limit):
        count = 1 if radius == 0.0 else 72
        for index in range(count):
            axis = desired39.normalized()
            seed = Vector((1.0, 0.0, 0.0)) if abs(axis.x) < 0.9 else Vector((0.0, 1.0, 0.0))
            tangent = axis.cross(seed).normalized()
            bitangent = axis.cross(tangent).normalized()
            azimuth = 2.0 * math.pi * index / max(count, 1)
            offset = tangent * math.cos(azimuth) + bitangent * math.sin(azimuth)
            desired = (axis * math.cos(radius) + offset * math.sin(radius)).normalized()
            for extra in (-TWIST_TOLERANCE, 0.0, TWIST_TOLERANCE):
                _canon, _orient, basis, twist_err, direction_err = solve(
                    desired, twist39 + math.radians(extra), parent39, desired39, twist39
                )
                away = qdeg(basis, basis39)
                toward = qdeg(basis, basis38)
                if away > max_from_39:
                    max_from_39 = away
                    worst = (round(math.degrees(radius), 5), extra, round(away, 4), round(toward, 4), round(twist_err, 6), round(direction_err, 6))
                if toward < min_from_38:
                    min_from_38 = toward
                    closest = (round(math.degrees(radius), 5), extra, round(away, 4), round(toward, 4), round(twist_err, 6), round(direction_err, 6))
    print("DIRECTION_LIMIT_DEG", round(math.degrees(direction_limit), 6))
    print("STEP3_MAX_FROM_39", worst)
    print("STEP3_MIN_FROM_38", closest)
    from humanoid_retarget.mapping import build_pairs
    pairs = build_pairs(source, target)
    options = retarget.RetargetOptions(pairs=pairs, forearm_chain_twist=True, foot_ik=False, hand_ik=False)
    quats = {}
    for frame in (38, 39):
        bpy.context.scene.frame_set(frame)
        retarget._apply_body_orientations(source, target, pairs, options)
        quats[frame] = target.pose.bones[target_name].matrix_basis.to_quaternion().copy()
    print("SOLVED_BASIS_DELTA", round(qdeg(quats[38], quats[39]), 4))
    print("DONE")


if __name__ == "__main__":
    main()
