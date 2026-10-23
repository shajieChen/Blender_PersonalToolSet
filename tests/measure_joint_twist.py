"""Scientific bake measurement: glb animation -> body.FBX target.

Reports per-frame elbow/knee fold polarity vs bind, chain fold angle, and
forearm local twist proxy. Runs with current plugin code (includes fold flip).
Also reports a no-flip counterfactual by replaying FK without fold correction.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sys
import traceback

import bpy
from mathutils import Matrix, Vector

ROOT = r"H:\Blender_Plugin"
SOURCE = r"h:\SErsiko_ExtactedTool\output\c0000_突刺_wp_a_0300.glb"
TARGET = r"c:\Users\chenshajie1\Downloads\body.FBX"
OUT_DIR = r"H:\tmp\joint_twist_measure_20261015"
SAMPLE_FRAMES = (1, 18, 20, 37, 52)
PREFERRED_ACTION = "a050_300000"


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest().upper()


def _rot3(matrix) -> Matrix:
    return matrix.to_3x3()


def _fold_pole(a: Vector, b: Vector, c: Vector) -> Vector:
    return (b - a).cross(c - b)


def _fold_angle_deg(a: Vector, b: Vector, c: Vector) -> float:
    ab = (a - b).normalized()
    cb = (c - b).normalized()
    value = max(-1.0, min(1.0, ab.dot(cb)))
    return math.degrees(math.acos(value))


def _ensure_plugin():
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    import humanoid_retarget  # noqa: F401
    from humanoid_retarget import pipeline, retarget

    return pipeline, retarget


def _pick_action(source):
    from humanoid_retarget.retarget import collect_actions

    actions = collect_actions(source)
    for action in actions:
        if PREFERRED_ACTION in action.name:
            return action
    return actions[0] if actions else None


def _measure_chain(tgt, roles, upper_role, mid_role, end_role):
    if not all(role in roles for role in (upper_role, mid_role, end_role)):
        return None
    upper_name = roles[upper_role]
    mid_name = roles[mid_role]
    end_name = roles[end_role]
    rest_u = tgt.data.bones[upper_name].head_local
    rest_m = tgt.data.bones[mid_name].head_local
    rest_e = tgt.data.bones[end_name].head_local
    rest_pole = _fold_pole(rest_u, rest_m, rest_e)
    upper = tgt.pose.bones[upper_name]
    mid = tgt.pose.bones[mid_name]
    end = tgt.pose.bones[end_name]
    posed_pole = _fold_pole(upper.head, mid.head, end.head)
    upper_delta = _rot3(upper.matrix) @ _rot3(upper.bone.matrix_local).inverted()
    preferred = upper_delta @ rest_pole if rest_pole.length_squared > 1e-12 else Vector((0, 0, 0))
    polarity = None
    if preferred.length_squared > 1e-12 and posed_pole.length_squared > 1e-12:
        polarity = posed_pole.dot(preferred)
    mid_q = tuple(round(v, 6) for v in mid.rotation_quaternion)
    # twist proxy: mid local rotation about its bone Y after removing swing to child
    local = mid.matrix_basis.to_quaternion().normalized()
    swing, twist = local.to_swing_twist("Y")
    return {
        "roles": [upper_role, mid_role, end_role],
        "bones": [upper_name, mid_name, end_name],
        "fold_angle_deg": round(_fold_angle_deg(upper.head, mid.head, end.head), 3),
        "rest_pole_len": round(rest_pole.length, 6),
        "posed_pole_len": round(posed_pole.length, 6),
        "polarity": None if polarity is None else round(polarity, 6),
        "opposed_to_bind": bool(polarity is not None and polarity < 0.0),
        "mid_local_quat": mid_q,
        "mid_twist_y_deg": round(math.degrees(twist), 3),
        "mid_swing_angle_deg": round(math.degrees(swing.angle), 3),
    }


def _sample(tgt, roles, frame: int):
    bpy.context.scene.frame_set(frame)
    bpy.context.view_layer.update()
    chains = {}
    for upper, mid, end in (
        ("upperarm_l", "forearm_l", "hand_l"),
        ("upperarm_r", "forearm_r", "hand_r"),
        ("thigh_l", "shin_l", "foot_l"),
        ("thigh_r", "shin_r", "foot_r"),
    ):
        measured = _measure_chain(tgt, roles, upper, mid, end)
        if measured is not None:
            chains[mid] = measured
    return {"frame": frame, "chains": chains}


def _bake_once(pipeline, retarget, with_fold: bool):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    source, _actions = pipeline.load_source(SOURCE)
    action = _pick_action(source)
    if action is None:
        raise RuntimeError("no source action")
    source.animation_data_create()
    source.animation_data.action = action
    source.animation_data.use_nla = False

    options = retarget.RetargetOptions(
        reference="REST",
        root_motion="KEEP",
        foot_ik=False,
        hand_ik=False,
        soft_repulsion=False,
        joint_limits=False,
    )

    original = retarget.correct_limb_fold_directions
    if not with_fold:
        retarget.correct_limb_fold_directions = lambda tgt, roles: None
    try:
        armature, summary, baked, auto = pipeline.load_target_and_retarget(
            TARGET, source, options
        )
    finally:
        retarget.correct_limb_fold_directions = original

    pairs = options.resolved_pairs or []
    roles = {role: name for role, _src, name in pairs}
    samples = [_sample(armature, roles, frame) for frame in SAMPLE_FRAMES]
    opposed = []
    for sample in samples:
        for mid, data in sample["chains"].items():
            if data["opposed_to_bind"]:
                opposed.append({"frame": sample["frame"], "mid": mid, **data})
    return {
        "with_fold_correction": with_fold,
        "source_name": source.name,
        "target_name": armature.name,
        "auto_rig": auto,
        "summary": summary,
        "action": action.name,
        "baked": [item.name for item in baked],
        "roles": roles,
        "samples": samples,
        "opposed_count": len(opposed),
        "opposed": opposed,
    }


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    pipeline, retarget = _ensure_plugin()
    report = {
        "blender": bpy.app.version_string,
        "build": bpy.app.build_hash.decode("utf-8", "ignore")
        if isinstance(bpy.app.build_hash, (bytes, bytearray))
        else str(bpy.app.build_hash),
        "source": SOURCE,
        "target": TARGET,
        "source_sha256": _sha256(SOURCE),
        "target_sha256": _sha256(TARGET),
        "sample_frames": list(SAMPLE_FRAMES),
        "note": "Source=animation glb, Target=body.FBX (matches prior pretzel study).",
        "blender_mcp": "unavailable_in_session; used_headless_bpy",
    }
    try:
        report["baseline_no_fold"] = _bake_once(pipeline, retarget, with_fold=False)
        report["current_with_fold"] = _bake_once(pipeline, retarget, with_fold=True)
        report["ok"] = True
    except Exception as exc:
        report["ok"] = False
        report["error"] = str(exc)
        report["traceback"] = traceback.format_exc()

    out_path = os.path.join(OUT_DIR, "measurement.json")
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    print("MEASURE_OUT", out_path)
    print("MEASURE_OK" if report.get("ok") else "MEASURE_FAIL")
    if report.get("ok"):
        print(
            "OPPOSED_NO_FOLD",
            report["baseline_no_fold"]["opposed_count"],
            "OPPOSED_WITH_FOLD",
            report["current_with_fold"]["opposed_count"],
        )
    else:
        print(report.get("traceback", report.get("error")))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
