"""Endpoint-locked calf roll, plan/bake split, and hand+foot frame-6 trace.

Experiment copy only. No save. Each bake clears the height-plan cache.
"""
import csv
import json
import math
import sys

import bpy

COPY = r"H:\Blender_Plugin\tmp_forearm_roll"
SOURCE = r"h:\SErsiko_ExtactedTool\output\c0000_突刺_wp_a_0300.glb"
TARGET = r"c:\Users\chenshajie1\Downloads\body.FBX"
OUT = r"H:\Blender_Plugin\tmp_forearm_roll\foot_sink_investigation"
MAIN = "a050_300000"
CLIPS = (MAIN, "a050_302011", "a050_300010")
TRACE_FRAMES = {5, 6, 7}


def chain_roll(arm, bone_name, child_name):
    from mathutils import Quaternion, Vector

    pose_bone = arm.pose.bones[bone_name]
    rest = pose_bone.bone.matrix_local.to_3x3()
    delta = pose_bone.matrix.to_3x3() @ rest.inverted()
    quat = delta.to_quaternion()
    if quat.w < 0.0:
        quat.negate()
    axis = arm.pose.bones[child_name].head - pose_bone.head
    if axis.length < 1e-9:
        return 0.0
    axis.normalize()
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


def angle_deg(a, b, c):
    first = a - b
    second = c - b
    if first.length < 1e-9 or second.length < 1e-9:
        return 180.0
    return math.degrees(first.angle(second))


def vec3(value):
    return [round(float(item), 6) for item in value]


