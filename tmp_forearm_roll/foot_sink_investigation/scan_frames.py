"""Single-action full-range scan for FK vs fixed foot IK. No save.

Usage: blender --background --factory-startup --python scan_frames.py -- <A|B> <csv>
A = foot IK off (FK baseline), B = foot IK on (coordinate-fixed copy).
"""
import csv
import json
import math
import sys

import bpy

COPY = r"H:\Blender_Plugin\tmp_forearm_roll"
SOURCE = r"h:\SErsiko_ExtactedTool\output\c0000_突刺_wp_a_0300.glb"
TARGET = r"c:\Users\chenshajie1\Downloads\body.FBX"


def angle_deg(a, b, c):
    first = a - b
    second = c - b
    if first.length < 1e-9 or second.length < 1e-9:
        return None
    return round(math.degrees(first.angle(second)), 3)


def main():
    args = sys.argv[sys.argv.index("--") + 1:]
    mode, out_csv = args[0], args[1]
    variant = args[2] if len(args) > 2 else "S0"
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

    if variant == "S1":
        ik_module._CONTACT_MAX_RAISE = 0.05
    elif variant == "S2":
        ik_module._CONTACT_MIN_KNEE_DEG = 25.0
    elif variant == "S3":
        ik_module._CONTACT_MIN_KNEE_DEG = 15.0
    elif variant == "S4":
        ik_module._CONTACT_MIN_KNEE_DEG = 15.0
        ik_module._CONTACT_KNEE_SMOOTH_DEG = 10.0
    elif variant in ("T1", "T2", "T3"):
        ik_module._CONTACT_MIN_KNEE_DEG = 15.0
    print("VARIANT", variant, "max_raise", ik_module._CONTACT_MAX_RAISE, "min_knee", ik_module._CONTACT_MIN_KNEE_DEG, "smooth", ik_module._CONTACT_KNEE_SMOOTH_DEG)

    solve_err = {}
    goal_calls = {}
    original_solve = ik_module._solve_chain

    def recording_solve(tgt, space, reference, goal, pole_hint=None):
        distance = original_solve(tgt, space, reference, goal, pole_hint=pole_hint)
        key = (bpy.context.scene.frame_current, reference.roles[2])
        solve_err[key] = round(float(distance), 4)
        goal_calls.setdefault(key, []).append(goal.position.copy())
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
    print("RANGE", mode, start, end)

    options = retarget.RetargetOptions(
        pairs=pairs, root_motion="KEEP", reference="REST",
        foot_ik=(mode == "B"), hand_ik=False,
        foot_ik_settings=FootIKSettings(floor_enabled=True, floor_alpha=1.0, floor_height_m=0.0),
        contact_min_knee_deg=15.0 if variant == "T3" else 0.0,
        correction_smoothing="height" if variant == "T3" else "",
    )
    report, _ = retarget.bake_retarget(source, target, options)
    print("BAKE", mode, report.replace("\n", " | "))
    if variant in ("T1", "T2"):
        from mathutils import Vector as _Vector

        raw_series = {}
        for (frame, role), calls in goal_calls.items():
            if role in ("foot_l", "foot_r") and len(calls) >= 2:
                raw_series[(frame, role)] = calls[-1] - calls[0]
            elif role in ("foot_l", "foot_r"):
                raw_series[(frame, role)] = _Vector((0.0, 0.0, 0.0))
        print("RAW_CORRECTIONS", variant, {
            f"{f}/{r}": [round(float(c), 4) for c in v]
            for (f, r), v in sorted(raw_series.items()) if f in (16, 17, 18)
        })
        ik_module._CORRECTION_PLAN = ik_module.build_correction_plan(
            raw_series, "B" if variant == "T1" else "C", lam=4.0
        )
        print("PLAN_16_18", variant, {
            f"{f}/{r}": [round(float(c), 4) for c in v]
            for (f, r), v in sorted(ik_module._CORRECTION_PLAN.items()) if f in (16, 17, 18)
        })
        ik_module.CONTACT_LOG.clear()
        ik_module.CONTACT_TRACE.clear()
        goal_calls.clear()
        solve_err.clear()
        report, _ = retarget.bake_retarget(source, target, options)
        print("BAKE2", mode, report.replace("\n", " | "))
    contact_local = {
        side: retarget._extract_foot_contact_local(target, roles["foot_" + side][1])
        for side in ("l", "r")
    }
    print("CONTACT_LOCAL", mode, {side: [[round(float(c), 3) for c in p] for p in pts] for side, pts in contact_local.items()})
    corrections = {}
    for entry in ik_module.CONTACT_LOG:
        frame, role, count, lowest, failed = entry[:5]
        dominant = entry[5] if len(entry) > 5 else None
        corrections[(frame, role)] = (count, lowest, failed, dominant)
    geometry = retarget._prepare_retarget_geometry(source, target, pairs, options, bpy.context.scene)
    skin_points = {limb.roles[2]: limb.skin_points for limb in geometry.limbs}
    print("SKIN_POINTS", mode, {role: len(points) for role, points in skin_points.items()})
    print("MODIFIERS", mode, [(mod.type, mod.name) for mod in mesh.modifiers])

    groups = [list(vertex.groups) for vertex in mesh.data.vertices]
    foot_indexes = {
        side: {g.index for g in mesh.vertex_groups if g.name == roles["foot_" + side][1]}
        for side in ("l", "r")
    }

    def world(name):
        return target.matrix_world @ target.pose.bones[name].head

    rows = []
    for frame in range(start, end + 1):
        bpy.context.scene.frame_set(frame)
        bpy.context.view_layer.update()
        deps = bpy.context.evaluated_depsgraph_get()
        evaluated = mesh.evaluated_get(deps)
        posed = evaluated.to_mesh()
        world_matrix = evaluated.matrix_world
        all_z = []
        side_z = {"l": [], "r": []}
        region_z = {"l": [], "r": []}
        region_indexes = {}
        for side in ("l", "r"):
            names = {roles["shin_" + side][1], roles["foot_" + side][1]}
            names.update(child.name for child in target.data.bones[roles["foot_" + side][1]].children)
            region_indexes[side] = {g.index for g in mesh.vertex_groups if g.name in names}
        for vertex in posed.vertices:
            point = world_matrix @ vertex.co
            all_z.append(point.z)
            for side in ("l", "r"):
                if any(item.group in foot_indexes[side] and item.weight > 0.2 for item in groups[vertex.index]):
                    side_z[side].append(point.z)
                if any(item.group in region_indexes[side] and item.weight > 0.2 for item in groups[vertex.index]):
                    region_z[side].append(point.z)
        evaluated.to_mesh_clear()
        row = {"mode": mode, "frame": frame}
        for side in ("l", "r"):
            thigh = world(roles["thigh_" + side][1])
            knee = world(roles["shin_" + side][1])
            ankle = world(roles["foot_" + side][1])
            toe_name = next(c.name for c in target.pose.bones[roles["foot_" + side][1]].children if "toe" in c.name.lower())
            toe = world(toe_name)
            row[side + "_ankle_z"] = round(ankle.z, 4)
            row[side + "_toe_z"] = round(toe.z, 4)
            row[side + "_knee_deg"] = angle_deg(thigh, knee, ankle)
            row[side + "_upper_len"] = round((knee - thigh).length, 4)
            row[side + "_lower_len"] = round((ankle - knee).length, 4)
            row[side + "_foot_lowest"] = round(min(side_z[side]), 4) if side_z[side] else None
            proxy = None
            if contact_local[side]:
                pose = target.pose.bones[roles["foot_" + side][1]]
                proxy = round(min((target.matrix_world @ (pose.matrix @ point)).z for point in contact_local[side]), 4)
            row[side + "_proxy_lowest"] = proxy
            corr = corrections.get((frame, "foot_" + side))
            row[side + "_corrections"] = None if corr is None else corr[0]
            row[side + "_failed"] = None if corr is None else corr[2]
            row[side + "_dominant"] = None if corr is None else corr[3]
            points = skin_points.get("foot_" + side) or ()
            row[side + "_lbs_lowest"] = (
                round(min(ik_module.skin_point_world(target, bind, influences).z for bind, influences in points), 4)
                if points else None
            )
            row[side + "_region_lowest"] = round(min(region_z[side]), 4) if region_z[side] else None
            row[side + "_err"] = solve_err.get((frame, "foot_" + side))
            foot_bone = target.pose.bones[roles["foot_" + side][1]]
            row[side + "_foot_quat"] = [round(float(x), 4) for x in (target.matrix_world @ foot_bone.matrix).to_quaternion()]
        row["hips_z"] = round(world(roles["hips"][1]).z, 4)
        row["mesh_lowest"] = round(min(all_z), 4)
        row["mesh_below"] = sum(1 for value in all_z if value < -0.001)
        row["forearm_l_quat"] = [round(float(x), 4) for x in target.pose.bones[roles["forearm_l"][1]].matrix_basis.to_quaternion()]
        rows.append(row)

    with open(out_csv, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        keys = [key for key in rows[0] if key not in ("l_foot_quat", "r_foot_quat", "forearm_l_quat")]
        writer.writerow(keys + ["l_foot_quat", "r_foot_quat", "forearm_l_quat"])
        for row in rows:
            writer.writerow([json.dumps(row[key]) if isinstance(row[key], list) else row[key] for key in keys]
                            + [json.dumps(row["l_foot_quat"]), json.dumps(row["r_foot_quat"]), json.dumps(row["forearm_l_quat"])])

    worst = min(rows, key=lambda item: item["mesh_lowest"])
    print("SUMMARY", mode, "min_mesh", worst["mesh_lowest"], "at", worst["frame"],
          "frames_below_-0.01", sum(1 for r in rows if r["mesh_lowest"] < -0.01),
          "max_below_count", max(r["mesh_below"] for r in rows))
    for frame in (0, 18, 24, 52):
        if start <= frame <= end:
            print("FRAME", mode, json.dumps(rows[frame - start]))
    print("DONE", mode)


if __name__ == "__main__":
    main()
