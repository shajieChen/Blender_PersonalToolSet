"""Measure frame-11 left forearm fold after bind-side pole fix (Hand IK on)."""
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
OUT = r"H:\tmp\hand_ik_pole_fix_20261015\measurement.json"
FRAME = 11
ACTION = "a050_300000"


def main():
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    from humanoid_retarget import pipeline, retarget
    from humanoid_retarget.retarget import collect_actions

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    source, _ = pipeline.load_source(SOURCE)
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
    tgt, summary, _baked, _auto = pipeline.load_target_and_retarget(
        TARGET, source, options
    )
    roles = {role: name for role, _s, name in (options.resolved_pairs or [])}
    bpy.context.scene.frame_set(FRAME)
    bpy.context.view_layer.update()
    upper = tgt.pose.bones[roles["upperarm_l"]]
    mid = tgt.pose.bones[roles["forearm_l"]]
    end = tgt.pose.bones[roles["hand_l"]]
    world = tgt.matrix_world
    upper_h = world @ upper.head
    mid_h = world @ mid.head
    end_h = world @ end.head
    rest_u = world @ tgt.data.bones[roles["upperarm_l"]].head_local
    rest_m = world @ tgt.data.bones[roles["forearm_l"]].head_local
    rest_e = world @ tgt.data.bones[roles["hand_l"]].head_local
    rest_pole = (rest_m - rest_u).cross(rest_e - rest_m)
    posed = (mid_h - upper_h).cross(end_h - mid_h)
    delta = upper.matrix.to_3x3() @ upper.bone.matrix_local.to_3x3().inverted()
    preferred = delta @ rest_pole
    pol = (
        posed.dot(preferred)
        if preferred.length_squared > 1e-12 and posed.length_squared > 1e-12
        else None
    )
    rest_dir = (rest_e - rest_u).normalized()
    cur_dir = (end_h - upper_h).normalized()
    rest_perp = (rest_m - rest_u) - rest_dir * (rest_m - rest_u).dot(rest_dir)
    mid_perp = (mid_h - upper_h) - cur_dir * (mid_h - upper_h).dot(cur_dir)
    chord_preferred = rest_dir.rotation_difference(cur_dir) @ rest_perp
    chord_dot = (
        mid_perp.dot(chord_preferred)
        if mid_perp.length_squared > 1e-12 and chord_preferred.length_squared > 1e-12
        else None
    )
    local = mid.matrix_basis.to_quaternion().normalized()
    _swing, twist = local.to_swing_twist("Y")
    forearm_l = {
        "triangle_polarity": None if pol is None else round(pol, 3),
        "triangle_opposed": bool(pol is not None and pol < 0.0),
        "chord_dot": None if chord_dot is None else round(chord_dot, 3),
        "chord_opposed": bool(chord_dot is not None and chord_dot < -1e-6),
        "rest_perp_len": round(rest_perp.length, 6),
        "mid_perp_len": round(mid_perp.length, 6),
        "twist_y_deg": round(math.degrees(twist), 3),
        "quat": [round(v, 6) for v in mid.rotation_quaternion],
    }
    report = {
        "frame": FRAME,
        "summary_ik": [line for line in summary.splitlines() if line.startswith("IK:")],
        "forearm_l": forearm_l,
        "baseline_triangle_opposed": True,
        "baseline_quat": [0.514327, -0.673108, -0.190779, 0.495978],
    }
    with open(OUT, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    print(json.dumps(forearm_l, ensure_ascii=False))
    # Triangle fold vs bind is the pretzel metric used in earlier bisects.
    # Chord_dot ~0 with finite mid_perp means the offset is nearly orthogonal
    # to the preferred axis, not a reverse fold.
    ok = not forearm_l["triangle_opposed"]
    print("MEASURE_OK" if ok else "MEASURE_STILL_OPPOSED")
    return 0 if ok else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
