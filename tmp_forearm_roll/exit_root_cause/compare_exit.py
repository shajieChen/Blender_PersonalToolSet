"""Compare forearm-roll exit rules in memory. Does not save a blend or edit the addon."""
from __future__ import annotations

import csv
import math
import sys
from pathlib import Path

import bpy
from mathutils import Quaternion, Vector

COPY = r"H:\Blender_Plugin\tmp_forearm_roll"
SOURCE = r"h:\SErsiko_ExtactedTool\output\c0000_突刺_wp_a_0300.glb"
TARGET = r"c:\Users\chenshajie1\Downloads\body.FBX"
ACTION = "a050_300000"
OUT = Path(r"H:\Blender_Plugin\tmp_forearm_roll\exit_root_cause")
BLEND_FRAMES = 8


def wrap(angle):
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


def qdeg(a, b):
    a = a.normalized()
    b = b.normalized()
    return math.degrees(2.0 * math.acos(min(1.0, abs(max(-1.0, min(1.0, a.dot(b)))))))


def make_orient(retarget, mode, rows):
    enter = retarget._FOREARM_ROLL_ENTER
    exit_angle = retarget._FOREARM_ROLL_EXIT
    return_roll = retarget._FOREARM_ROLL_RETURN

    def orient_fn(options, role, desired, twist, p0_orient, rest_chain):
        if not bool(getattr(options, "forearm_roll_continuity", True)):
            return p0_orient
        frame = bpy.context.scene.frame_current
        memory = getattr(options, "_forearm_roll_memory", None)
        if memory is None:
            memory = {}
            options._forearm_roll_memory = memory
        desired = desired.normalized()
        p0_quat = p0_orient.to_quaternion().normalized()
        previous = memory.get(role)
        rest_angle = rest_chain.normalized().angle(desired)
        source_delta = None
        applied_delta = None
        signed = None
        branch = ""
        if previous is None or previous["frame"] != frame - 1:
            orient = p0_quat
            latched = rest_angle >= enter
            blend = 0
            blending = False
            branch = "gap_or_init"
        else:
            carried = previous["desired"].rotation_difference(desired).to_matrix() @ previous["orient"].to_matrix()
            source_delta = wrap(twist - previous["twist"])
            continuous = (Quaternion(desired, source_delta).to_matrix() @ carried).to_quaternion().normalized()
            signed = retarget._twist_component(continuous @ p0_quat.inverted(), desired)
            applied_delta = retarget._twist_component(continuous @ previous["orient"].inverted(), desired)
            if previous["latched"] or previous.get("blending"):
                angle_ok = rest_angle < exit_angle
                roll_ok = abs(signed) <= return_roll
                if mode == "A":
                    if previous["latched"] and angle_ok and roll_ok:
                        orient = p0_quat
                        latched = False
                        blend = 0
                        blending = False
                        branch = "A_exit"
                    else:
                        orient = continuous
                        latched = True
                        blend = 0
                        blending = False
                        branch = "A_hold" if previous["latched"] else "A_gap"
                else:
                    start_blend = previous["latched"] and angle_ok and not previous.get("blending")
                    keep_blend = previous.get("blending") and rest_angle < enter
                    if start_blend or keep_blend:
                        blend = previous.get("blend", 0) + 1
                        factor = min(1.0, blend / float(BLEND_FRAMES))
                        if mode == "B":
                            orient = continuous.slerp(p0_quat, factor)
                            branch = "B_blend"
                        else:
                            orient = (Quaternion(desired, -signed * factor) @ continuous).normalized()
                            branch = "C_blend"
                        blending = factor < 1.0
                        latched = False
                    elif rest_angle >= enter:
                        orient = continuous
                        latched = True
                        blend = 0
                        blending = False
                        branch = "reenter"
                    else:
                        orient = continuous
                        latched = True
                        blend = 0
                        blending = False
                        branch = "hold"
            elif rest_angle >= enter:
                orient = continuous
                latched = True
                blend = 0
                blending = False
                branch = "enter"
            else:
                orient = p0_quat
                latched = False
                blend = 0
                blending = False
                branch = "p0"
        memory[role] = {
            "frame": frame,
            "desired": desired.copy(),
            "twist": twist,
            "orient": orient.copy(),
            "latched": latched,
            "blend": blend,
            "blending": blending,
        }
        if role == "forearm_l":
            rows.append({
                "mode": mode,
                "frame": frame,
                "branch": branch,
                "rest_deg": math.degrees(rest_angle),
                "latched": int(latched),
                "blending": int(blending),
                "blend": blend,
                "source_twist_deg": math.degrees(twist),
                "source_delta_deg": "" if source_delta is None else math.degrees(source_delta),
                "applied_delta_deg": "" if applied_delta is None else math.degrees(applied_delta),
                "signed_roll_deg": "" if signed is None else math.degrees(signed),
                "angle_below_150": int(rest_angle < exit_angle),
                "roll_within_8": int(signed is not None and abs(signed) <= return_roll),
            })
        return orient.to_matrix()

    return orient_fn


