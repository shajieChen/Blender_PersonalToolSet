import csv
import json
from pathlib import Path

OUT = Path(r"H:\Blender_Plugin\tmp_forearm_roll\foot_sink_investigation")


def load(name):
    with (OUT / name).open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def vec(text):
    return [float(v) for v in json.loads(text)]


g = {(r["config"], r["action"], int(r["frame"])): r for r in load("datum_guard_frames.csv")}
d = {(r["config"], r["action"], int(r["frame"])): r for r in load("datum_fix_frames.csv")}

wp = wh = wk = 0.0
cmin = 999.0
for f in range(53):
    a = g[("TRANSL_F0", "a050_300000", f)]
    b = d[("OBJ_ONLY", "a050_300000", f)]
    for field in ("pelvis", "head"):
        delta = max(abs(x - y) * 1000.0 for x, y in zip(vec(a[field]), vec(b[field])))
        if field == "pelvis":
            wp = max(wp, delta)
        else:
            wh = max(wh, delta)
    for side in ("l", "r"):
        wk = max(wk, abs(float(a[side + "_knee_deg"]) - float(b[side + "_knee_deg"])))
        if a[side + "_contact"] == "True":
            cmin = min(cmin, float(a[side + "_sole_rel_mm"]))
print(
    f"TRANSL_F0 vs datum OBJ_ONLY: pelvis<={wp:.3f}mm head<={wh:.3f}mm "
    f"knee<={wk:.3f}deg contact_min={cmin:.3f}mm"
)

# TRANSL_FM: same object move, floor -0.05 -> feet ground at -50mm, pelvis follows OBJ_ONLY-style invariance
wp = 0.0
cmin = 999.0
for f in range(53):
    a = g[("TRANSL_FM", "a050_300000", f)]
    b = d[("FM", "a050_300000", f)]
    delta = max(abs(x - y) * 1000.0 for x, y in zip(vec(a["pelvis"]), vec(b["pelvis"])))
    wp = max(wp, delta)
    for side in ("l", "r"):
        if a[side + "_contact"] == "True":
            cmin = min(cmin, float(a[side + "_sole_rel_mm"]))
print(f"TRANSL_FM vs datum FM: pelvis<={wp:.3f}mm contact_min={cmin:.3f}mm")
print("DONE")
