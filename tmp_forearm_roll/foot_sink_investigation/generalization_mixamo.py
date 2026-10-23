"""Labeled motion-state audit: Mixamo Walking / Breathing Idle -> body.FBX."""
import csv
import json
import math
import sys
from pathlib import Path

import bpy

ADDONS = Path(bpy.utils.resource_path("USER")) / "scripts" / "addons"
sys.path.insert(0, str(ADDONS))
for name in list(sys.modules):
    if name == "humanoid_retarget" or name.startswith("humanoid_retarget."):
        del sys.modules[name]

import humanoid_retarget
import humanoid_retarget.ik as ik_module
import humanoid_retarget.retarget as retarget
from humanoid_retarget.foot_ik import FootIKSettings
from humanoid_retarget.mapping import build_pairs
from humanoid_retarget import pipeline

TARGET = r"c:\Users\chenshajie1\Downloads\body.FBX"
OUT = Path(r"H:\Blender_Plugin\tmp_forearm_roll\foot_sink_investigation")
JOBS = [("WALK", r"C:\Users\chenshajie1\Downloads\Walking.fbx"),
        ("IDLE", r"C:\Users\chenshajie1\Downloads\Breathing Idle.fbx")]

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

for config, source_path in JOBS:
    retarget.collect_actions = real_collect
    bpy.ops.wm.read_factory_settings(use_empty=True)
    retarget.collect_actions = real_collect
    source, _ = pipeline.load_source(source_path)
    objects, _ = pipeline.import_model(TARGET)
    target = pipeline.pick_armature(objects)
    mesh = next(obj for obj in bpy.data.objects if obj.type == "MESH" and obj.parent == target)
    pairs = build_pairs(source, target)
    roles = {role: (s, t) for role, s, t in pairs}
    actions = [a for a in real_collect(source)
               if not a.is_empty and "Footsteps" not in a.name]
    print("JOB", config, "source", source.name, "actions", [a.name for a in actions], flush=True)
    retarget.collect_actions = lambda _src: [holder["action"]]

    def sole_lowest(foot_name):
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

    def head(name):
        return target.matrix_world @ target.pose.bones[name].head

    for action in actions:
        if target.animation_data:
            target.animation_data_clear()
        for pb in target.pose.bones:
            pb.rotation_mode = "QUATERNION"
            pb.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
            pb.location = (0.0, 0.0, 0.0)
            pb.scale = (1.0, 1.0, 1.0)
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
            foot_ik_settings=FootIKSettings(floor_enabled=True, floor_alpha=1.0, floor_height_m=0.0),
            contact_min_knee_deg=15.0, correction_smoothing="height",
        )
        retarget.bake_retarget(source, target, options)
        feedback = {(e[0], e[1]): e for e in ik_module.CONTACT_LOG}
        for pb in target.pose.bones:
            pb.scale = (1.0, 1.0, 1.0)
        start, end = int(action.frame_range[0]), int(round(action.frame_range[1]))
        for frame in range(start, end + 1):
            bpy.context.scene.frame_set(frame)
            bpy.context.view_layer.update()
            row = {"config": config, "action": action.name, "frame": frame}
            row["pelvis"] = json.dumps([round(float(v), 6) for v in head(roles["hips"][1])])
            mesh_low = None
            for side in ("l", "r"):
                thigh = head(roles["thigh_" + side][1])
                knee = head(roles["shin_" + side][1])
                ankle = head(roles["foot_" + side][1])
                overall, sole = sole_lowest(roles["foot_" + side][1])
                mesh_low = overall if mesh_low is None else min(mesh_low, overall)
                first, second = thigh - knee, ankle - knee
                row[side + "_sole_rel_mm"] = round(sole * 1000.0, 3)
                row[side + "_knee_deg"] = round(math.degrees(first.angle(second)), 3)
                row[side + "_err_mm"] = round(solve_err.get((frame, "foot_" + side), 0.0) * 1000.0, 4)
                speed = speed_log.get((frame, "foot_" + side), -1.0)
                row[side + "_contact"] = bool(0.0 <= float(speed) <= 0.15)
                entry = feedback.get((frame, "foot_" + side))
                row[side + "_recheck_raised_mm"] = None if entry is None else round(float(entry[6]) * 1000.0, 3)
            row["mesh_lowest_rel_mm"] = round(mesh_low * 1000.0, 3)
            rows.append(row)
        print("DONE", config, action.name, start, end, flush=True)

with (OUT / "generalization_mixamo_frames.csv").open("w", newline="", encoding="utf-8") as handle:
    writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
print("ROWS", len(rows), "DONE", flush=True)
