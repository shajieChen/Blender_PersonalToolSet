"""Regression bake against a chosen plugin root. No .blend is saved.

Usage:
  blender --background --factory-startup --python official_regress.py -- <plugin_parent> <OFF|T3> <csv>
OFF = foot IK on, new options at their defaults (closed).
T3 = foot IK on, correction_smoothing=height, contact_min_knee_deg=15.
"""
import csv
import json
import math
import sys

import bpy

SOURCE = r"h:\SErsiko_ExtactedTool\output\c0000_突刺_wp_a_0300.glb"
TARGET = r"c:\Users\chenshajie1\Downloads\body.FBX"


def angle_deg(a, b, c):
    first = a - b
    second = c - b
    if first.length < 1e-9 or second.length < 1e-9:
        return None
    return round(math.degrees(first.angle(second)), 3)


def main():
    plugin_parent, mode, out_csv = sys.argv[sys.argv.index("--") + 1:]
    sys.path.insert(0, plugin_parent)
    for name in list(sys.modules):
        if name == "humanoid_retarget" or name.startswith("humanoid_retarget."):
            del sys.modules[name]
    bpy.ops.wm.read_factory_settings(use_empty=True)
    from humanoid_retarget.mapping import build_pairs
    from humanoid_retarget import pipeline
    import humanoid_retarget.retarget as retarget
    import humanoid_retarget.ik as ik_module
    from humanoid_retarget.foot_ik import FootIKSettings

    enabled = mode == "T3"
    foot_ik = mode != "FK"
    print("MODE", mode, "stack_default", ik_module._CONTACT_STACK_ENABLED if hasattr(ik_module, "_CONTACT_STACK_ENABLED") else "absent", "min_knee_default", getattr(ik_module, "_CONTACT_MIN_KNEE_DEG", "absent"))

    source, _ = pipeline.load_source(SOURCE)
    objects, _ = pipeline.import_model(TARGET)
    target = pipeline.pick_armature(objects)
    mesh = next(obj for obj in bpy.data.objects if obj.type == "MESH" and obj.parent == target)
    action = next(item for item in retarget.collect_actions(source) if item.name == "a050_300000")
    retarget._assign_action(source, action)
    retarget.collect_actions = lambda _src: [action]
    pairs = build_pairs(source, target)
    roles = {role: (s, t) for role, s, t in pairs}
    start, end = int(action.frame_range[0]), int(round(action.frame_range[1]))
    kwargs = dict(
        pairs=pairs, root_motion="KEEP", reference="REST",
        foot_ik=foot_ik, hand_ik=False,
        foot_ik_settings=FootIKSettings(floor_enabled=True, floor_alpha=1.0, floor_height_m=0.0),
    )
    if enabled:
        kwargs["contact_min_knee_deg"] = 15.0
        kwargs["correction_smoothing"] = "height"
    options = retarget.RetargetOptions(**kwargs)
    report, _ = retarget.bake_retarget(source, target, options)
    print("BAKE", report.replace("\n", " | "))
    print("AFTER stack", getattr(ik_module, "_CONTACT_STACK_ENABLED", None), "plan", getattr(ik_module, "_CORRECTION_PLAN", None), "cache", len(getattr(ik_module, "_PLAN_CACHE", {})))

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
        for vertex in posed.vertices:
            point = world_matrix @ vertex.co
            all_z.append(point.z)
            for side in ("l", "r"):
                if any(item.group in foot_indexes[side] and item.weight > 0.2 for item in groups[vertex.index]):
                    side_z[side].append(point.z)
        evaluated.to_mesh_clear()
        row = {"frame": frame, "mesh_lowest": round(min(all_z), 4), "mesh_below": sum(1 for value in all_z if value < -0.01)}
        for side in ("l", "r"):
            thigh = world(roles["thigh_" + side][1])
            knee = world(roles["shin_" + side][1])
            ankle = world(roles["foot_" + side][1])
            toe_name = next(c.name for c in target.pose.bones[roles["foot_" + side][1]].children if "toe" in c.name.lower())
            toe = world(toe_name)
            row[side + "_knee_deg"] = angle_deg(thigh, knee, ankle)
            row[side + "_toe_z"] = round(toe.z, 4)
            row[side + "_ankle_z"] = round(ankle.z, 4)
            row[side + "_foot_lowest"] = round(min(side_z[side]), 4) if side_z[side] else None
            row[side + "_upper_len"] = round((knee - thigh).length, 4)
            row[side + "_lower_len"] = round((ankle - knee).length, 4)
            row[side + "_foot_quat"] = json.dumps([round(float(x), 4) for x in (target.matrix_world @ target.pose.bones[roles["foot_" + side][1]].matrix).to_quaternion()])
        row["hips_z"] = round(world(roles["hips"][1]).z, 4)
        row["forearm_l_quat"] = json.dumps([round(float(x), 4) for x in target.pose.bones[roles["forearm_l"][1]].matrix_basis.to_quaternion()])
        row["upperarm_l_quat"] = json.dumps([round(float(x), 4) for x in target.pose.bones[roles["upperarm_l"][1]].matrix_basis.to_quaternion()])
        rows.append(row)
    with open(out_csv, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    worst = min(rows, key=lambda item: item["mesh_lowest"])
    print("SUMMARY", mode, "min_mesh", worst["mesh_lowest"], "frames_below", sum(1 for row in rows if row["mesh_lowest"] < -0.01))
    print("DONE", mode)


if __name__ == "__main__":
    main()
