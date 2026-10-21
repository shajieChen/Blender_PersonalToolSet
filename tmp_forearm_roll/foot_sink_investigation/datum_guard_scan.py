"""B1/B2 guard validation for the datum candidate (never the installed addon)."""
import csv
import hashlib
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix

CANDIDATE_ROOT = Path(r"H:\Blender_Plugin\tmp_forearm_roll\floor_candidate_root")
OUT = Path(r"H:\Blender_Plugin\tmp_forearm_roll\foot_sink_investigation")
sys.path.insert(0, str(CANDIDATE_ROOT))
for name in list(sys.modules):
    if name == "humanoid_retarget" or name.startswith("humanoid_retarget."):
        del sys.modules[name]

import humanoid_retarget
import humanoid_retarget.ik as ik_module
import humanoid_retarget.retarget as retarget
import humanoid_retarget.foot_ik as foot_ik_module
import humanoid_retarget.pipeline as pipeline_module
from humanoid_retarget.foot_ik import FootIKSettings
from humanoid_retarget.mapping import build_pairs
from humanoid_retarget import pipeline

module_file = Path(humanoid_retarget.__file__).resolve()
assert str(module_file).lower().startswith(str(CANDIDATE_ROOT.resolve()).lower()), module_file
for mod, expect in (
    (ik_module, "510331A44DF47D67DEB1CE5E88C0E214734B13ADEFBF5FC49790E81C48E135FB"),
    (foot_ik_module, "E10538A060FF90DB034C19A3B10323855BA8EB14B33D8F997C42943D5036A3CD"),
    (retarget, "40B95B68D864B66DB80E57083305F7A9CDA8F7B893336C265E659D277BC0F9DA"),
    (pipeline_module, "404D58C2B0B118EB05277C3FD3C4D59C41F3B7D4F21295D4C0908A23104D8368"),
):
    digest = hashlib.sha256(Path(mod.__file__).read_bytes()).hexdigest().upper()
    print("CANDIDATE_FILE", Path(mod.__file__).name, digest, flush=True)
    assert digest == expect, (mod.__file__, digest)
print("CANDIDATE", module_file, humanoid_retarget.bl_info["version"], flush=True)

SOURCE = r"h:\SErsiko_ExtactedTool\output\c0000_突刺_wp_a_0300.glb"
TARGET = r"c:\Users\chenshajie1\Downloads\body.FBX"

real_collect = retarget.collect_actions
holder = {"action": None}
retarget.collect_actions = lambda _src: [holder["action"]]
solve_err = {}
speed_log = {}
real_solve = ik_module._solve_chain
real_apply = retarget.apply_contact_ik
real_prepare = retarget._prepare_retarget_geometry


def recording_solve(tgt, space, reference, goal, pole_hint=None):
    distance = real_solve(tgt, space, reference, goal, pole_hint=pole_hint)
    solve_err[(bpy.context.scene.frame_current, reference.roles[2])] = float(distance)
    return distance


def recording_apply(src, tgt, geometry, settings, states, speeds, pelvis_delta, dt):
    for role, value in (speeds or {}).items():
        speed_log[(bpy.context.scene.frame_current, role)] = float(value)
    return real_apply(src, tgt, geometry, settings, states, speeds, pelvis_delta, dt)


def logging_prepare(*args, **kwargs):
    geometry = real_prepare(*args, **kwargs)
    pelvis = geometry.pelvis
    print(
        "GEOMETRY src_datum_mm",
        None if pelvis.source_datum_height is None else round(pelvis.source_datum_height * 1000.0, 3),
        "tgt_datum_mm",
        None if pelvis.target_datum_height is None else round(pelvis.target_datum_height * 1000.0, 3),
        "height_offsets_mm", [round(limb.height_offset * 1000.0, 3) for limb in geometry.limbs],
        flush=True,
    )
    return geometry


ik_module._solve_chain = recording_solve
retarget.apply_contact_ik = recording_apply
retarget._prepare_retarget_geometry = logging_prepare
rows = []
world = {}


