"""Extended regression for the calf-roll scheme A. Experiment copy only. No save.

Profiles every source clip, then bakes the main clip, hand-IK combinations,
and up to three other clips chosen for deep knee / extension / turn / foot roll.
Clears the height-plan cache before every bake so the roll switch cannot reuse
another config's plan.
"""
import csv
import json
import math
import sys

import bpy

COPY = r"H:\Blender_Plugin\tmp_forearm_roll"
SOURCE = r"h:\SErsiko_ExtactedTool\output\c0000_突刺_wp_a_0300.glb"
TARGET = r"c:\Users\chenshajie1\Downloads\body.FBX"
OUT_DIR = r"H:\Blender_Plugin\tmp_forearm_roll\foot_sink_investigation"
MAIN = "a050_300000"


def chain_roll(arm, bone_name, child_name):
    from mathutils import Quaternion, Vector

    pose_bone = arm.pose.bones[bone_name]
    rest = pose_bone.bone.matrix_local.to_3x3()
    delta = pose_bone.matrix.to_3x3() @ rest.inverted()
    quat = delta.to_quaternion()
    if quat.w < 0.0:
        quat.negate()
    axis = (arm.pose.bones[child_name].head - pose_bone.head)
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


def quat_angle_deg(a, b):
    dot = abs(sum(float(x) * float(y) for x, y in zip(a, b)))
    dot = max(-1.0, min(1.0, dot))
    return math.degrees(2.0 * math.acos(dot))


