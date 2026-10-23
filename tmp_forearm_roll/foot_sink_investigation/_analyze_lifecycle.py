import csv, json
from pathlib import Path

OUT = Path(r"H:\Blender_Plugin\tmp_forearm_roll\foot_sink_investigation")

def load(name):
    with (OUT / name).open(encoding="utf-8") as h:
        return list(csv.DictReader(h))

L = {(r["config"], r["action"], int(r["frame"])): r for r in load("datum_lifecycle_frames.csv")}
D = {(r["config"], r["action"], int(r["frame"])): r for r in load("datum_fix_frames.csv")}
R = {(r["config"], r["action"], int(r["frame"])): r for r in load("datum_regression_frames.csv")}
CLIP = "a050_300000"

def z(js): return json.loads(js)[2] * 1000.0
def xyz(js): return [v * 1000.0 for v in json.loads(js)]

def soles(rows, config, clip=CLIP):
    vals = [float(r[s + "_sole_rel_mm"]) for (c, a, f), r in rows.items()
            if c == config and a == clip for s in ("l", "r")]
    return (round(min(vals), 3), round(max(vals), 3)) if vals else None

def contact_min(rows, config, clip=CLIP):
    vals = [float(r[s + "_sole_rel_mm"]) for (c, a, f), r in rows.items()
            if c == config and a == clip for s in ("l", "r") if r[s + "_contact"] == "True"]
    return (round(min(vals), 3), round(max(vals), 3), len(vals)) if vals else None

def inv_diff(cfg, ref_rows=D, ref_cfg="F0", shift=(0.0, 0.0, 0.0), clip=CLIP):
    dpz = dhz = dknee = de = 0.0
    for (c, a, f), r in L.items():
        if c != cfg or a != clip:
            continue
        r0 = ref_rows[(ref_cfg, a, f)]
        dpz = max(dpz, abs((z(r["pelvis"]) - shift[2]) - z(r0["pelvis"])))
        dhz = max(dhz, abs((z(r["head"]) - shift[2]) - z(r0["head"])))
        for s in ("l", "r"):
            dknee = max(dknee, abs(float(r[s + "_knee_deg"]) - float(r0[s + "_knee_deg"])))
            de = max(de, abs(float(r[s + "_err_mm"]) - float(r0[s + "_err_mm"])))
    print(f"{cfg}: dPelvisZ={dpz:.3f} dHeadZ={dhz:.3f} dKneeMax={dknee:.3f} dAnkleErr={de:.4f} "
          f"soleRelAll={soles(L, cfg, clip)} contact={contact_min(L, cfg, clip)}")

print("=== regression rerun: datum_regression vs datum_fix (should be identical) ===")
worst = 0.0
diffs = 0
for k, r in R.items():
    o = D.get(k)
    if o is None:
        continue
    d = abs(z(r["pelvis"]) - z(o["pelvis"]))
    if d > 0.01:
        diffs += 1
    worst = max(worst, d)
print(f"regression rows={len(R)} pelvisDiff>0.01mm count={diffs} worst={worst:.3f}")
for cfg, fmm in (("FP", 50.0), ("FM", -50.0)):
    dp = 0.0
    for clip in ("a050_300000", "a050_300010", "a050_301000", "a050_302011"):
        for (c, a, f), r in R.items():
            if c == cfg and a == clip:
                r0 = R[("F0", a, f)]
                dp = max(dp, abs((z(r["pelvis"]) - fmm) - z(r0["pelvis"])))
    print(f"regression {cfg} pelvis normalized worst={dp:.3f} contactMin={contact_min(R, cfg)}")
for cfg in ("T2", "T3"):
    dp = 0.0
    for (c, a, f), r in R.items():
        if c == cfg:
            r0 = R[("F0", a, f)]
            dp = max(dp, abs((z(r["pelvis"]) - 50.0) - z(r0["pelvis"])))
    print(f"regression {cfg} pelvis normalized worst={dp:.3f} contactMin={contact_min(R, cfg, 'a050_300000')}")

print("\n=== lifecycle vs F0 (datum_fix) ===")
inv_diff("LTRANS", shift=(30.0, -20.0, 0.0))
# LTRANS xy check
dxy = 0.0
for (c, a, f), r in L.items():
    if c == "LTRANS":
        p, p0 = xyz(r["pelvis"]), xyz(D[("F0", a, f)]["pelvis"])
        dxy = max(dxy, abs((p[0] - 30.0) - p0[0]), abs((p[1] + 20.0) - p0[1]))
print(f"LTRANS pelvis xy (after expected +30/-20 shift) worst={dxy:.3f}")
inv_diff("LYAW")
inv_diff("LYAWFM", shift=(0.0, 0.0, -50.0))
inv_diff("LTILT")
inv_diff("LSCALE")
inv_diff("LSCALEFM", shift=(0.0, 0.0, -50.0))
inv_diff("LSCALEFIX")
for cfg in ("LCORRUPT1", "LCORRUPT2", "LCORRUPT3", "LCORRUPT4"):
    dp = 0.0
    for (c, a, f), r in L.items():
        if c == cfg:
            o = D[("FBFM", a, f)]
            dp = max(dp, abs(z(r["pelvis"]) - z(o["pelvis"])))
    print(f"{cfg} vs FBFM(legacy fallback) dPelvis={dp:.3f} contact={contact_min(L, cfg)}")
inv_diff("LWRONG")
inv_diff("CHAN0")
# CHANFM vs CHAN0
dp = dk = 0.0
for (c, a, f), r in L.items():
    if c == "CHANFM":
        r0 = L[("CHAN0", a, f)]
        dp = max(dp, abs((z(r["pelvis"]) + 50.0) - z(r0["pelvis"])))
        for s in ("l", "r"):
            dk = max(dk, abs(float(r[s + "_knee_deg"]) - float(r0[s + "_knee_deg"])))
print(f"CHANFM vs CHAN0 normalized dPelvis={dp:.3f} dKneeMax={dk:.3f} contact={contact_min(L, 'CHANFM')}")
print("RIGIFY_FM soleRelAll:", soles(L, "RIGIFY_FM"))
dp = 0.0
for (c, a, f), r in L.items():
    if c == "RIGIFY_FM":
        r0 = D[("F0", a, f)]
        dp = max(dp, abs((z(r["pelvis"]) + 50.0) - z(r0["pelvis"])))
print(f"RIGIFY_FM pelvis vs F0-50 worst={dp:.3f}")
