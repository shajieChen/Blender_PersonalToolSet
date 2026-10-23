"""IK contact regression protection for the archived 1.7.5 decision.

Two modes:

1. Archive check (plain Python, no Blender)::

       python test_ik_contact_regression.py --check-archive

   Validates root_comp_frames.csv, adaptive_frames.csv and
   cross_frames.csv against the baselines recorded in
   ik_contact_decision.md, including the rejected B/C evidence.

2. Blender rebake (headless, official installed addon read-only)::

       blender.exe --background --factory-startup --python-exit-code 1 \
           --python test_ik_contact_regression.py

   Rebakes only group A (existing redirect + contact stack) for the four
   verified clips with the official 1.7.5 code and compares every frame
   against the archived A rows in cross_frames.csv. The official addon,
   the live scene, the source assets and existing bakes are never written.
"""

import csv
import json
import math
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CROSS_CSV = HERE / "cross_frames.csv"
ADAPTIVE_CSV = HERE / "adaptive_frames.csv"
ROOT_CSV = HERE / "root_comp_frames.csv"
OUT_CSV = HERE / "ik_contact_regression_frames.csv"

OFFICIAL_VERSION = (1, 7, 5)
OFFICIAL_IK_SHA256 = "AD87866E49A40A711A3344C1868CE54A768DA779BA29B355C523E4F7A84A6A08"

SOURCE_GLB = r"h:\SErsiko_ExtactedTool\output\c0000_突刺_wp_a_0300.glb"
TARGET_FBX = r"c:\Users\chenshajie1\Downloads\body.FBX"
CLIPS = ("a050_300000", "a050_300010", "a050_301000", "a050_302011")
REST_UPPER_M = 0.254161
REST_LOWER_M = 0.190716

# Archived A-group baselines, recomputed from cross_frames.csv.
# sole/mesh/error/recheck are millimetres, knee is the interior angle.
BASELINE = {
    "a050_300000": {"sole_min": -1.000, "mesh_min": -1.000, "max_err": 0.043,
                    "knee_min": 15.000, "knee_lt15_feet": 0, "max_recheck": 163.0},
    "a050_300010": {"sole_min": -1.000, "mesh_min": -2.588, "max_err": 0.056,
                    "knee_min": 12.942, "knee_lt15_feet": 1, "max_recheck": 149.9},
    "a050_301000": {"sole_min": -0.999, "mesh_min": -61.042, "max_err": 0.041,
                    "knee_min": 15.000, "knee_lt15_feet": 0, "max_recheck": 160.6},
    "a050_302011": {"sole_min": -0.996, "mesh_min": -0.996, "max_err": 0.048,
                    "knee_min": 15.000, "knee_lt15_feet": 0, "max_recheck": 160.3},
}
# Group B foot-deep frame counts (frame counted once if either sole < -10 mm).
B_DEEP_FRAMES = {"a050_300000": 9, "a050_300010": 19, "a050_301000": 16, "a050_302011": 14}


class Check:
    def __init__(self):
        self.failures = []

    def expect(self, condition, message):
        if condition:
            print("PASS", message)
        else:
            print("FAIL", message)
            self.failures.append(message)

    def finish(self, label):
        if self.failures:
            print(label + "_FAIL", len(self.failures))
            for message in self.failures:
                print(" -", message)
            return 1
        print(label + "_PASS")
        return 0


def load_csv(path):
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def vec(text):
    return json.loads(text)


def dist_mm(left, right):
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(vec(left), vec(right)))) * 1000.0


def sole_mm(row, side):
    return float(row[side + "_sole_z"]) * 1000.0


