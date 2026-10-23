"""Parent-space location probe after calf roll. One channel at a time.

Does not change the roll algorithm, bone rotation, or the ankle goal.
The location write is temporary and is not saved.
"""
import csv
import json
import math
import sys

import bpy

COPY = r"H:\Blender_Plugin\tmp_forearm_roll"
SOURCE = r"h:\SErsiko_ExtactedTool\output\c0000_突刺_wp_a_0300.glb"
TARGET = r"c:\Users\chenshajie1\Downloads\body.FBX"
OUT = r"H:\Blender_Plugin\tmp_forearm_roll\foot_sink_investigation"
CLIPS = ("a050_300010", "a050_300000")
# Neighbour frames are recorded for continuity. Compensation is only applied
# on the authorised ranges.
RANGES = {
    "a050_300010": (3, 13, 4, 12),
    "a050_300000": (8, 17, 9, 16),
}
# One parent-space location unit. Measured in world millimetres after evaluation.
# This probe is not scaled up when the ankle or the knee moves.
DELTA = 0.1
AXES = ("x", "y", "z")


def chain_roll(arm, bone_name, child_name):
    from mathutils import Quaternion, Vector

    pose_bone = arm.pose.bones[bone_name]
    rest = pose_bone.bone.matrix_local.to_3x3()
    delta = pose_bone.matrix.to_3x3() @ rest.inverted()
    quat = delta.to_quaternion()
    if quat.w < 0.0:
        quat.negate()
    axis = arm.pose.bones[child_name].head - pose_bone.head
    if axis.length < 1e-9:
        return 0.0
    axis.normalize()
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


def quat_deg(a, b):
    dot = abs(max(-1.0, min(1.0, a.dot(b))))
    return math.degrees(2.0 * math.acos(dot))


