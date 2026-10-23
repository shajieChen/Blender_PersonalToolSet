"""Generalization audit of the official 1.7.5 contact stack.

Runs in a fresh headless process against the installed addon (read-only).
Variants are built in-process only; no file, scene or bake on disk changes.
"""
import csv
import json
import math
import os
import sys
from pathlib import Path

import bpy
from mathutils import Vector

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

SOURCE = r"h:\SErsiko_ExtactedTool\output\c0000_突刺_wp_a_0300.glb"
TARGET = r"c:\Users\chenshajie1\Downloads\body.FBX"
OUT = Path(r"H:\Blender_Plugin\tmp_forearm_roll\foot_sink_investigation")
EXTRA_CLIPS = ("a050_300001", "a050_300011", "a050_301050", "a050_302010", "a050_305000", "a050_305001")

print("MODULE", humanoid_retarget.__file__, humanoid_retarget.bl_info["version"], flush=True)

holder = {"action": None}
_real_collect = retarget.collect_actions
retarget.collect_actions = lambda _src: [holder["action"]]
solve_err = {}
speed_log = {}
real_solve = ik_module._solve_chain
real_apply = ik_module.apply_contact_ik


def recording_solve(tgt, space, reference, goal, pole_hint=None):
    distance = real_solve(tgt, space, reference, goal, pole_hint=pole_hint)
    solve_err[(bpy.context.scene.frame_current, reference.roles[2])] = float(distance)
    return distance


def recording_apply(src, tgt, geometry, settings, states, speeds, pelvis_delta, dt):
    for role, value in (speeds or {}).items():
        speed_log[(bpy.context.scene.frame_current, role)] = float(value)
    return real_apply(src, tgt, geometry, settings, states, speeds, pelvis_delta, dt)


ik_module._solve_chain = recording_solve
# retarget.py does `from .ik import apply_contact_ik`, so patch its namespace.
retarget.apply_contact_ik = recording_apply


def load_world_full(variant):
    retarget.collect_actions = _real_collect
    bpy.ops.wm.read_factory_settings(use_empty=True)
    try:
        source, _ = pipeline.load_source(SOURCE)
        objects, _ = pipeline.import_model(TARGET)
        target = pipeline.pick_armature(objects)
        mesh = next(obj for obj in bpy.data.objects if obj.type == "MESH" and obj.parent == target)
        if variant in ("P1", "P2"):
            scale = 0.008 if variant == "P1" else 0.0125
            target.scale = (scale, scale, scale)
            bpy.context.view_layer.update()
        elif variant == "SEG":
            # Lengthen the calf by 20% of its world length: shift the calf
            # tail, the foot and toe bones by that world-space delta.
            bpy.context.view_layer.objects.active = target
            shifts = {}
            for side in ("L", "R"):
                calf_bone = target.data.bones["Bip01 " + side + " Calf"]
                head_w = target.matrix_world @ calf_bone.head_local
                tail_w = target.matrix_world @ calf_bone.tail_local
                delta_world = (tail_w - head_w) * 0.20
                shifts[side] = target.matrix_world.inverted().to_3x3() @ delta_world
            bpy.ops.object.mode_set(mode="EDIT")
            for side in ("L", "R"):
                delta = shifts[side]
                calf = target.data.edit_bones["Bip01 " + side + " Calf"]
                foot = target.data.edit_bones["Bip01 " + side + " Foot"]
                old_foot_head = foot.head.copy()
                calf.tail = calf.tail + delta
                foot.use_connect = False
                foot.head = calf.tail.copy()
                foot.tail = foot.tail + delta
                actual = foot.head - old_foot_head
                for bone in list(foot.children_recursive):
                    bone.head = bone.head + actual
                    bone.tail = bone.tail + actual
                print("SEG_EDIT", side, "foot_head_shift_armature", round(float(actual.length), 4), flush=True)
            bpy.ops.object.mode_set(mode="OBJECT")
            for side in ("L", "R"):
                calf_bone = target.data.bones["Bip01 " + side + " Calf"]
                foot_bone = target.data.bones["Bip01 " + side + " Foot"]
                length = (target.matrix_world @ calf_bone.tail_local
                          - target.matrix_world @ calf_bone.head_local).length
                joint = (target.matrix_world @ foot_bone.head_local
                         - target.matrix_world @ calf_bone.head_local).length
                print("SEG_REST", side, "calf_world_m", round(float(length), 4),
                      "shin_to_ankle_m", round(float(joint), 4), flush=True)
            world_deltas = {side: target.matrix_world.to_3x3() @ delta for side, delta in shifts.items()}
            inverse = mesh.matrix_world.inverted()
            group_index = {g.name: g.index for g in mesh.vertex_groups}
            for side, world_delta in world_deltas.items():
                idx = group_index["Bip01 " + side + " Foot"]
                for vertex in mesh.data.vertices:
                    weight = next((g.weight for g in vertex.groups if g.group == idx), 0.0)
                    if weight > 0.5:
                        vertex.co = inverse @ (mesh.matrix_world @ vertex.co + world_delta)
            mesh.data.update()
        bpy.context.view_layer.update()
        pairs = build_pairs(source, target)
        actions = {item.name: item for item in _real_collect(source)}
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


