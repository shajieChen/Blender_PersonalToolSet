"""Bisect uncommitted fold flip vs Hand IK on real body.FBX / 突刺 glb assets.

Prints forearm_l metrics at frame 11 (screenshot) for:
  A) hand_ik on, fold correction on  (current uncommitted bake)
  B) hand_ik on, fold correction off
"""
from __future__ import annotations

import json
import math
import os
import sys
import traceback

import bpy
from mathutils import Vector

ROOT = r"H:\Blender_Plugin"
SOURCE = r"h:\SErsiko_ExtactedTool\output\c0000_突刺_wp_a_0300.glb"
TARGET = r"c:\Users\chenshajie1\Downloads\body.FBX"
OUT = r"H:\tmp\fold_vs_hand_ik_20261015\measurement.json"
FRAME = 11
ACTION = "a050_300000"


def _ensure():
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    from humanoid_retarget import pipeline, retarget
    return pipeline, retarget


def _polarity(tgt, roles):
    upper = tgt.pose.bones[roles["upperarm_l"]]
    mid = tgt.pose.bones[roles["forearm_l"]]
    end = tgt.pose.bones[roles["hand_l"]]
    rest_u = tgt.data.bones[roles["upperarm_l"]].head_local
    rest_m = tgt.data.bones[roles["forearm_l"]].head_local
    rest_e = tgt.data.bones[roles["hand_l"]].head_local
    rest_pole = (rest_m - rest_u).cross(rest_e - rest_m)
    posed = (mid.head - upper.head).cross(end.head - mid.head)
    delta = upper.matrix.to_3x3() @ upper.bone.matrix_local.to_3x3().inverted()
    preferred = delta @ rest_pole
    pol = posed.dot(preferred) if preferred.length_squared > 1e-12 and posed.length_squared > 1e-12 else None
    local = mid.matrix_basis.to_quaternion().normalized()
    _swing, twist = local.to_swing_twist("Y")
    # binormal proxy: posed bone local Z in armature space
    z_axis = mid.matrix.to_3x3() @ Vector((0.0, 0.0, 1.0))
    rest_z = mid.bone.matrix_local.to_3x3() @ Vector((0.0, 0.0, 1.0))
    upper_delta = upper.matrix.to_3x3() @ upper.bone.matrix_local.to_3x3().inverted()
    expected_z = upper_delta @ rest_z
    return {
        "fold_angle_deg": round(math.degrees(
            math.acos(max(-1.0, min(1.0, (upper.head - mid.head).normalized().dot((end.head - mid.head).normalized()))))
        ), 3),
        "polarity": None if pol is None else round(pol, 3),
        "opposed": bool(pol is not None and pol < 0.0),
        "twist_y_deg": round(math.degrees(twist), 3),
        "binormal_dot": round(z_axis.normalized().dot(expected_z.normalized()), 6),
        "quat": [round(v, 6) for v in mid.rotation_quaternion],
    }


def _bake(pipeline, retarget, fold_on: bool):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    source, _ = pipeline.load_source(SOURCE)
    from humanoid_retarget.retarget import collect_actions
    action = next(a for a in collect_actions(source) if ACTION in a.name)
    source.animation_data_create()
    source.animation_data.action = action
    source.animation_data.use_nla = False
    options = retarget.RetargetOptions(
        reference="REST",
        root_motion="KEEP",
        foot_ik=True,
        hand_ik=True,
        soft_repulsion=False,
        joint_limits=False,
    )
    original = retarget.correct_limb_fold_directions
    if not fold_on:
        retarget.correct_limb_fold_directions = lambda *_a, **_k: None
    try:
        tgt, summary, _baked, _auto = pipeline.load_target_and_retarget(
            TARGET, source, options
        )
    finally:
        retarget.correct_limb_fold_directions = original
    roles = {role: name for role, _s, name in (options.resolved_pairs or [])}
    bpy.context.scene.frame_set(FRAME)
    bpy.context.view_layer.update()
    return {
        "fold_on": fold_on,
        "summary_ik": [line for line in summary.splitlines() if line.startswith("IK:")],
        "forearm_l": _polarity(tgt, roles),
    }


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    pipeline, retarget = _ensure()
    report = {"frame": FRAME, "ok": False}
    try:
        report["with_fold"] = _bake(pipeline, retarget, True)
        report["without_fold"] = _bake(pipeline, retarget, False)
        report["ok"] = True
    except Exception as exc:
        report["error"] = str(exc)
        report["traceback"] = traceback.format_exc()
    with open(OUT, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    print("OUT", OUT)
    if report.get("ok"):
        a = report["with_fold"]["forearm_l"]
        b = report["without_fold"]["forearm_l"]
        print("WITH_FOLD", a)
        print("WITHOUT_FOLD", b)
        print("MEASURE_OK")
        return 0
    print(report.get("traceback", report.get("error")))
    print("MEASURE_FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
