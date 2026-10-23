"""Final regression of the official-based candidate. Roll default stays off."""
import csv
import json
import math
import sys

import bpy

CANDIDATE = r"H:\Blender_Plugin\tmp_forearm_roll\candidate_root"
SOURCE = r"h:\SErsiko_ExtactedTool\output\c0000_突刺_wp_a_0300.glb"
TARGET = r"c:\Users\chenshajie1\Downloads\body.FBX"
OUT = r"H:\Blender_Plugin\tmp_forearm_roll\foot_sink_investigation"
CLIPS = ("a050_300000", "a050_300010", "a050_302011", "a050_301000")
MAIN = "a050_300000"


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


def quat_of(matrix):
    quat = matrix.to_quaternion()
    if quat.w < 0.0:
        quat.negate()
    return quat


def vec3(value):
    return [round(float(item), 6) for item in value]


def main():
    sys.path.insert(0, CANDIDATE)
    for name in list(sys.modules):
        if name == "humanoid_retarget" or name.startswith("humanoid_retarget."):
            del sys.modules[name]
    bpy.ops.wm.read_factory_settings(use_empty=True)
    from humanoid_retarget.mapping import build_pairs
    from humanoid_retarget import pipeline
    import humanoid_retarget.retarget as retarget
    import humanoid_retarget.ik as ik_module
    from humanoid_retarget.foot_ik import FootIKSettings

    print("MODULE", ik_module.__file__, "STACK_DEFAULT", ik_module._CONTACT_STACK_ENABLED, "ROLL_DEFAULT", ik_module._CALF_ROLL_FIX_ENABLED, flush=True)
    source, _ = pipeline.load_source(SOURCE)
    objects, _ = pipeline.import_model(TARGET)
    target = pipeline.pick_armature(objects)
    mesh = next(obj for obj in bpy.data.objects if obj.type == "MESH" and obj.parent == target)
    pairs = build_pairs(source, target)
    roles = {role: (src_name, tgt_name) for role, src_name, tgt_name in pairs}
    actions = {item.name: item for item in retarget.collect_actions(source) if item.name in CLIPS}
    missing = [name for name in CLIPS if name not in actions]
    print("MISSING", missing, "FOUND", sorted(actions), flush=True)
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

    def mesh_low():
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
        depth = 0.0 if lowest is None or lowest >= 0.0 else -lowest
        return float(lowest if lowest is not None else 0.0), n0, n01, depth

    def world_quat(name):
        pose = target.pose.bones[name]
        return quat_of(target.matrix_world @ pose.matrix)

    def scan(config, action_name, plan):
        for pose_bone in target.pose.bones:
            pose_bone.scale = (1.0, 1.0, 1.0)
        feedback = {(entry[0], entry[1]): entry for entry in ik_module.CONTACT_LOG}
        action = actions[action_name]
        start, end = int(action.frame_range[0]), int(round(action.frame_range[1]))
        for frame in range(start, end + 1):
            bpy.context.scene.frame_set(frame)
            bpy.context.view_layer.update()
            lowest, n0, n01, depth = mesh_low()
            hips = target.matrix_world @ target.pose.bones[roles["hips"][1]].head
            row = {
                "config": config,
                "action": action_name,
                "frame": frame,
                "mesh_lowest": round(lowest, 6),
                "n_z_lt_0": n0,
                "n_z_lt_001": n01,
                "penetration_mm": round(depth * 1000.0, 3),
                "hips": json.dumps(vec3(hips)),
                "forearm_l_roll": round(chain_roll(target, roles["forearm_l"][1], roles["hand_l"][1]), 4),
                "forearm_r_roll": round(chain_roll(target, roles["forearm_r"][1], roles["hand_r"][1]), 4),
            }
            spine_role = "spine" if "spine" in roles else None
            if spine_role:
                row["spine_quat"] = json.dumps([round(float(item), 6) for item in world_quat(roles[spine_role][1])])
            else:
                row["spine_quat"] = ""
            for side in ("l", "r"):
                thigh = target.matrix_world @ target.pose.bones[roles["thigh_" + side][1]].head
                knee = target.matrix_world @ target.pose.bones[roles["shin_" + side][1]].head
                ankle = target.matrix_world @ target.pose.bones[roles["foot_" + side][1]].head
                foot_q = world_quat(roles["foot_" + side][1])
                row[side + "_roll"] = round(chain_roll(target, roles["shin_" + side][1], roles["foot_" + side][1]), 4)
                row[side + "_knee"] = json.dumps(vec3(knee))
                row[side + "_ankle"] = json.dumps(vec3(ankle))
                row[side + "_upper_len"] = round((knee - thigh).length, 6)
                row[side + "_lower_len"] = round((ankle - knee).length, 6)
                row[side + "_foot_quat"] = json.dumps([round(float(item), 6) for item in foot_q])
                row[side + "_err_mm"] = round(solve_err.get((frame, "foot_" + side), 0.0) * 1000.0, 4)
                entry = feedback.get((frame, "foot_" + side))
                row[side + "_feedback"] = None if entry is None else entry[2]
                row[side + "_raised_mm"] = None if entry is None else round(float(entry[6]) * 1000.0, 3)
                planned = None if plan is None else plan.get((frame, "foot_" + side))
                row[side + "_plan_z"] = 0.0 if planned is None else round(float(planned.z), 6)
            rows.append(row)

    def bake(config, action, foot_ik, hand_ik, roll):
        reset_pose()
        holder["action"] = action
        retarget._assign_action(source, action)
        ik_module.clear_correction_plan_cache()
        ik_module._CORRECTION_PLAN = None
        ik_module._LAST_PLAN = None
        ik_module._CONTACT_MIN_KNEE_DEG = None
        ik_module._CONTACT_STACK_ENABLED = False
        ik_module.CALF_ROLL_LOG.clear()
        ik_module.FOOT_POSE_LOG.clear()
        ik_module.CONTACT_LOG.clear()
        solve_err.clear()
        ik_module._CALF_ROLL_FIX_ENABLED = roll
        ik_module._CALF_ROLL_APPLY = "restore_foot"
        options = retarget.RetargetOptions(
            pairs=pairs, root_motion="KEEP", reference="REST",
            foot_ik=foot_ik, hand_ik=hand_ik,
            foot_ik_settings=settings,
            contact_min_knee_deg=15.0 if foot_ik else 0.0,
            correction_smoothing="height" if foot_ik else "",
        )
        retarget.bake_retarget(source, target, options)
        ik_module._CALF_ROLL_FIX_ENABLED = False
        plan = None
        if ik_module._LAST_PLAN is not None:
            plan = {key: value.copy() for key, value in ik_module._LAST_PLAN.items()}
        restored = ik_module.FOOT_POSE_LOG
        roll_after = max((abs(item[3]) for item in ik_module.CALF_ROLL_LOG), default=0.0)
        foot_left = max((item[2] for item in restored), default=0.0)
        ankle_left = max((item[3] for item in restored), default=0.0)
        print("BAKE", config, action.name, "roll_after", round(roll_after, 4),
              "snap_foot", round(foot_left, 4), "snap_ankle", round(ankle_left, 4),
              "stack", ik_module._CONTACT_STACK_ENABLED, flush=True)
        scan(config, action.name, plan)

    jobs = []
    for name in CLIPS:
        jobs.append((name, "foot_off", True, False, False))
        jobs.append((name, "foot_on", True, False, True))
    jobs.extend((
        (MAIN, "fk_off", False, False, False),
        (MAIN, "fk_on", False, False, True),
        (MAIN, "hand_off", False, True, False),
        (MAIN, "hand_on", False, True, True),
        (MAIN, "both_off", True, True, False),
        (MAIN, "both_on", True, True, True),
    ))
    for name, config, foot_ik, hand_ik, roll in jobs:
        if name not in actions:
            print("SKIP", name, flush=True)
            continue
        bake(config, actions[name], foot_ik, hand_ik, roll)

    with open(OUT + r"\final_regression_frames.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print("ROWS", len(rows), "DONE", flush=True)


if __name__ == "__main__":
    main()
