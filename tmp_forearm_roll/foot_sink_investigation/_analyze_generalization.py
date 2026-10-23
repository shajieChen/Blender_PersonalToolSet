import csv
import json
import math
import pathlib

base = pathlib.Path(r"H:\Blender_Plugin\tmp_forearm_roll\foot_sink_investigation")
rows = list(csv.DictReader((base / "generalization_frames.csv").open(newline="", encoding="utf-8-sig")))


def vec(s):
    return json.loads(s)


def dist(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(vec(a), vec(b)))) * 1000


groups = {}
for r in rows:
    groups.setdefault((r["config"], r["action"]), []).append(r)

for (cfg, act), g in groups.items():
    allsole = [float(r[s + "_sole_rel_mm"]) for r in g for s in ("l", "r")]
    contact = [float(r[s + "_sole_rel_mm"]) for r in g for s in ("l", "r") if r[s + "_contact"] == "True"]
    swing = [float(r[s + "_sole_rel_mm"]) for r in g for s in ("l", "r") if r[s + "_contact"] == "False"]
    deep = sum(1 for r in g if min(float(r["l_sole_rel_mm"]), float(r["r_sole_rel_mm"])) < -10)
    errs = max(max(float(r["l_err_mm"]), float(r["r_err_mm"])) for r in g)
    knees = min(min(float(r["l_knee_deg"]), float(r["r_knee_deg"])) for r in g)
    knee15 = sum(1 for r in g for s in ("l", "r") if round(float(r[s + "_knee_deg"]), 3) < 15)
    raised = max(max(float(r["l_recheck_raised_mm"] or 0), float(r["r_recheck_raised_mm"] or 0)) for r in g)
    meshmin = min(float(r["mesh_lowest_rel_mm"]) for r in g)
    nonfoot = sum(1 for r in g if float(r["mesh_lowest_rel_mm"]) < -10
                  and min(float(r["l_sole_rel_mm"]), float(r["r_sole_rel_mm"])) >= -1)
    lens = {(round(float(r["l_upper_len"]), 4), round(float(r["l_lower_len"]), 4)) for r in g}
    print(cfg, act, "n=", len(g), "sole_min=", round(min(allsole), 3), "deepFr=", deep,
          "mesh_min=", round(meshmin, 3), "nonfootDeepFr=", nonfoot, "err=", round(errs, 3),
          "knee_min=", round(knees, 3), "knee<15=", knee15, "raised_max=", round(raised, 1),
          "plan=", g[0]["plan_size"], "lens=", sorted(lens)[:2])
    if contact:
        print("   contact n=", len(contact), "min=", round(min(contact), 3),
              "below-1=", sum(x < -1 for x in contact), "float>2=", sum(x > 2 for x in contact),
              "max=", round(max(contact), 3))
    if swing:
        print("   swing n=", len(swing), "min=", round(min(swing), 3),
              "below-1=", sum(x < -1 for x in swing), "in[-1,2]=", sum(-1 <= x <= 2 for x in swing))

on = {r["frame"]: r for r in groups[("STACK_ON", "a050_301000")]}
off = {r["frame"]: r for r in groups[("STACK_OFF", "a050_301000")]}
for key in ("pelvis", "spine", "head", "l_hand", "r_hand", "l_ankle", "r_ankle"):
    print("301000 on-vs-off max", key, round(max(dist(on[f][key], off[f][key]) for f in on), 3), "mm")
for s in ("l", "r"):
    sw = [f for f in on if on[f][s + "_contact"] == "False"]
    ct = [f for f in on if on[f][s + "_contact"] == "True"]
    if sw:
        print(" swing ankle diff", s, round(max(dist(on[f][s + "_ankle"], off[f][s + "_ankle"]) for f in sw), 3), "n", len(sw))
    if ct:
        print(" contact ankle diff", s, round(max(dist(on[f][s + "_ankle"], off[f][s + "_ankle"]) for f in ct), 3), "n", len(ct))

p0 = {r["frame"]: r for r in groups[("P0", "a050_300000")]}
hon = {r["frame"]: r for r in groups[("HAND_ON", "a050_300000")]}
print("HAND_ON hand err max mm", max(max(float(r["l_hand_err_mm"]), float(r["r_hand_err_mm"])) for r in hon.values()))
print("HAND_ON vs OFF hand pos max mm", round(max(max(dist(hon[f]["l_hand"], p0[f]["l_hand"]), dist(hon[f]["r_hand"], p0[f]["r_hand"])) for f in p0), 3))
print("HAND_ON sole min", min(min(float(r["l_sole_rel_mm"]), float(r["r_sole_rel_mm"])) for r in hon.values()))

for (cfg, act), g in groups.items():
    hi = [(r["frame"], s, round(float(r[s + "_sole_rel_mm"]), 1)) for r in g for s in ("l", "r")
          if r[s + "_contact"] == "True" and float(r[s + "_sole_rel_mm"]) > 50]
    lo = [(r["frame"], s, round(float(r[s + "_sole_rel_mm"]), 1)) for r in g for s in ("l", "r")
          if r[s + "_contact"] == "False" and float(r[s + "_sole_rel_mm"]) < -1]
    if hi or lo:
        print(cfg, act, "contact-but->50mm", len(hi), hi[:4], "| swing-but-below-1", len(lo), lo[:4])

# Floor groups: sole world should cluster near floor height if goals follow it.
for cfg in ("FLOOR_P50", "FLOOR_M50"):
    g = groups[(cfg, "a050_300000")]
    world = [float(r[s + "_sole_world_mm"]) for r in g for s in ("l", "r")]
    rel = [float(r[s + "_sole_rel_mm"]) for r in g for s in ("l", "r")]
    print(cfg, "sole_world min/max", round(min(world), 3), round(max(world), 3),
          "sole_rel min", round(min(rel), 3), "contact below floor-1:",
          sum(1 for r in g for s in ("l", "r") if r[s + "_contact"] == "True" and float(r[s + "_sole_rel_mm"]) < -1))
