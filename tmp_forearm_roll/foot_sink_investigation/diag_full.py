"""Full 53-frame foot continuity diagnostic for S3 / integrated T3. No save.

Usage: blender --background --factory-startup --python diag_full.py -- <S3|T3> <csv>
Per frame/side: hip/knee/ankle/toe/heel world, knee angle, hip-ankle distance,
bone lengths, foot-group lowest, LBS lowest, whole-mesh lowest, foot world
quaternion, ground correction (CONTACT_LOG raised Z, iterations). For T3 also
writes <csv>_plan.csv with raw vs planned correction and target-height check.
"""
import csv
import json
import math
import sys

import bpy

COPY = r"H:\Blender_Plugin\tmp_forearm_roll"
SOURCE = r"h:\SErsiko_ExtactedTool\output\c0000_突刺_wp_a_0300.glb"
TARGET = r"c:\Users\chenshajie1\Downloads\body.FBX"


def v3(value):
    return [round(float(item), 4) for item in value]


def angle_deg(a, b, c):
    first = a - b
    second = c - b
    return round(math.degrees(first.angle(second)), 3) if first.length > 1e-9 and second.length > 1e-9 else None


def main():
    args = sys.argv[sys.argv.index("--") + 1:]
    variant, out_csv = args[0], args[1]
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

    if variant == "S3":
        ik_module._CONTACT_MIN_KNEE_DEG = 15.0
    print("VARIANT", variant)

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
    options = retarget.RetargetOptions(
        pairs=pairs, root_motion="KEEP", reference="REST",
        foot_ik=True, hand_ik=False,
        foot_ik_settings=FootIKSettings(floor_enabled=True, floor_alpha=1.0, floor_height_m=0.0),
        contact_min_knee_deg=15.0 if variant == "T3" else 0.0,
        correction_smoothing="height" if variant == "T3" else "",
    )
    retarget.bake_retarget(source, target, options)
    log = {(entry[0], entry[1]): entry for entry in ik_module.CONTACT_LOG}
    geometry = retarget._prepare_retarget_geometry(source, target, pairs, options, bpy.context.scene)
    skin_points = {limb.roles[2]: limb.skin_points for limb in geometry.limbs}
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
        side_z = {"l": [], "r": []}
        all_z = []
        for vertex in posed.vertices:
            point = world_matrix @ vertex.co
            all_z.append(point.z)
            for side in ("l", "r"):
                if any(item.group in foot_indexes[side] and item.weight > 0.2 for item in groups[vertex.index]):
                    side_z[side].append(point.z)
        evaluated.to_mesh_clear()
        for side in ("l", "r"):
            thigh = world(roles["thigh_" + side][1])
            knee = world(roles["shin_" + side][1])
            ankle = world(roles["foot_" + side][1])
            foot_bone = target.pose.bones[roles["foot_" + side][1]]
            heel = target.matrix_world @ foot_bone.tail
            toe_name = next(c.name for c in target.pose.bones[roles["foot_" + side][1]].children if "toe" in c.name.lower())
            toe = world(toe_name)
            entry = log.get((frame, "foot_" + side))
            points = skin_points.get("foot_" + side) or ()
            rows.append({
                "variant": variant, "frame": frame, "side": side,
                "hip": json.dumps(v3(thigh)), "knee_pos": json.dumps(v3(knee)),
                "ankle": json.dumps(v3(ankle)), "toe": json.dumps(v3(toe)),
                "heel": json.dumps(v3(heel)),
                "knee_deg": angle_deg(thigh, knee, ankle),
                "hip_ankle_dist": round((ankle - thigh).length, 4),
                "upper_len": round((knee - thigh).length, 4),
                "lower_len": round((ankle - knee).length, 4),
                "foot_lowest": round(min(side_z[side]), 4) if side_z[side] else None,
                "lbs_lowest": round(min(ik_module.skin_point_world(target, bind, influences).z for bind, influences in points), 4) if points else None,
                "mesh_lowest": round(min(all_z), 4),
                "mesh_below_001": sum(1 for value in all_z if value < -0.01),
                "foot_quat": json.dumps([round(float(x), 5) for x in (target.matrix_world @ foot_bone.matrix).to_quaternion()]),
                "correction_z": None if entry is None else entry[6],
                "corrections": None if entry is None else entry[2],
                "log_knee_deg": None if entry is None else entry[7],
                "hips_z": round(world(roles["hips"][1]).z, 4),
            })
    with open(out_csv, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    if variant == "T3":
        raw = getattr(ik_module, "_LAST_RAW_SERIES", {})
        lowest = getattr(ik_module, "_LAST_LOWEST_SERIES", {})
        plan = getattr(ik_module, "_LAST_PLAN", {})
        actual = {(row["frame"], "foot_" + row["side"]): row for row in rows}
        plan_path = out_csv.replace(".csv", "_plan.csv")
        with open(plan_path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["frame", "role", "raw_z", "plan_z", "plan_ge_raw", "raw_lowest", "target_height", "actual_lbs", "actual_foot_lowest", "deviation_actual_minus_target"])
            for (frame, role) in sorted(raw):
                raw_v = raw[(frame, role)]
                plan_v = plan.get((frame, role))
                base_lowest = lowest.get((frame, role))
                target_height = None if base_lowest is None or plan_v is None else round(base_lowest + (plan_v.z - raw_v.z), 4)
                row = actual.get((frame, role), {})
                writer.writerow([
                    frame, role, round(float(raw_v.z), 4),
                    None if plan_v is None else round(float(plan_v.z), 4),
                    None if plan_v is None else bool(plan_v.z >= raw_v.z - 1e-9),
                    base_lowest, target_height,
                    row.get("lbs_lowest"), row.get("foot_lowest"),
                    None if target_height is None or row.get("lbs_lowest") is None else round(row["lbs_lowest"] - target_height, 4),
                ])
        print("PLAN_CHECK", plan_path)
    print("DONE", variant)


if __name__ == "__main__":
    main()
