import csv
import json
from pathlib import Path

p = Path(r"H:\Blender_Plugin\tmp_forearm_roll\foot_sink_investigation")
rows = list(csv.DictReader(open(p / "calf_roll_endpoint_frames.csv", encoding="utf-8")))
idx = {(r["config"], r["action"], int(r["frame"])): r for r in rows}


def dist(a, b):
    left = json.loads(a)
    right = json.loads(b)
    return (sum((x - y) ** 2 for x, y in zip(left, right)) ** 0.5) * 1000.0


focus = {
    "a050_300000": [15, 16],
    "a050_302011": [9, 10],
    "a050_300010": list(range(0, 13)),
}
print("=== focus frames ===")
for act, frames in focus.items():
    print("---", act)
    for frame in frames:
        a = idx[("A_base", act, frame)]
        b = idx[("B_final", act, frame)]
        c = idx[("C_lock", act, frame)]
        print(
            "f", frame,
            "rollA", a["l_roll"], a["r_roll"],
            "rollB", b["l_roll"], b["r_roll"],
            "rollC", c["l_roll"], c["r_roll"],
        )
        print(
            "  fbL", a["l_feedback"], b["l_feedback"], c["l_feedback"],
            "fbR", a["r_feedback"], b["r_feedback"], c["r_feedback"],
            "raisedL", a["l_raised_mm"], b["l_raised_mm"], c["l_raised_mm"],
        )
        print(
            "  kneeL AB/AC", round(dist(a["l_knee"], b["l_knee"]), 3), round(dist(a["l_knee"], c["l_knee"]), 3),
            "ankleL AB/AC", round(dist(a["l_ankle"], b["l_ankle"]), 3), round(dist(a["l_ankle"], c["l_ankle"]), 3),
            "kneeR AB/AC", round(dist(a["r_knee"], b["r_knee"]), 3), round(dist(a["r_knee"], c["r_knee"]), 3),
            "ankleR AB/AC", round(dist(a["r_ankle"], b["r_ankle"]), 3), round(dist(a["r_ankle"], c["r_ankle"]), 3),
        )
        print(
            "  lenL", a["l_lower_len"], b["l_lower_len"], c["l_lower_len"],
            "lenR", a["r_lower_len"], b["r_lower_len"], c["r_lower_len"],
            "kdegL", a["l_knee_deg"], b["l_knee_deg"], c["l_knee_deg"],
        )
        print(
            "  hips", a["hips_z"], b["hips_z"], c["hips_z"],
            "mesh", a["mesh_lowest"], b["mesh_lowest"], c["mesh_lowest"],
            "z01", a["n_z_lt_001"], b["n_z_lt_001"], c["n_z_lt_001"],
        )
        print("  planL", a["l_plan"], "|", b["l_plan"], "|", c["l_plan"])

print("=== endpoint lock samples ===")
el = list(csv.DictReader(open(p / "calf_roll_endpoint_lock.csv", encoding="utf-8")))
for action in ("a050_300000", "a050_300010", "a050_302011"):
    subset = [r for r in el if r["config"] == "C_lock" and r["action"] == action and r["stage"] == "drift"]
    if not subset:
        continue
    worst_ankle = max(subset, key=lambda r: abs(float(r["ankle_mm"])))
    worst_knee = max(subset, key=lambda r: abs(float(r["knee_mm"])))
    print(action, "n", len(subset), "worst_ankle", worst_ankle["frame"], worst_ankle["role"], worst_ankle["ankle_mm"], "knee", worst_knee["knee_mm"], "boney", worst_ankle["bone_y_deg"])

print("--- C 300010 f1-12 foot_l ---")
for r in el:
    if r["config"] == "C_lock" and r["action"] == "a050_300010" and r["role"] == "foot_l" and int(r["frame"]) <= 12:
        print(r["frame"], r["stage"], r["knee_mm"], r["ankle_mm"], r["length_mm"], r["pre_length_mm"], r["chain_deg"], r["roll_deg"])

print("=== frame 6 trace left foot bake ===")
tr = list(csv.DictReader(open(p / "calf_roll_hand_trace.csv", encoding="utf-8")))
for r in tr:
    if r["action"] == "a050_300000" and r["phase"] == "bake" and r["role"] in ("foot_l", "hand_l") and r["frame"] in ("5", "6", "7"):
        if r["config"] in ("A_base", "H_hand", "H_both_off", "H_both_final", "H_both_lock"):
            print(
                r["config"], "f", r["frame"], r["role"], "seq", r["seq"],
                "knee_move", r["knee_move_mm"], "ankle_move", r["ankle_move_mm"],
                "hips_move", r["hips_move_mm"], "err", r["err_mm"],
            )
            print("  knee_b", r["knee_before"])
            print("  knee_a", r["knee_after"])
            print("  ankle_a", r["ankle_after"])
            print("  goal", r["goal"])
            print("  pole", r["pole"])
            print("  hips_a", r["hips_after"])
