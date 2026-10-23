"""Compare roll-off, inline roll, and roll-after-contact. Copy only. No save.

Each bake clears the height-plan cache and builds its own plan.
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

    def recording_solve(tgt, space, reference, goal, pole_hint=None):
        distance = real_solve(tgt, space, reference, goal, pole_hint=pole_hint)
        solve_err[(bpy.context.scene.frame_current, reference.roles[2])] = float(distance)
        return distance

    ik_module._solve_chain = recording_solve
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
    plans = {}

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
                row[side + "_upper_len"] = round((knee - thigh).length, 6)
                row[side + "_lower_len"] = round((ankle - knee).length, 6)
                row[side + "_err_mm"] = round(solve_err.get((frame, "foot_" + side), 0.0) * 1000.0, 4)
                entry = feedback.get((frame, "foot_" + side))
                row[side + "_feedback"] = None if entry is None else entry[2]
                row[side + "_raised_mm"] = None if entry is None else round(float(entry[6]) * 1000.0, 3)
                planned = None if plan is None else plan.get((frame, "foot_" + side))
                row[side + "_plan"] = json.dumps(vec3(planned if planned is not None else Vector()))
            rows.append(row)

    def bake(config, action, hand_ik, roll, apply_mode):
        holder["action"] = action
        retarget._assign_action(source, action)
        ik_module.clear_correction_plan_cache()
        ik_module._CORRECTION_PLAN = None
        ik_module._LAST_PLAN = None
        ik_module._CONTACT_MIN_KNEE_DEG = None
        ik_module.CALF_ROLL_LOG.clear()
        ik_module.CONTACT_LOG.clear()
        solve_err.clear()
        ik_module._CALF_ROLL_FIX_ENABLED = roll
        ik_module._CALF_ROLL_APPLY = apply_mode
        options = retarget.RetargetOptions(
            pairs=pairs, root_motion="KEEP", reference="REST",
            foot_ik=True, hand_ik=hand_ik,
            foot_ik_settings=settings,
            contact_min_knee_deg=15.0, correction_smoothing="height",
        )
        report, _ = retarget.bake_retarget(source, target, options)
        ik_module._CALF_ROLL_FIX_ENABLED = False
        ik_module._CALF_ROLL_APPLY = "inline"
        plan = None
        if ik_module._LAST_PLAN is not None:
            plan = {key: value.copy() for key, value in ik_module._LAST_PLAN.items()}
            plans[(config, action.name)] = plan
        roles_logged = sorted({item[1] for item in ik_module.CALF_ROLL_LOG})
        print("BAKE", config, action.name, "apply", apply_mode, "roll_roles", roles_logged,
              "contact", len(ik_module.CONTACT_LOG), "plan", 0 if plan is None else len(plan),
              report.replace("\n", " | ")[:120], flush=True)
        start, end = int(action.frame_range[0]), int(round(action.frame_range[1]))
        scan(config, action.name, start, end, plan)

    for name in CLIPS:
        action = actions[name]
        bake("A_base", action, False, False, "inline")
        bake("B_inline", action, False, True, "inline")
        bake("C_final", action, False, True, "final")
    bake("H_base", actions[MAIN], True, False, "inline")
    bake("H_inline", actions[MAIN], True, True, "inline")
    bake("H_final", actions[MAIN], True, True, "final")

    with open(OUT + r"\calf_roll_order_frames.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    indexed = {(row["config"], row["action"], int(row["frame"])): row for row in rows}

    def dist(left, right):
        return math.sqrt(sum((x - y) ** 2 for x, y in zip(json.loads(left), json.loads(right))))

    def plan_delta(left_key, right_key):
        left = plans.get(left_key)
        right = plans.get(right_key)
        if not left or not right:
            print("PLAN_MISSING", left_key, right_key, flush=True)
            return
        delta = 0.0
        at = None
        for key, value in left.items():
            other = right.get(key)
            if other is None:
                continue
            distance = (value - other).length
            if distance > delta:
                delta = distance
                at = key
        print("PLAN_DELTA", left_key[1], left_key[0], right_key[0], "max_m", round(delta, 6), "at", at, flush=True)

    def summarize(config, action):
        subset = [row for row in rows if row["config"] == config and row["action"] == action]
        roll = max(max(abs(float(row["l_roll"])), abs(float(row["r_roll"]))) for row in subset)
        z0 = sum(1 for row in subset if int(row["n_z_lt_0"]) > 0)
        z01 = sum(1 for row in subset if int(row["n_z_lt_001"]) > 0)
        worst = min(subset, key=lambda row: float(row["mesh_lowest"]))
        err = max(max(float(row["l_err_mm"]), float(row["r_err_mm"])) for row in subset)
        print("SUM", config, action, "roll", round(roll, 4), "Z<0", z0, "Z<-0.01", z01,
              "min_z", worst["mesh_lowest"], "at", worst["frame"], "n0", worst["n_z_lt_0"],
              "n01", worst["n_z_lt_001"], "err_mm", round(err, 4), flush=True)

    def pair(left, right, action):
        frames = sorted(frame for cfg, name, frame in indexed if cfg == left and name == action)
        knee = ankle = length = knee_deg = hips = mesh = forearm = 0.0
        knee_at = ankle_at = mesh_at = None
        for frame in frames:
            a = indexed[(left, action, frame)]
            b = indexed[(right, action, frame)]
            for side in ("l", "r"):
                knee_d = dist(a[side + "_knee"], b[side + "_knee"])
                ankle_d = dist(a[side + "_ankle"], b[side + "_ankle"])
                if knee_d > knee:
                    knee = knee_d
                    knee_at = (frame, side, round(knee_d * 1000.0, 2))
                if ankle_d > ankle:
                    ankle = ankle_d
                    ankle_at = (frame, side, round(ankle_d * 1000.0, 2))
                length = max(length, abs(float(a[side + "_upper_len"]) - float(b[side + "_upper_len"])))
                length = max(length, abs(float(a[side + "_lower_len"]) - float(b[side + "_lower_len"])))
                knee_deg = max(knee_deg, abs(float(a[side + "_knee_deg"]) - float(b[side + "_knee_deg"])))
            hips = max(hips, abs(float(a["hips_z"]) - float(b["hips_z"])))
            mesh_d = float(b["mesh_lowest"]) - float(a["mesh_lowest"])
            if abs(mesh_d) > abs(mesh):
                mesh = mesh_d
                mesh_at = (frame, round(mesh_d * 1000.0, 3), a["mesh_lowest"], b["mesh_lowest"])
            forearm = max(forearm, abs(float(a["forearm_l_roll"]) - float(b["forearm_l_roll"])))
            forearm = max(forearm, abs(float(a["forearm_r_roll"]) - float(b["forearm_r_roll"])))
        print("PAIR", left, right, action, "knee_mm", knee_at, "ankle_mm", ankle_at,
              "knee_deg", round(knee_deg, 4), "len_m", round(length, 6), "hips_m", round(hips, 6),
              "mesh_dz_mm", mesh_at, "fore_deg", round(forearm, 4), flush=True)

    def focus(action, frames):
        for frame in frames:
            for config in ("A_base", "B_inline", "C_final"):
                row = indexed[(config, action, frame)]
                print("FOCUS", config, action, frame,
                      "roll", row["l_roll"], row["r_roll"],
                      "kdeg", row["l_knee_deg"], row["r_knee_deg"],
                      "kneeL", row["l_knee"], "ankleL", row["l_ankle"],
                      "kneeR", row["r_knee"], "ankleR", row["r_ankle"],
                      "fb", row["l_feedback"], row["r_feedback"],
                      "raised", row["l_raised_mm"], row["r_raised_mm"],
                      "planL", row["l_plan"], "planR", row["r_plan"],
                      "hips", row["hips_z"], "mesh", row["mesh_lowest"],
                      "n0", row["n_z_lt_0"], "n01", row["n_z_lt_001"], flush=True)

    for name in CLIPS:
        for config in ("A_base", "B_inline", "C_final"):
            summarize(config, name)
        plan_delta(("A_base", name), ("B_inline", name))
        plan_delta(("A_base", name), ("C_final", name))
        pair("A_base", "B_inline", name)
        pair("A_base", "C_final", name)
    focus(MAIN, (15, 16))
    focus("a050_302011", (9, 10))
    for config in ("H_base", "H_inline", "H_final"):
        summarize(config, MAIN)
    pair("H_base", "H_inline", MAIN)
    pair("H_base", "H_final", MAIN)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
