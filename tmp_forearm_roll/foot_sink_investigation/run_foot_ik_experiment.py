"""Isolated A/B/C foot experiment. Runs in a fresh headless scene and never saves."""
import json
import math
import sys

import bpy
from mathutils import Vector

COPY = r"H:\Blender_Plugin\tmp_forearm_roll"
SOURCE = r"h:\SErsiko_ExtactedTool\output\c0000_突刺_wp_a_0300.glb"
TARGET = r"c:\Users\chenshajie1\Downloads\body.FBX"
FRAMES = (0, 18, 24, 52)


def v3(value):
    return [round(float(item), 4) for item in value]


def q4(value):
    return [round(float(item), 4) for item in value]


def angle_deg(a, b, c):
    first = a - b
    second = c - b
    if first.length < 1e-9 or second.length < 1e-9:
        return None
    return round(math.degrees(first.angle(second)), 3)


def main():
    mode = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else "A"
    sys.path.insert(0, COPY)
    for name in list(sys.modules):
        if name == "humanoid_retarget" or name.startswith("humanoid_retarget."):
            del sys.modules[name]
    bpy.ops.wm.read_factory_settings(use_empty=True)
    from humanoid_retarget.mapping import build_pairs
    from humanoid_retarget import pipeline
    import humanoid_retarget.retarget as retarget
    import humanoid_retarget.ik as ik_module
    from humanoid_retarget.foot_ik import FootIKSettings, constrain_goal_floor, generate_limb_goal, plant_goal

    solve_log = []
    original_solve = ik_module._solve_chain

    def recording_solve(tgt, space, reference, goal, pole_hint=None):
        distance = original_solve(tgt, space, reference, goal, pole_hint=pole_hint)
        solve_log.append({
            "frame": bpy.context.scene.frame_current,
            "role": reference.roles[2],
            "goal_z": round(float(goal.position.z), 4),
            "end_error_m": round(float(distance), 4),
        })
        return distance

    ik_module._solve_chain = recording_solve

    if mode == "C":
        def toe_contact_ik(src, tgt, geometry, settings, states, speeds, pelvis_delta, dt):
            for limb in geometry.limbs:
                end_role = limb.roles[2]
                source_start_pose = src.pose.bones.get(limb.source_names[0])
                source_end_pose = src.pose.bones.get(limb.source_names[2])
                target_start_pose = tgt.pose.bones.get(limb.target_names[0])
                target_end_pose = tgt.pose.bones.get(limb.target_names[2])
                if not source_start_pose or not source_end_pose or not target_start_pose:
                    continue
                source_space = geometry.source_space
                target_space = geometry.target_space
                source_start = source_space.position(src.matrix_world @ source_start_pose.head)
                source_end = source_space.position(src.matrix_world @ source_end_pose.head)
                source_end_rotation = source_space.rotation(src.matrix_world @ source_end_pose.matrix)
                target_start = target_space.position(tgt.matrix_world @ target_start_pose.head)
                goal = generate_limb_goal(
                    source_start, source_end, source_end_rotation, target_start, limb, pelvis_delta,
                )
                if end_role in ("foot_l", "foot_r"):
                    goal.position = constrain_goal_floor(
                        goal.position, source_end.z, limb.height_offset, settings,
                    )
                    toe_pose = None
                    for child in target_end_pose.children:
                        if "toe" in child.name.lower():
                            toe_pose = child
                            break
                    ankle_space = target_space.position(tgt.matrix_world @ target_end_pose.head)
                    if toe_pose is not None:
                        toe_space = target_space.position(tgt.matrix_world @ toe_pose.head)
                    else:
                        toe_space = target_space.position(tgt.matrix_world @ target_end_pose.tail)
                    if toe_space.z < 0.0:
                        # Desired ankle height keeps the current ankle->toe drop at floor level.
                        goal.position.z = max(goal.position.z, -(toe_space.z - ankle_space.z))
                    state = states.get(end_role)
                    if state is not None:
                        goal.position = plant_goal(
                            goal.position, speeds.get(end_role, -1.0), state, dt, settings,
                        )
                pole_hint = ik_module.transfer_source_fold_pole(
                    src, source_space, tgt, target_space, limb, goal.position,
                )
                ik_module._solve_chain(tgt, target_space, limb, goal, pole_hint=pole_hint)

        retarget.apply_contact_ik = toe_contact_ik

    source, _summary = pipeline.load_source(SOURCE)
    objects, _summary = pipeline.import_model(TARGET)
    target = pipeline.pick_armature(objects)
    mesh = next(obj for obj in bpy.data.objects if obj.type == "MESH" and obj.parent == target)
    action = next(item for item in retarget.collect_actions(source) if item.name == "a050_300000")
    retarget._assign_action(source, action)
    pairs = build_pairs(source, target)
    roles = {role: (src_name, tgt_name) for role, src_name, tgt_name in pairs}
    settings = FootIKSettings(
        floor_enabled=True, floor_alpha=1.0, floor_height_m=0.0,
    )
    options = retarget.RetargetOptions(
        pairs=pairs,
        root_motion="KEEP",
        reference="REST",
        foot_ik=mode in ("B", "C"),
        hand_ik=False,
        foot_ik_settings=settings,
    )
    report, _actions = retarget.bake_retarget(source, target, options)
    print("BAKE_REPORT", mode, report.replace("\n", " | "))
    print("SOLVE_LOG", json.dumps(solve_log))

    def world(arm, name):
        return arm.matrix_world @ arm.pose.bones[name].head

    def sole_lowest(side):
        foot_name = roles["foot_" + side][1]
        indexes = {group.index for group in mesh.vertex_groups if group.name == foot_name}
        groups = [list(vertex.groups) for vertex in mesh.data.vertices]
        deps = bpy.context.evaluated_depsgraph_get()
        evaluated = mesh.evaluated_get(deps)
        posed = evaluated.to_mesh()
        world_matrix = evaluated.matrix_world
        values = []
        all_values = []
        for vertex in posed.vertices:
            point = world_matrix @ vertex.co
            all_values.append(point.z)
            if any(item.group in indexes and item.weight > 0.2 for item in groups[vertex.index]):
                values.append(point.z)
        evaluated.to_mesh_clear()
        return {
            "foot_group_lowest_z": round(min(values), 4) if values else None,
            "mesh_lowest_z": round(min(all_values), 4),
            "mesh_below_count": sum(1 for value in all_values if value < -0.001),
        }

    for frame in FRAMES:
        bpy.context.scene.frame_set(frame)
        bpy.context.view_layer.update()
        row = {"mode": mode, "frame": frame}
        for side in ("l", "r"):
            thigh = roles["thigh_" + side][1]
            shin = roles["shin_" + side][1]
            foot = roles["foot_" + side][1]
            toe = next(child.name for child in target.pose.bones[foot].children if "toe" in child.name.lower())
            thigh_w = world(target, thigh)
            knee_w = world(target, shin)
            ankle_w = world(target, foot)
            toe_w = world(target, toe)
            row[side] = {
                "thigh": v3(thigh_w),
                "knee": v3(knee_w),
                "ankle": v3(ankle_w),
                "toe": v3(toe_w),
                "knee_angle": angle_deg(thigh_w, knee_w, ankle_w),
                "upper_len": round((knee_w - thigh_w).length, 4),
                "lower_len": round((ankle_w - knee_w).length, 4),
                "ankle_toe": v3(toe_w - ankle_w),
                "foot_quat": q4((target.matrix_world @ target.pose.bones[foot].matrix).to_quaternion()),
                **sole_lowest(side),
            }
        row["hips"] = v3(world(target, roles["hips"][1]))
        row["pelvis_loc"] = v3(target.pose.bones[roles["hips"][1]].location)
        for role in ("forearm_l", "upperarm_l", "spine", "chest"):
            name = roles[role][1]
            row[role + "_quat"] = q4(target.pose.bones[name].matrix_basis.to_quaternion())
        print("ROW", json.dumps(row))
    print("DONE", mode)


if __name__ == "__main__":
    main()
