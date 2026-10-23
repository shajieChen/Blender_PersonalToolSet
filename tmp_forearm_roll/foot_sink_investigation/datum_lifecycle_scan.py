"""Datum lifecycle + uncovered-path validation (candidate only)."""
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix

sys.path.insert(0, r"H:\Blender_Plugin\tmp_forearm_roll\foot_sink_investigation")
import datum_fix_scan as base

retarget = base.retarget
pipeline = base.pipeline
ik_module = base.ik_module
OUT = base.OUT
matrices = {}


def record(config):
    source, target, _mesh, _pairs, _actions = base.world["data"]
    matrices[config] = {
        "target": [list(row) for row in target.matrix_world],
        "source": [list(row) for row in source.matrix_world],
    }


def try_bake(config, clip, floor, mode="REST"):
    record(config)
    try:
        base.bake_and_scan(config, clip, floor, mode=mode)
        print("BAKE_OK", config, flush=True)
    except Exception as exc:  # recorded, not hidden
        print("BAKE_ERROR", config, type(exc).__name__, str(exc)[:240], flush=True)


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


def main():
    # L1: translate only (x/y/z) after registration
    base.world["data"] = base.load_world()
    source, target, _m, _p, _a = base.world["data"]
    target.location.x += 0.03
    target.location.y -= 0.02
    target.location.z += 0.05
    bpy.context.view_layer.update()
    try_bake("LTRANS", "a050_300000", 0.0)

    # L2: yaw 30 deg after registration
    base.world["data"] = base.load_world()
    source, target, _m, _p, _a = base.world["data"]
    rotate_about_origin(target, "Z", 30.0)
    try_bake("LYAW", "a050_300000", 0.0)
    try_bake("LYAWFM", "a050_300000", -0.05)

    # L3: tilt 20 deg about X after registration
    base.world["data"] = base.load_world()
    source, target, _m, _p, _a = base.world["data"]
    rotate_about_origin(target, "X", 20.0)
    try_bake("LTILT", "a050_300000", 0.0)

    # L4: uniform scale +20% after registration (stale datum expected)
    base.world["data"] = base.load_world()
    source, target, _m, _p, _a = base.world["data"]
    target.scale = (0.012, 0.012, 0.012)
    bpy.context.view_layer.update()
    try_bake("LSCALE", "a050_300000", 0.0)
    try_bake("LSCALEFM", "a050_300000", -0.05)
    # L5: re-capture datum after the scale change, then bake again
    result = retarget.capture_ground_datum(target)
    print("RECapture_AFTER_SCALE", None if result is None else result["meters_per_unit"], flush=True)
    try_bake("LSCALEFIX", "a050_300000", 0.0)

    # L6: non-uniform scale (MotionSpace must reject explicitly)
    base.world["data"] = base.load_world()
    source, target, _m, _p, _a = base.world["data"]
    target.scale = (0.01, 0.013, 0.01)
    bpy.context.view_layer.update()
    try_bake("LNONUNIFORM", "a050_300000", 0.0)

    # L7: corrupt / unparseable datum (target side; source stays valid)
    corrupt = [
        ("LCORRUPT1", "garbage"),
        ("LCORRUPT2", "{}"),
        ("LCORRUPT3", '{"matrix": [[1,0,0,0]], "sole": [0,0,0], "meters_per_unit": 1.0}'),
        ("LCORRUPT4", '{"matrix": [[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]], "sole": [0,0,0], "meters_per_unit": "x"}'),
        ("LWRONG", '{"matrix": [[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]], "sole": [0,0,0], "meters_per_unit": 1.0}'),
    ]
    base.world["data"] = base.load_world()
    source, target, _m, _p, _a = base.world["data"]
    for config, raw in corrupt:
        target["hr_ground_datum"] = raw
        try_bake(config, "a050_300000", -0.05)

    # L8: true no-skin capture (meshes removed before capture)
    base.world["data"] = base.load_world()
    source, target, mesh, _p, _a = base.world["data"]
    for obj in list(bpy.data.objects):
        if obj.type == "MESH" and obj.parent == target:
            bpy.data.objects.remove(obj, do_unlink=True)
    if "hr_ground_datum" in target:
        del target["hr_ground_datum"]
    result = retarget.capture_ground_datum(target)
    print("TRUE_NOSKIN_CAPTURE", result, "hr_ground_datum" in target, flush=True)

    # P1: pose-channel path (joint_limits triggers channel_state), datum off
    base.world["data"] = base.load_world()
    orig_options = retarget.RetargetOptions
    retarget.RetargetOptions = lambda **kw: orig_options(**{**kw, "joint_limits": True})
    try:
        try_bake("CHAN0", "a050_300000", 0.0)
        try_bake("CHANFM", "a050_300000", -0.05)
    finally:
        retarget.RetargetOptions = orig_options

    # P2: Rigify metarig hop path
    base.world["data"] = base.load_world()
    source, target, mesh, pairs, actions = base.world["data"]
    base.reset_pose(target)
    base.holder["action"] = actions["a050_300000"]
    retarget.collect_actions = base.real_collect
    try:
        options = retarget.RetargetOptions(
            pairs=pairs, root_motion="KEEP", reference="REST",
            foot_ik=True, hand_ik=False, standard_skeleton="RIGIFY_HUMAN_METARIG",
            foot_ik_settings=base.FootIKSettings(floor_enabled=True, floor_alpha=1.0, floor_height_m=-0.05),
            contact_min_knee_deg=15.0, correction_smoothing="height",
        )
        report, baked = pipeline.retarget_existing(source, target, options)
        print("RIGIFY_OK", str(report)[:200], flush=True)
        # measure the baked result with the core scan's row logic
        base.world["data"] = (source, target, mesh, pairs, actions)
        roles = {role: (s, t) for role, s, t in pairs}
        for pose_bone in target.pose.bones:
            pose_bone.scale = (1.0, 1.0, 1.0)
        def head(name):
            return target.matrix_world @ target.pose.bones[name].head
        for frame in range(0, 53):
            bpy.context.scene.frame_set(frame)
            bpy.context.view_layer.update()
            row = {"config": "RIGIFY_FM", "action": "a050_300000", "frame": frame,
                   "floor_m": -0.05, "mode": "RIGIFY", "plan_size": 0}
            row["pelvis"] = json.dumps([round(float(v), 6) for v in head(roles["hips"][1])])
            row["head"] = json.dumps([round(float(v), 6) for v in head(roles["head"][1])])
            row["l_hand"] = row["r_hand"] = None
            row["src_hips_world_z_mm"] = None
            row["src_datum_hips_mm"] = None
            mesh_low = None
            for side in ("l", "r"):
                thigh = head(roles["thigh_" + side][1])
                knee = head(roles["shin_" + side][1])
                ankle = head(roles["foot_" + side][1])
                overall, sole = base.sole_lowest(mesh, roles["foot_" + side][1])
                mesh_low = overall if mesh_low is None else min(mesh_low, overall)
                first, second = thigh - knee, ankle - knee
                row[side + "_sole_world_mm"] = round(sole * 1000.0, 3)
                row[side + "_sole_rel_mm"] = round((sole + 0.05) * 1000.0, 3)
                row[side + "_ankle"] = json.dumps([round(float(v), 6) for v in ankle])
                row[side + "_knee_deg"] = round(math.degrees(first.angle(second)), 3)
                row[side + "_upper_len"] = round((knee - thigh).length, 6)
                row[side + "_lower_len"] = round((ankle - knee).length, 6)
                row[side + "_err_mm"] = 0.0
                row[side + "_contact"] = False
                row[side + "_recheck_raised_mm"] = None
                row[side + "_log_lowest_rel_mm"] = None
            row["mesh_lowest_world_mm"] = round(mesh_low * 1000.0, 3)
            base.rows.append(row)
    except Exception as exc:
        print("RIGIFY_ERROR", type(exc).__name__, str(exc)[:240], flush=True)
    finally:
        retarget.collect_actions = lambda _src: [base.holder["action"]]

    with (OUT / "datum_lifecycle_frames.csv").open("w", newline="", encoding="utf-8") as handle:
        import csv
        writer = csv.DictWriter(handle, fieldnames=list(base.rows[0].keys()))
        writer.writeheader()
        writer.writerows(base.rows)
    (OUT / "datum_lifecycle_matrices.json").write_text(json.dumps(matrices, indent=1), encoding="utf-8")
    print("ROWS", len(base.rows), "DONE", flush=True)


if __name__ == "__main__":
    main()
