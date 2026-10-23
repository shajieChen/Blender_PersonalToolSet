"""Validate the floor-height fix candidate (never the installed addon)."""
import csv
import hashlib
import json
import math
import sys
from pathlib import Path

import bpy

CANDIDATE_ROOT = Path(r"H:\Blender_Plugin\tmp_forearm_roll\floor_candidate_root")
OUT = Path(r"H:\Blender_Plugin\tmp_forearm_roll\foot_sink_investigation")
sys.path.insert(0, str(CANDIDATE_ROOT))
for name in list(sys.modules):
    if name == "humanoid_retarget" or name.startswith("humanoid_retarget."):
        del sys.modules[name]

import humanoid_retarget
import humanoid_retarget.ik as ik_module
import humanoid_retarget.retarget as retarget
from humanoid_retarget.foot_ik import FootIKSettings
from humanoid_retarget.mapping import build_pairs
from humanoid_retarget import pipeline

module_file = Path(humanoid_retarget.__file__).resolve()
assert str(module_file).lower().startswith(str(CANDIDATE_ROOT.resolve()).lower()), module_file
ik_hash = hashlib.sha256(Path(ik_module.__file__).read_bytes()).hexdigest().upper()
print("CANDIDATE", module_file, humanoid_retarget.bl_info["version"], "IK_SHA256", ik_hash, flush=True)
assert ik_hash == "0ED8BB563226F5E5C7739249303AEEA5ACAEBCCFE5D3D987A3236D78E9CC0B3B", ik_hash

SOURCE = r"h:\SErsiko_ExtactedTool\output\c0000_突刺_wp_a_0300.glb"
TARGET = r"c:\Users\chenshajie1\Downloads\body.FBX"
CLIPS = ("a050_300000", "a050_300010", "a050_301000", "a050_302011")

real_collect = retarget.collect_actions
holder = {"action": None}
retarget.collect_actions = lambda _src: [holder["action"]]
solve_err = {}
speed_log = {}
real_solve = ik_module._solve_chain
real_apply = retarget.apply_contact_ik


def recording_solve(tgt, space, reference, goal, pole_hint=None):
    distance = real_solve(tgt, space, reference, goal, pole_hint=pole_hint)
    solve_err[(bpy.context.scene.frame_current, reference.roles[2])] = float(distance)
    return distance


def recording_apply(src, tgt, geometry, settings, states, speeds, pelvis_delta, dt):
    for role, value in (speeds or {}).items():
        speed_log[(bpy.context.scene.frame_current, role)] = float(value)
    return real_apply(src, tgt, geometry, settings, states, speeds, pelvis_delta, dt)


ik_module._solve_chain = recording_solve
retarget.apply_contact_ik = recording_apply
rows = []
world = {}


def load_world(source_dz=0.0, target_dz=0.0):
    retarget.collect_actions = real_collect
    bpy.ops.wm.read_factory_settings(use_empty=True)
    try:
        source, _ = pipeline.load_source(SOURCE)
        objects, _ = pipeline.import_model(TARGET)
        target = pipeline.pick_armature(objects)
        mesh = next(obj for obj in bpy.data.objects if obj.type == "MESH" and obj.parent == target)
        source.location.z += source_dz
        target.location.z += target_dz
        bpy.context.view_layer.update()
        pairs = build_pairs(source, target)
        actions = {item.name: item for item in real_collect(source)}
        return source, target, mesh, pairs, actions
    finally:
        retarget.collect_actions = lambda _src: [holder["action"]]


def reset_pose(target):
    if target.animation_data:
        target.animation_data_clear()
    for pose_bone in target.pose.bones:
        pose_bone.rotation_mode = "QUATERNION"
        pose_bone.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
        pose_bone.location = (0.0, 0.0, 0.0)
        pose_bone.scale = (1.0, 1.0, 1.0)
    bpy.context.view_layer.update()


def sole_lowest(mesh, foot_name):
    deps = bpy.context.evaluated_depsgraph_get()
    evaluated = mesh.evaluated_get(deps)
    posed = evaluated.to_mesh()
    matrix = evaluated.matrix_world
    group_index = {g.name: g.index for g in mesh.vertex_groups}
    overall, sole = None, None
    for vertex in posed.vertices:
        point = matrix @ vertex.co
        if overall is None or point.z < overall:
            overall = point.z
        idx = group_index.get(foot_name)
        if idx is not None:
            weight = next((g.weight for g in vertex.groups if g.group == idx), 0.0)
            if weight > 0.5 and (sole is None or point.z < sole):
                sole = point.z
    evaluated.to_mesh_clear()
    return float(overall), float(sole)


