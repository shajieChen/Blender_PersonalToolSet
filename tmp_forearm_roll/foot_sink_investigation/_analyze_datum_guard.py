"""Analyze B1/B2 guard results against archived datum-round frames."""
import csv
import json
from pathlib import Path

OUT = Path(r"H:\Blender_Plugin\tmp_forearm_roll\foot_sink_investigation")


def load(name):
    with (OUT / name).open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def vec(text):
    return None if text in (None, "", "None") else [float(v) for v in json.loads(text)]


def index(rows):
    return {(r["config"], r["action"], int(r["frame"])): r for r in rows}


def compare(new, old, label, z_shift_mm=0.0):
    worst_pelvis = worst_head = worst_knee = 0.0
    contact_min = 999.0
    checked = 0
    for key, a in new.items():
        b = old.get(key)
        if b is None:
            continue
        checked += 1
        for field, worst in (("pelvis", "p"), ("head", "h")):
            va, vb = vec(a[field]), vec(b[field])
            if va is None or vb is None:
                continue
            d = max(
                abs(va[0] - vb[0]) * 1000.0,
                abs(va[1] - vb[1]) * 1000.0,
                abs((va[2] - vb[2]) * 1000.0 - z_shift_mm),
            )
            if worst == "p":
                worst_pelvis = max(worst_pelvis, d)
            else:
                worst_head = max(worst_head, d)
        for side in ("l", "r"):
            worst_knee = max(
                worst_knee,
                abs(float(a[side + "_knee_deg"]) - float(b[side + "_knee_deg"])),
            )
            if a[side + "_contact"] == "True":
                contact_min = min(contact_min, float(a[side + "_sole_rel_mm"]))
    print(
        f"{label}: frames={checked} pelvisΔ≤{worst_pelvis:.3f}mm "
        f"headΔ≤{worst_head:.3f}mm kneeΔ≤{worst_knee:.3f}° contact_min={contact_min:.3f}mm"
    )
    return worst_pelvis, worst_head, worst_knee


guard = load("datum_guard_frames.csv")
datum = load("datum_fix_frames.csv")
lifecycle = load("datum_lifecycle_frames.csv")
gi, di, li = index(guard), index(datum), index(lifecycle)

CLIP = "a050_300000"


def subset(idx, config, action=CLIP):
    return {k: v for k, v in idx.items() if k[0] == config and k[1] == action}


def renamed(idx, config, as_config, action=CLIP):
    return {(as_config, k[1], k[2]): v for k, v in idx.items() if k[0] == config and k[1] == action}


# B1 legal datum still used and identical to datum round
compare(renamed(gi, "LEGAL_FM", "X"), renamed(di, "FM", "X"), "B1 legal FM vs datum FM")
compare(renamed(gi, "LEGAL_FP", "X"), renamed(di, "FP", "X"), "B1 legal FP vs datum FP")
# B1 fallbacks must reproduce legacy FBFM exactly
for cfg in ("MISSING_FM", "ONESIDE_FM", "GARBAGE_FM", "EMPTY_FM", "RAGGED_FM",
            "STRSCALE_FM", "NAN_FM", "FORGED_TGT_FM", "FORGED_SRC_FM"):
    compare(renamed(gi, cfg, "X"), renamed(di, "FBFM", "X"), f"B1 {cfg} vs legacy FBFM")
compare(renamed(gi, "MISSING_F0", "X"), renamed(di, "FB0", "X"), "B1 MISSING_F0 vs legacy FB0")
# pre-fix forged damage reference (lifecycle LWRONG vs FBFM-equivalent L-scale rows)
compare(renamed(li, "LWRONG", "X"), renamed(di, "FBFM", "X"), "PRE-FIX forged LWRONG vs legacy FBFM (damage reference)")
# B1 post-registration translation/yaw stay valid
compare(renamed(gi, "TRANSL_F0", "X"), renamed(di, "F0", "X"), "B1 TRANSL_F0 vs F0 (+50mm z)", z_shift_mm=50.0)
compare(renamed(gi, "TRANSL_FM", "X"), renamed(di, "FM", "X"), "B1 TRANSL_FM vs FM (+50mm z)", z_shift_mm=50.0)
compare(renamed(li, "LYAW", "X"), renamed(gi, "YAW_F0", "X"), "B1 YAW_F0 vs pre-fix LYAW")
compare(renamed(li, "LYAWFM", "X"), renamed(gi, "YAW_FM", "X"), "B1 YAW_FM vs pre-fix LYAWFM")
# B2 channel floor 0 unchanged vs pre-fix CHAN0
compare(renamed(li, "CHAN0", "X"), renamed(gi, "CHAN0", "X"), "B2 CHAN0 vs pre-fix CHAN0")
print("ANALYSIS DONE")
