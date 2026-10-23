"""Frames 14-21 continuity diagnostic for a knee-candidate variant. No save.

Usage: blender --background --factory-startup --python diag_continuity.py -- <S0|S2|S3|S4> <csv>
Records per frame/side: final ankle goal (motion space), solved hip/knee/ankle/toe
world positions, knee angle, foot-group lowest point, mesh lowest, corrections and
cumulative goal raise from CONTACT_LOG.
"""
import csv
import json
import math
import sys

import bpy

COPY = r"H:\Blender_Plugin\tmp_forearm_roll"
SOURCE = r"h:\SErsiko_ExtactedTool\output\c0000_突刺_wp_a_0300.glb"
TARGET = r"c:\Users\chenshajie1\Downloads\body.FBX"
FIRST, LAST = 14, 21


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

    if variant == "S2":
        ik_module._CONTACT_MIN_KNEE_DEG = 25.0
    elif variant == "S3":
        ik_module._CONTACT_MIN_KNEE_DEG = 15.0
    elif variant == "S4":
        ik_module._CONTACT_MIN_KNEE_DEG = 15.0
        ik_module._CONTACT_KNEE_SMOOTH_DEG = 10.0
    elif variant in ("T1", "T2", "T3"):
        ik_module._CONTACT_MIN_KNEE_DEG = 15.0
    print("VARIANT", variant, "min_knee", ik_module._CONTACT_MIN_KNEE_DEG, "smooth", ik_module._CONTACT_KNEE_SMOOTH_DEG)

    goals = {}
    goal_calls = {}
    original_solve = ik_module._solve_chain

    def recording_solve(tgt, space, reference, goal, pole_hint=None):
        distance = original_solve(tgt, space, reference, goal, pole_hint=pole_hint)
        key = (bpy.context.scene.frame_current, reference.roles[2])
        goals[key] = v3(goal.position)
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
    options = retarget.RetargetOptions(
        pairs=pairs, root_motion="KEEP", reference="REST",
        foot_ik=True, hand_ik=False,
        foot_ik_settings=FootIKSettings(floor_enabled=True, floor_alpha=1.0, floor_height_m=0.0),
    )
    retarget.bake_retarget(source, target, options)
    if variant in ("T1", "T2", "T3"):
        from mathutils import Vector as _Vector

        raw_series = {}
        for (frame, role), calls in goal_calls.items():
            if role in ("foot_l", "foot_r"):
                raw_series[(frame, role)] = calls[-1] - calls[0] if len(calls) >= 2 else _Vector()
        if variant == "T3":
            lowest_series = {
                (entry[0], entry[1]): entry[3] for entry in ik_module.CONTACT_LOG
            }
            ik_module._CORRECTION_PLAN = ik_module.build_height_plan(
                raw_series, lowest_series
            )
        else:
            ik_module._CORRECTION_PLAN = ik_module.build_correction_plan(
                raw_series, "B" if variant == "T1" else "C", lam=4.0
            )
        ik_module.CONTACT_LOG.clear()
        ik_module.CONTACT_TRACE.clear()
        goal_calls.clear()
        goals.clear()
        retarget.bake_retarget(source, target, options)
    trace_path = out_csv.replace(".csv", "_trace.csv")
    with open(trace_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["frame", "role", "iteration", "lowest_before", "raise_this", "knee_before"])
        for entry in ik_module.CONTACT_TRACE:
            if FIRST <= entry[0] <= LAST:
                writer.writerow(entry)
    print("TRACE", trace_path)
    log = {(entry[0], entry[1]): entry for entry in ik_module.CONTACT_LOG}
    groups = [list(vertex.groups) for vertex in mesh.data.vertices]
    foot_indexes = {
        side: {g.index for g in mesh.vertex_groups if g.name == roles["foot_" + side][1]}
        for side in ("l", "r")
    }

    def world(name):
        return target.matrix_world @ target.pose.bones[name].head

    rows = []
    for frame in range(FIRST, LAST + 1):
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
            toe_name = next(c.name for c in target.pose.bones[roles["foot_" + side][1]].children if "toe" in c.name.lower())
            toe = world(toe_name)
            entry = log.get((frame, "foot_" + side))
            rows.append({
                "variant": variant, "frame": frame, "side": side,
                "hip": json.dumps(v3(thigh)), "knee_pos": json.dumps(v3(knee)),
                "ankle": json.dumps(v3(ankle)), "toe": json.dumps(v3(toe)),
                "ankle_goal": json.dumps(goals.get((frame, "foot_" + side))),
                "knee_deg": angle_deg(thigh, knee, ankle),
                "foot_lowest": round(min(side_z[side]), 4) if side_z[side] else None,
                "mesh_lowest": round(min(all_z), 4),
                "hips_z": round(world(roles["hips"][1]).z, 4),
                "corrections": None if entry is None else entry[2],
                "raised_m": None if entry is None else entry[6],
                "log_knee_deg": None if entry is None else entry[7],
            })
    with open(out_csv, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    for row in rows:
        print("CONT", json.dumps(row))
    print("DONE", variant)


if __name__ == "__main__":
    main()