def main():
    sys.path.insert(0, COPY)
    for name in list(sys.modules):
        if name == "humanoid_retarget" or name.startswith("humanoid_retarget."):
            del sys.modules[name]
    bpy.ops.wm.read_factory_settings(use_empty=True)
    from mathutils import Vector
    from humanoid_retarget.mapping import build_pairs
    from humanoid_retarget import pipeline
    import humanoid_retarget.retarget as retarget
    import humanoid_retarget.ik as ik_module
    from humanoid_retarget.foot_ik import FootIKSettings

    real_solve = ik_module._solve_chain
    solve_err = {}
    solve_trace = []
    seq = {"n": 0}
    state = {"config": "", "action": ""}

    def recording_solve(tgt, space, reference, goal, pole_hint=None):
        frame = bpy.context.scene.frame_current
        role = reference.roles[2]
        world = tgt.matrix_world
        names = reference.target_names

        def snapshot():
            thigh = world @ tgt.pose.bones[names[0]].head
            knee = world @ tgt.pose.bones[names[1]].head
            ankle = world @ tgt.pose.bones[names[2]].head
            hips_name = roles["hips"][1]
            hips = world @ tgt.pose.bones[hips_name].head
            return thigh, knee, ankle, hips

        before = snapshot() if frame in TRACE_FRAMES else None
        distance = real_solve(tgt, space, reference, goal, pole_hint=pole_hint)
        solve_err[(frame, role)] = float(distance)
        if before is not None:
            after = snapshot()
            phase = "bake" if ik_module._CORRECTION_PLAN is not None else "plan"
            seq["n"] += 1
            pole = None if pole_hint is None else vec3(pole_hint)
            solve_trace.append({
                "config": state["config"],
                "action": state["action"],
                "phase": phase,
                "seq": seq["n"],
                "frame": frame,
                "role": role,
                "goal": json.dumps(vec3(goal.position)),
                "pole": json.dumps(pole),
                "err_mm": round(float(distance) * 1000.0, 4),
                "knee_before": json.dumps(vec3(before[1])),
                "knee_after": json.dumps(vec3(after[1])),
                "ankle_before": json.dumps(vec3(before[2])),
                "ankle_after": json.dumps(vec3(after[2])),
                "hips_before": json.dumps(vec3(before[3])),
                "hips_after": json.dumps(vec3(after[3])),
                "knee_move_mm": round((after[1] - before[1]).length * 1000.0, 3),
                "ankle_move_mm": round((after[2] - before[2]).length * 1000.0, 3),
                "hips_move_mm": round((after[3] - before[3]).length * 1000.0, 3),
            })
        return distance

    ik_module._solve_chain = recording_solve
    source, _ = pipeline.load_source(SOURCE)
    objects, _ = pipeline.import_model(TARGET)
    target = pipeline.pick_armature(objects)
    mesh = next(obj for obj in bpy.data.objects if obj.type == "MESH" and obj.parent == target)
    pairs = build_pairs(source, target)
    roles = {role: (src_name, tgt_name) for role, src_name, tgt_name in pairs}
    for bone_name in (
        roles["thigh_l"][1], roles["shin_l"][1], roles["foot_l"][1],
        roles["upperarm_l"][1], roles["forearm_l"][1], roles["hand_l"][1],
    ):
        bone = target.data.bones[bone_name]
        pose = target.pose.bones[bone_name]
        parent = bone.parent.name if bone.parent else ""
        constraints = [(item.type, item.name, item.mute) for item in pose.constraints]
        y_axis = bone.matrix_local.to_3x3() @ __import__("mathutils").Vector((0.0, 1.0, 0.0))
        print("BONE", bone_name, "parent", parent, "connect", bone.use_connect,
              "constraints", constraints, "rest_y", vec3(y_axis), flush=True)
    actions = {item.name: item for item in retarget.collect_actions(source) if item.name in CLIPS}
    holder = {"action": None}
    retarget.collect_actions = lambda _src: [holder["action"]]
    settings = FootIKSettings(floor_enabled=True, floor_alpha=1.0, floor_height_m=0.0)
    rows = []
    endpoint_rows = []
    plans = {}
    bpy.context.view_layer.update()
    for side in ("l", "r"):
        shin = target.pose.bones[roles["shin_" + side][1]]
        foot = target.pose.bones[roles["foot_" + side][1]]
        chain = foot.head - shin.head
        bone_y = shin.matrix.to_3x3() @ Vector((0.0, 1.0, 0.0))
        tail = shin.tail - shin.head
        angle = math.degrees(bone_y.angle(chain)) if chain.length > 1e-9 and bone_y.length > 1e-9 else -1.0
        tail_angle = math.degrees(tail.angle(chain)) if chain.length > 1e-9 and tail.length > 1e-9 else -1.0
        print("REST", side, "boneY_vs_chain", round(angle, 3), "tail_vs_chain", round(tail_angle, 3),
              "chain", round(chain.length, 6), "connect_shin", shin.bone.use_connect,
              "connect_foot", foot.bone.use_connect, flush=True)

    def mesh_stats():
        deps = bpy.context.evaluated_depsgraph_get()
        evaluated = mesh.evaluated_get(deps)
        posed = evaluated.to_mesh()
        world = evaluated.matrix_world
        lowest = None
        n0 = 0
        n01 = 0
        for vertex in posed.vertices:
            z = (world @ vertex.co).z
            if lowest is None or z < lowest:
                lowest = z
            if z < 0.0:
                n0 += 1
            if z < -0.01:
                n01 += 1
        evaluated.to_mesh_clear()
        return float(lowest if lowest is not None else 0.0), n0, n01

    def world_head(name):
        return target.matrix_world @ target.pose.bones[name].head

    def scan(config, action_name, start, end, plan):
        for pose_bone in target.pose.bones:
            pose_bone.scale = (1.0, 1.0, 1.0)
        bpy.context.view_layer.update()
        feedback = {(entry[0], entry[1]): entry for entry in ik_module.CONTACT_LOG}
        for frame in range(start, end + 1):
            bpy.context.scene.frame_set(frame)
            bpy.context.view_layer.update()
            lowest, n0, n01 = mesh_stats()
            hips = world_head(roles["hips"][1])
            row = {
                "config": config,
                "action": action_name,
                "frame": frame,
                "hips_z": round(hips.z, 6),
                "hips": json.dumps(vec3(hips)),
                "mesh_lowest": round(lowest, 6),
                "n_z_lt_0": n0,
                "n_z_lt_001": n01,
                "forearm_l_roll": round(chain_roll(target, roles["forearm_l"][1], roles["hand_l"][1]), 4),
            }
            for side in ("l", "r"):
                thigh = world_head(roles["thigh_" + side][1])
                knee = world_head(roles["shin_" + side][1])
                ankle = world_head(roles["foot_" + side][1])
                row[side + "_roll"] = round(chain_roll(target, roles["shin_" + side][1], roles["foot_" + side][1]), 4)
                row[side + "_knee_deg"] = round(angle_deg(thigh, knee, ankle), 4)
                row[side + "_knee"] = json.dumps(vec3(knee))
                row[side + "_ankle"] = json.dumps(vec3(ankle))
                row[side + "_lower_len"] = round((ankle - knee).length, 6)
                row[side + "_err_mm"] = round(solve_err.get((frame, "foot_" + side), 0.0) * 1000.0, 4)
                entry = feedback.get((frame, "foot_" + side))
                row[side + "_feedback"] = None if entry is None else entry[2]
                row[side + "_raised_mm"] = None if entry is None else round(float(entry[6]) * 1000.0, 3)
                planned = None if plan is None else plan.get((frame, "foot_" + side))
                row[side + "_plan"] = json.dumps(vec3(planned if planned is not None else Vector()))
            rows.append(row)

    def reset_pose():
        if target.animation_data:
            target.animation_data_clear()
        for pose_bone in target.pose.bones:
            pose_bone.rotation_mode = "QUATERNION"
            pose_bone.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
            pose_bone.location = (0.0, 0.0, 0.0)
            pose_bone.scale = (1.0, 1.0, 1.0)
        bpy.context.view_layer.update()

    def bake(config, action, foot_ik, hand_ik, roll, apply_mode):
        reset_pose()
        holder["action"] = action
        retarget._assign_action(source, action)
        ik_module.clear_correction_plan_cache()
        ik_module._CORRECTION_PLAN = None
        ik_module._LAST_PLAN = None
        ik_module._CONTACT_MIN_KNEE_DEG = None
        ik_module.CALF_ROLL_LOG.clear()
        ik_module.ENDPOINT_LOG.clear()
        ik_module.CONTACT_LOG.clear()
        solve_err.clear()
        state["config"] = config
        state["action"] = action.name
        seq["n"] = 0
        ik_module._CALF_ROLL_FIX_ENABLED = roll
        ik_module._CALF_ROLL_APPLY = apply_mode
        options = retarget.RetargetOptions(
            pairs=pairs, root_motion="KEEP", reference="REST",
            foot_ik=foot_ik, hand_ik=hand_ik,
            foot_ik_settings=settings,
            contact_min_knee_deg=15.0 if foot_ik else 0.0,
            correction_smoothing="height" if foot_ik else "",
        )
        report, _ = retarget.bake_retarget(source, target, options)
        ik_module._CALF_ROLL_FIX_ENABLED = False
        ik_module._CALF_ROLL_APPLY = "inline"
        plan = None
        if ik_module._LAST_PLAN is not None:
            plan = {key: value.copy() for key, value in ik_module._LAST_PLAN.items()}
            plans[(config, action.name)] = plan
        for item in ik_module.ENDPOINT_LOG:
            endpoint_rows.append({
                "config": config,
                "action": action.name,
                "frame": item[0],
                "role": item[1],
                "stage": item[2],
                "knee_mm": item[3],
                "ankle_mm": item[4],
                "length_mm": item[5],
                "pre_length_mm": item[6],
                "chain_deg": item[7],
                "roll_deg": item[8],
                "bone_y_deg": item[9],
            })
        locked = [item for item in ik_module.ENDPOINT_LOG if item[2] == "locked"]
        drifted = [item for item in ik_module.ENDPOINT_LOG if item[2] == "drift"]

        def worst(items, index):
            return max(items, key=lambda item: abs(item[index])) if items else None

        print("BAKE", config, action.name, "apply", apply_mode,
              "roll_n", len(ik_module.CALF_ROLL_LOG),
              "drift_knee", worst(drifted, 3), "drift_ankle", worst(drifted, 4),
              "lock_knee", worst(locked, 3), "lock_ankle", worst(locked, 4),
              "lock_chain", worst(locked, 7),
              report.replace("\n", " | ")[:100], flush=True)
        start, end = int(action.frame_range[0]), int(round(action.frame_range[1]))
        scan(config, action.name, start, end, plan)

    for name in CLIPS:
        action = actions[name]
        bake("A_base", action, True, False, False, "inline")
        bake("B_final", action, True, False, True, "final")
        bake("C_lock", action, True, False, True, "bake_lock")
    main = actions[MAIN]
    bake("H_hand", main, False, True, False, "inline")
    bake("H_both_off", main, True, True, False, "inline")
    bake("H_both_final", main, True, True, True, "final")
    bake("H_both_lock", main, True, True, True, "bake_lock")

    with open(OUT + r"\calf_roll_endpoint_frames.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    with open(OUT + r"\calf_roll_endpoint_lock.csv", "w", newline="", encoding="utf-8") as handle:
        if endpoint_rows:
            writer = csv.DictWriter(handle, fieldnames=list(endpoint_rows[0].keys()))
            writer.writeheader()
            writer.writerows(endpoint_rows)
    with open(OUT + r"\calf_roll_hand_trace.csv", "w", newline="", encoding="utf-8") as handle:
        if solve_trace:
            writer = csv.DictWriter(handle, fieldnames=list(solve_trace[0].keys()))
            writer.writeheader()
            writer.writerows(solve_trace)

    indexed = {(row["config"], row["action"], int(row["frame"])): row for row in rows}

    def dist(left, right):
        return math.sqrt(sum((x - y) ** 2 for x, y in zip(json.loads(left), json.loads(right))))

    def summarize(config, action):
        subset = [row for row in rows if row["config"] == config and row["action"] == action]
        roll = max(max(abs(float(row["l_roll"])), abs(float(row["r_roll"]))) for row in subset)
        z0 = sum(1 for row in subset if int(row["n_z_lt_0"]) > 0)
        z01 = sum(1 for row in subset if int(row["n_z_lt_001"]) > 0)
        worst = min(subset, key=lambda row: float(row["mesh_lowest"]))
        print("SUM", config, action, "roll", round(roll, 4), "Z<0", z0, "Z<-0.01", z01,
              "min_z", worst["mesh_lowest"], "at", worst["frame"], flush=True)

    def pair(left, right, action, frames=None):
        chosen = frames or sorted(frame for cfg, name, frame in indexed if cfg == left and name == action)
        knee = ankle = length = hips = 0.0
        knee_at = ankle_at = mesh_at = None
        mesh = 0.0
        for frame in chosen:
            if (right, action, frame) not in indexed:
                continue
            a = indexed[(left, action, frame)]
            b = indexed[(right, action, frame)]
            for side in ("l", "r"):
                knee_d = dist(a[side + "_knee"], b[side + "_knee"])
                ankle_d = dist(a[side + "_ankle"], b[side + "_ankle"])
                if knee_d > knee:
                    knee = knee_d
                    knee_at = (frame, side, round(knee_d * 1000.0, 3))
                if ankle_d > ankle:
                    ankle = ankle_d
                    ankle_at = (frame, side, round(ankle_d * 1000.0, 3))
                length = max(length, abs(float(a[side + "_lower_len"]) - float(b[side + "_lower_len"])))
            hips = max(hips, abs(float(a["hips_z"]) - float(b["hips_z"])))
            mesh_d = (float(b["mesh_lowest"]) - float(a["mesh_lowest"])) * 1000.0
            if abs(mesh_d) > abs(mesh):
                mesh = mesh_d
                mesh_at = (frame, round(mesh_d, 3), a["mesh_lowest"], b["mesh_lowest"])
        print("PAIR", left, right, action, "knee_mm", knee_at, "ankle_mm", ankle_at,
              "len_m", round(length, 6), "hips_m", round(hips, 6), "mesh_dz_mm", mesh_at, flush=True)

    for name in CLIPS:
        for config in ("A_base", "B_final", "C_lock"):
            summarize(config, name)
        pair("A_base", "B_final", name)
        pair("A_base", "C_lock", name)
    print("--- 300010 frames 1-12 mesh dz C-A mm ---", flush=True)
    for frame in range(1, 13):
        a = indexed[("A_base", "a050_300010", frame)]
        c = indexed[("C_lock", "a050_300010", frame)]
        print(frame, "dz", round((float(c["mesh_lowest"]) - float(a["mesh_lowest"])) * 1000.0, 3),
              "A", a["mesh_lowest"], "C", c["mesh_lowest"],
              "kneeL", round(dist(a["l_knee"], c["l_knee"]) * 1000.0, 3),
              "ankleL", round(dist(a["l_ankle"], c["l_ankle"]) * 1000.0, 3),
              "lenL", a["l_lower_len"], c["l_lower_len"], flush=True)
    print("--- frame 6 left knee ---", flush=True)
    for config in ("A_base", "H_hand", "H_both_off", "H_both_final", "H_both_lock"):
        row = indexed[(config, MAIN, 6)]
        prev = indexed[(config, MAIN, 5)]
        nxt = indexed[(config, MAIN, 7)]
        print(config, "knee", row["l_knee"], "ankle", row["l_ankle"], "hips", row["hips"],
              "kdeg", row["l_knee_deg"], "mesh", row["mesh_lowest"], "roll", row["l_roll"],
              "step56", round(dist(prev["l_knee"], row["l_knee"]) * 1000.0, 1),
              "step67", round(dist(row["l_knee"], nxt["l_knee"]) * 1000.0, 1),
              "fb", row["l_feedback"], "plan", row["l_plan"], flush=True)
    print("TRACE", len(solve_trace), "DONE", flush=True)


if __name__ == "__main__":
    main()
