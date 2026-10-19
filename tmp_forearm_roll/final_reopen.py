"""Reopen the temporary bake and check playback against the stored keys."""
from __future__ import annotations

import hashlib
import json
import math
import sys

import bpy
from mathutils import Quaternion, Vector

COPY = r"H:\Blender_Plugin\tmp_forearm_roll"
BLEND = r"H:\Blender_Plugin\tmp_forearm_roll\final_bake.blend"
RECORD = r"H:\Blender_Plugin\tmp_forearm_roll\final_bake_record.json"


def qdeg(a, b):
    a = a.normalized()
    b = b.normalized()
    return math.degrees(2.0 * math.acos(min(1.0, abs(max(-1.0, min(1.0, a.dot(b)))))))


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


def digest(action, slot, bone):
    bag = action.layers[0].strips[0].channelbag(slot)
    hasher = hashlib.sha256()
    count = 0
    frames = set()
    for curve in bag.fcurves:
        if f'pose.bones["{bone}"].rotation_quaternion' not in curve.data_path:
            continue
        count += 1
        for key in curve.keyframe_points:
            frames.add(int(round(key.co[0])))
            hasher.update(f"{curve.array_index}:{key.co[0]:.6f},{key.co[1]:.8f};".encode())
    return {"curves": count, "frames": len(frames), "sha256": hasher.hexdigest()}