def bake_and_scan(config, action_name, floor_m):
    source, target, mesh, pairs, actions = world["data"]
    roles = {role: (s, t) for role, s, t in pairs}
    action = actions[action_name]
    reset_pose(target)
    holder["action"] = action
    retarget._assign_action(source, action)
    ik_module.clear_correction_plan_cache()
    ik_module._CORRECTION_PLAN = None
    ik_module._LAST_PLAN = None
    ik_module.CONTACT_LOG.clear()
    solve_err.clear()
    speed_log.clear()
    options = retarget.RetargetOptions(
        pairs=pairs, root_motion="KEEP", reference="REST",
        foot_ik=True, hand_ik=False,
        foot_ik_settings=FootIKSettings(floor_enabled=True, floor_alpha=1.0, floor_height_m=floor_m),
        contact_min_knee_deg=15.0, correction_smoothing="height",
    )
    retarget.bake_retarget(source, target, options)
    feedback = {(e[0], e[1]): e for e in ik_module.CONTACT_LOG}
    plan_size = len(ik_module._LAST_PLAN or {})
    for pose_bone in target.pose.bones:
        pose_bone.scale = (1.0, 1.0, 1.0)

    def head(name):
        return target.matrix_world @ target.pose.bones[name].head

    start, end = int(action.frame_range[0]), int(round(action.frame_range[1]))
    for frame in range(start, end + 1):
        bpy.context.scene.frame_set(frame)
        bpy.context.view_layer.update()
        row = {"config": config, "action": action_name, "frame": frame, "floor_m": floor_m,
               "plan_size": plan_size}
        row["pelvis"] = json.dumps([round(float(v), 6) for v in head(roles["hips"][1])])
        row["head"] = json.dumps([round(float(v), 6) for v in head(roles["head"][1])])
        mesh_low = None
        for side in ("l", "r"):
            thigh = head(roles["thigh_" + side][1])
            knee = head(roles["shin_" + side][1])
            ankle = head(roles["foot_" + side][1])
            overall, sole = sole_lowest(mesh, roles["foot_" + side][1])
            mesh_low = overall if mesh_low is None else min(mesh_low, overall)
            first, second = thigh - knee, ankle - knee
            row[side + "_sole_world_mm"] = round(sole * 1000.0, 3)
            row[side + "_sole_rel_mm"] = round((sole - floor_m) * 1000.0, 3)
            row[side + "_ankle"] = json.dumps([round(float(v), 6) for v in ankle])
            row[side + "_knee_deg"] = round(math.degrees(first.angle(second)), 3)
            row[side + "_upper_len"] = round((knee - thigh).length, 6)
            row[side + "_lower_len"] = round((ankle - knee).length, 6)
            row[side + "_err_mm"] = round(solve_err.get((frame, "foot_" + side), 0.0) * 1000.0, 4)
            speed = speed_log.get((frame, "foot_" + side), -1.0)
            row[side + "_contact"] = bool(0.0 <= float(speed) <= 0.15)
            entry = feedback.get((frame, "foot_" + side))
            row[side + "_recheck_raised_mm"] = None if entry is None else round(float(entry[6]) * 1000.0, 3)
            row[side + "_log_lowest_rel_mm"] = None if entry is None else round(float(entry[3]) * 1000.0, 3)
        row["mesh_lowest_world_mm"] = round(mesh_low * 1000.0, 3)
        rows.append(row)
    print("DONE", config, action_name, "floor", floor_m, "plan", plan_size, flush=True)


def main():
    world["data"] = load_world()
    for clip in CLIPS:
        bake_and_scan("F0", clip, 0.0)
    for clip in CLIPS:
        bake_and_scan("FP", clip, 0.05)
    for clip in CLIPS:
        bake_and_scan("FM", clip, -0.05)
    world["data"] = load_world(target_dz=0.05)
    bake_and_scan("T2", "a050_300000", 0.05)
    bake_and_scan("T2", "a050_301000", 0.05)
    world["data"] = load_world(source_dz=0.05, target_dz=0.05)
    bake_and_scan("T3", "a050_300000", 0.05)
    world["data"] = load_world(source_dz=0.03)
    bake_and_scan("SRC_RAISED", "a050_300000", 0.0)
    with (OUT / "floor_fix_frames.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print("ROWS", len(rows), "DONE", flush=True)


if __name__ == "__main__":
    main()