rows = []
world = {}


def sole_lowest(mesh, foot_name):
    deps = bpy.context.evaluated_depsgraph_get()
    evaluated = mesh.evaluated_get(deps)
    posed = evaluated.to_mesh()
    matrix = evaluated.matrix_world
    group_index = {g.name: g.index for g in mesh.vertex_groups}
    overall = None
    sole = None
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


def bake_and_scan(config, action_name, floor_m=0.0, hand_ik=False, stack_on=True):
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
    settings = FootIKSettings(floor_enabled=True, floor_alpha=1.0, floor_height_m=floor_m)
    options = retarget.RetargetOptions(
        pairs=pairs, root_motion="KEEP", reference="REST",
        foot_ik=True, hand_ik=hand_ik, foot_ik_settings=settings,
        contact_min_knee_deg=15.0 if stack_on else 0.0,
        correction_smoothing="height" if stack_on else "",
    )
    retarget.bake_retarget(source, target, options)
    feedback = {(e[0], e[1]): e for e in ik_module.CONTACT_LOG}
    plan_size = len(ik_module._LAST_PLAN or {})
    for pose_bone in target.pose.bones:
        pose_bone.scale = (1.0, 1.0, 1.0)
    start, end = int(action.frame_range[0]), int(round(action.frame_range[1]))

    def head(name):
        return target.matrix_world @ target.pose.bones[name].head

    for frame in range(start, end + 1):
        bpy.context.scene.frame_set(frame)
        bpy.context.view_layer.update()
        row = {"config": config, "action": action_name, "frame": frame, "floor_m": floor_m,
               "plan_size": plan_size}
        row["pelvis"] = json.dumps([round(float(v), 6) for v in head(roles["hips"][1])])
        row["spine"] = json.dumps([round(float(v), 6) for v in head(roles["spine"][1])])
        row["head"] = json.dumps([round(float(v), 6) for v in head(roles["head"][1])])
        mesh_low = None
        for side in ("l", "r"):
            thigh = head(roles["thigh_" + side][1])
            knee = head(roles["shin_" + side][1])
            ankle = head(roles["foot_" + side][1])
            overall, sole = sole_lowest(mesh, roles["foot_" + side][1])
            mesh_low = overall if mesh_low is None else min(mesh_low, overall)
            first, second = thigh - knee, ankle - knee
            row[side + "_sole_rel_mm"] = round((sole - floor_m) * 1000.0, 3)
            row[side + "_sole_world_mm"] = round(sole * 1000.0, 3)
            row[side + "_ankle"] = json.dumps([round(float(v), 6) for v in ankle])
            row[side + "_knee_deg"] = round(math.degrees(first.angle(second)), 3)
            row[side + "_upper_len"] = round((knee - thigh).length, 6)
            row[side + "_lower_len"] = round((ankle - knee).length, 6)
            row[side + "_err_mm"] = round(solve_err.get((frame, "foot_" + side), 0.0) * 1000.0, 4)
            row[side + "_hand_err_mm"] = round(solve_err.get((frame, "hand_" + side), 0.0) * 1000.0, 4)
            speed = speed_log.get((frame, "foot_" + side), -1.0)
            row[side + "_speed"] = None if speed is None else round(float(speed), 4)
            row[side + "_contact"] = bool(0.0 <= float(speed) <= 0.15) if speed is not None else None
            entry = feedback.get((frame, "foot_" + side))
            row[side + "_recheck_raised_mm"] = None if entry is None else round(float(entry[6]) * 1000.0, 3)
            row[side + "_hand"] = json.dumps([round(float(v), 6) for v in head(roles["hand_" + side][1])])
        row["mesh_lowest_rel_mm"] = round((mesh_low - floor_m) * 1000.0, 3)
        rows.append(row)
    print("DONE", config, action_name, "frames", end - start + 1, "plan", plan_size, flush=True)


def main():
    if os.environ.get("GEN_SEG_ONLY"):
        world["data"] = load_world_full("SEG")
        bake_and_scan("SEG2", "a050_300000")
        with (OUT / "generalization_seg_frames.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        print("ROWS", len(rows), "DONE", flush=True)
        return
    # Proportions on a050_300000 (P0 is the unmodified imported target).
    for variant in ("P0", "P1", "P2", "SEG"):
        world["data"] = load_world_full(variant)
        bake_and_scan(variant, "a050_300000")
    # Floors and extra motion states on the baseline skeleton.
    world["data"] = load_world_full("P0")
    bake_and_scan("FLOOR_P50", "a050_300000", floor_m=0.05)
    bake_and_scan("FLOOR_M50", "a050_300000", floor_m=-0.05)
    for clip in EXTRA_CLIPS:
        bake_and_scan("CLIP", clip)
    bake_and_scan("STACK_ON", "a050_301000")
    bake_and_scan("STACK_OFF", "a050_301000", stack_on=False)
    bake_and_scan("HAND_ON", "a050_300000", hand_ik=True)
    with (OUT / "generalization_frames.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print("ROWS", len(rows), "DONE", flush=True)


if __name__ == "__main__":
    main()
