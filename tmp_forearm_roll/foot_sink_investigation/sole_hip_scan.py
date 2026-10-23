"""A baseline / B sole target / C sole+hip on the independent solehip copy."""
import csv
import json
import math
import sys

import bpy

ROOT = r"H:\Blender_Plugin\tmp_forearm_roll\solehip_root"
SOURCE = r"h:\SErsiko_ExtactedTool\output\c0000_突刺_wp_a_0300.glb"
TARGET = r"c:\Users\chenshajie1\Downloads\body.FBX"
OUT = r"H:\Blender_Plugin\tmp_forearm_roll\foot_sink_investigation"
CLIPS = ("a050_300000", "a050_300010", "a050_301000")
REST_UPPER = 0.2542
REST_LOWER = 0.1907


def main():
    sys.path.insert(0, ROOT)
    for name in list(sys.modules):
        if name == "humanoid_retarget" or name.startswith("humanoid_retarget."):
            del sys.modules[name]
    bpy.ops.wm.read_factory_settings(use_empty=True)
    from humanoid_retarget.mapping import build_pairs
    from humanoid_retarget import pipeline
    import humanoid_retarget.retarget as retarget
    import humanoid_retarget.ik as ik_module
    from humanoid_retarget.foot_ik import FootIKSettings

    print("MODULE", ik_module.__file__, "EXP_DEFAULT", ik_module.EXP_SOLE, ik_module.EXP_HIP, flush=True)
    source, _ = pipeline.load_source(SOURCE)
    objects, _ = pipeline.import_model(TARGET)
    target = pipeline.pick_armature(objects)
    mesh = next(obj for obj in bpy.data.objects if obj.type == "MESH" and obj.parent == target)
    pairs = build_pairs(source, target)
    roles = {role: (src_name, tgt_name) for role, src_name, tgt_name in pairs}
    actions = {item.name: item for item in retarget.collect_actions(source) if item.name in CLIPS}
    print("FOUND", sorted(actions), flush=True)
    holder = {"action": None}
    retarget.collect_actions = lambda _src: [holder["action"]]
    settings = FootIKSettings(floor_enabled=True, floor_alpha=1.0, floor_height_m=0.0)
    rows = []
    solve_err = {}
    real_solve = ik_module._solve_chain

    def recording_solve(tgt, space, reference, goal, pole_hint=None):
        distance = real_solve(tgt, space, reference, goal, pole_hint=pole_hint)
        solve_err[(bpy.context.scene.frame_current, reference.roles[2])] = float(distance)
        return distance

    ik_module._solve_chain = recording_solve

    def reset_pose():
        if target.animation_data:
            target.animation_data_clear()
        for pose_bone in target.pose.bones:
            pose_bone.rotation_mode = "QUATERNION"
            pose_bone.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
            pose_bone.location = (0.0, 0.0, 0.0)
            pose_bone.scale = (1.0, 1.0, 1.0)
        bpy.context.view_layer.update()

    def sole_lowest(foot_name):
        deps = bpy.context.evaluated_depsgraph_get()
        evaluated = mesh.evaluated_get(deps)
        posed = evaluated.to_mesh()
        world = evaluated.matrix_world
        group_index = {g.name: g.index for g in mesh.vertex_groups}
        overall_lo = None
        overall_hi = None
        sole = None
        for vertex in posed.vertices:
            point = world @ vertex.co
            if overall_lo is None or point.z < overall_lo:
                overall_lo = point.z
            if overall_hi is None or point.z > overall_hi:
                overall_hi = point.z
            idx = group_index.get(foot_name)
            if idx is not None:
                weight = 0.0
                for item in vertex.groups:
                    if item.group == idx:
                        weight = item.weight
                        break
                if weight > 0.5 and (sole is None or point.z < sole):
                    sole = point.z
        evaluated.to_mesh_clear()
        return float(overall_lo), float(overall_hi), (None if sole is None else float(sole))

    def head(name):
        return target.matrix_world @ target.pose.bones[name].head

    def scan(config, action_name, exp_log, hip_log):
        for pose_bone in target.pose.bones:
            pose_bone.scale = (1.0, 1.0, 1.0)
        feedback = {(e[0], e[1]): e for e in ik_module.CONTACT_LOG}
        action = actions[action_name]
        start, end = int(action.frame_range[0]), int(round(action.frame_range[1]))
        for frame in range(start, end + 1):
            bpy.context.scene.frame_set(frame)
            bpy.context.view_layer.update()
            row = {"config": config, "action": action_name, "frame": frame}
            pelvis = head(roles["hips"][1])
            row["pelvis"] = json.dumps([round(float(v), 6) for v in pelvis])
            row["spine"] = json.dumps([round(float(v), 6) for v in head(roles["spine"][1])])
            row["head"] = json.dumps([round(float(v), 6) for v in head(roles["head"][1])])
            hip_entry = hip_log.get(frame)
            row["hip_delta_mm"] = None if hip_entry is None else hip_entry[1]
            overall = {}
            for side in ("l", "r"):
                thigh = head(roles["thigh_" + side][1])
                knee = head(roles["shin_" + side][1])
                ankle = head(roles["foot_" + side][1])
                toe = head(roles["toe_" + side][1]) if "toe_" + side in roles else ankle
                lo, hi, sole = sole_lowest(roles["foot_" + side][1])
                overall[side] = (lo, hi)
                first = thigh - knee
                second = ankle - knee
                knee_deg = math.degrees(first.angle(second)) if first.length > 1e-9 and second.length > 1e-9 else 0.0
                row[side + "_sole_z"] = None if sole is None else round(sole, 6)
                row[side + "_ankle"] = json.dumps([round(float(v), 6) for v in ankle])
                row[side + "_knee"] = json.dumps([round(float(v), 6) for v in knee])
                row[side + "_thigh"] = json.dumps([round(float(v), 6) for v in thigh])
                row[side + "_toe_z"] = round(float(toe.z), 6)
                row[side + "_knee_deg"] = round(knee_deg, 3)
                row[side + "_reach"] = round((ankle - thigh).length, 6)
                row[side + "_slack"] = round(REST_UPPER + REST_LOWER - (ankle - thigh).length, 6)
                row[side + "_upper_len"] = round((knee - thigh).length, 6)
                row[side + "_lower_len"] = round((ankle - knee).length, 6)
                row[side + "_err_mm"] = round(solve_err.get((frame, "foot_" + side), 0.0) * 1000.0, 4)
                entry = exp_log.get((frame, "foot_" + side))
                row[side + "_contact"] = None if entry is None else entry[2]
                row[side + "_sole_corr_mm"] = None if entry is None else entry[3]
                row[side + "_goal_z_mm"] = None if entry is None else entry[6]
                fb = feedback.get((frame, "foot_" + side))
                row[side + "_feedback"] = None if fb is None else fb[2]
                hand = head(roles["hand_" + side][1])
                row[side + "_hand"] = json.dumps([round(float(v), 6) for v in hand])
            row["mesh_lowest"] = round(min(v[0] for v in overall.values()), 6)
            row["mesh_highest"] = round(max(v[1] for v in overall.values()), 6)
            rows.append(row)

    def bake(config, action, sole, hip):
        reset_pose()
        holder["action"] = action
        retarget._assign_action(source, action)
        ik_module.clear_correction_plan_cache()
        ik_module._CORRECTION_PLAN = None
        ik_module._LAST_PLAN = None
        ik_module._CONTACT_MIN_KNEE_DEG = None
        ik_module._CONTACT_STACK_ENABLED = False
        ik_module.EXP_LOG.clear()
        ik_module.EXP_HIP_LOG.clear()
        ik_module.CONTACT_LOG.clear()
        solve_err.clear()
        ik_module.EXP_SOLE = sole
        ik_module.EXP_HIP = hip
        options = retarget.RetargetOptions(
            pairs=pairs, root_motion="KEEP", reference="REST",
            foot_ik=True, hand_ik=False,
            foot_ik_settings=settings,
            contact_min_knee_deg=15.0,
            correction_smoothing="height",
        )
        retarget.bake_retarget(source, target, options)
        ik_module.EXP_SOLE = False
        ik_module.EXP_HIP = False
        exp_log = {(e[0], e[1]): e for e in ik_module.EXP_LOG}
        hip_log = {e[0]: e for e in ik_module.EXP_HIP_LOG}
        corr = [e[3] for e in ik_module.EXP_LOG if e[3]]
        deltas = [e[1] for e in ik_module.EXP_HIP_LOG if e[1]]
        print("BAKE", config, action.name,
              "sole_corr_max_mm", round(max(corr), 3) if corr else 0.0,
              "hip_delta_max_mm", round(max(deltas), 3) if deltas else 0.0,
              "hip_frames", sum(1 for d in deltas if d > 0), flush=True)
        scan(config, action.name, exp_log, hip_log)

    for name in CLIPS:
        if name not in actions:
            print("SKIP", name, flush=True)
            continue
        bake("A", actions[name], False, False)
        bake("B", actions[name], True, False)
        bake("C", actions[name], True, True)

    with open(OUT + r"\sole_hip_frames.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print("ROWS", len(rows), "DONE", flush=True)


if __name__ == "__main__":
    main()
