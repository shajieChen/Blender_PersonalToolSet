"""Scheme-A calf-roll experiment: FK / T3 baseline / A / FK-with-switch scan.

Fresh headless Blender, loads the EXPERIMENT COPY of the plugin only.
No save. Writes one combined CSV.

Usage: blender --background --factory-startup --python-exit-code 1 \
  --python calf_roll_fix_scan.py -- <out_csv>
"""
import csv
import json
import math
import sys

import bpy

COPY = r"H:\Blender_Plugin\tmp_forearm_roll"
SOURCE = r"h:\SErsiko_ExtactedTool\output\c0000_突刺_wp_a_0300.glb"
TARGET = r"c:\Users\chenshajie1\Downloads\body.FBX"


def chain_roll(arm, bone_name, child_name):
    from mathutils import Quaternion, Vector

    pose_bone = arm.pose.bones[bone_name]
    rest = pose_bone.bone.matrix_local.to_3x3()
    delta = pose_bone.matrix.to_3x3() @ rest.inverted()
    quat = delta.to_quaternion()
    if quat.w < 0.0:
        quat.negate()
    axis = (arm.pose.bones[child_name].head - pose_bone.head).normalized()
    vector = Vector((quat.x, quat.y, quat.z))
    projected = axis * vector.dot(axis)
    twist = Quaternion((quat.w, projected.x, projected.y, projected.z))
    if twist.magnitude < 1e-10:
        return 0.0
    twist.normalize()
    angle = 2.0 * math.degrees(math.acos(max(-1.0, min(1.0, abs(twist.w)))))
    if Vector((twist.x, twist.y, twist.z)).dot(axis) < 0.0:
        angle = -angle
    return angle


def angle_deg(a, b, c):
    first = a - b
    second = c - b
    if first.length < 1e-9 or second.length < 1e-9:
        return None
    return round(math.degrees(first.angle(second)), 3)


def vec_json(v):
    return json.dumps([round(float(x), 5) for x in v])