def vec3(value):
    return [round(float(item), 6) for item in value]


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
    pairs = build_pairs(source, target)
    roles = {role: (src_name, tgt_name) for role, src_name, tgt_name in pairs}
    print("GROUPS", [group.name for group in mesh.vertex_groups], flush=True)
    actions = {item.name: item for item in retarget.collect_actions(source) if item.name in CLIPS}
    holder = {"action": None}
    retarget.collect_actions = lambda _src: [holder["action"]]
    settings = FootIKSettings(floor_enabled=True, floor_alpha=1.0, floor_height_m=0.0)
    rows = []
    vertices = []

    def reset_pose():
        if target.animation_data:
            target.animation_data_clear()
        for pose_bone in target.pose.bones:
            pose_bone.rotation_mode = "QUATERNION"
            pose_bone.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
            pose_bone.location = (0.0, 0.0, 0.0)
            pose_bone.scale = (1.0, 1.0, 1.0)
        bpy.context.view_layer.update()

    def bake(action, roll, apply_mode):
        reset_pose()
        holder["action"] = action
        retarget._assign_action(source, action)
        ik_module.clear_correction_plan_cache()
        ik_module._CORRECTION_PLAN = None
        ik_module._LAST_PLAN = None
        ik_module._CONTACT_MIN_KNEE_DEG = None
        ik_module.CALF_ROLL_LOG.clear()
        ik_module.ENDPOINT_LOG.clear()
        ik_module.CONTACT_LOG.clear()
        ik_module._CALF_ROLL_FIX_ENABLED = roll
        ik_module._CALF_ROLL_APPLY = apply_mode
        options = retarget.RetargetOptions(
            pairs=pairs, root_motion="KEEP", reference="REST",
            foot_ik=True, hand_ik=False,
            foot_ik_settings=settings,
            contact_min_knee_deg=15.0,
            correction_smoothing="height",
        )
        retarget.bake_retarget(source, target, options)
        ik_module._CALF_ROLL_FIX_ENABLED = False
        ik_module._CALF_ROLL_APPLY = "inline"
        print("BAKED", apply_mode, action.name, "roll_max_log",
              max((abs(item[3]) for item in ik_module.CALF_ROLL_LOG), default=0.0), flush=True)

    def world_point(pose_bone, local):
        return target.matrix_world @ local

    def mesh_low(sample_weights):
        deps = bpy.context.evaluated_depsgraph_get()
        evaluated = mesh.evaluated_get(deps)
        posed = evaluated.to_mesh()
        world = evaluated.matrix_world
        lowest = None
        n0 = 0
        n01 = 0
        ranked = []
        for vertex in posed.vertices:
            co = world @ vertex.co
            z = co.z
            if lowest is None or z < lowest:
                lowest = z
            if z < 0.0:
                n0 += 1
            if z < -0.01:
                n01 += 1
            ranked.append((z, vertex.index, co.copy()))
        evaluated.to_mesh_clear()
        ranked.sort(key=lambda item: item[0])
        samples = []
        if sample_weights:
            for z, index, co in ranked[:5]:
                groups = []
                for group in mesh.data.vertices[index].groups:
                    weight = group.weight
                    if weight <= 0.01:
                        continue
                    groups.append((mesh.vertex_groups[group.group].name, round(weight, 4)))
                groups.sort(key=lambda item: -item[1])
                samples.append({
                    "index": index,
                    "z": round(z, 6),
                    "co": vec3(co),
                    "weights": groups[:6],
                })
        depth_mm = 0.0 if lowest is None or lowest >= 0.0 else round(-lowest * 1000.0, 3)
        return float(lowest if lowest is not None else 0.0), n0, n01, depth_mm, samples

    def hold_pose():
        bases = {pose_bone.name: pose_bone.matrix_basis.copy() for pose_bone in target.pose.bones}
        action = target.animation_data.action
        target.animation_data.action = None
        for pose_bone in target.pose.bones:
            pose_bone.matrix_basis = bases[pose_bone.name]
        bpy.context.view_layer.update()
        return action

    def measure(action_name, frame, config, channel, delta, sample_weights):
        lowest, n0, n01, depth_mm, samples = mesh_low(sample_weights)
        row = {
            "action": action_name,
            "frame": frame,
            "config": config,
            "channel": channel,
            "delta": delta,
            "mesh_lowest": round(lowest, 6),
            "n_z_lt_0": n0,
            "n_z_lt_001": n01,
            "penetration_mm": depth_mm,
        }
        for side in ("l", "r"):
            thigh = target.pose.bones[roles["thigh_" + side][1]]
            calf = target.pose.bones[roles["shin_" + side][1]]
            foot = target.pose.bones[roles["foot_" + side][1]]
            hip = world_point(thigh, thigh.head)
            knee = world_point(calf, calf.head)
            ankle = world_point(foot, foot.head)
            thigh_tail = world_point(thigh, thigh.tail)
            calf_tail = world_point(calf, calf.tail)
            row[side + "_knee"] = json.dumps(vec3(knee))
            row[side + "_ankle"] = json.dumps(vec3(ankle))
            row[side + "_upper_len"] = round((knee - hip).length, 6)
            row[side + "_lower_len"] = round((ankle - knee).length, 6)
            row[side + "_roll"] = round(chain_roll(target, roles["shin_" + side][1], roles["foot_" + side][1]), 4)
            row[side + "_knee_to_thigh_tail_mm"] = round((knee - thigh_tail).length * 1000.0, 3)
            row[side + "_ankle_to_calf_tail_mm"] = round((ankle - calf_tail).length * 1000.0, 3)
            row[side + "_calf_loc"] = json.dumps(vec3(calf.location))
            row[side + "_calf_quat"] = json.dumps([round(float(item), 6) for item in calf.rotation_quaternion])
            row[side + "_foot_loc"] = json.dumps(vec3(foot.location))
            row[side + "_foot_quat"] = json.dumps([round(float(item), 6) for item in foot.rotation_quaternion])
        if sample_weights:
            for sample in samples:
                vertices.append({
                    "action": action_name,
                    "frame": frame,
                    "config": config,
                    "channel": channel,
                    "index": sample["index"],
                    "z": sample["z"],
                    "co": json.dumps(sample["co"]),
                    "weights": json.dumps(sample["weights"], ensure_ascii=False),
                })
            row["low_vertex"] = "" if not samples else json.dumps(samples[0], ensure_ascii=False)
        else:
            row["low_vertex"] = ""
        return row

    def pose_action(action_name):
        baked = bpy.data.actions[target.name + "_" + action_name]
        target.animation_data_create().action = baked
        for pose_bone in target.pose.bones:
            pose_bone.scale = (1.0, 1.0, 1.0)
        bpy.context.view_layer.update()

    for name in CLIPS:
        action = actions[name]
        bake(action, False, "inline")
        baked_a = bpy.data.actions[target.name + "_" + name]
        baked_a.name = target.name + "_" + name + "_A"
        bake(action, True, "bake_lock")
        baked_c = bpy.data.actions[target.name + "_" + name]
        start, end, comp_start, comp_end = RANGES[name]
        for label, baked in (("A_base", baked_a), ("C_lock", baked_c)):
            target.animation_data_create().action = baked
            for pose_bone in target.pose.bones:
                pose_bone.scale = (1.0, 1.0, 1.0)
            for frame in range(start, end + 1):
                bpy.context.scene.frame_set(frame)
                bpy.context.view_layer.update()
                rows.append(measure(name, frame, label, "baseline", 0.0, True))
        target.animation_data.action = baked_c
        for pose_bone in target.pose.bones:
            pose_bone.scale = (1.0, 1.0, 1.0)
        for frame in range(comp_start, comp_end + 1):
            for side in ("l", "r"):
                calf_name = roles["shin_" + side][1]
                parent = target.pose.bones[calf_name].parent.name
                for axis_index, axis_name in enumerate(AXES):
                    bpy.context.scene.frame_set(frame)
                    bpy.context.view_layer.update()
                    calf = target.pose.bones[calf_name]
                    foot = target.pose.bones[roles["foot_" + side][1]]
                    calf_quat = calf.rotation_quaternion.copy()
                    foot_quat = foot.rotation_quaternion.copy()
                    foot_loc = foot.location.copy()
                    action = hold_pose()
                    calf = target.pose.bones[calf_name]
                    before = calf.location.copy()
                    calf.location[axis_index] = before[axis_index] + DELTA
                    bpy.context.view_layer.update()
                    row = measure(name, frame, "C_loc", side + "_calf_loc_" + axis_name, DELTA, False)
                    row["parent"] = parent
                    row["calf_quat_delta_deg"] = round(quat_deg(calf.rotation_quaternion, calf_quat), 6)
                    row["foot_quat_delta_deg"] = round(quat_deg(foot.rotation_quaternion, foot_quat), 6)
                    row["foot_loc_delta_mm"] = round((foot.location - foot_loc).length * 1000.0, 4)
                    rows.append(row)
                    target.animation_data.action = action
                    bpy.context.view_layer.update()
                    print("LOC", name, frame, side, axis_name,
                          "mesh", row["mesh_lowest"],
                          "knee", row[side + "_knee"],
                          "ankle", row[side + "_ankle"],
                          "quat", row["calf_quat_delta_deg"],
                          "foot_quat", row["foot_quat_delta_deg"],
                          flush=True)

    with open(OUT + r"\calf_parent_location_frames.csv", "w", newline="", encoding="utf-8") as handle:
        fields = []
        seen = set()
        for row in rows:
            for key in row.keys():
                if key not in seen:
                    seen.add(key)
                    fields.append(key)
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    with open(OUT + r"\calf_parent_location_vertices.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(vertices[0].keys()))
        writer.writeheader()
        writer.writerows(vertices)
    print("ROWS", len(rows), "VERTS", len(vertices), "DONE", flush=True)


if __name__ == "__main__":
    main()
