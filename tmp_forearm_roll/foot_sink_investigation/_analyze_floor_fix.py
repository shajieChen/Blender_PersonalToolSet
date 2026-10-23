import csv
import json
import math
import pathlib

base = pathlib.Path(r"H:\Blender_Plugin\tmp_forearm_roll\foot_sink_investigation")
rows = list(csv.DictReader((base / "floor_fix_frames.csv").open(newline="", encoding="utf-8-sig")))
arch = list(csv.DictReader((base / "cross_frames.csv").open(newline="", encoding="utf-8-sig")))
arch_a = {(r["action"], int(r["frame"])): r for r in arch if r["config"] == "A"}


def vec(s):
    return json.loads(s)


def dist(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(vec(a), vec(b)))) * 1000


groups = {}
for r in rows:
    groups.setdefault((r["config"], r["action"]), []).append(r)

print("== per-group summary ==")
for (cfg, act), g in sorted(groups.items()):
    soles = [float(r[s + "_sole_rel_mm"]) for r in g for s in ("l", "r")]
    contact = [float(r[s + "_sole_rel_mm"]) for r in g for s in ("l", "r") if r[s + "_contact"] == "True"]
    deep = sum(1 for r in g if min(float(r["l_sole_rel_mm"]), float(r["r_sole_rel_mm"])) < -10)
    errs = max(max(float(r["l_err_mm"]), float(r["r_err_mm"])) for r in g)
    knees = min(min(float(r["l_knee_deg"]), float(r["r_knee_deg"])) for r in g)
    raised = max(max(float(r["l_recheck_raised_mm"] or 0), float(r["r_recheck_raised_mm"] or 0)) for r in g)
    logdiff = max(abs(float(r[s + "_log_lowest_rel_mm"]) - float(r[s + "_sole_rel_mm"]))
                  for r in g for s in ("l", "r") if r[s + "_log_lowest_rel_mm"] not in ("", None))
    print(cfg, act, "n=", len(g), "sole_rel_min=", round(min(soles), 3), "deepFr=", deep,
          "err=", round(errs, 3), "knee_min=", round(knees, 3), "raised_max=", round(raised, 1),
          "contact_min=", round(min(contact), 3) if contact else None,
          "contact_below-1=", sum(1 for x in contact if x < -1),
          "log_vs_scan_max_mm=", round(logdiff, 3),
          "mesh_world_min=", round(min(float(r["mesh_lowest_world_mm"]) for r in g), 3))

print("== F0 vs archived A ==")
for act in ("a050_300000", "a050_300010", "a050_301000", "a050_302011"):
    g = groups[("F0", act)]
    max_ankle = max_head = max_pelvis = max_knee = max_sole = max_raised = 0.0
    for r in g:
        a = arch_a[(act, int(r["frame"]))]
        max_pelvis = max(max_pelvis, dist(r["pelvis"], a["pelvis"]))
        max_head = max(max_head, dist(r["head"], a["head"]))
        for s in ("l", "r"):
            max_ankle = max(max_ankle, dist(r[s + "_ankle"], a[s + "_ankle"]))
            max_knee = max(max_knee, abs(float(r[s + "_knee_deg"]) - float(a[s + "_knee_deg"])))
            max_sole = max(max_sole, abs(float(r[s + "_sole_rel_mm"]) - float(a[s + "_sole_z"]) * 1000.0))
            max_raised = max(max_raised, abs(float(r[s + "_recheck_raised_mm"] or 0)
                                             - float(a[s + "_recheck_raised_mm"] or 0)))
    print(act, "pelvis", round(max_pelvis, 4), "head", round(max_head, 4), "ankle", round(max_ankle, 4),
          "knee_deg", round(max_knee, 4), "sole_mm", round(max_sole, 4), "raised_mm", round(max_raised, 4))

print("== exceptions ==")
r = next(r for r in groups[("F0", "a050_300010")] if int(r["frame"]) == 15)
print("300010 f15 knees (candidate F0):", r["l_knee_deg"], r["r_knee_deg"])
for cfg in ("F0", "FP", "FM"):
    r = next(r for r in groups[(cfg, "a050_301000")] if int(r["frame"]) == 0)
    print(cfg, "301000 f0 mesh_world", r["mesh_lowest_world_mm"],
          "soles_rel", r["l_sole_rel_mm"], r["r_sole_rel_mm"])

print("== F2 T2 vs F0 (normalized) ==")
for act in ("a050_300000", "a050_301000"):
    t2 = {int(r["frame"]): r for r in groups[("T2", act)]}
    f0 = {int(r["frame"]): r for r in groups[("F0", act)]}
    dsole = dknee = dankle = dpelvis = 0.0
    for f, r in t2.items():
        a = f0[f]
        dpelvis = max(dpelvis, abs((vec(r["pelvis"])[2] - 0.05) - vec(a["pelvis"])[2]) * 1000,
                      abs(vec(r["pelvis"])[0] - vec(a["pelvis"])[0]) * 1000,
                      abs(vec(r["pelvis"])[1] - vec(a["pelvis"])[1]) * 1000)
        for s in ("l", "r"):
            dsole = max(dsole, abs(float(r[s + "_sole_rel_mm"]) - float(a[s + "_sole_rel_mm"])))
            dknee = max(dknee, abs(float(r[s + "_knee_deg"]) - float(a[s + "_knee_deg"])))
            dankle = max(dankle, abs((vec(r[s + "_ankle"])[2] - 0.05) - vec(a[s + "_ankle"])[2]) * 1000)
    print(act, "sole_rel", round(dsole, 4), "knee", round(dknee, 4), "ankleZ_norm", round(dankle, 4), "pelvis_norm", round(dpelvis, 4))

print("== T3 vs F0 ==")
t3 = {int(r["frame"]): r for r in groups[("T3", "a050_300000")]}
f0 = {int(r["frame"]): r for r in groups[("F0", "a050_300000")]}
dknee = dsole = 0.0
worst = []
for f, r in t3.items():
    a = f0[f]
    for s in ("l", "r"):
        dsole = max(dsole, abs(float(r[s + "_sole_rel_mm"]) - float(a[s + "_sole_rel_mm"])))
        d = abs(float(r[s + "_knee_deg"]) - float(a[s + "_knee_deg"]))
        if d > dknee:
            dknee = d
            worst = [(f, s, a[s + "_knee_deg"], r[s + "_knee_deg"])]
print("sole_rel_max_diff", round(dsole, 4), "knee_max_diff", round(dknee, 4), worst)
print("T3 sole_rel_min", round(min(float(r[s + "_sole_rel_mm"]) for r in t3.values() for s in ("l", "r")), 3))

print("== SRC_RAISED (source +30mm, floor 0) ==")
g = groups[("SRC_RAISED", "a050_300000")]
print("sole_rel min/median:", round(min(float(r[s + "_sole_rel_mm"]) for r in g for s in ("l", "r")), 3),
      sorted(float(r[s + "_sole_rel_mm"]) for r in g for s in ("l", "r"))[len(g):][0] if False else "")