def main():
    sys.path.insert(0, COPY)
    with open(RECORD, encoding="utf-8") as handle:
        record = json.load(handle)
    bpy.ops.wm.open_mainfile(filepath=BLEND)
    from humanoid_retarget.mapping import build_pairs
    import humanoid_retarget.retarget as retarget

    source = next(obj for obj in bpy.data.objects if obj.type == "ARMATURE" and obj.name != "Bip01")
    target = bpy.data.objects["Bip01"]
    mesh = bpy.data.objects["body00"]
    action = target.animation_data.action
    print("REOPEN_ACTION", action.name, "FRAME", bpy.context.scene.frame_current)
    mismatches = []
    for bone, expected in record["digests"].items():
        actual = digest(action, target.animation_data.action_slot, bone)
        same = actual == expected
        print("REOPEN_DIGEST", bone, "MATCH" if same else "DIFFER", actual["sha256"])
        if not same:
            mismatches.append(bone)
    print("REOPEN_KEY_MATCH", not mismatches)

    def pose_quat(frame, bone):
        bpy.context.scene.frame_set(frame)
        return target.pose.bones[bone].matrix_basis.to_quaternion().copy()

    sequential = {frame: pose_quat(frame, "Bip01 L Forearm") for frame in range(30, 53)}
    scrub_order = (10, 52, 19, 39, 33, 40, 45, 39)
    scrub = {frame: pose_quat(frame, "Bip01 L Forearm") for frame in scrub_order}
    direct = {}
    for frame in (39, 40, 41, 52):
        direct[frame] = pose_quat(frame, "Bip01 L Forearm")

    pairs = build_pairs(source, target)
    roles = {role: (source_name, target_name) for role, source_name, target_name in pairs}
    options = retarget.RetargetOptions(
        pairs=pairs, forearm_chain_twist=True, foot_ik=False, hand_ik=False, reference="REST",
    )
    options.forearm_roll_continuity = False
    p0 = {}
    forward = {}
    options_forward = retarget.RetargetOptions(
        pairs=pairs, forearm_chain_twist=True, foot_ik=False, hand_ik=False, reference="REST",
    )
    options_forward.forearm_roll_continuity = True
    options_forward._forearm_roll_memory = {}
    src_roles = {role: pair[0] for role, pair in roles.items()}
    tgt_roles = {role: pair[1] for role, pair in roles.items()}
    source_body = retarget._body_matrix(source, retarget._anatomical_roles(source, src_roles))
    target_body = retarget._body_matrix(target, retarget._anatomical_roles(target, tgt_roles))
    rest_chain = (
        target.data.bones[roles["forearm_l"][1]].tail_local * 0.0
        + target.data.bones[roles["hand_l"][1]].head_local
        - target.data.bones[roles["forearm_l"][1]].head_local
    ).normalized()

    def desired_of(side):
        source_name = roles[f"forearm_{side}"][0]
        hand_name = roles[f"hand_{side}"][0]
        chain = (source.pose.bones[hand_name].head - source.pose.bones[source_name].head).normalized()
        return (target_body @ (source_body.inverted() @ chain)).normalized()

    group = {item.name: item.index for item in mesh.vertex_groups}

    def weight(vertex, name):
        index = group[name]
        for item in vertex.groups:
            if item.group == index:
                return item.weight
        return 0.0

    forearm_name = roles["forearm_l"][1]
    upper_name = roles["upperarm_l"][1]
    blended = [
        vertex.index for vertex in mesh.data.vertices
        if 0.0 < weight(vertex, forearm_name) < 0.999 and weight(vertex, upper_name) > 0.0
    ]

    def capture_elbow():
        depsgraph = bpy.context.evaluated_depsgraph_get()
        evaluated = mesh.evaluated_get(depsgraph)
        temporary = evaluated.to_mesh()
        world = evaluated.matrix_world.copy()
        points = {index: world @ temporary.vertices[index].co for index in blended}
        evaluated.to_mesh_clear()
        arm_eval = target.evaluated_get(depsgraph)
        bone = arm_eval.matrix_world @ arm_eval.pose.bones[forearm_name].matrix
        return points, bone

    baked_pose = {}
    baked_elbow = {}
    for frame in range(0, 53):
        bpy.context.scene.frame_set(frame)
        baked_pose[frame] = {
            "forearm_l": target.pose.bones[roles["forearm_l"][1]].matrix_basis.to_quaternion().copy(),
            "forearm_r": target.pose.bones[roles["forearm_r"][1]].matrix_basis.to_quaternion().copy(),
            "upperarm_l": target.pose.bones[roles["upperarm_l"][1]].matrix_basis.to_quaternion().copy(),
            "upperarm_r": target.pose.bones[roles["upperarm_r"][1]].matrix_basis.to_quaternion().copy(),
            "hand_l": target.pose.bones[roles["hand_l"][1]].matrix_basis.to_quaternion().copy(),
            "hand_r": target.pose.bones[roles["hand_r"][1]].matrix_basis.to_quaternion().copy(),
            "hips": target.pose.bones[roles["hips"][1]].matrix_basis.to_quaternion().copy(),
            "chain": (
                target.pose.bones[roles["hand_l"][1]].head - target.pose.bones[roles["forearm_l"][1]].head
            ).normalized(),
            "desired": desired_of("l"),
            "desired_r": desired_of("r"),
            "chain_r": (
                target.pose.bones[roles["hand_r"][1]].head - target.pose.bones[roles["forearm_r"][1]].head
            ).normalized(),
        }
        if frame in range(32, 42):
            baked_elbow[frame] = capture_elbow()
        retarget._apply_body_orientations(source, target, pairs, options)
        p0[frame] = {
            role: target.pose.bones[roles[role][1]].matrix_basis.to_quaternion().copy()
            for role in ("forearm_l", "forearm_r", "upperarm_l", "upperarm_r", "hand_l", "hand_r", "hips")
        }
        retarget._apply_body_orientations(source, target, pairs, options_forward)
        forward[frame] = target.pose.bones[roles["forearm_l"][1]].matrix_basis.to_quaternion().copy()

    play_error = max(qdeg(sequential[frame], baked_pose[frame]["forearm_l"]) for frame in range(30, 53))
    scrub_error = max(qdeg(scrub[frame], baked_pose[frame]["forearm_l"]) for frame in set(scrub_order))
    direct_error = max(qdeg(direct[frame], baked_pose[frame]["forearm_l"]) for frame in direct)
    recompute_error = max(qdeg(forward[frame], baked_pose[frame]["forearm_l"]) for frame in range(0, 53))
    print("PLAY_30_52_VS_BAKE", round(play_error, 8))
    print("SCRUB_VS_BAKE", round(scrub_error, 8))
    print("START39_VS_BAKE", round(direct_error, 8))
    print("RECOMPUTE_FORWARD_VS_BAKE", round(recompute_error, 8))
    print("FRAME39_BAKE_VS_P0", round(qdeg(baked_pose[39]["forearm_l"], p0[39]["forearm_l"]), 4))
    print("START39_VS_P0", round(qdeg(direct[39], p0[39]["forearm_l"]), 4))

    print("FRAME stepL rollL dirL p0dev stepR dirR elbow")
    for frame in range(30, 53):
        step_l = 0.0 if frame == 30 else qdeg(baked_pose[frame - 1]["forearm_l"], baked_pose[frame]["forearm_l"])
        step_r = 0.0 if frame == 30 else qdeg(baked_pose[frame - 1]["forearm_r"], baked_pose[frame]["forearm_r"])
        roll = 0.0 if frame == 30 else twist_about(
            baked_pose[frame]["forearm_l"] @ baked_pose[frame - 1]["forearm_l"].inverted(),
            baked_pose[frame]["chain"],
        )
        dot = max(-1.0, min(1.0, baked_pose[frame]["chain"].dot(baked_pose[frame]["desired"])))
        dot_r = max(-1.0, min(1.0, baked_pose[frame]["chain_r"].dot(baked_pose[frame]["desired_r"])))
        dev = qdeg(baked_pose[frame]["forearm_l"], p0[frame]["forearm_l"])
        elbow = ""
        if frame in baked_elbow and frame - 1 in baked_elbow:
            before, bone_before = baked_elbow[frame - 1]
            after, bone_after = baked_elbow[frame]
            worst = 0.0
            inverse_before = bone_before.inverted()
            inverse_after = bone_after.inverted()
            for index in blended:
                delta = (inverse_before @ before[index]) - (inverse_after @ after[index])
                worst = max(worst, (bone_after.to_3x3() @ delta).length)
            elbow = f"{worst:.4f}"
        print(
            frame,
            f"{step_l:.3f}",
            f"{roll:.3f}",
            f"{math.degrees(math.acos(dot)):.5f}",
            f"{dev:.3f}",
            f"{step_r:.3f}",
            f"{math.degrees(math.acos(dot_r)):.5f}",
            elbow,
        )
    for frame, label in ((19, "F19"), (33, "F33"), (1, "F01")):
        print(
            label,
            "stepL", round(qdeg(baked_pose[frame - 1]["forearm_l"], baked_pose[frame]["forearm_l"]), 3),
            "stepUpperL", round(qdeg(baked_pose[frame - 1]["upperarm_l"], baked_pose[frame]["upperarm_l"]), 3),
            "stepR", round(qdeg(baked_pose[frame - 1]["forearm_r"], baked_pose[frame]["forearm_r"]), 3),
            "p0devL", round(qdeg(baked_pose[frame]["forearm_l"], p0[frame]["forearm_l"]), 3),
        )
    for role in ("forearm_r", "upperarm_l", "upperarm_r", "hand_l", "hand_r", "hips"):
        dev = max(qdeg(baked_pose[frame][role], p0[frame][role]) for frame in range(0, 53))
        window = max(qdeg(baked_pose[frame][role], p0[frame][role]) for frame in range(30, 53))
        print("REGRESS", role, "max", round(dev, 4), "from30", round(window, 4))
    print("DONE")


if __name__ == "__main__":
    main()
