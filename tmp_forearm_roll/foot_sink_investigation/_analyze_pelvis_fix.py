import csv, json, math
from pathlib import Path

OUT = Path(r"H:\Blender_Plugin\tmp_forearm_roll\foot_sink_investigation")

def load(name):
    with (OUT / name).open(encoding="utf-8") as h:
        return list(csv.DictReader(h))

new = load("pelvis_fix_frames.csv")
old = load("floor_fix_frames.csv")  # phase-1 candidate (F0 verified == archived A baseline)

def key(r): return (r["config"], r["action"], int(r["frame"]))
def ok(r): return (r["action"], int(r["frame"]))

N = {(r["config"], r["action"], int(r["frame"])): r for r in new}
O = {(r["config"], r["action"], int(r["frame"])): r for r in old}
CLIPS = ("a050_300000", "a050_300010", "a050_301000", "a050_302011")

def z(js): return json.loads(js)[2] * 1000.0
def xyz(js): return [v * 1000.0 for v in json.loads(js)]

def contact_sole_min(rows, config, clip):
    vals = []
    for r in rows:
        if r["config"] == config and r["action"] == clip:
            for s in ("l", "r"):
                if r[s + "_contact"] == "True":
                    vals.append(float(r[s + "_sole_rel_mm"]))
    return (min(vals), len(vals)) if vals else (None, 0)

def sole_below(rows, config, clip, thresh=-10.0):
    out = []
    for r in rows:
        if r["config"] == config and r["action"] == clip:
            for s in ("l", "r"):
                if float(r[s + "_sole_rel_mm"]) < thresh:
                    out.append((int(r["frame"]), s, float(r[s + "_sole_rel_mm"])))
    return out

print("=== F0: phase2 F0 vs phase1 F0 (== archived baseline) ===")
for clip in CLIPS:
    dp = dh = de = 0.0
    recheck = 0.0
    knee_min = 999.0
    frames = 0
    for (cfg, act, f), r in N.items():
        if cfg != "F0" or act != clip:
            continue
        o = O[("F0", act, f)]
        frames += 1
        dp = max(dp, abs(z(r["pelvis"]) - z(o["pelvis"])))
        dh = max(dh, abs(z(r["head"]) - z(o["head"])))
        for s in ("l", "r"):
            de = max(de, abs(float(r[s + "_err_mm"]) - float(o[s + "_err_mm"])))
            rv = r[s + "_recheck_raised_mm"]
            if rv not in (None, "", "None"):
                recheck = max(recheck, float(rv))
            knee_min = min(knee_min, float(r[s + "_knee_deg"]))
    cs, n = contact_sole_min(new, "F0", clip)
    print(f"{clip} frames={frames} dPelvisZmax={dp:.3f} dHeadZmax={dh:.3f} dAnkleErrmax={de:.4f} "
          f"contactSoleMin={cs} (n={n}) recheckMax={recheck:.1f} kneeMin={knee_min:.3f}")

print("\n=== F1: FP/FM vs own F0 (pelvis/head/hand world = F0 + floor, tol 2mm) ===")
for cfg, fmm in (("FP", 50.0), ("FM", -50.0)):
    for clip in CLIPS:
        dp = dh = dhand = dknee = 0.0
        dp_frame = None
        for (c, act, f), r in N.items():
            if c != cfg or act != clip:
                continue
            r0 = N[("F0", act, f)]
            v = abs((z(r["pelvis"]) - fmm) - z(r0["pelvis"]))
            if v > dp: dp, dp_frame = v, f
            dh = max(dh, abs((z(r["head"]) - fmm) - z(r0["head"])))
            for s in ("l", "r"):
                if r[s + "_hand"] and r0[s + "_hand"]:
                    hv = xyz(r[s + "_hand"]); h0 = xyz(r0[s + "_hand"])
                    dhand = max(dhand, abs((hv[2] - fmm) - h0[2]), abs(hv[0] - h0[0]), abs(hv[1] - h0[1]))
                dknee = max(dknee, abs(float(r[s + "_knee_deg"]) - float(r0[s + "_knee_deg"])))
        cs, n = contact_sole_min(new, cfg, clip)
        below = sole_below(new, cfg, clip)
        print(f"{cfg} {clip} dPelvis={dp:.3f}@f{dp_frame} dHead={dh:.3f} dHand={dhand:.3f} dKneeMax={dknee:.3f} "
              f"contactSoleMin={cs} (n={n}) soleBelow-10mm={below[:4]}")

