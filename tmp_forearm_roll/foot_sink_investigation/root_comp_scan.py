"""Root-bone (pelvis) height tiers 0/10/20/30 mm with frozen sole-corrected foot goals."""
import csv
import json
import math
import sys

import bpy

ROOT = r"H:\Blender_Plugin\tmp_forearm_roll\solehip_root"
SOURCE = r"h:\SErsiko_ExtactedTool\output\c0000_突刺_wp_a_0300.glb"
TARGET = r"c:\Users\chenshajie1\Downloads\body.FBX"
OUT = r"H:\Blender_Plugin\tmp_forearm_roll\foot_sink_investigation"
MAIN = "a050_300000"
SPOT = "a050_300010"
REST_UPPER = 0.2542
REST_LOWER = 0.1907


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

    print("MODULE", ik_module.__file__, flush=True)
    source, _ = pipeline.load_source(SOURCE)
    objects, _ = pipeline.import_model(TARGET)
    target = pipeline.pick_armature(objects)
    mesh = next(obj for obj in bpy.data.objects if obj.type == "MESH" and obj.parent == target)
    print("OBJECT_MATRIX", [round(float(v), 6) for v in target.matrix_world.translation], flush=True)
    pairs = build_pairs(source, target)
    roles = {role: (src_name, tgt_name) for role, src_name, tgt_name in pairs}
    wanted = (MAIN, SPOT)
    actions = {item.name: item for item in retarget.collect_actions(source) if item.name in wanted}
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
        overall = None
        sole = None
        for vertex in posed.vertices:
            point = world @ vertex.co
            if overall is None or point.z < overall:
                overall = point.z
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
        return float(overall), (None if sole is None else float(sole))

    def head(name):
        return target.matrix_world @ target.pose.bones[name].head

    def scan(config, action_name, exp_log, hip_log):
        for pose_bone in target.pose.bones:
            pose_bone.scale = (1.0, 1.0, 1.0)
        action = actions[action_name]
        start, end = int(action.frame_range[0]), int(round(action.frame_range[1]))
        for frame in range(start, end + 1):
            bpy.context.scene.frame_set(frame)
            bpy.context.view_layer.update()
            row = {"config": config, "action": action_name, "frame": frame}
            row["pelvis"] = json.dumps([round(float(v), 6) for v in head(roles["hips"][1])])
            row["spine"] = json.dumps([round(float(v), 6) for v in head(roles["spine"][1])])
            row["head"] = json.dumps([round(float(v), 6) for v in head(roles["head"][1])])
            entry = hip_log.get(frame)
            row["applied_delta_mm"] = None if entry is None else entry[1]
            row["forearm_l_roll"] = round(chain_roll(target, roles["forearm_l"][1], roles["hand_l"][1]), 4)
            row["forearm_r_roll"] = round(chain_roll(target, roles["forearm_r"][1], roles["hand_r"][1]), 4)
            lows = []
            for side in ("l", "r"):
                thigh = head(roles["thigh_" + side][1])
                knee = head(roles["shin_" + side][1])
                ankle = head(roles["foot_" + side][1])
                lo, sole = sole_lowest(roles["foot_" + side][1])
                lows.append(lo)
                first = thigh - knee
                second = ankle - knee
                knee_deg = math.degrees(first.angle(second)) if first.length > 1e-9 and second.length > 1e-9 else 0.0
                row[side + "_sole_z"] = None if sole is None else round(sole, 6)
                row[side + "_ankle"] = json.dumps([round(float(v), 6) for v in ankle])
                row[side + "_knee_deg"] = round(knee_deg, 3)
                row[side + "_reach"] = round((ankle - thigh).length, 6)
                row[side + "_slack"] = round(REST_UPPER + REST_LOWER - (ankle - thigh).length, 6)
                row[side + "_err_mm"] = round(solve_err.get((frame, "foot_" + side), 0.0) * 1000.0, 4)
                row[side + "_hand_err_mm"] = round(solve_err.get((frame, "hand_" + side), 0.0) * 1000.0, 4)
                exp = exp_log.get((frame, "foot_" + side))
                row[side + "_contact"] = None if exp is None else exp[2]
                row[side + "_hand"] = json.dumps([round(float(v), 6) for v in head(roles["hand_" + side][1])])
            row["mesh_lowest"] = round(min(lows), 6)
            rows.append(row)

    def bake(config, action, root_delta, hand_ik):
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
        ik_module.EXP_SOLE = True
        ik_module.EXP_HIP = root_delta > 0.0
        ik_module.EXP_ROOT_DELTA = root_delta
        options = retarget.RetargetOptions(
            pairs=pairs, root_motion="KEEP", reference="REST",
            foot_ik=True, hand_ik=hand_ik,
            foot_ik_settings=settings,
            contact_min_knee_deg=15.0,
            correction_smoothing="height",
        )
        retarget.bake_retarget(source, target, options)
        ik_module.EXP_SOLE = False
        ik_module.EXP_HIP = False
        ik_module.EXP_ROOT_DELTA = 0.0
        exp_log = {(e[0], e[1]): e for e in ik_module.EXP_LOG}
        hip_log = {e[0]: e for e in ik_module.EXP_HIP_LOG}
        applied = [e[1] for e in ik_module.EXP_HIP_LOG]
        print("BAKE", config, action.name,
              "applied_min", round(min(applied), 3) if applied else None,
              "applied_max", round(max(applied), 3) if applied else None,
              "capped_frames", sum(1 for a in applied if a < root_delta * 1000.0 - 0.01), flush=True)
        scan(config, action.name, exp_log, hip_log)

    jobs = [
        ("R0", MAIN, 0.0, False),
        ("R10", MAIN, 0.010, False),
        ("R20", MAIN, 0.020, False),
        ("R30", MAIN, 0.030, False),
        ("H0", MAIN, 0.0, True),
        ("H30", MAIN, 0.030, True),
        ("R0", SPOT, 0.0, False),
        ("R30", SPOT, 0.030, False),
    ]
    for config, name, delta, hand_ik in jobs:
        if name not in actions:
            print("SKIP", name, flush=True)
            continue
        bake(config, actions[name], delta, hand_ik)

    with open(OUT + r"\root_comp_frames.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print("ROWS", len(rows), "DONE", flush=True)


if __name__ == "__main__":
    main()
