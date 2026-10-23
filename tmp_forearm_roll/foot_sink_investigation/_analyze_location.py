import csv
import json
from pathlib import Path

p = Path(r"H:\Blender_Plugin\tmp_forearm_roll\foot_sink_investigation")
rows = list(csv.DictReader(open(p / "calf_parent_location_frames.csv", encoding="utf-8")))
verts = list(csv.DictReader(open(p / "calf_parent_location_vertices.csv", encoding="utf-8")))


def dist(a, b):
    left = json.loads(a)
    right = json.loads(b)
    return (sum((x - y) ** 2 for x, y in zip(left, right)) ** 0.5) * 1000.0


base = {(r["config"], r["action"], int(r["frame"])): r for r in rows if r["channel"] == "baseline"}

print("=== A vs C baseline ===")
for action, frames in (("a050_300010", range(4, 13)), ("a050_300000", range(9, 17))):
    print("---", action)
    for frame in frames:
        a = base[("A_base", action, frame)]
        c = base[("C_lock", action, frame)]
        print(
            frame,
            "mesh", a["mesh_lowest"], c["mesh_lowest"],
            "dz", round((float(c["mesh_lowest"]) - float(a["mesh_lowest"])) * 1000.0, 3),
            "n0", a["n_z_lt_0"], c["n_z_lt_0"],
            "n01", a["n_z_lt_001"], c["n_z_lt_001"],
            "depth", c["penetration_mm"],
            "rollL", a["l_roll"], c["l_roll"],
            "rollR", a["r_roll"], c["r_roll"],
            "kneeL", round(dist(a["l_knee"], c["l_knee"]), 3),
            "ankleL", round(dist(a["l_ankle"], c["l_ankle"]), 3),
            "kneeR", round(dist(a["r_knee"], c["r_knee"]), 3),
            "ankleR", round(dist(a["r_ankle"], c["r_ankle"]), 3),
            "lenL", a["l_lower_len"], c["l_lower_len"],
            "lenU", a["l_upper_len"], c["l_upper_len"],
            "gap_knee", a["l_knee_to_thigh_tail_mm"], c["l_knee_to_thigh_tail_mm"],
            "gap_tail", a["l_ankle_to_calf_tail_mm"], c["l_ankle_to_calf_tail_mm"],
        )

print("=== lowest vertex weights on C ===")
for action in ("a050_300010", "a050_300000"):
    frames = range(4, 13) if action.endswith("010") else (9, 15, 16)
    for frame in frames:
        picked = [v for v in verts if v["action"] == action and int(v["frame"]) == frame and v["config"] == "C_lock"]
        if not picked:
            continue
        top = min(picked, key=lambda item: float(item["z"]))
        print(action, frame, "z", top["z"], top["weights"])