def check_archive():
    check = Check()
    cross = load_csv(CROSS_CSV)
    adaptive = load_csv(ADAPTIVE_CSV)
    root = load_csv(ROOT_CSV)
    check.expect(len(cross) == 636, "cross_frames.csv has 636 rows")
    check.expect(len(adaptive) == 371, "adaptive_frames.csv has 371 rows")
    check.expect(len(root) == 424, "root_comp_frames.csv has 424 rows")
    actions = sorted({row["action"] for row in cross if row["config"] == "A"})
    check.expect(actions == sorted(CLIPS), "cross A actions are the four verified clips")

    for action in CLIPS:
        rows = [r for r in cross if r["config"] == "A" and r["action"] == action]
        base = BASELINE[action]
        check.expect(len(rows) == 53 and [int(r["frame"]) for r in rows] == list(range(53)),
                     action + " A covers frames 0-52")
        sole_min = min(min(sole_mm(r, "l"), sole_mm(r, "r")) for r in rows)
        mesh_min = min(float(r["mesh_lowest"]) * 1000.0 for r in rows)
        max_err = max(max(float(r["l_err_mm"]), float(r["r_err_mm"])) for r in rows)
        knee_min = min(min(float(r["l_knee_deg"]), float(r["r_knee_deg"])) for r in rows)
        knee_lt15 = sum(1 for r in rows for s in ("l", "r") if float(r[s + "_knee_deg"]) < 15.0)
        max_recheck = max(max(float(r["l_recheck_raised_mm"] or 0),
                              float(r["r_recheck_raised_mm"] or 0)) for r in rows)
        check.expect(abs(sole_min - base["sole_min"]) <= 0.01, action + " A sole min matches baseline")
        check.expect(abs(mesh_min - base["mesh_min"]) <= 0.01, action + " A mesh min matches baseline")
        check.expect(abs(max_err - base["max_err"]) <= 0.002, action + " A solver error matches baseline")
        check.expect(abs(knee_min - base["knee_min"]) <= 0.01, action + " A knee min matches baseline")
        check.expect(knee_lt15 == base["knee_lt15_feet"], action + " A knee<15 foot count matches baseline")
        check.expect(abs(max_recheck - base["max_recheck"]) <= 0.2, action + " A recheck/plan lift matches baseline")
        deep_b = sum(1 for r in cross
                     if r["config"] == "B" and r["action"] == action
                     and min(sole_mm(r, "l"), sole_mm(r, "r")) < -10.0)
        check.expect(deep_b == B_DEEP_FRAMES[action], action + " B deep-frame evidence intact")
        bones_ok = all(abs(float(r[s + "_upper_len"]) - REST_UPPER_M) < 5e-4
                       and abs(float(r[s + "_lower_len"]) - REST_LOWER_M) < 5e-4
                       for r in rows for s in ("l", "r"))
        check.expect(bones_ok, action + " A bone lengths stay on the rest baseline")

    def find(config, action, frame):
        return next(r for r in cross if r["config"] == config
                    and r["action"] == action and int(r["frame"]) == frame)

    row0 = find("A", "a050_301000", 0)
    check.expect(float(row0["mesh_lowest"]) * 1000.0 < -50.0
                 and sole_mm(row0, "l") > 0.0 and sole_mm(row0, "r") > 0.0,
                 "a050_301000 frame 0 penetration is non-foot (mesh only)")
    knee_row = find("A", "a050_300010", 15)
    check.expect(abs(float(knee_row["r_knee_deg"]) - 12.942) <= 0.01,
                 "known baseline knee exception a050_300010 frame 15 right = 12.942 deg")
    b0 = find("B", "a050_300010", 0)
    check.expect(sole_mm(b0, "r") < -20.0 and b0["r_pre_contact"] == "False",
                 "B misses a penetrating foot classified as non-contact")
    a10 = find("A", "a050_300010", 10)
    c10 = find("C", "a050_300010", 10)
    check.expect(abs(float(c10["r_pre_corr_mm"]) - 10.289) <= 0.01
                 and abs(sole_mm(c10, "r") - sole_mm(a10, "r") - float(c10["r_pre_corr_mm"])) <= 0.05
                 and abs(float(c10["r_recheck_raised_mm"]) - float(a10["r_recheck_raised_mm"])) <= 0.01,
                 "C double compensation equals the pre-correction amount")
    pelvis_max = 0.0
    swing_max = 0.0
    for row in cross:
        if row["config"] != "C":
            continue
        ref = find("A", row["action"], int(row["frame"]))
        pelvis_max = max(pelvis_max, dist_mm(row["pelvis"], ref["pelvis"]),
                         dist_mm(row["head"], ref["head"]))
        for side in ("l", "r"):
            if sole_mm(ref, side) > 20.0:
                swing_max = max(swing_max, dist_mm(row[side + "_ankle"], ref[side + "_ankle"]))
    check.expect(pelvis_max <= 0.001, "C leaves pelvis/head on A (no hip compensation)")
    check.expect(swing_max <= 0.01, "C leaves swing ankles on A within 0.01 mm")

    hip = [float(r["hip_delta_mm"]) for r in adaptive
           if r["config"] == "C" and r["hip_delta_mm"] not in ("", None)]
    check.expect(len([v for v in hip if v > 0]) == 14 and max(hip) <= 1.001,
                 "adaptive C compensation is nonzero on 14 frames and <= 1 mm")
    folded = [r for r in root if r["config"] == "R30" and r["action"] == "a050_300000"
              and int(r["frame"]) == 17]
    check.expect(bool(folded) and float(folded[0]["l_knee_deg"]) < 1.0,
                 "fixed 30 mm root lift collapses the folded leg at frame 17")
    return check.finish("ARCHIVE_REGRESSION")


