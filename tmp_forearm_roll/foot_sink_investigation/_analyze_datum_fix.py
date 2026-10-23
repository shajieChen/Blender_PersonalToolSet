import csv, json
from pathlib import Path

OUT = Path(r"H:\Blender_Plugin\tmp_forearm_roll\foot_sink_investigation")

def load(name):
    with (OUT / name).open(encoding="utf-8") as h:
        return list(csv.DictReader(h))

new = load("datum_fix_frames.csv")
old = load("floor_fix_frames.csv")  # phase-1 candidate, F0 == archived A baseline

N = {(r["config"], r["action"], int(r["frame"])): r for r in new}
O = {(r["config"], r["action"], int(r["frame"])): r for r in old}
CLIPS = ("a050_300000", "a050_300010", "a050_301000", "a050_302011")

def z(js): return json.loads(js)[2] * 1000.0
def xyz(js): return [v * 1000.0 for v in json.loads(js)]

def contact_soles(rows, config, clip):
    vals = []
    for r in rows:
        if r["config"] == config and r["action"] == clip:
            for s in ("l", "r"):
                if r[s + "_contact"] == "True":
                    vals.append(float(r[s + "_sole_rel_mm"]))
    return (min(vals), max(vals), len(vals)) if vals else (None, None, 0)

def compare(cfg, ref, clip, shift_mm, label):
    dp = dh = dhand = dknee = de = 0.0
    for (c, act, f), r in N.items():
        if c != cfg or act != clip:
            continue
        r0 = N[(ref, act, f)]
        dp = max(dp, abs((z(r["pelvis"]) - shift_mm) - z(r0["pelvis"])))
        dh = max(dh, abs((z(r["head"]) - shift_mm) - z(r0["head"])))
        for s in ("l", "r"):
            if r[s + "_hand"] and r0[s + "_hand"]:
                hv, h0 = xyz(r[s + "_hand"]), xyz(r0[s + "_hand"])
                dhand = max(dhand, abs((hv[2] - shift_mm) - h0[2]), abs(hv[0] - h0[0]), abs(hv[1] - h0[1]))
            dknee = max(dknee, abs(float(r[s + "_knee_deg"]) - float(r0[s + "_knee_deg"])))
            de = max(de, abs(float(r[s + "_err_mm"]) - float(r0[s + "_err_mm"])))
    cs = contact_soles(new, cfg, clip)
    print(f"{label} {clip} dPelvis={dp:.3f} dHead={dh:.3f} dHand={dhand:.3f} dKneeMax={dknee:.3f} "
          f"dAnkleErr={de:.4f} contactSole[min,max,n]={cs}")

print("=== F0: datum F0 vs archived baseline (phase-1 F0) ===")
for clip in CLIPS:
    dp = dh = de = 0.0
    recheck = 0.0
    knee_min = 999.0
    for (cfg, act, f), r in N.items():
        if cfg != "F0" or act != clip:
            continue
        o = O[("F0", act, f)]
        dp = max(dp, abs(z(r["pelvis"]) - z(o["pelvis"])))
        dh = max(dh, abs(z(r["head"]) - z(o["head"])))
        for s in ("l", "r"):
            de = max(de, abs(float(r[s + "_err_mm"]) - float(o[s + "_err_mm"])))
            rv = r[s + "_recheck_raised_mm"]
            if rv not in (None, "", "None"):
                recheck = max(recheck, float(rv))
            knee_min = min(knee_min, float(r[s + "_knee_deg"]))
    cs = contact_soles(new, "F0", clip)
    print(f"{clip} dPelvisZmax={dp:.3f} dHeadZmax={dh:.3f} dAnkleErrmax={de:.4f} "
          f"contactSole={cs} recheckMax={recheck:.1f} kneeMin={knee_min:.3f}")

print("\n=== F1: FP/FM vs own F0 (world = F0 + floor) ===")
for cfg, fmm in (("FP", 50.0), ("FM", -50.0)):
    for clip in CLIPS:
        compare(cfg, "F0", clip, fmm, cfg)

print("\n=== F2: CURRENT / fallback / no-skin ===")
compare("CURFM", "CUR0", "a050_300000", -50.0, "CURFM vs CUR0")
print("CUR0 contactSole:", contact_soles(new, "CUR0", "a050_300000"))
dp = 0.0
for (c, act, f), r in N.items():
    if c == "CUR0":
        r0 = N[("F0", act, f)]
        dp = max(dp, abs(z(r["pelvis"]) - z(r0["pelvis"])))
print(f"CUR0 vs REST F0 dPelvis (reference semantics, not equivalence): {dp:.3f}")
for cfg, ocfg in (("FB0", "F0"), ("FBFM", "FM"), ("NOSKIN0", "F0"), ("NOSKINFM", "FM")):
    dp = 0.0
    for (c, act, f), r in N.items():
        if c != cfg:
            continue
        o = O[(ocfg, act, f)]
        dp = max(dp, abs(z(r["pelvis"]) - z(o["pelvis"])))
    print(f"{cfg} vs phase1 {ocfg}: dPelvisMax={dp:.3f} contactSole={contact_soles(new, cfg, 'a050_300000')}")

print("\n=== F3: transform independence ===")
compare("OBJ_ONLY", "F0", "a050_300000", 0.0, "OBJ_ONLY(world==F0)")
compare("OBJ_ONLY", "F0", "a050_301000", 0.0, "OBJ_ONLY(world==F0)")
compare("SRC_ONLY", "F0", "a050_300000", 0.0, "SRC_ONLY(world==F0)")
compare("T2", "F0", "a050_300000", 50.0, "T2(norm)")
compare("T2", "F0", "a050_301000", 50.0, "T2(norm)")
compare("T3", "F0", "a050_300000", 50.0, "T3(norm)")

print("\n=== known exceptions ===")
r = N[("F0", "a050_300010", 15)]
print("300010 f15 knees:", r["l_knee_deg"], r["r_knee_deg"], "(archived 160.339/12.942)")
r = N[("F0", "a050_301000", 0)]
print("301000 f0 mesh_lowest:", r["mesh_lowest_world_mm"], "soles:", r["l_sole_world_mm"], r["r_sole_world_mm"])

print("\n=== datum branch B coverage (src datum hips > 970mm) ===")
for cfg in ("F0", "FP", "FM", "T3", "SRC_ONLY", "OBJ_ONLY", "T2"):
    frames = sorted(f for (c, a, f), r in N.items()
                    if c == cfg and r["src_datum_hips_mm"] not in (None, "", "None")
                    and float(r["src_datum_hips_mm"]) > 970.0)
    print(cfg, len(frames), frames[:12])

print("\n=== mesh lowest rel floor worst (per F-config) ===")
for cfg in ("F0", "FP", "FM", "T2", "T3"):
    for clip in CLIPS:
        worst = sorted(
            (float(r["mesh_lowest_world_mm"]) - float(r["floor_m"]) * 1000.0, int(r["frame"]))
            for (c, a, f), r in N.items() if c == cfg and a == clip
        )[:2]
        print(cfg, clip, [(round(v, 1), f) for v, f in worst])
