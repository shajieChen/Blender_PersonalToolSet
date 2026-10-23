"""Compare roll-off, inherited foot pose, and local-rotation world restore.

Independent copy only. Location channels of the calf are not written.
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
PRIORITY = {
    "a050_300010": list(range(4, 13)),
    "a050_300000": [9, 15, 16],
}


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
    for side in ("l", "r"):
        foot = target.data.bones[roles["foot_" + side][1]]
        print("FOOT", foot.name, "children", [child.name for child in foot.children], flush=True)
    actions = {item.name: item for item in retarget.collect_actions(source) if item.name in CLIPS}
    holder = {"action": None}
    retarget.collect_actions = lambda _src: [holder["action"]]
    settings = FootIKSettings(floor_enabled=True, floor_alpha=1.0, floor_height_m=0.0)
    rows = []
    pose_rows = []

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
        ik_module.FOOT_POSE_LOG.clear()
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
        for item in ik_module.FOOT_POSE_LOG:
            pose_rows.append({
                "action": action.name,
                "mode": apply_mode,
                "frame": item[0],
                "role": item[1],
                "stage": item[2],
                "foot_deg": item[3],
                "ankle_mm": item[4],
                "knee_mm": item[5],
                "length_mm": item[6],
                "calf_loc_mm": item[7],
            })
        print("BAKED", apply_mode, action.name, "pose_log", len(ik_module.FOOT_POSE_LOG), flush=True)

    def mesh_low():
        deps = bpy.context.evaluated_depsgraph_get()
        evaluated = mesh.evaluated_get(deps)
        posed = evaluated.to_mesh()
        world = evaluated.matrix_world
        lowest = None
        n0 = 0
        n01 = 0
        for vertex in posed.vertices:
            z = (world @ vertex.co).z
            if lowest is None or z < lowest:
                lowest = z
            if z < 0.0:
                n0 += 1
            if z < -0.01:
                n01 += 1
        evaluated.to_mesh_clear()
        depth = 0.0 if lowest is None or lowest >= 0.0 else -lowest
        return float(lowest if lowest is not None else 0.0), n0, n01, depth

    def measure(action_name, frame, config):
        lowest, n0, n01, depth = mesh_low()
        row = {
            "action": action_name,
            "frame": frame,
            "config": config,
            "mesh_lowest": round(lowest, 6),
            "n_z_lt_0": n0,
            "n_z_lt_001": n01,
            "penetration_mm": round(depth * 1000.0, 3),
        }
        for side in ("l", "r"):
            thigh = target.pose.bones[roles["thigh_" + side][1]]
            calf = target.pose.bones[roles["shin_" + side][1]]
            foot = target.pose.bones[roles["foot_" + side][1]]
            hip = target.matrix_world @ thigh.head
            knee = target.matrix_world @ calf.head
            ankle = target.matrix_world @ foot.head
            world_mat = target.matrix_world @ foot.matrix
            quat = world_mat.to_quaternion()
            if quat.w < 0.0:
                quat.negate()
            toe = foot.tail - foot.head
            if toe.length > 1e-9:
                toe = (target.matrix_world.to_3x3() @ toe).normalized()
            sole = (target.matrix_world.to_3x3() @ foot.matrix.to_3x3() @ __import__("mathutils").Vector((0.0, 0.0, 1.0))).normalized()
            row[side + "_roll"] = round(chain_roll(target, roles["shin_" + side][1], roles["foot_" + side][1]), 4)
            row[side + "_knee"] = json.dumps(vec3(knee))
            row[side + "_ankle"] = json.dumps(vec3(ankle))
            row[side + "_upper_len"] = round((knee - hip).length, 6)
            row[side + "_lower_len"] = round((ankle - knee).length, 6)
            row[side + "_foot_quat"] = json.dumps([round(float(item), 6) for item in quat])
            row[side + "_toe"] = json.dumps(vec3(toe))
            row[side + "_sole"] = json.dumps(vec3(sole))
            row[side + "_calf_loc"] = json.dumps(vec3(calf.location))
        return row

    def collect(action_name, baked, config, frames):
        target.animation_data_create().action = baked
        for pose_bone in target.pose.bones:
            pose_bone.scale = (1.0, 1.0, 1.0)
        for frame in frames:
            bpy.context.scene.frame_set(frame)
            bpy.context.view_layer.update()
            rows.append(measure(action_name, frame, config))

    stored = {}
    for name in CLIPS:
        action = actions[name]
        bake(action, False, "inline")
        baked_a = bpy.data.actions[target.name + "_" + name]
        baked_a.name = target.name + "_" + name + "_A"
        bake(action, True, "inherit")
        baked_b = bpy.data.actions[target.name + "_" + name]
        baked_b.name = target.name + "_" + name + "_B"
        bake(action, True, "restore_foot")
        baked_c = bpy.data.actions[target.name + "_" + name]
        baked_c.name = target.name + "_" + name + "_C"
        stored[name] = {"A_base": baked_a, "B_inherit": baked_b, "C_restore": baked_c}
        start, end = int(action.frame_range[0]), int(round(action.frame_range[1]))
        stored[name]["span"] = list(range(start, end + 1))

    for name in CLIPS:
        for config, baked in stored[name].items():
            if config == "span":
                continue
            collect(name, baked, config, PRIORITY[name])

    def dist(a, b):
        left = json.loads(a)
        right = json.loads(b)
        return (sum((x - y) ** 2 for x, y in zip(left, right)) ** 0.5) * 1000.0

    def angle(a, b):
        from mathutils import Vector
        left = Vector(json.loads(a))
        right = Vector(json.loads(b))
        if left.length < 1e-9 or right.length < 1e-9:
            return 0.0
        return math.degrees(left.angle(right))

    indexed = {(row["config"], row["action"], int(row["frame"])): row for row in rows}

    def worst(name, config, frames):
        knee = ankle = length = foot = toe = sole = 0.0
        roll = 0.0
        new_deep = []
        z0 = z01 = 0
        depth = 0.0
        for frame in frames:
            base = indexed[("A_base", name, frame)]
            other = indexed[(config, name, frame)]
            if int(other["n_z_lt_0"]) > 0:
                z0 += 1
            if int(other["n_z_lt_001"]) > 0:
                z01 += 1
            depth = max(depth, float(other["penetration_mm"]))
            if float(other["mesh_lowest"]) < -0.01 and float(base["mesh_lowest"]) >= -0.01:
                new_deep.append(frame)
            for side in ("l", "r"):
                knee = max(knee, dist(base[side + "_knee"], other[side + "_knee"]))
                ankle = max(ankle, dist(base[side + "_ankle"], other[side + "_ankle"]))
                length = max(length, abs(float(base[side + "_lower_len"]) - float(other[side + "_lower_len"])) * 1000.0)
                foot = max(foot, quat_deg(
                    __import__("mathutils").Quaternion(json.loads(base[side + "_foot_quat"])),
                    __import__("mathutils").Quaternion(json.loads(other[side + "_foot_quat"])),
                ))
                toe = max(toe, angle(base[side + "_toe"], other[side + "_toe"]))
                sole = max(sole, angle(base[side + "_sole"], other[side + "_sole"]))
                roll = max(roll, abs(float(other[side + "_roll"])))
        return {
            "knee_mm": round(knee, 4),
            "ankle_mm": round(ankle, 4),
            "len_mm": round(length, 4),
            "foot_deg": round(foot, 4),
            "toe_deg": round(toe, 4),
            "sole_deg": round(sole, 4),
            "roll": round(roll, 4),
            "z0": z0,
            "z01": z01,
            "depth_mm": round(depth, 3),
            "new_deep": new_deep,
        }

    priority_ok = True
    for name in CLIPS:
        for config in ("B_inherit", "C_restore"):
            stats = worst(name, config, PRIORITY[name])
            print("PRIORITY", name, config, json.dumps(stats), flush=True)
            if config == "C_restore":
                if stats["roll"] > 5.0 or stats["knee_mm"] > 0.1 or stats["ankle_mm"] > 0.1 or stats["len_mm"] > 0.1 or stats["foot_deg"] > 0.5 or stats["new_deep"]:
                    priority_ok = False
    print("PRIORITY_OK", priority_ok, flush=True)
    if priority_ok:
        for name in CLIPS:
            extra = [frame for frame in stored[name]["span"] if frame not in PRIORITY[name]]
            for config in ("A_base", "B_inherit", "C_restore"):
                collect(name, stored[name][config], config, extra)
        indexed = {(row["config"], row["action"], int(row["frame"])): row for row in rows}
        for name in CLIPS:
            for config in ("B_inherit", "C_restore"):
                print("FULL", name, config, json.dumps(worst(name, config, stored[name]["span"])), flush=True)

    with open(OUT + r"\calf_foot_world_frames.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    with open(OUT + r"\calf_foot_world_pose_log.csv", "w", newline="", encoding="utf-8") as handle:
        if pose_rows:
            writer = csv.DictWriter(handle, fieldnames=list(pose_rows[0].keys()))
            writer.writeheader()
            writer.writerows(pose_rows)
    print("ROWS", len(rows), "DONE", flush=True)


if __name__ == "__main__":
    main()