def vec3(v):
    return [round(float(x), 6) for x in v]


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
    trace_rows = []
    trace_on = {"enabled": False, "config": ""}
    seq = {"n": 0}

    def traced_solve(tgt, space, reference, goal, pole_hint=None):
        distance = real_solve(tgt, space, reference, goal, pole_hint=pole_hint)
        frame = bpy.context.scene.frame_current
        role = reference.roles[2]
        solve_err[(frame, role)] = float(distance)
        if trace_on["enabled"] and frame == 15 and role in ("foot_l", "foot_r"):
            world = tgt.matrix_world
            names = reference.target_names
            thigh = world @ tgt.pose.bones[names[0]].head
            knee = world @ tgt.pose.bones[names[1]].head
            ankle = world @ tgt.pose.bones[names[2]].head
            lowest, n0, n01 = mesh_stats()
            phase = "bake" if ik_module._CORRECTION_PLAN is not None else "plan"
            seq["n"] += 1
            trace_rows.append({
                "config": trace_on["config"],
                "phase": phase,
                "seq": seq["n"],
                "role": role,
                "goal": json.dumps(vec3(goal.position)),
                "knee": json.dumps(vec3(knee)),
                "ankle": json.dumps(vec3(ankle)),
                "knee_deg": round(angle_deg(thigh, knee, ankle), 4),
                "mesh_lowest": round(lowest, 6),
                "n_z_lt_0": n0,
                "n_z_lt_001": n01,
                "err_mm": round(float(distance) * 1000.0, 4),
            })
        return distance

    ik_module._solve_chain = traced_solve

    source, _ = pipeline.load_source(SOURCE)
    objects, _ = pipeline.import_model(TARGET)
    target = pipeline.pick_armature(objects)
    mesh = next(obj for obj in bpy.data.objects if obj.type == "MESH" and obj.parent == target)
    pairs = build_pairs(source, target)
    roles = {role: (src_name, tgt_name) for role, src_name, tgt_name in pairs}
    upper_roles = [
        role for role in (
            "hips", "spine", "chest", "neck", "head",
            "upperarm_l", "forearm_l", "hand_l",
            "upperarm_r", "forearm_r", "hand_r",
        ) if role in roles
    ]
    print("SWITCH_DEFAULT", ik_module._CALF_ROLL_FIX_ENABLED, flush=True)
    print("PAIRS", len(pairs), "MESH_VERTS", len(mesh.data.vertices), flush=True)

    def mesh_stats():
        deps = bpy.context.evaluated_depsgraph_get()
        evaluated = mesh.evaluated_get(deps)
        posed = evaluated.to_mesh()
        world = evaluated.matrix_world
        n0 = 0
        n01 = 0
        lowest = None
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

    def world_head(arm, name):
        return arm.matrix_world @ arm.pose.bones[name].head

    actions = [item for item in retarget.collect_actions(source) if item.name.startswith("a050_")]
    print("SOURCE_ACTIONS", [(item.name, int(item.frame_range[0]), int(round(item.frame_range[1]))) for item in actions], flush=True)

    profiles = []
    for action in actions:
        retarget._assign_action(source, action)
        start, end = int(action.frame_range[0]), int(round(action.frame_range[1]))
        knees = []
        yaws = []
        prev_yaw = None
        yaw_acc = 0.0
        foot_span = 0.0
        foot_ref = {}
        for frame in range(start, end + 1):
            bpy.context.scene.frame_set(frame)
            pair = []
            for side in ("l", "r"):
                thigh = world_head(source, roles["thigh_" + side][0])
                knee = world_head(source, roles["shin_" + side][0])
                ankle = world_head(source, roles["foot_" + side][0])
                pair.append(angle_deg(thigh, knee, ankle))
                foot = source.pose.bones[roles["foot_" + side][0]]
                quat = (source.matrix_world @ foot.matrix).to_quaternion()
                if side not in foot_ref:
                    foot_ref[side] = quat.copy()
                else:
                    foot_span = max(foot_span, math.degrees(foot_ref[side].rotation_difference(quat).angle))
            knees.append(min(pair))
            hips = source.pose.bones[roles["hips"][0]]
            yaw = math.degrees((source.matrix_world @ hips.matrix).to_euler("XYZ").z)
            if prev_yaw is None:
                yaw_acc = yaw
            else:
                yaw_acc += (yaw - prev_yaw + 180.0) % 360.0 - 180.0
            prev_yaw = yaw
            yaws.append(yaw_acc)
        profiles.append({
            "action": action.name,
            "frames": end - start + 1,
            "min_knee": round(min(knees), 2),
            "max_knee": round(max(knees), 2),
            "yaw_span": round(max(yaws) - min(yaws), 2),
            "foot_span": round(foot_span, 2),
        })
    for item in profiles:
        print("PROFILE", json.dumps(item), flush=True)

    others = [item for item in profiles if item["action"] != MAIN]
    picked = []
    for label, key, reverse in (
        ("deep_knee", "min_knee", False),
        ("extension", "max_knee", True),
        ("turn", "yaw_span", True),
        ("foot_roll", "foot_span", True),
    ):
        ranking = sorted(others, key=lambda item: item[key], reverse=reverse)
        chosen = next(item["action"] for item in ranking if item["action"] not in picked)
        picked.append(chosen)
        print("PICK", label, chosen, json.dumps(next(item for item in ranking if item["action"] == chosen)), flush=True)
    extra = []
    for name in picked:
        if name not in extra:
            extra.append(name)
        if len(extra) == 4:
            break
    print("EXTRA_CLIPS", extra, flush=True)

    holder = {"action": None}
    retarget.collect_actions = lambda _src: [holder["action"]]
    settings = FootIKSettings(floor_enabled=True, floor_alpha=1.0, floor_height_m=0.0)
    rows = []

    def scan(config, action_name, start, end):
        for frame in range(start, end + 1):
            bpy.context.scene.frame_set(frame)
            bpy.context.view_layer.update()
            lowest, n0, n01 = mesh_stats()
            row = {
                "config": config,
                "action": action_name,
                "frame": frame,
                "mesh_lowest": round(lowest, 6),
                "n_z_lt_0": n0,
                "n_z_lt_001": n01,
            }
            for side in ("l", "r"):
                thigh_n = roles["thigh_" + side][1]
                shin_n = roles["shin_" + side][1]
                foot_n = roles["foot_" + side][1]
                thigh = world_head(target, thigh_n)
                knee = world_head(target, shin_n)
                ankle = world_head(target, foot_n)
                toe_name = next(c.name for c in target.pose.bones[foot_n].children if "toe" in c.name.lower())
                toe = world_head(target, toe_name)
                row[side + "_roll"] = round(chain_roll(target, shin_n, foot_n), 4)
                row[side + "_knee_deg"] = round(angle_deg(thigh, knee, ankle), 4)
                row[side + "_knee"] = json.dumps(vec3(knee))
                row[side + "_ankle"] = json.dumps(vec3(ankle))
                direction = toe - ankle
                row[side + "_toe_dir"] = json.dumps(vec3(direction.normalized() if direction.length > 1e-9 else direction))
                row[side + "_err_mm"] = round(solve_err.get((frame, "foot_" + side), 0.0) * 1000.0, 4)
            for role, child in (("forearm_l", "hand_l"), ("forearm_r", "hand_r")):
                row[role + "_roll"] = round(chain_roll(target, roles[role][1], roles[child][1]), 4)
            upper = {}
            for role in upper_roles:
                quat = target.pose.bones[roles[role][1]].matrix_basis.to_quaternion()
                upper[role] = [round(float(x), 5) for x in quat]
            row["upper"] = json.dumps(upper)
            rows.append(row)

    def bake(config, action, foot_ik, hand_ik, roll_fix, do_trace):
        holder["action"] = action
        retarget._assign_action(source, action)
        ik_module.clear_correction_plan_cache()
        ik_module._CORRECTION_PLAN = None
        ik_module._LAST_PLAN = None
        ik_module.CALF_ROLL_LOG.clear()
        ik_module.CONTACT_LOG.clear()
        ik_module.CONTACT_TRACE.clear()
        solve_err.clear()
        ik_module._CALF_ROLL_FIX_ENABLED = roll_fix
        trace_on["enabled"] = do_trace
        trace_on["config"] = config
        seq["n"] = 0
        options = retarget.RetargetOptions(
            pairs=pairs, root_motion="KEEP", reference="REST",
            foot_ik=foot_ik, hand_ik=hand_ik,
            foot_ik_settings=settings,
            contact_min_knee_deg=15.0, correction_smoothing="height",
        )
        report, _ = retarget.bake_retarget(source, target, options)
        ik_module._CALF_ROLL_FIX_ENABLED = False
        trace_on["enabled"] = False
        start, end = int(action.frame_range[0]), int(round(action.frame_range[1]))
        foot_log = [item for item in ik_module.CALF_ROLL_LOG if item[1] in ("foot_l", "foot_r")]
        other_log = [item for item in ik_module.CALF_ROLL_LOG if item[1] not in ("foot_l", "foot_r")]
        print("BAKE", config, action.name, "foot", foot_ik, "hand", hand_ik, "fix", roll_fix,
              "roll_entries", len(foot_log), "nonfoot_entries", len(other_log),
              "plan15L", None if not ik_module._LAST_PLAN else vec3(ik_module._LAST_PLAN.get((15, "foot_l"), Vector())),
              report.replace("\n", " | ")[:180], flush=True)
        scan(config, action.name, start, end)
        return ik_module._LAST_PLAN

    by_name = {item.name: item for item in actions}
    plans = {}
    plans["BASE"] = bake("BASE", by_name[MAIN], True, False, False, True)
    plans["A"] = bake("A", by_name[MAIN], True, False, True, True)
    bake("FK", by_name[MAIN], False, False, False, False)
    bake("FK_FIX", by_name[MAIN], False, False, True, False)
    bake("HAND_FK", by_name[MAIN], False, True, False, False)
    bake("HAND_FK_FIX", by_name[MAIN], False, True, True, False)
    bake("HAND_FOOT", by_name[MAIN], True, True, False, False)
    bake("HAND_FOOT_FIX", by_name[MAIN], True, True, True, False)
    for name in extra:
        bake("X_" + name, by_name[name], True, False, False, False)
        bake("XA_" + name, by_name[name], True, False, True, False)

    def dump(path, items):
        if not items:
            return
        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(items[0].keys()))
            writer.writeheader()
            writer.writerows(items)

    dump(OUT_DIR + r"\calf_roll_regress.csv", rows)
    dump(OUT_DIR + r"\calf_roll_frame15.csv", trace_rows)
    with open(OUT_DIR + r"\calf_roll_action_profile.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(profiles[0].keys()))
        writer.writeheader()
        writer.writerows(profiles)

    indexed = {(row["config"], row["action"], row["frame"]): row for row in rows}

    def rows_of(config, action=MAIN):
        return [row for row in rows if row["config"] == config and row["action"] == action]

    def summarize(config, action=MAIN):
        subset = rows_of(config, action)
        if not subset:
            print("EMPTY", config, action, flush=True)
            return
        for side in ("l", "r"):
            rolls = [abs(row[side + "_roll"]) for row in subset]
            print("ROLL", config, action, side, "max", round(max(rolls), 4), flush=True)
        z0 = sum(1 for row in subset if row["n_z_lt_0"] > 0)
        z01 = sum(1 for row in subset if row["n_z_lt_001"] > 0)
        worst = min(subset, key=lambda row: row["mesh_lowest"])
        err = max(max(row["l_err_mm"], row["r_err_mm"]) for row in subset)
        print("MESH", config, action, "frames", len(subset), "Z<0_frames", z0, "Z<-0.01_frames", z01,
              "min_z", worst["mesh_lowest"], "worst_frame", worst["frame"],
              "worst_n0", worst["n_z_lt_0"], "max_err_mm", round(err, 4), flush=True)

    for config in ("FK", "FK_FIX", "BASE", "A", "HAND_FK", "HAND_FK_FIX", "HAND_FOOT", "HAND_FOOT_FIX"):
        summarize(config)
    for name in extra:
        summarize("X_" + name, name)
        summarize("XA_" + name, name)

    def max_pair_delta(left, right, action=MAIN):
        pos = 0.0
        toe = 0.0
        knee = 0.0
        upper = 0.0
        forearm = 0.0
        where = {}
        frames = sorted(row["frame"] for row in rows_of(left, action))
        for frame in frames:
            a = indexed[(left, action, frame)]
            b = indexed[(right, action, frame)]
            for side in ("l", "r"):
                for key in ("knee", "ankle"):
                    pa = json.loads(a[side + "_" + key])
                    pb = json.loads(b[side + "_" + key])
                    dist = math.sqrt(sum((x - y) ** 2 for x, y in zip(pa, pb)))
                    if dist > pos:
                        pos = dist
                        where["pos"] = (frame, side, key, round(dist, 6))
                da = json.loads(a[side + "_toe_dir"])
                db = json.loads(b[side + "_toe_dir"])
                dot = max(-1.0, min(1.0, sum(x * y for x, y in zip(da, db))))
                dang = math.degrees(math.acos(dot))
                if dang > toe:
                    toe = dang
                    where["toe"] = (frame, side, round(dang, 4))
                dk = abs(a[side + "_knee_deg"] - b[side + "_knee_deg"])
                if dk > knee:
                    knee = dk
                    where["knee"] = (frame, side, round(dk, 4))
            for role in ("forearm_l", "forearm_r"):
                droll = abs(a[role + "_roll"] - b[role + "_roll"])
                if droll > forearm:
                    forearm = droll
                    where["forearm"] = (frame, role, round(droll, 4))
            ua = json.loads(a["upper"])
            ub = json.loads(b["upper"])
            for role in upper_roles:
                dang = quat_angle_deg(ua[role], ub[role])
                if dang > upper:
                    upper = dang
                    where["upper"] = (frame, role, round(dang, 4))
        print("DELTA", left, right, action,
              "pos_m", where.get("pos"), "toe_deg", where.get("toe"),
              "knee_deg", where.get("knee"), "forearm_roll", where.get("forearm"),
              "upper_deg", where.get("upper"), flush=True)

    max_pair_delta("FK", "FK_FIX")
    max_pair_delta("BASE", "A")
    max_pair_delta("HAND_FK", "HAND_FK_FIX")
    max_pair_delta("HAND_FOOT", "HAND_FOOT_FIX")
    for name in extra:
        max_pair_delta("X_" + name, "XA_" + name, name)

    if plans.get("BASE") and plans.get("A"):
        delta = 0.0
        at = None
        for key, value in plans["BASE"].items():
            other = plans["A"].get(key)
            if other is None:
                continue
            dist = (value - other).length
            if dist > delta:
                delta = dist
                at = (key, vec3(value), vec3(other))
        print("PLAN_MAX_DELTA_M", round(delta, 6), "AT", at, flush=True)

    print("TRACE_ROWS", len(trace_rows), flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