def main():
    sys.path.insert(0, COPY)
    for name in list(sys.modules):
        if name == "humanoid_retarget" or name.startswith("humanoid_retarget."):
            del sys.modules[name]
    bpy.ops.wm.read_factory_settings(use_empty=True)
    from humanoid_retarget.mapping import build_pairs
    from humanoid_retarget import pipeline
    import humanoid_retarget.retarget as retarget

    source, _ = pipeline.load_source(SOURCE)
    objects, _ = pipeline.import_model(TARGET)
    target = pipeline.pick_armature(objects)
    mesh = next(obj for obj in objects if obj.type == "MESH")
    action = next(item for item in retarget.collect_actions(source) if item.name == ACTION)
    retarget._assign_action(source, action)
    pairs = build_pairs(source, target)
    roles = {role: (source_name, target_name) for role, source_name, target_name in pairs}
    watched = ("forearm_l", "forearm_r", "upperarm_l", "upperarm_r")
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
    src_roles = {role: pair[0] for role, pair in roles.items()}
    tgt_roles = {role: pair[1] for role, pair in roles.items()}
    source_body = retarget._body_matrix(source, retarget._anatomical_roles(source, src_roles))
    target_body = retarget._body_matrix(target, retarget._anatomical_roles(target, tgt_roles))

    def desired_chain():
        chain = (
            source.pose.bones[roles["hand_l"][0]].head
            - source.pose.bones[roles["forearm_l"][0]].head
        ).normalized()
        return (target_body @ (source_body.inverted() @ chain)).normalized()

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

    def run(mode, order, fresh_each=False):
        rows = []
        retarget._continuous_forearm_orient = make_orient(retarget, mode, rows)
        options = retarget.RetargetOptions(
            pairs=pairs, forearm_chain_twist=True, foot_ik=False, hand_ik=False,
            reference="REST", root_motion="KEEP", joint_limits=False, soft_repulsion=False,
        )
        options.forearm_roll_continuity = True
        options._forearm_roll_memory = {}
        poses = {}
        elbows = {}
        directions = {}
        for frame in order:
            if fresh_each:
                options._forearm_roll_memory = {}
            bpy.context.scene.frame_set(frame)
            retarget._apply_body_orientations(source, target, pairs, options)
            poses[frame] = {
                role: target.pose.bones[roles[role][1]].matrix_basis.to_quaternion().copy()
                for role in watched
            }
            got = (
                target.pose.bones[roles["hand_l"][1]].head
                - target.pose.bones[roles["forearm_l"][1]].head
            ).normalized()
            want = desired_chain()
            directions[frame] = math.degrees(got.angle(want))
            if 32 <= frame <= 52 and order == list(range(0, 53)):
                elbows[frame] = capture_elbow()
        return poses, rows, directions, elbows

    retarget._continuous_forearm_orient = lambda options, role, desired, twist, p0_orient, rest_chain: p0_orient
    p0_options = retarget.RetargetOptions(
        pairs=pairs, forearm_chain_twist=True, foot_ik=False, hand_ik=False,
        reference="REST", root_motion="KEEP", joint_limits=False, soft_repulsion=False,
    )
    p0_options.forearm_roll_continuity = False
    p0_poses = {}
    p0_elbows = {}
    for frame in range(0, 53):
        bpy.context.scene.frame_set(frame)
        retarget._apply_body_orientations(source, target, pairs, p0_options)
        p0_poses[frame] = {
            role: target.pose.bones[roles[role][1]].matrix_basis.to_quaternion().copy()
            for role in watched
        }
        if 32 <= frame <= 52:
            p0_elbows[frame] = capture_elbow()

    summaries = []
    all_rows = []
    for mode in ("A", "B", "C"):
        forward, rows, directions, elbows = run(mode, list(range(0, 53)))
        repeat, _, _, _ = run(mode, list(range(0, 53)))
        reverse, _, _, _ = run(mode, list(range(52, -1, -1)))
        single, _, _, _ = run(mode, [39], fresh_each=True)
        by_frame = {row["frame"]: row for row in rows}
        for frame, row in by_frame.items():
            row["basis_step_deg"] = 0.0 if frame == 0 else qdeg(forward[frame - 1]["forearm_l"], forward[frame]["forearm_l"])
            row["dir_deg"] = directions[frame]
            row["p0dev_deg"] = qdeg(forward[frame]["forearm_l"], p0_poses[frame]["forearm_l"])
            row["elbow_m"] = elbow_shift(elbows, frame) if frame in elbows and frame - 1 in elbows else ""
            row["elbow_p0_m"] = elbow_shift(p0_elbows, frame) if frame in p0_elbows and frame - 1 in p0_elbows else ""
            all_rows.append(row)
        exit_steps = [
            row["basis_step_deg"] for row in rows
            if row["branch"] in {"B_blend", "C_blend", "A_exit"}
        ]
        def dev(role):
            return max(qdeg(forward[frame][role], p0_poses[frame][role]) for frame in range(30, 53))
        summaries.append({
            "mode": mode,
            "step_38_39": qdeg(forward[38]["forearm_l"], forward[39]["forearm_l"]),
            "step_39_40": qdeg(forward[39]["forearm_l"], forward[40]["forearm_l"]),
            "exit_max_step": max(exit_steps) if exit_steps else 0.0,
            "exit_frames": [row["frame"] for row in rows if row["branch"] in {"B_blend", "C_blend", "A_exit"}],
            "end_vs_start": qdeg(forward[0]["forearm_l"], forward[52]["forearm_l"]),
            "max_dir": max(directions[frame] for frame in range(30, 53)),
            "max_source_gap": max(
                (0.0 if row["applied_delta_deg"] == "" or row["source_delta_deg"] == ""
                 else abs(float(row["applied_delta_deg"]) - float(row["source_delta_deg"])))
                for row in rows if 30 <= row["frame"] <= 52
            ),
            "dev_forearm_l": dev("forearm_l"),
            "dev_forearm_r": dev("forearm_r"),
            "dev_upper_l": dev("upperarm_l"),
            "dev_upper_r": dev("upperarm_r"),
            "repeat": max(qdeg(forward[frame]["forearm_l"], repeat[frame]["forearm_l"]) for frame in range(0, 53)),
            "reverse39_vs_forward": qdeg(reverse[39]["forearm_l"], forward[39]["forearm_l"]),
            "single39_vs_forward": qdeg(single[39]["forearm_l"], forward[39]["forearm_l"]),
            "single39_vs_p0": qdeg(single[39]["forearm_l"], p0_poses[39]["forearm_l"]),
            "elbow39": elbow_shift(elbows, 39) if 39 in elbows and 38 in elbows else None,
        })
        print("MODE", mode, {key: (round(value, 4) if isinstance(value, float) else value) for key, value in summaries[-1].items()})

    OUT.mkdir(parents=True, exist_ok=True)
    fieldnames = list(all_rows[0].keys())
    with (OUT / "exit_trace.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)
    print("WROTE", OUT / "exit_trace.csv")
    print("DONE")


if __name__ == "__main__":
    main()