def run_blender():
    import hashlib

    import bpy
    from mathutils import Quaternion, Vector

    addons = Path(bpy.utils.resource_path("USER")) / "scripts" / "addons"
    if not (addons / "humanoid_retarget").is_dir():
        addons = Path(os.environ["APPDATA"]) / "Blender Foundation" / "Blender" / "5.1" / "scripts" / "addons"
    sys.path.insert(0, str(addons))
    for name in list(sys.modules):
        if name == "humanoid_retarget" or name.startswith("humanoid_retarget."):
            del sys.modules[name]

    check = Check()
    import humanoid_retarget
    import humanoid_retarget.ik as ik_module
    import humanoid_retarget.retarget as retarget
    from humanoid_retarget.foot_ik import FootIKSettings
    from humanoid_retarget.mapping import build_pairs
    from humanoid_retarget import pipeline

    module_root = Path(humanoid_retarget.__file__).resolve().parent
    check.expect(str(module_root).lower().startswith(str(addons.resolve()).lower()),
                 "imports the installed addon, not the workspace copy: " + str(module_root))
    check.expect(tuple(humanoid_retarget.bl_info["version"]) == OFFICIAL_VERSION,
                 "official addon version is 1.7.5")
    digest = hashlib.sha256((module_root / "ik.py").read_bytes()).hexdigest().upper()
    check.expect(digest == OFFICIAL_IK_SHA256, "official ik.py hash matches archived 1.7.5")
    check.expect(Path(SOURCE_GLB).is_file() and Path(TARGET_FBX).is_file(),
                 "source and target assets exist for a credible baseline")
    if check.failures:
        return check.finish("BLENDER_REGRESSION")

    archived = {(r["action"], int(r["frame"])): r for r in load_csv(CROSS_CSV)
                if r["config"] == "A"}
    bpy.ops.wm.read_factory_settings(use_empty=True)
    # read_factory_settings drops the path insert's modules; re-import cleanly.
    if "humanoid_retarget" not in sys.modules:
        import humanoid_retarget  # noqa: F401
        import humanoid_retarget.ik as ik_module
        import humanoid_retarget.retarget as retarget
        from humanoid_retarget.foot_ik import FootIKSettings
        from humanoid_retarget.mapping import build_pairs
        from humanoid_retarget import pipeline

    source, _ = pipeline.load_source(SOURCE_GLB)
    objects, _ = pipeline.import_model(TARGET_FBX)
    target = pipeline.pick_armature(objects)
    mesh = next(obj for obj in bpy.data.objects if obj.type == "MESH" and obj.parent == target)
    pairs = build_pairs(source, target)
    roles = {role: (src_name, tgt_name) for role, src_name, tgt_name in pairs}
    actions = {item.name: item for item in retarget.collect_actions(source) if item.name in CLIPS}
    check.expect(sorted(actions) == sorted(CLIPS), "all four verified clips are present")
    if check.failures:
        return check.finish("BLENDER_REGRESSION")

    holder = {"action": None}
    retarget.collect_actions = lambda _src: [holder["action"]]
    settings = FootIKSettings(floor_enabled=True, floor_alpha=1.0, floor_height_m=0.0)
    solve_err = {}
    real_solve = ik_module._solve_chain

    def recording_solve(tgt, space, reference, goal, pole_hint=None):
        distance = real_solve(tgt, space, reference, goal, pole_hint=pole_hint)
        solve_err[(bpy.context.scene.frame_current, reference.roles[2])] = float(distance)
        return distance

    ik_module._solve_chain = recording_solve

    def reset_pose():
        if target.animation_data:
            target.animation_data_clear()
        for pose_bone in target.pose.bones:
            pose_bone.rotation_mode = "QUATERNION"
            pose_bone.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
            pose_bone.location = (0.0, 0.0, 0.0)
            pose_bone.scale = (1.0, 1.0, 1.0)
        bpy.context.view_layer.update()

    def sole_lowest(foot_name):
        deps = bpy.context.evaluated_depsgraph_get()
        evaluated = mesh.evaluated_get(deps)
        posed = evaluated.to_mesh()
        world = evaluated.matrix_world
        group_index = {group.name: group.index for group in mesh.vertex_groups}
        overall = None
        sole = None
        for vertex in posed.vertices:
            point = world @ vertex.co
            if overall is None or point.z < overall:
                overall = point.z
            idx = group_index.get(foot_name)
            if idx is not None:
                weight = next((item.weight for item in vertex.groups if item.group == idx), 0.0)
                if weight > 0.5 and (sole is None or point.z < sole):
                    sole = point.z
        evaluated.to_mesh_clear()
        return float(overall), float(sole)

    def head(name):
        return target.matrix_world @ target.pose.bones[name].head

    out_rows = []
    for action_name in CLIPS:
        reset_pose()
        holder["action"] = actions[action_name]
        retarget._assign_action(source, actions[action_name])
        ik_module.clear_correction_plan_cache()
        ik_module._CORRECTION_PLAN = None
        ik_module._LAST_PLAN = None
        ik_module.CONTACT_LOG.clear()
        solve_err.clear()
        options = retarget.RetargetOptions(
            pairs=pairs, root_motion="KEEP", reference="REST",
            foot_ik=True, hand_ik=False, foot_ik_settings=settings,
            contact_min_knee_deg=15.0, correction_smoothing="height",
        )
        retarget.bake_retarget(source, target, options)
        contact_log = list(ik_module.CONTACT_LOG)
        plan = dict(ik_module._LAST_PLAN or {})
        for pose_bone in target.pose.bones:
            pose_bone.scale = (1.0, 1.0, 1.0)

        soles, knees, errs = [], [], []
        deep_frames = 0
        max_body_diff = 0.0
        max_swing_diff = 0.0
        max_ground_float = 0.0
        max_foot_angle = 0.0
        bones_ok = True
        for frame in range(0, 53):
            bpy.context.scene.frame_set(frame)
            bpy.context.view_layer.update()
            ref = archived[(action_name, frame)]
            row = {"action": action_name, "frame": frame}
            body_diff = max(
                (head(roles["hips"][1]) - Vector(vec(ref["pelvis"]))).length,
                (head(roles["head"][1]) - Vector(vec(ref["head"]))).length,
            ) * 1000.0
            max_body_diff = max(max_body_diff, body_diff)
            frame_soles = []
            for side in ("l", "r"):
                thigh = head(roles["thigh_" + side][1])
                knee = head(roles["shin_" + side][1])
                ankle = head(roles["foot_" + side][1])
                _overall, sole = sole_lowest(roles["foot_" + side][1])
                if side == "l":
                    mesh_low = _overall
                frame_soles.append(sole * 1000.0)
                soles.append(sole * 1000.0)
                first, second = thigh - knee, ankle - knee
                knee_deg = math.degrees(first.angle(second))
                knees.append(knee_deg)
                errs.append(solve_err.get((frame, "foot_" + side), 0.0) * 1000.0)
                if abs((knee - thigh).length - REST_UPPER_M) > 5e-4 or \
                        abs((ankle - knee).length - REST_LOWER_M) > 5e-4:
                    bones_ok = False
                ankle_diff = (ankle - Vector(vec(ref[side + "_ankle"]))).length * 1000.0
                ref_sole = sole_mm(ref, side)
                if ref_sole > 20.0:
                    max_swing_diff = max(max_swing_diff, ankle_diff)
                if ref_sole <= 2.0:
                    max_ground_float = max(max_ground_float, sole * 1000.0 - ref_sole)
                foot_q = (target.matrix_world
                          @ target.pose.bones[roles["foot_" + side][1]].matrix).to_quaternion().normalized()
                ref_q = Quaternion(vec(ref[side + "_foot_quat"])).normalized()
                max_foot_angle = max(max_foot_angle, math.degrees(foot_q.rotation_difference(ref_q).angle))
                row[side + "_sole_mm"] = round(sole * 1000.0, 3)
                row[side + "_knee_deg"] = round(knee_deg, 3)
                row[side + "_ankle_diff_mm"] = round(ankle_diff, 3)
            row["mesh_lowest_mm"] = round(mesh_low * 1000.0, 3)
            row["body_diff_mm"] = round(body_diff, 3)
            if min(frame_soles) < -10.0:
                deep_frames += 1
            out_rows.append(row)

        base = BASELINE[action_name]
        raised = [entry[6] * 1000.0 for entry in contact_log]
        check.expect(len(contact_log) == 106, action_name + " contact log has both feet for 53 frames")
        check.expect(bool(plan) and max(raised or [0.0]) > 50.0,
                     action_name + " height plan and recheck actually engage")
        check.expect(min(soles) >= -1.5 and min(soles) >= base["sole_min"] - 0.5,
                     action_name + " contact sole stays within the -1 mm tolerance band")
        check.expect(deep_frames == 0, action_name + " has no foot sole below -10 mm")
        check.expect(max(errs) <= 0.10, action_name + " ankle solver error <= 0.10 mm")
        check.expect(min(knees) >= base["knee_min"] - 0.5,
                     action_name + " knee minimum does not regress past the archived baseline")
        # Archived CSV stores knee angles rounded to 3 decimals, so count
        # with the same rounding; frames sitting exactly on 15.000 deg
        # otherwise flip on sub-millidegree jitter. The unrounded
        # knee-minimum check above still guards the magnitude.
        knee_lt15 = sum(1 for value in knees if round(value, 3) < 15.0)
        print("KNEE_LT15", action_name, knee_lt15, "baseline", base["knee_lt15_feet"], flush=True)
        check.expect(knee_lt15 <= base["knee_lt15_feet"],
                     action_name + " adds no new knee<15 foot-frames beyond the known exception")
        check.expect(max_body_diff <= 2.0, action_name + " pelvis/head stay on the archived A trajectory")
        check.expect(max_swing_diff <= 2.0, action_name + " swing ankles are not pressed toward the floor")
        check.expect(max_ground_float <= 3.0, action_name + " grounded feet do not float past baseline + 3 mm")
        check.expect(max_foot_angle <= 1.0, action_name + " foot orientation stays within 1 degree of A")
        check.expect(bones_ok, action_name + " posed bone lengths stay on the rest baseline")
        print("ACTION_DONE", action_name, "sole_min_mm", round(min(soles), 3),
              "max_err_mm", round(max(errs), 3), "max_recheck_mm", round(max(raised or [0.0]), 1),
              flush=True)

    frame0 = next(r for r in out_rows if r["action"] == "a050_301000" and r["frame"] == 0)
    check.expect(frame0["mesh_lowest_mm"] < -50.0 and frame0["l_sole_mm"] > 0.0
                 and frame0["r_sole_mm"] > 0.0,
                 "rebaked a050_301000 frame 0 still separates non-foot mesh penetration")

    with OUT_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(out_rows[0].keys()))
        writer.writeheader()
        writer.writerows(out_rows)
    print("WROTE", OUT_CSV)
    return check.finish("BLENDER_REGRESSION")


def main():
    if "--check-archive" in sys.argv:
        return check_archive()
    try:
        import bpy  # noqa: F401
    except ImportError:
        print("Blender not available; running archive check only.")
        return check_archive()
    return run_blender()


if __name__ == "__main__":
    sys.exit(main())