def load_world():
    retarget.collect_actions = real_collect
    bpy.ops.wm.read_factory_settings(use_empty=True)
    try:
        source, _ = pipeline.load_source(SOURCE)
        objects, _ = pipeline.import_model(TARGET)
        target = pipeline.pick_armature(objects)
        mesh = next(obj for obj in bpy.data.objects if obj.type == "MESH" and obj.parent == target)
        print("DATUM_PROPS", "source", "hr_ground_datum" in source,
              "target", "hr_ground_datum" in target, flush=True)
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
    print("BAKE", config, action_name, "floor", floor_m, flush=True)
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
               "mode": "REST", "plan_size": plan_size}
        row["pelvis"] = json.dumps([round(float(v), 6) for v in head(roles["hips"][1])])
        row["head"] = json.dumps([round(float(v), 6) for v in head(roles["head"][1])])
        for side in ("l", "r"):
            hand_role = "hand_" + side
            row[side + "_hand"] = (
                json.dumps([round(float(v), 6) for v in head(roles[hand_role][1])])
                if hand_role in roles else None
            )
        row["src_hips_world_z_mm"] = None
        row["src_datum_hips_mm"] = None
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


def try_bake(config, clip, floor):
    try:
        bake_and_scan(config, clip, floor)
        print("BAKE_OK", config, flush=True)
    except Exception as exc:  # recorded, not hidden
        print("BAKE_ERROR", config, type(exc).__name__, str(exc)[:300], flush=True)


def rotate_about_origin(obj, axis, degrees):
    mw = obj.matrix_world.copy()
    origin = mw.translation.copy()
    rot = (
        Matrix.Translation(origin)
        @ Matrix.Rotation(math.radians(degrees), 4, axis)
        @ Matrix.Translation(-origin)
    )
    obj.matrix_world = rot @ mw
    bpy.context.view_layer.update()


FORGED = '{"matrix": [[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]], "sole": [0,0,0], "meters_per_unit": 1.0}'
BAD_TARGET = [
    ("GARBAGE_FM", "garbage"),
    ("EMPTY_FM", "{}"),
    ("RAGGED_FM", '{"matrix": [[1,0,0,0]], "sole": [0,0,0], "meters_per_unit": 1.0}'),
    ("STRSCALE_FM", '{"matrix": [[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]], "sole": [0,0,0], "meters_per_unit": "x"}'),
    ("NAN_FM", '{"matrix": [[NaN,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]], "sole": [0,0,0], "meters_per_unit": 1.0}'),
    ("FORGED_TGT_FM", FORGED),
]


def main():
    # B1-1: legal datum
    world["data"] = load_world()
    try_bake("LEGAL_FP", "a050_300000", 0.05)
    try_bake("LEGAL_FM", "a050_300000", -0.05)

    # B1-2/3/4/5: missing, corrupt, forged, single-side (target), forged source
    world["data"] = load_world()
    source, target, _m, _p, _a = world["data"]
    src_raw = source["hr_ground_datum"]
    tgt_raw = target["hr_ground_datum"]
    for obj in (source, target):
        del obj["hr_ground_datum"]
    try_bake("MISSING_F0", "a050_300000", 0.0)
    try_bake("MISSING_FM", "a050_300000", -0.05)
    source["hr_ground_datum"] = src_raw
    try_bake("ONESIDE_FM", "a050_300000", -0.05)  # target still missing
    for config, raw in BAD_TARGET:
        target["hr_ground_datum"] = raw
        try_bake(config, "a050_300000", -0.05)
    target["hr_ground_datum"] = tgt_raw
    source["hr_ground_datum"] = FORGED
    try_bake("FORGED_SRC_FM", "a050_300000", -0.05)
    source["hr_ground_datum"] = src_raw

    # B1-6: post-registration translation and yaw must stay valid
    world["data"] = load_world()
    source, target, _m, _p, _a = world["data"]
    target.location.z += 0.05
    bpy.context.view_layer.update()
    try_bake("TRANSL_F0", "a050_300000", 0.0)
    try_bake("TRANSL_FM", "a050_300000", -0.05)
    world["data"] = load_world()
    source, target, _m, _p, _a = world["data"]
    rotate_about_origin(target, "Z", 30.0)
    try_bake("YAW_F0", "a050_300000", 0.0)
    try_bake("YAW_FM", "a050_300000", -0.05)

    # B2: pose-channel path at floors 0 / +0.05 / -0.05
    world["data"] = load_world()
    orig_options = retarget.RetargetOptions
    retarget.RetargetOptions = lambda **kw: orig_options(**{**kw, "joint_limits": True})
    try:
        try_bake("CHAN0", "a050_300000", 0.0)
        try_bake("CHANFP", "a050_300000", 0.05)
        try_bake("CHANFM", "a050_300000", -0.05)
    finally:
        retarget.RetargetOptions = orig_options

    with (OUT / "datum_guard_frames.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print("ROWS", len(rows), "DONE", flush=True)


if __name__ == "__main__":
    main()