def main():
    out_csv = sys.argv[sys.argv.index("--") + 1]
    sys.path.insert(0, COPY)
    for name in list(sys.modules):
        if name == "humanoid_retarget" or name.startswith("humanoid_retarget."):
            del sys.modules[name]
    bpy.ops.wm.read_factory_settings(use_empty=True)
    from humanoid_retarget.mapping import build_pairs
    from humanoid_retarget import pipeline
    import humanoid_retarget.retarget as retarget
    import humanoid_retarget.ik as ik_module
    from humanoid_retarget.foot_ik import FootIKSettings

    solve_err = {}
    original_solve = ik_module._solve_chain

    def recording_solve(tgt, space, reference, goal, pole_hint=None):
        distance = original_solve(tgt, space, reference, goal, pole_hint=pole_hint)
        solve_err[(bpy.context.scene.frame_current, reference.roles[2])] = round(float(distance), 5)
        return distance

    ik_module._solve_chain = recording_solve

    source, _ = pipeline.load_source(SOURCE)
    objects, _ = pipeline.import_model(TARGET)
    target = pipeline.pick_armature(objects)
    mesh = next(obj for obj in bpy.data.objects if obj.type == "MESH" and obj.parent == target)
    action = next(item for item in retarget.collect_actions(source) if item.name == "a050_300000")
    retarget._assign_action(source, action)
    retarget.collect_actions = lambda _src: [action]
    pairs = build_pairs(source, target)
    roles = {role: (s, t) for role, s, t in pairs}
    start, end = (int(action.frame_range[0]), int(round(action.frame_range[1])))
    print("RANGE", start, end, "TARGET", target.name, "MESH", mesh.name, flush=True)

    groups = [list(vertex.groups) for vertex in mesh.data.vertices]
    region_indexes = {}
    for side in ("l", "r"):
        names = {roles["shin_" + side][1], roles["foot_" + side][1]}
        names.update(child.name for child in target.data.bones[roles["foot_" + side][1]].children)
        region_indexes[side] = {g.index for g in mesh.vertex_groups if g.name in names}

    def world(name):
        return target.matrix_world @ target.pose.bones[name].head

    def scan(tag):
        rows = []
        for frame in range(start, end + 1):
            bpy.context.scene.frame_set(frame)
            bpy.context.view_layer.update()
            deps = bpy.context.evaluated_depsgraph_get()
            evaluated = mesh.evaluated_get(deps)
            posed = evaluated.to_mesh()
            world_matrix = evaluated.matrix_world
            all_z = []
            region_z = {"l": [], "r": []}
            for vertex in posed.vertices:
                point = world_matrix @ vertex.co
                all_z.append(point.z)
                for side in ("l", "r"):
                    if any(item.group in region_indexes[side] and item.weight > 0.2 for item in groups[vertex.index]):
                        region_z[side].append(point.z)
            evaluated.to_mesh_clear()
            row = {"config": tag, "frame": frame}
            for side in ("l", "r"):
                thigh_n = roles["thigh_" + side][1]
                shin_n = roles["shin_" + side][1]
                foot_n = roles["foot_" + side][1]
                thigh = world(thigh_n)
                knee = world(shin_n)
                ankle = world(foot_n)
                toe_name = next(c.name for c in target.pose.bones[foot_n].children if "toe" in c.name.lower())
                toe = world(toe_name)
                row[side + "_roll"] = round(chain_roll(target, shin_n, foot_n), 3)
                row[side + "_thigh_roll"] = round(chain_roll(target, thigh_n, shin_n), 3)
                row[side + "_thigh_dir"] = vec_json((knee - thigh).normalized())
                row[side + "_shin_dir"] = vec_json((ankle - knee).normalized())
                row[side + "_knee_pos"] = vec_json(knee)
                row[side + "_ankle_pos"] = vec_json(ankle)
                row[side + "_knee_deg"] = angle_deg(thigh, knee, ankle)
                row[side + "_upper_len"] = round((knee - thigh).length, 5)
                row[side + "_lower_len"] = round((ankle - knee).length, 5)
                row[side + "_err"] = solve_err.get((frame, "foot_" + side))
                foot_bone = target.pose.bones[foot_n]
                row[side + "_foot_quat"] = vec_json((target.matrix_world @ foot_bone.matrix).to_quaternion())
                row[side + "_toe_dir"] = vec_json((toe - ankle).normalized())
                row[side + "_toe_z"] = round(toe.z, 4)
                row[side + "_region_lowest"] = round(min(region_z[side]), 4) if region_z[side] else None
            row["mesh_lowest"] = round(min(all_z), 4)
            row["mesh_below"] = sum(1 for value in all_z if value < -0.001)
            row["hips_z"] = round(world(roles["hips"][1]).z, 4)
            rows.append(row)
        return rows

    settings = FootIKSettings(floor_enabled=True, floor_alpha=1.0, floor_height_m=0.0)

    def bake(tag, foot_ik, roll_fix):
        solve_err.clear()
        ik_module.CALF_ROLL_LOG.clear()
        ik_module._CALF_ROLL_FIX_ENABLED = roll_fix
        options = retarget.RetargetOptions(
            pairs=pairs, root_motion="KEEP", reference="REST",
            foot_ik=foot_ik, hand_ik=False,
            foot_ik_settings=settings,
            contact_min_knee_deg=15.0, correction_smoothing="height",
        )
        report, _ = retarget.bake_retarget(source, target, options)
        print("BAKE", tag, "roll_fix", roll_fix, report.replace("\n", " | ")[:300], flush=True)
        if roll_fix:
            worst = max(ik_module.CALF_ROLL_LOG, key=lambda e: abs(e[3]), default=None)
            print("ROLLLOG", tag, "entries", len(ik_module.CALF_ROLL_LOG), "worst_after", worst, flush=True)
            for frame in (15, 16, 17, 18):
                for role in ("foot_l", "foot_r"):
                    entries = [e for e in ik_module.CALF_ROLL_LOG if e[0] == frame and e[1] == role]
                    if entries:
                        print("ROLLLOG_FRAME", frame, role, "last", entries[-1], "n", len(entries), flush=True)
        rows = scan(tag)
        ik_module._CALF_ROLL_FIX_ENABLED = False
        return rows

    all_rows = []
    all_rows += bake("FK", foot_ik=False, roll_fix=False)
    all_rows += bake("BASE", foot_ik=True, roll_fix=False)
    all_rows += bake("A", foot_ik=True, roll_fix=True)
    all_rows += bake("FK_A", foot_ik=False, roll_fix=True)

    keys = list(all_rows[0].keys())
    with open(out_csv, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        writer.writerows(all_rows)

    by = {(r["config"], r["frame"]): r for r in all_rows}

    def wrap(d):
        return (d + 180.0) % 360.0 - 180.0

    for tag in ("FK", "BASE", "A", "FK_A"):
        rows = [r for r in all_rows if r["config"] == tag]
        for side in ("l", "r"):
            series = {r["frame"]: r[side + "_roll"] for r in rows}
            steps = [abs(wrap(series[f] - series[f - 1])) for f in series if f > start]
            print("SUMMARY", tag, side, "max_abs_roll", max(series.items(), key=lambda kv: abs(kv[1])),
                  "max_step", round(max(steps), 3), flush=True)
        print("SUMMARY", tag, "mesh_min", min(r["mesh_lowest"] for r in rows),
              "frames_below_-0.01", sum(1 for r in rows if r["mesh_lowest"] < -0.01),
              "frames_below_-0.001", sum(1 for r in rows if r["mesh_lowest"] < -0.001), flush=True)

    # Focus frames 15-18: BASE vs A
    for frame in (15, 16, 17, 18):
        b, a = by[("BASE", frame)], by[("A", frame)]
        for side in ("l", "r"):
            bd = json.loads(b[side + "_shin_dir"]); ad = json.loads(a[side + "_shin_dir"])
            dot = max(-1.0, min(1.0, sum(x * y for x, y in zip(bd, ad))))
            print("FOCUS", frame, side, "roll", b[side + "_roll"], "->", a[side + "_roll"],
                  "shin_dir_deg", round(math.degrees(math.acos(dot)), 4),
                  "knee_deg", b[side + "_knee_deg"], "->", a[side + "_knee_deg"],
                  "err", b[side + "_err"], "->", a[side + "_err"], flush=True)

    # FK invariance (FK vs FK_A): rolls and foot quats must match exactly-ish
    fk_diffs = []
    for frame in range(start, end + 1):
        f0, f1 = by[("FK", frame)], by[("FK_A", frame)]
        for side in ("l", "r"):
            fk_diffs.append(abs(f0[side + "_roll"] - f1[side + "_roll"]))
            fk_diffs.append(max(abs(float(x) - float(y)) for x, y in zip(json.loads(f0[side + "_foot_quat"]), json.loads(f1[side + "_foot_quat"]))))
    print("FK_INVARIANCE max_diff", max(fk_diffs), flush=True)
    print("DONE", out_csv, flush=True)


if __name__ == "__main__":
    main()
