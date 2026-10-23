"""Isolate calf-roll coupling from the height plan and contact feedback.

Experiment copy only. No save. Each bake clears the plan cache.
A = roll off, own height plan, contact feedback.
B = roll on, own height plan, contact feedback.
C0 / C = feedback skipped, roll off / on.
D = roll on, but the height plan is the one just built by A for that clip.
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
FOCUS = {
    MAIN: {15, 16, 23},
    "a050_302011": {9, 10},
    "a050_300010": {6, 11, 14},
}


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
    import inspect

    signature = inspect.getsource(retarget._correction_plan_signature)
    print("SIGNATURE_HAS", json.dumps({
        "calf_roll_flag": "_CALF_ROLL" in signature,
        "contact_stack": "_CONTACT_STACK" in signature,
        "knee_option": "contact_min_knee_deg" in signature,
        "smoothing": "correction_smoothing" in signature,
        "foot_ik": "foot_ik" in signature,
        "hand_ik": "hand_ik" in signature,
        "floor_settings": "ik_settings" in signature,
    }), flush=True)
    print("COPY_DEFAULTS", "knee", retarget.RetargetOptions().contact_min_knee_deg,
          "smoothing", repr(retarget.RetargetOptions().correction_smoothing),
          "roll_flag", ik_module._CALF_ROLL_FIX_ENABLED,
          "plan_version", ik_module.CORRECTION_PLAN_VERSION, flush=True)

    real_solve = ik_module._solve_chain
    real_build = ik_module.build_height_plan
    real_apply = retarget.apply_contact_ik
    solve_err = {}
    traces = []
    seq = {"n": 0}
    state = {"config": "", "action": "", "trace": False, "skip_feedback": False}
    hold_plan = {"plan": None}
    saved_plans = {}

    def traced_solve(tgt, space, reference, goal, pole_hint=None):
        frame = bpy.context.scene.frame_current
        role = reference.roles[2]
        before = None
        if state["trace"] and frame in FOCUS.get(state["action"], ()):
            before = chain_roll(tgt, roles["forearm_l"][1], roles["hand_l"][1])
        distance = real_solve(tgt, space, reference, goal, pole_hint=pole_hint)
        solve_err[(frame, role)] = float(distance)
        if state["trace"] and frame in FOCUS.get(state["action"], ()):
            world = tgt.matrix_world
            names = reference.target_names
            thigh = world @ tgt.pose.bones[names[0]].head
            knee = world @ tgt.pose.bones[names[1]].head
            ankle = world @ tgt.pose.bones[names[2]].head
            hips = world @ tgt.pose.bones[roles["hips"][1]].head
            skin_z = None
            if reference.skin_points:
                skin_z, _dominant = ik_module._skin_lowest_world(tgt, reference.skin_points)
            mesh_z, n0, _n01 = mesh_stats()
            seq["n"] += 1
            traces.append({
                "config": state["config"],
                "action": state["action"],
                "phase": "bake" if ik_module._CORRECTION_PLAN is not None else "plan",
                "seq": seq["n"],
                "frame": frame,
                "role": role,
                "goal": json.dumps(vec3(goal.position)),
                "knee": json.dumps(vec3(knee)),
                "ankle": json.dumps(vec3(ankle)),
                "knee_deg": round(angle_deg(thigh, knee, ankle), 4),
                "hips_z": round(hips.z, 6),
                "skin_z": None if skin_z is None else round(float(skin_z), 6),
                "mesh_z": round(mesh_z, 6),
                "n_z_lt_0": n0,
                "err_mm": round(float(distance) * 1000.0, 4),
                "forearm_l_before": None if before is None else round(before, 4),
                "forearm_l_after": round(chain_roll(tgt, roles["forearm_l"][1], roles["hand_l"][1]), 4),
                "calf_l": round(chain_roll(tgt, roles["shin_l"][1], roles["foot_l"][1]), 4),
            })
        return distance

    def build_plan(raw_series, lowest_series):
        built = real_build(raw_series, lowest_series)
        forced = hold_plan["plan"]
        if forced is None:
            return built
        delta = 0.0
        at = None
        for key, value in built.items():
            other = forced.get(key)
            if other is None:
                continue
            dist = (value - other).length
            if dist > delta:
                delta = dist
                at = key
        print("PLAN_BUILT_VS_FORCED", state["config"], state["action"],
              "max_m", round(delta, 6), "at", at, flush=True)
        return {key: value.copy() for key, value in forced.items()}

    def apply_ik(*args, **kwargs):
        geometry = args[2]
        saved = None
        if state["skip_feedback"]:
            saved = [(limb, limb.skin_points, limb.contact_local) for limb in geometry.limbs]
            for limb, _points, _local in saved:
                limb.skin_points = ()
                limb.contact_local = ()
        try:
            return real_apply(*args, **kwargs)
        finally:
            if saved is not None:
                for limb, points, local in saved:
                    limb.skin_points = points
                    limb.contact_local = local

    ik_module._solve_chain = traced_solve
    ik_module.build_height_plan = build_plan
    retarget.apply_contact_ik = apply_ik

    source, _ = pipeline.load_source(SOURCE)
    objects, _ = pipeline.import_model(TARGET)
    target = pipeline.pick_armature(objects)
    mesh = next(obj for obj in bpy.data.objects if obj.type == "MESH" and obj.parent == target)
    pairs = build_pairs(source, target)
    roles = {role: (src_name, tgt_name) for role, src_name, tgt_name in pairs}
    actions = {item.name: item for item in retarget.collect_actions(source) if item.name in CLIPS}
    holder = {"action": None}
    retarget.collect_actions = lambda _src: [holder["action"]]
    settings = FootIKSettings(floor_enabled=True, floor_alpha=1.0, floor_height_m=0.0)
    rows = []

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

    def scan(config, action_name, start, end):
        feedback = {}
        for entry in ik_module.CONTACT_LOG:
            feedback[(entry[0], entry[1])] = entry
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
                "mesh_lowest": round(lowest, 6),
                "n_z_lt_0": n0,
                "n_z_lt_001": n01,
                "forearm_l_roll": round(chain_roll(target, roles["forearm_l"][1], roles["hand_l"][1]), 4),
                "forearm_r_roll": round(chain_roll(target, roles["forearm_r"][1], roles["hand_r"][1]), 4),
            }
            for side in ("l", "r"):
                thigh = world_head(roles["thigh_" + side][1])
                knee = world_head(roles["shin_" + side][1])
                ankle = world_head(roles["foot_" + side][1])
                row[side + "_roll"] = round(chain_roll(target, roles["shin_" + side][1], roles["foot_" + side][1]), 4)
                row[side + "_knee_deg"] = round(angle_deg(thigh, knee, ankle), 4)
                row[side + "_knee"] = json.dumps(vec3(knee))
                row[side + "_ankle"] = json.dumps(vec3(ankle))
                row[side + "_err_mm"] = round(solve_err.get((frame, "foot_" + side), 0.0) * 1000.0, 4)
                entry = feedback.get((frame, "foot_" + side))
                row[side + "_feedback"] = None if entry is None else entry[2]
                row[side + "_raised_mm"] = None if entry is None else round(float(entry[6]) * 1000.0, 3)
                row[side + "_skin_z"] = None if entry is None else entry[3]
            rows.append(row)

    def bake(config, action, foot_ik, hand_ik, roll, feedback, knee, smoothing, use_saved_plan):
        holder["action"] = action
        retarget._assign_action(source, action)
        ik_module.clear_correction_plan_cache()
        ik_module._CORRECTION_PLAN = None
        ik_module._LAST_PLAN = None
        ik_module._CONTACT_MIN_KNEE_DEG = None
        ik_module.CALF_ROLL_LOG.clear()
        ik_module.CONTACT_LOG.clear()
        ik_module.CONTACT_TRACE.clear()
        solve_err.clear()
        ik_module._CALF_ROLL_FIX_ENABLED = roll
        state["config"] = config
        state["action"] = action.name
        state["trace"] = True
        state["skip_feedback"] = not feedback
        hold_plan["plan"] = saved_plans.get(action.name) if use_saved_plan else None
        seq["n"] = 0
        options = retarget.RetargetOptions(
            pairs=pairs, root_motion="KEEP", reference="REST",
            foot_ik=foot_ik, hand_ik=hand_ik,
            foot_ik_settings=settings,
            contact_min_knee_deg=knee, correction_smoothing=smoothing,
        )
        report, _ = retarget.bake_retarget(source, target, options)
        ik_module._CALF_ROLL_FIX_ENABLED = False
        state["skip_feedback"] = False
        hold_plan["plan"] = None
        start, end = int(action.frame_range[0]), int(round(action.frame_range[1]))
        roles_logged = sorted({item[1] for item in ik_module.CALF_ROLL_LOG})
        print("BAKE", config, action.name, "roll_roles", roles_logged,
              "contact", len(ik_module.CONTACT_LOG),
              report.replace("\n", " | ")[:140], flush=True)
        if config.endswith("base") or config == "A_base":
            if ik_module._LAST_PLAN is not None:
                saved_plans[action.name] = {key: value.copy() for key, value in ik_module._LAST_PLAN.items()}
                print("SAVED_PLAN", action.name, "entries", len(saved_plans[action.name]), flush=True)
        scan(config, action.name, start, end)

    for name in CLIPS:
        action = actions[name]
        bake("A_base", action, True, False, False, True, 15.0, "height", False)
        bake("B_roll", action, True, False, True, True, 15.0, "height", False)
        bake("C0_nofb", action, True, False, False, False, 0.0, "", False)
        bake("C_roll_nofb", action, True, False, True, False, 0.0, "", False)
        bake("D_sameplan", action, True, False, True, True, 15.0, "height", True)

    main = actions[MAIN]
    bake("H_hand", main, False, True, False, False, 0.0, "", False)
    bake("H_hand_roll", main, False, True, True, False, 0.0, "", False)
    bake("H_both", main, True, True, False, True, 15.0, "height", False)
    bake("H_both_roll", main, True, True, True, True, 15.0, "height", False)

    def dump(path, items):
        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(items[0].keys()))
            writer.writeheader()
            writer.writerows(items)

    dump(OUT + r"\calf_roll_coupling_frames.csv", rows)
    dump(OUT + r"\calf_roll_coupling_trace.csv", traces)
    indexed = {(row["config"], row["action"], int(row["frame"])): row for row in rows}

    def dist(a, b):
        return math.sqrt(sum((x - y) ** 2 for x, y in zip(json.loads(a), json.loads(b))))

    def summarize(config, action):
        subset = [row for row in rows if row["config"] == config and row["action"] == action]
        rolls = [max(abs(float(row["l_roll"])), abs(float(row["r_roll"]))) for row in subset]
        z0 = sum(1 for row in subset if int(row["n_z_lt_0"]) > 0)
        z01 = sum(1 for row in subset if int(row["n_z_lt_001"]) > 0)
        worst = min(subset, key=lambda row: float(row["mesh_lowest"]))
        err = max(max(float(row["l_err_mm"]), float(row["r_err_mm"])) for row in subset)
        print("SUM", config, action, "roll", round(max(rolls), 4),
              "Z<0", z0, "Z<-0.01", z01, "min_z", worst["mesh_lowest"],
              "err_mm", round(err, 4), flush=True)

    def pair(left, right, action, frames):
        for frame in frames:
            a = indexed[(left, action, frame)]
            b = indexed[(right, action, frame)]
            print("PAIR", left, right, action, frame,
                  "roll", a["l_roll"], b["l_roll"], a["r_roll"], b["r_roll"],
                  "kneeL_mm", round(dist(a["l_knee"], b["l_knee"]) * 1000, 2),
                  "ankleL_mm", round(dist(a["l_ankle"], b["l_ankle"]) * 1000, 2),
                  "kneeR_mm", round(dist(a["r_knee"], b["r_knee"]) * 1000, 2),
                  "ankleR_mm", round(dist(a["r_ankle"], b["r_ankle"]) * 1000, 2),
                  "kdegL", a["l_knee_deg"], b["l_knee_deg"],
                  "hips", a["hips_z"], b["hips_z"],
                  "mesh", a["mesh_lowest"], b["mesh_lowest"],
                  "fb", a["l_feedback"], b["l_feedback"], a["r_feedback"], b["r_feedback"],
                  "raised", a["l_raised_mm"], b["l_raised_mm"],
                  "foreL", a["forearm_l_roll"], b["forearm_l_roll"], flush=True)

    for name in CLIPS:
        for config in ("A_base", "B_roll", "C0_nofb", "C_roll_nofb", "D_sameplan"):
            summarize(config, name)
    pair("A_base", "B_roll", MAIN, (15, 16))
    pair("C0_nofb", "C_roll_nofb", MAIN, (15, 16))
    pair("A_base", "D_sameplan", MAIN, (15, 16))
    pair("A_base", "B_roll", "a050_302011", (9, 10))
    pair("C0_nofb", "C_roll_nofb", "a050_302011", (9, 10))
    pair("A_base", "D_sameplan", "a050_302011", (9, 10))
    pair("A_base", "B_roll", "a050_300010", (6, 11, 14))
    pair("C0_nofb", "C_roll_nofb", "a050_300010", (6, 11, 14))
    pair("A_base", "D_sameplan", "a050_300010", (6, 11, 14))

    def forearm_delta(left, right):
        deltas = []
        for frame in range(53):
            a = indexed[(left, MAIN, frame)]
            b = indexed[(right, MAIN, frame)]
            deltas.append((abs(float(a["forearm_l_roll"]) - float(b["forearm_l_roll"])), frame, "l",
                           a["forearm_l_roll"], b["forearm_l_roll"]))
            deltas.append((abs(float(a["forearm_r_roll"]) - float(b["forearm_r_roll"])), frame, "r",
                           a["forearm_r_roll"], b["forearm_r_roll"]))
        deltas.sort(reverse=True)
        print("FORE", left, right, "top", [(round(d, 4), fr, side) for d, fr, side, _a, _b in deltas[:3]], flush=True)

    forearm_delta("A_base", "B_roll")
    forearm_delta("H_hand", "H_hand_roll")
    forearm_delta("H_both", "H_both_roll")
    print("TRACE", len(traces), "DONE", flush=True)


if __name__ == "__main__":
    main()
