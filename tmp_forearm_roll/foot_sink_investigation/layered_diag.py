"""Layered diagnosis of existing foot IK at frame 24, single action. No save."""
import json
import math
import sys

import bpy

COPY = r"H:\Blender_Plugin\tmp_forearm_roll"
SOURCE = r"h:\SErsiko_ExtactedTool\output\c0000_突刺_wp_a_0300.glb"
TARGET = r"c:\Users\chenshajie1\Downloads\body.FBX"
FRAME = 24


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

    source, _ = pipeline.load_source(SOURCE)
    objects, _ = pipeline.import_model(TARGET)
    target = pipeline.pick_armature(objects)
    mesh = next(obj for obj in bpy.data.objects if obj.type == "MESH" and obj.parent == target)
    action = next(item for item in retarget.collect_actions(source) if item.name == "a050_300000")
    retarget._assign_action(source, action)
    pairs = build_pairs(source, target)
    roles = {role: (s, t) for role, s, t in pairs}

    # Only this one action in the bake.
    retarget.collect_actions = lambda _src: [action]

    log = {"floor": [], "solve_in": [], "solve_err": []}

    original_floor = ik_module.constrain_goal_floor

    def floor_spy(goal, source_end_z, reference_height_offset, settings):
        before = goal.copy()
        result = original_floor(goal, source_end_z, reference_height_offset, settings)
        if bpy.context.scene.frame_current == FRAME:
            log["floor"].append({
                "goal_before_motion": v3(before),
                "goal_after_motion": v3(result),
                "source_end_z": round(float(source_end_z), 4),
                "height_offset": round(float(reference_height_offset), 4),
                "floor_enabled": settings.floor_enabled,
                "floor_alpha": settings.floor_alpha,
                "falloff_start_m": settings.falloff_start_m,
                "falloff_distance_m": settings.falloff_distance_m,
                "maintain_height_offset": settings.maintain_height_offset,
                "floor_height_m": settings.floor_height_m,
            })
        return result

    ik_module.constrain_goal_floor = floor_spy

    original_solve = ik_module._solve_chain

    def solve_spy(tgt, space, reference, goal, pole_hint=None):
        capture = bpy.context.scene.frame_current == FRAME
        if capture:
            world = tgt.matrix_world
            upper, mid, end = reference.target_names
            toe = next(child.name for child in tgt.pose.bones[end].children if "toe" in child.name.lower())
            log["solve_in"].append({
                "role": reference.roles[2],
                "goal_motion": v3(goal.position),
                "goal_world": v3(world @ space.armature_position(goal.position)),
                "pole_world": None if pole_hint is None else v3(world @ space.armature_position(pole_hint)),
                "root_world": v3(world @ tgt.pose.bones[upper].head),
                "pre_thigh": v3(world @ tgt.pose.bones[upper].head),
                "pre_knee": v3(world @ tgt.pose.bones[mid].head),
                "pre_ankle": v3(world @ tgt.pose.bones[end].head),
                "pre_toe": v3(world @ tgt.pose.bones[toe].head),
                "upper_len": round(float(reference.target_upper_length), 4),
                "lower_len": round(float(reference.target_lower_length), 4),
                "goal_rotation": q4(goal.rotation),
            })
        distance = original_solve(tgt, space, reference, goal, pole_hint=pole_hint)
        if capture:
            log["solve_err"].append({
                "role": reference.roles[2],
                "end_error_m": round(float(distance), 4),
            })
        return distance

    ik_module._solve_chain = solve_spy

    def leg_snapshot(arm, side, toe_name):
        thigh = roles["thigh_" + side][1] if arm == target else roles["thigh_" + side][0]
        shin = roles["shin_" + side][1] if arm == target else roles["shin_" + side][0]
        foot = roles["foot_" + side][1] if arm == target else roles["foot_" + side][0]
        world = arm.matrix_world
        thigh_w = world @ arm.pose.bones[thigh].head
        knee_w = world @ arm.pose.bones[shin].head
        ankle_w = world @ arm.pose.bones[foot].head
        toe_w = world @ arm.pose.bones[toe_name].head
        return {
            "thigh": v3(thigh_w), "knee": v3(knee_w), "ankle": v3(ankle_w), "toe": v3(toe_w),
            "knee_angle": angle_deg(thigh_w, knee_w, ankle_w),
            "upper_len": round((knee_w - thigh_w).length, 4),
            "lower_len": round((ankle_w - knee_w).length, 4),
            "foot_quat_world": q4((world @ arm.pose.bones[foot].matrix).to_quaternion()),
        }

    solved = {}
    original_apply = ik_module.apply_contact_ik

    def apply_spy(src, tgt, geometry, settings, states, speeds, pelvis_delta, dt):
        result = original_apply(src, tgt, geometry, settings, states, speeds, pelvis_delta, dt)
        if bpy.context.scene.frame_current == FRAME:
            solved["pelvis_delta_motion"] = v3(pelvis_delta)
            solved["hips_world"] = v3(tgt.matrix_world @ tgt.pose.bones[roles["hips"][1]].head)
            solved["hips_loc"] = v3(tgt.pose.bones[roles["hips"][1]].location)
            for side, toe in (("l", "Bip01 L Toe0"), ("r", "Bip01 R Toe0")):
                solved[side] = leg_snapshot(tgt, side, toe)
            solved["src"] = {}
            for side, toe in (("l", "L_Toe0"), ("r", "R_Toe0")):
                solved["src"][side] = leg_snapshot(src, side, toe)
        return result

    retarget.apply_contact_ik = apply_spy

    settings = FootIKSettings(floor_enabled=True, floor_alpha=1.0, floor_height_m=0.0)
    options = retarget.RetargetOptions(
        pairs=pairs, root_motion="KEEP", reference="REST",
        foot_ik=True, hand_ik=False, foot_ik_settings=settings,
    )
    report, _actions = retarget.bake_retarget(source, target, options)
    print("BAKE", report.replace("\n", " | "))
    print("LOG", json.dumps(log))
    print("SOLVED", json.dumps(solved))

    # Stage D: re-evaluate baked keys at frame 24.
    bpy.context.scene.frame_set(FRAME)
    bpy.context.view_layer.update()
    baked = {"hips_world": v3(target.matrix_world @ target.pose.bones[roles["hips"][1]].head),
             "hips_loc": v3(target.pose.bones[roles["hips"][1]].location)}
    for side, toe in (("l", "Bip01 L Toe0"), ("r", "Bip01 R Toe0")):
        baked[side] = leg_snapshot(target, side, toe)
    print("BAKED", json.dumps(baked))

    # Keyed channels for leg bones at frame 24.
    anim = target.animation_data
    act = anim.action
    slot = anim.action_slot
    bag = act.layers[0].strips[0].channelbag(slot)
    wanted = {roles["hips"][1], roles["thigh_l"][1], roles["shin_l"][1], roles["foot_l"][1],
              roles["thigh_r"][1], roles["shin_r"][1], roles["foot_r"][1]}
    channels = {}
    for curve in bag.fcurves:
        bone = curve.data_path.split('"')[1] if '"' in curve.data_path else curve.data_path
        if bone in wanted:
            channels.setdefault(bone, []).append(
                curve.data_path.split(".")[-1] + "[%d]=%.4f" % (curve.array_index, curve.evaluate(FRAME))
            )
    print("CHANNELS", json.dumps(channels))

    # Stage E: deformed mesh.
    def mesh_stats(side=None):
        deps = bpy.context.evaluated_depsgraph_get()
        evaluated = mesh.evaluated_get(deps)
        posed = evaluated.to_mesh()
        world = evaluated.matrix_world
        groups = [list(vertex.groups) for vertex in mesh.data.vertices]
        indexes = None
        if side:
            foot_name = roles["foot_" + side][1]
            indexes = {group.index for group in mesh.vertex_groups if group.name == foot_name}
        values = []
        side_values = []
        for vertex in posed.vertices:
            point = world @ vertex.co
            values.append(point.z)
            if indexes and any(item.group in indexes and item.weight > 0.2 for item in groups[vertex.index]):
                side_values.append(point.z)
        evaluated.to_mesh_clear()
        return {
            "lowest": round(min(values), 4),
            "below": sum(1 for value in values if value < -0.001),
            "foot_lowest": None if not side_values else round(min(side_values), 4),
        }

    print("MESH", json.dumps({"all": mesh_stats(), "l": mesh_stats("l"), "r": mesh_stats("r")}))
    print("DONE")


if __name__ == "__main__":
    main()