print("\n=== mesh lowest relative to floor (all frames; non-foot dips expected only 301000 f0) ===")
for cfg in ("F0", "FP", "FM"):
    for clip in CLIPS:
        worst = []
        for (c, act, f), r in N.items():
            if c == cfg and act == clip:
                rel = float(r["mesh_lowest_world_mm"]) - float(r["floor_m"]) * 1000.0
                worst.append((rel, f))
        worst.sort()
        print(cfg, clip, "worst3", [(round(v, 1), f) for v, f in worst[:3]])

print("\n=== F2: CURRENT + fallback ===")
for cfg, ref, fmm in (("CUR0", "F0", 0.0), ("CURFM", "CUR0", -50.0)):
    dp = dh = 0.0
    for (c, act, f), r in N.items():
        if c != cfg:
            continue
        r0 = N[(ref, act, f)]
        dp = max(dp, abs((z(r["pelvis"]) - fmm) - z(r0["pelvis"])))
        dh = max(dh, abs((z(r["head"]) - fmm) - z(r0["head"])))
    cs, n = contact_sole_min(new, cfg, "a050_300000")
    print(f"{cfg} vs {ref}: dPelvis={dp:.3f} dHead={dh:.3f} contactSoleMin={cs} (n={n})")
for cfg, ocfg in (("FB0", "F0"), ("FBFM", "FM")):
    dp = 0.0
    for (c, act, f), r in N.items():
        if c != cfg:
            continue
        o = O[(ocfg, act, f)]
        dp = max(dp, abs(z(r["pelvis"]) - z(o["pelvis"])))
    cs, n = contact_sole_min(new, cfg, "a050_300000")
    print(f"{cfg} vs phase1 {ocfg}: dPelvisMax={dp:.3f} contactSoleMin={cs} (n={n})")

print("\n=== F3: T2/T3/SRC_RAISED normalized vs F0; known exceptions ===")
for cfg, clips in (("T2", ("a050_300000", "a050_301000")), ("T3", ("a050_300000",)), ("SRC_RAISED", ("a050_300000",))):
    for clip in clips:
        dp = dh = dknee = 0.0
        for (c, act, f), r in N.items():
            if c != cfg or act != clip:
                continue
            r0 = N[("F0", act, f)]
            dp = max(dp, abs((z(r["pelvis"]) - 50.0) - z(r0["pelvis"])))
            dh = max(dh, abs((z(r["head"]) - 50.0) - z(r0["head"])))
            for s in ("l", "r"):
                dknee = max(dknee, abs(float(r[s + "_knee_deg"]) - float(r0[s + "_knee_deg"])))
        cs, n = contact_sole_min(new, cfg, clip)
        print(f"{cfg} {clip} dPelvisNorm={dp:.3f} dHeadNorm={dh:.3f} dKneeMax={dknee:.3f} contactSoleMin={cs} (n={n})")
r = N[("F0", "a050_300010", 15)]
print("known exception 300010 f15 knees F0:", r["l_knee_deg"], r["r_knee_deg"])
r = N[("F0", "a050_301000", 0)]
print("known exception 301000 f0 mesh_lowest_world_mm:", r["mesh_lowest_world_mm"],
      "soles:", r["l_sole_world_mm"], r["r_sole_world_mm"])

print("\n=== branch B coverage (src hips world z > rest 970mm, REST configs) ===")
for cfg in ("F0", "FP", "FM", "T3", "SRC_RAISED"):
    frames = [f for (c, a, f), r in N.items() if c == cfg and float(r["src_hips_world_z_mm"]) > 970.0]
    print(cfg, "branchB frames:", len(frames), sorted(frames)[:12])
frames = [f for (c, a, f), r in N.items() if c in ("CUR0", "CURFM") and float(r["src_hips_world_z_mm"]) > 942.771]
print("CUR branchB frames (>942.771):", len(frames), sorted(frames)[:12])
