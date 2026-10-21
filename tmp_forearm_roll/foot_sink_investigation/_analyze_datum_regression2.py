"""Core regression: guard-regression frames vs datum-round frames, config-matched."""
import csv
import json
from pathlib import Path

OUT = Path(r"H:\Blender_Plugin\tmp_forearm_roll\foot_sink_investigation")


def load(name):
    with (OUT / name).open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def vec(text):
    return None if text in (None, "", "None") else [float(v) for v in json.loads(text)]


new = {(r["config"], r["action"], int(r["frame"])): r for r in load("datum_guard_regression_frames.csv")}
old = {(r["config"], r["action"], int(r["frame"])): r for r in load("datum_fix_frames.csv")}
print("rows", len(new), len(old), "keys equal:", set(new) == set(old))

worst = {"pelvis": 0.0, "head": 0.0, "knee": 0.0, "ankle": 0.0, "sole": 0.0, "err": 0.0}
knee_below = {"new": 0, "old": 0}
contact_min = {}
for key, a in new.items():
    b = old[key]
    for field in ("pelvis", "head"):
        va, vb = vec(a[field]), vec(b[field])
        worst[field] = max(worst[field], max(abs(x - y) * 1000.0 for x, y in zip(va, vb)))
    ck = (key[0], key[1])
    for side in ("l", "r"):
        worst["knee"] = max(worst["knee"], abs(float(a[side + "_knee_deg"]) - float(b[side + "_knee_deg"])))
        va, vb = vec(a[side + "_ankle"]), vec(b[side + "_ankle"])
        worst["ankle"] = max(worst["ankle"], max(abs(x - y) * 1000.0 for x, y in zip(va, vb)))
        worst["sole"] = max(worst["sole"], abs(float(a[side + "_sole_rel_mm"]) - float(b[side + "_sole_rel_mm"])))
        worst["err"] = max(worst["err"], abs(float(a[side + "_err_mm"]) - float(b[side + "_err_mm"])))
        if round(float(a[side + "_knee_deg"]), 3) < 15.0:
            knee_below["new"] += 1
        if round(float(b[side + "_knee_deg"]), 3) < 15.0:
            knee_below["old"] += 1
        if a[side + "_contact"] == "True":
            contact_min[ck] = min(contact_min.get(ck, 999.0), float(a[side + "_sole_rel_mm"]))
print("worst diffs (mm/deg):", {k: round(v, 4) for k, v in worst.items()})
print("knee<15 counts:", knee_below)
print("contact sole min per config/action:")
for key in sorted(contact_min):
    print(" ", key, round(contact_min[key], 3))
# known baseline exceptions
for cfg, clip, frame, label in (
    ("F0", "a050_300010", 15, "r_knee exception"),
    ("F0", "a050_301000", 0, "non-foot mesh lowest"),
):
    r = new[(cfg, clip, frame)]
    print(label, "r_knee:", r["r_knee_deg"], "mesh_lowest:", r["mesh_lowest_world_mm"],
          "soles:", r["l_sole_world_mm"], r["r_sole_world_mm"])
print("REGRESSION ANALYSIS DONE")