print("=== channel coupling vs C baseline ===")
tests = [r for r in rows if r["config"] == "C_loc"]
summary = {}
for row in tests:
    key = (row["action"], row["channel"])
    c = base[("C_lock", row["action"], int(row["frame"]))]
    side = "l" if row["channel"].startswith("l_") else "r"
    knee = dist(c[side + "_knee"], row[side + "_knee"])
    ankle = dist(c[side + "_ankle"], row[side + "_ankle"])
    other = "r" if side == "l" else "l"
    other_ankle = dist(c[other + "_ankle"], row[other + "_ankle"])
    mesh = (float(row["mesh_lowest"]) - float(c["mesh_lowest"])) * 1000.0
    upper = (float(row[side + "_upper_len"]) - float(c[side + "_upper_len"])) * 1000.0
    lower = (float(row[side + "_lower_len"]) - float(c[side + "_lower_len"])) * 1000.0
    gap_k = float(row[side + "_knee_to_thigh_tail_mm"]) - float(c[side + "_knee_to_thigh_tail_mm"])
    gap_t = float(row[side + "_ankle_to_calf_tail_mm"]) - float(c[side + "_ankle_to_calf_tail_mm"])
    item = summary.setdefault(key, {"n": 0, "knee": 0, "ankle": 0, "mesh": 0, "upper": 0, "lower": 0,
                                     "gap_k": 0, "gap_t": 0, "quat": 0, "foot_quat": 0, "foot_loc": 0,
                                     "roll": 0, "other_ankle": 0, "still_below": 0})
    item["n"] += 1
    item["knee"] = max(item["knee"], knee)
    item["ankle"] = max(item["ankle"], ankle)
    item["other_ankle"] = max(item["other_ankle"], other_ankle)
    item["mesh"] = mesh if abs(mesh) > abs(item["mesh"]) else item["mesh"]
    item["upper"] = upper if abs(upper) > abs(item["upper"]) else item["upper"]
    item["lower"] = lower if abs(lower) > abs(item["lower"]) else item["lower"]
    item["gap_k"] = gap_k if abs(gap_k) > abs(item["gap_k"]) else item["gap_k"]
    item["gap_t"] = gap_t if abs(gap_t) > abs(item["gap_t"]) else item["gap_t"]
    item["quat"] = max(item["quat"], float(row["calf_quat_delta_deg"]))
    item["foot_quat"] = max(item["foot_quat"], float(row["foot_quat_delta_deg"]))
    item["foot_loc"] = max(item["foot_loc"], float(row["foot_loc_delta_mm"]))
    item["roll"] = max(item["roll"], abs(float(row[side + "_roll"]) - float(c[side + "_roll"])))
    if float(row["mesh_lowest"]) < -0.01:
        item["still_below"] += 1

for key, item in summary.items():
    print(key, {name: round(value, 4) if isinstance(value, float) else value for name, value in item.items()})

print("=== per-frame 300010 left channels, frame 8 ===")
for row in tests:
    if row["action"] == "a050_300010" and int(row["frame"]) == 8 and row["channel"].startswith("l_"):
        c = base[("C_lock", row["action"], 8)]
        print(row["channel"],
              "knee", round(dist(c["l_knee"], row["l_knee"]), 3),
              "ankle", round(dist(c["l_ankle"], row["l_ankle"]), 3),
              "mesh_dz", round((float(row["mesh_lowest"]) - float(c["mesh_lowest"])) * 1000.0, 3),
              "upper_d", round((float(row["l_upper_len"]) - float(c["l_upper_len"])) * 1000.0, 3),
              "lower_d", round((float(row["l_lower_len"]) - float(c["l_lower_len"])) * 1000.0, 3),
              "gap_k", round(float(row["l_knee_to_thigh_tail_mm"]) - float(c["l_knee_to_thigh_tail_mm"]), 3),
              "gap_t", round(float(row["l_ankle_to_calf_tail_mm"]) - float(c["l_ankle_to_calf_tail_mm"]), 3),
              "roll", row["l_roll"], "base_roll", c["l_roll"],
              "quat", row["calf_quat_delta_deg"], "footq", row["foot_quat_delta_deg"],
              "z", row["mesh_lowest"], "n01", row["n_z_lt_001"])

print("=== continuity pop, left loc_z on 300010 ===")
for frame in range(4, 13):
    row = next(r for r in tests if r["action"] == "a050_300010" and int(r["frame"]) == frame and r["channel"] == "l_calf_loc_z")
    prev = base[("C_lock", "a050_300010", frame - 1)]
    cur = base[("C_lock", "a050_300010", frame)]
    print(frame,
          "knee_vs_prev_base", round(dist(prev["l_knee"], row["l_knee"]), 3),
          "knee_base_step", round(dist(prev["l_knee"], cur["l_knee"]), 3),
          "ankle_vs_prev", round(dist(prev["l_ankle"], row["l_ankle"]), 3),
          "ankle_base_step", round(dist(prev["l_ankle"], cur["l_ankle"]), 3))
