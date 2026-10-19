"""Reopen the acceptance bake and measure playback, continuity, and regression."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import sys

import bpy
from mathutils import Quaternion, Vector

COPY = r"H:\Blender_Plugin\tmp_forearm_roll"
BLEND = r"H:\Blender_Plugin\tmp_forearm_roll\acceptance_final\acceptance_bake.blend"
RECORD = r"H:\Blender_Plugin\tmp_forearm_roll\acceptance_final\acceptance_bake_record.json"
CSV_PATH = r"H:\Blender_Plugin\tmp_forearm_roll\acceptance_final\per_frame.csv"
OFFICIAL = r"C:\Users\chenshajie1\AppData\Roaming\Blender Foundation\Blender\5.1\scripts\addons\humanoid_retarget\retarget.py"


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


def digest_bone(action, slot, bone):
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


def load_copy():
    sys.path.insert(0, COPY)
    for name in list(sys.modules):
        if name == "humanoid_retarget" or name.startswith("humanoid_retarget."):
            del sys.modules[name]
    import humanoid_retarget.retarget as retarget
    from humanoid_retarget.mapping import build_pairs
    return retarget, build_pairs


def main():
    with open(RECORD, encoding="utf-8") as handle:
        record = json.load(handle)
    bpy.ops.wm.open_mainfile(filepath=BLEND)
    scene = bpy.context.scene
    scene.tool_settings.use_keyframe_insert_auto = False
    retarget, build_pairs = load_copy()
    print("COPY_FILE", retarget.__file__)
    print("OFFICIAL_SHA", hashlib.sha256(open(OFFICIAL, "rb").read()).hexdigest())
    print("HANDLERS", [handler.__name__ for handler in bpy.app.handlers.frame_change_post])
    source = next(obj for obj in bpy.data.objects if obj.type == "ARMATURE" and obj.name != "Bip01")
    target = bpy.data.objects["Bip01"]
    mesh = bpy.data.objects["body00"]
    action = target.animation_data.action
    slot = target.animation_data.action_slot
    mismatches = []
    for bone, expected in record["digests"].items():
        actual = digest_bone(action, slot, bone)
        print("REOPEN_DIGEST", bone, "MATCH" if actual == expected else "DIFFER", actual["sha256"])
        if actual != expected:
            mismatches.append(bone)
    print("REOPEN_KEY_MATCH", not mismatches)

    def pose_quat(bone):
        return target.pose.bones[bone].matrix_basis.to_quaternion().copy()

    scene.frame_set(39)
    start39 = pose_quat("Bip01 L Forearm")
    sequential = {}
    for frame in range(0, 53):
        scene.frame_set(frame)
        sequential[frame] = pose_quat("Bip01 L Forearm")
    scrub_order = (52, 10, 39, 19, 33, 40, 45, 30, 39)
    scrub = {}
    for frame in scrub_order:
        scene.frame_set(frame)
        scrub[frame] = pose_quat("Bip01 L Forearm")
    scene.frame_set(39)
    replay39 = pose_quat("Bip01 L Forearm")
    print("START39_VS_SEQUENTIAL", round(qdeg(start39, sequential[39]), 8))
    print("SCRUB_MAX", round(max(qdeg(scrub[frame], sequential[frame]) for frame in set(scrub_order)), 8))
    print("REPLAY39_VS_SEQUENTIAL", round(qdeg(replay39, sequential[39]), 8))

    pairs = build_pairs(source, target)
    roles = {role: (source_name, target_name) for role, source_name, target_name in pairs}
    src_roles = {role: pair[0] for role, pair in roles.items()}
    tgt_roles = {role: pair[1] for role, pair in roles.items()}
    source_body = retarget._body_matrix(source, retarget._anatomical_roles(source, src_roles))
    target_body = retarget._body_matrix(target, retarget._anatomical_roles(target, tgt_roles))

    def desired(side):
        chain = (
            source.pose.bones[roles[f"hand_{side}"][0]].head
            - source.pose.bones[roles[f"forearm_{side}"][0]].head
        ).normalized()
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

    def elbow_shift(captured, frame):
        before, bone_before = captured[frame - 1]
        after, bone_after = captured[frame]
        worst = 0.0
        inverse_before = bone_before.inverted()
        inverse_after = bone_after.inverted()
        for index in blended:
            delta = (inverse_before @ before[index]) - (inverse_after @ after[index])
            worst = max(worst, (bone_after.to_3x3() @ delta).length)
        return worst

    watched = ("forearm_l", "forearm_r", "upperarm_l", "upperarm_r", "hand_l", "hand_r", "hips", "spine")
    baked = {}
    baked_elbow = {}
    for frame in range(0, 53):
        scene.frame_set(frame)
        item = {}
        for role in watched:
            if role in roles:
                item[role] = target.pose.bones[roles[role][1]].matrix_basis.to_quaternion().copy()
        item["chain_l"] = (
            target.pose.bones[roles["hand_l"][1]].head - target.pose.bones[roles["forearm_l"][1]].head
        ).normalized()
        item["chain_r"] = (
            target.pose.bones[roles["hand_r"][1]].head - target.pose.bones[roles["forearm_r"][1]].head
        ).normalized()
        item["desired_l"] = desired("l")
        item["desired_r"] = desired("r")
        baked[frame] = item
        if 32 <= frame <= 41:
            baked_elbow[frame] = capture_elbow()

    p0_options = retarget.RetargetOptions(
        pairs=pairs, forearm_chain_twist=True, foot_ik=False, hand_ik=False,
        reference="REST", root_motion="KEEP", joint_limits=False, soft_repulsion=False,
    )
    p0_options.forearm_roll_continuity = False
    forward_options = retarget.RetargetOptions(
        pairs=pairs, forearm_chain_twist=True, foot_ik=False, hand_ik=False,
        reference="REST", root_motion="KEEP", joint_limits=False, soft_repulsion=False,
    )
    forward_options.forearm_roll_continuity = True
    forward_options._forearm_roll_memory = {}
    p0 = {}
    forward = {}
    latch = {}
    p0_elbow = {}
    for frame in range(0, 53):
        scene.frame_set(frame)
        retarget._apply_body_orientations(source, target, pairs, p0_options)
        p0[frame] = {
            role: target.pose.bones[roles[role][1]].matrix_basis.to_quaternion().copy()
            for role in watched if role in roles
        }
        if 32 <= frame <= 41:
            p0_elbow[frame] = capture_elbow()
        retarget._apply_body_orientations(source, target, pairs, forward_options)
        forward[frame] = target.pose.bones[roles["forearm_l"][1]].matrix_basis.to_quaternion().copy()
        state = forward_options._forearm_roll_memory.get("forearm_l")
        latch[frame] = bool(state and state["latched"])

    print("PLAY_30_52_VS_BAKE", round(max(qdeg(sequential[frame], baked[frame]["forearm_l"]) for frame in range(30, 53)), 8))
    print("RECOMPUTE_FORWARD_VS_BAKE", round(max(qdeg(forward[frame], baked[frame]["forearm_l"]) for frame in range(0, 53)), 8))
    print("FRAME39_BAKE_VS_P0", round(qdeg(baked[39]["forearm_l"], p0[39]["forearm_l"]), 4))
    print("START39_VS_P0", round(qdeg(start39, p0[39]["forearm_l"]), 4))
    print("FRAME19_STEP", round(qdeg(baked[18]["forearm_l"], baked[19]["forearm_l"]), 4))
    print("FRAME19_UPPER", round(qdeg(baked[18]["upperarm_l"], baked[19]["upperarm_l"]), 4))
    print("FRAME19_P0DEV", round(qdeg(baked[19]["forearm_l"], p0[19]["forearm_l"]), 4))
    print("FRAME33_STEP", round(qdeg(baked[32]["forearm_l"], baked[33]["forearm_l"]), 4))
    print("FRAME33_P0_STEP", round(qdeg(p0[32]["forearm_l"], p0[33]["forearm_l"]), 4))
    print("FRAME33_P0DEV", round(qdeg(baked[33]["forearm_l"], p0[33]["forearm_l"]), 4))
    print("FRAME33_LATCH", latch[33], "FRAME32_LATCH", latch[32])
    print("LATCH_RANGE", min(frame for frame, on in latch.items() if on), max(frame for frame, on in latch.items() if on))

    rows = []
    for frame in range(0, 53):
        step_l = 0.0 if frame == 0 else qdeg(baked[frame - 1]["forearm_l"], baked[frame]["forearm_l"])
        step_r = 0.0 if frame == 0 else qdeg(baked[frame - 1]["forearm_r"], baked[frame]["forearm_r"])
        step_ul = 0.0 if frame == 0 else qdeg(baked[frame - 1]["upperarm_l"], baked[frame]["upperarm_l"])
        step_ur = 0.0 if frame == 0 else qdeg(baked[frame - 1]["upperarm_r"], baked[frame]["upperarm_r"])
        dot_l = max(-1.0, min(1.0, baked[frame]["chain_l"].dot(baked[frame]["desired_l"])))
        dot_r = max(-1.0, min(1.0, baked[frame]["chain_r"].dot(baked[frame]["desired_r"])))
        dev_l = qdeg(baked[frame]["forearm_l"], p0[frame]["forearm_l"])
        dev_r = qdeg(baked[frame]["forearm_r"], p0[frame]["forearm_r"])
        roll = 0.0 if frame == 0 else twist_about(
            baked[frame]["forearm_l"] @ baked[frame - 1]["forearm_l"].inverted(),
            baked[frame]["chain_l"],
        )
        elbow_bake = elbow_shift(baked_elbow, frame) if frame in baked_elbow and frame - 1 in baked_elbow else ""
        elbow_p0 = elbow_shift(p0_elbow, frame) if frame in p0_elbow and frame - 1 in p0_elbow else ""
        rows.append({
            "frame": frame,
            "step_forearm_l": f"{step_l:.6f}",
            "step_forearm_r": f"{step_r:.6f}",
            "step_upper_l": f"{step_ul:.6f}",
            "step_upper_r": f"{step_ur:.6f}",
            "dir_l_deg": f"{math.degrees(math.acos(dot_l)):.6f}",
            "dir_r_deg": f"{math.degrees(math.acos(dot_r)):.6f}",
            "dir_l_abs_dot_minus_1": f"{abs(dot_l - 1.0):.8e}",
            "p0dev_forearm_l": f"{dev_l:.6f}",
            "p0dev_forearm_r": f"{dev_r:.6f}",
            "chain_roll_l": f"{roll:.6f}",
            "latched": int(latch[frame]),
            "recompute_vs_bake_l": f"{qdeg(forward[frame], baked[frame]['forearm_l']):.6f}",
            "elbow_blend_m": elbow_bake if elbow_bake == "" else f"{elbow_bake:.6f}",
            "elbow_blend_p0_m": elbow_p0 if elbow_p0 == "" else f"{elbow_p0:.6f}",
        })
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    for frame in (19, 33, 34, 35, 36, 37, 38, 39, 40, 52):
        row = rows[frame]
        print(
            "ROW", frame,
            "stepL", row["step_forearm_l"],
            "stepR", row["step_forearm_r"],
            "dirL", row["dir_l_deg"],
            "p0devL", row["p0dev_forearm_l"],
            "p0devR", row["p0dev_forearm_r"],
            "roll", row["chain_roll_l"],
            "elbow", row["elbow_blend_m"],
            "elbowP0", row["elbow_blend_p0_m"],
            "latch", row["latched"],
            "recompute", row["recompute_vs_bake_l"],
        )
    for role in ("forearm_r", "upperarm_l", "upperarm_r", "hand_l", "hand_r", "hips"):
        if role not in baked[0]:
            continue
        dev = max(qdeg(baked[frame][role], p0[frame][role]) for frame in range(0, 53))
        print("REGRESS", role, round(dev, 4))
    end_mismatches = []
    for bone, expected in record["digests"].items():
        actual = digest_bone(action, slot, bone)
        if actual != expected:
            end_mismatches.append(bone)
    print("KEYS_UNCHANGED_AFTER_EVAL", not end_mismatches)
    print("P0_TOLERANCE_CLAIMED", False)
    print("WHOLE_CLIP_CONTINUITY_PASSED", False)
    print("DONE")


if __name__ == "__main__":
    main()
