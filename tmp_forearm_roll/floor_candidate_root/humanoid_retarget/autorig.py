"""Fit a Mixamo-style skeleton to an upright T-pose or A-pose humanoid mesh.

This is the local stand-in for Mixamo Upload Character. It does not ask for
marker clicks when the silhouette is a clear biped. Odd poses, extra limbs,
and props wider than the hands need a real skeleton instead.
"""

from __future__ import annotations

import bpy
from mathutils import Vector

from .classify import CORE_ROLES, classify_armature


class AutoRigError(RuntimeError):
    pass


def _percentile(values, pct):
    if not values:
        return 0.0
    ordered = sorted(values)
    index = int(round((len(ordered) - 1) * pct))
    return ordered[max(0, min(index, len(ordered) - 1))]


def _mean(points):
    count = len(points)
    return Vector((
        sum(point.x for point in points) / count,
        sum(point.y for point in points) / count,
        sum(point.z for point in points) / count,
    ))


def mesh_world_vertices(meshes):
    coords = []
    depsgraph = bpy.context.evaluated_depsgraph_get()
    for obj in meshes:
        if obj.type != "MESH":
            continue
        eval_obj = obj.evaluated_get(depsgraph)
        mesh = eval_obj.to_mesh()
        try:
            matrix = obj.matrix_world
            coords.extend(matrix @ vertex.co for vertex in mesh.vertices)
        finally:
            eval_obj.to_mesh_clear()
    return coords


def detect_landmarks(verts):
    if len(verts) < 20:
        raise AutoRigError("网格顶点太少，无法估计人体关节。")
    xs = [vertex.x for vertex in verts]
    ys = [vertex.y for vertex in verts]
    zs = [vertex.z for vertex in verts]
    min_z, max_z = min(zs), max(zs)
    height = max(max_z - min_z, 1e-6)
    center_x = _percentile(xs, 0.5)
    center_y = _percentile(ys, 0.5)

    def z_at(ratio):
        return min_z + height * ratio

    def band(r0, r1):
        z0, z1 = z_at(r0), z_at(r1)
        return [vertex for vertex in verts if z0 <= vertex.z <= z1]

    upper = [vertex for vertex in verts if vertex.z >= z_at(0.48)]
    if len(upper) < 10:
        raise AutoRigError("角色上半身顶点不够。请让模型直立，脚在下、头在上。")

    def extremity(sign):
        pool = [vertex for vertex in upper if (vertex.x - center_x) * sign > 0]
        if not pool:
            raise AutoRigError("没有分出左右两侧，无法自动绑定。")
        reach = max((vertex.x - center_x) * sign for vertex in pool)
        keep = [vertex for vertex in pool if (vertex.x - center_x) * sign >= reach - height * 0.04]
        return _mean(keep)

    wrist_l = extremity(1.0)
    wrist_r = extremity(-1.0)
    if (wrist_l - wrist_r).length < height * 0.35:
        raise AutoRigError("双臂没有张开。请改成 T Pose 或 A Pose，手臂离开躯干后再自动绑定。")

    chest = band(0.62, 0.84) or upper
    radii = sorted(abs(vertex.x - center_x) for vertex in chest)
    torso_half = _percentile(radii, 0.72)
    if len(radii) >= 8:
        gap_at = torso_half
        gap_size = 0.0
        for left, right in zip(radii, radii[1:]):
            gap = right - left
            if gap > gap_size:
                gap_size = gap
                gap_at = left
        if gap_size > height * 0.02:
            torso_half = gap_at + gap_size * 0.15
    torso_half = max(torso_half, height * 0.06)

    def shoulder(sign, wrist):
        pool = [
            vertex for vertex in upper
            if (vertex.x - center_x) * sign > torso_half * 0.4
            and abs(vertex.x - center_x) < torso_half + height * 0.12
            and abs(vertex.z - wrist.z) < height * 0.2
        ]
        if len(pool) < 3:
            return Vector((center_x + sign * torso_half, center_y, wrist.z))
        return _mean(pool)

    shoulder_l = shoulder(1.0, wrist_l)
    shoulder_r = shoulder(-1.0, wrist_r)

    def along(start, end, ratio):
        guess = start.lerp(end, ratio)
        near = [vertex for vertex in verts if (vertex - guess).length < height * 0.1]
        return _mean(near) if len(near) >= 3 else guess

    elbow_l = along(shoulder_l, wrist_l, 0.5)
    elbow_r = along(shoulder_r, wrist_r, 0.5)

    groin_z = z_at(0.47)
    saw_split = False
    for step in range(8, 68):
        sample = band(step / 100.0, step / 100.0 + 0.025)
        if len(sample) < 6:
            continue
        left_n = sum(1 for vertex in sample if vertex.x < center_x - height * 0.015)
        right_n = sum(1 for vertex in sample if vertex.x > center_x + height * 0.015)
        mid_n = len(sample) - left_n - right_n
        split = left_n >= 3 and right_n >= 3 and mid_n <= (left_n + right_n) * 0.25
        if split:
            groin_z = z_at(step / 100.0 + 0.025)
            saw_split = True
        elif saw_split:
            break
    hips = Vector((center_x, center_y, groin_z))

    def leg_point(sign, ratio):
        z = min_z + (groin_z - min_z) * ratio
        pool = [
            vertex for vertex in verts
            if abs(vertex.z - z) < height * 0.06 and (vertex.x - center_x) * sign > 0
        ]
        if len(pool) < 3:
            return Vector((center_x + sign * torso_half * 0.45, center_y, z))
        return _mean(pool)

    knee_l = leg_point(1.0, 0.48)
    knee_r = leg_point(-1.0, 0.48)
    ankle_l = leg_point(1.0, 0.06)
    ankle_r = leg_point(-1.0, 0.06)
    ankle_l.z = min(ankle_l.z, z_at(0.08))
    ankle_r.z = min(ankle_r.z, z_at(0.08))

    head_band = band(0.88, 0.99) or band(0.8, 1.0)
    if head_band:
        y0 = _percentile([vertex.y for vertex in head_band], 0.08)
        y1 = _percentile([vertex.y for vertex in head_band], 0.92)
        mid_y = _percentile([vertex.y for vertex in head_band], 0.5)
        if abs(y0 - mid_y) > abs(y1 - mid_y) + height * 0.01:
            facing = Vector((0.0, -1.0, 0.0))
        elif abs(y1 - mid_y) > abs(y0 - mid_y) + height * 0.01:
            facing = Vector((0.0, 1.0, 0.0))
        else:
            facing = Vector((0.0, -1.0, 0.0))
    else:
        facing = Vector((0.0, -1.0, 0.0))

    neck = Vector((center_x, center_y, z_at(0.84)))
    head_top = Vector((center_x, center_y, max_z - height * 0.01))
    return {
        "hips": hips,
        "neck": neck,
        "head_top": head_top,
        "shoulder_l": shoulder_l,
        "elbow_l": elbow_l,
        "wrist_l": wrist_l,
        "shoulder_r": shoulder_r,
        "elbow_r": elbow_r,
        "wrist_r": wrist_r,
        "knee_l": knee_l,
        "ankle_l": ankle_l,
        "knee_r": knee_r,
        "ankle_r": ankle_r,
        "facing": facing,
        "height": height,
        "center": Vector((center_x, center_y, min_z)),
    }


def _new_bone(armature, name, head, tail, parent=None):
    if (tail - head).length < 1e-4:
        tail = head + Vector((0.0, 0.0, 1e-3))
    bone = armature.edit_bones.new(name)
    bone.head = head
    bone.tail = tail
    bone.use_connect = False
    if parent is not None:
        bone.parent = parent
    try:
        bone.align_roll(Vector((0.0, -1.0, 0.0)))
    except Exception:
        pass
    return bone


def _extend(origin, toward, length):
    direction = toward - origin
    if direction.length < 1e-6:
        direction = Vector((0.0, -1.0, 0.0))
    return origin + direction.normalized() * length


def build_skeleton(landmarks):
    height = landmarks["height"]
    hips_p = landmarks["hips"]
    neck_p = landmarks["neck"]
    head_p = landmarks["head_top"]
    facing = landmarks["facing"]
    hand_len = height * 0.07
    foot_len = height * 0.07

    spine_a = hips_p.lerp(neck_p, 0.34)
    spine_b = hips_p.lerp(neck_p, 0.67)
    hips_tail = hips_p.lerp(spine_a, 0.35)
    arm_data = bpy.data.armatures.new("HR_Rig")
    arm_obj = bpy.data.objects.new("HR_Rig", arm_data)
    bpy.context.scene.collection.objects.link(arm_obj)
    bpy.context.view_layer.objects.active = arm_obj
    bpy.ops.object.mode_set(mode="EDIT")
    try:
        hips = _new_bone(arm_data, "Hips", hips_p, hips_tail)
        spine = _new_bone(arm_data, "Spine", hips_tail, spine_a, hips)
        chest = _new_bone(arm_data, "Spine2", spine_a, spine_b, spine)
        neck = _new_bone(arm_data, "Neck", spine_b, neck_p, chest)
        _new_bone(arm_data, "Head", neck_p, head_p, neck)

        def arm(side, shoulder_p, elbow_p, wrist_p, parent):
            prefix = "Left" if side == "l" else "Right"
            shoulder = _new_bone(arm_data, f"{prefix}Shoulder", spine_b, shoulder_p, parent)
            upper = _new_bone(arm_data, f"{prefix}Arm", shoulder_p, elbow_p, shoulder)
            forearm = _new_bone(arm_data, f"{prefix}ForeArm", elbow_p, wrist_p, upper)
            _new_bone(arm_data, f"{prefix}Hand", wrist_p, _extend(wrist_p, wrist_p - elbow_p, hand_len), forearm)

        def leg(side, knee_p, ankle_p, parent):
            prefix = "Left" if side == "l" else "Right"
            outward = Vector((0.08 if side == "l" else -0.08, 0.0, 0.0)) * height
            thigh_head = Vector((hips_p.x, hips_p.y, hips_p.z)) + outward * 0.15
            thigh = _new_bone(arm_data, f"{prefix}UpLeg", thigh_head, knee_p, parent)
            shin = _new_bone(arm_data, f"{prefix}Leg", knee_p, ankle_p, thigh)
            foot_tail = ankle_p + facing * foot_len + Vector((0.0, 0.0, -height * 0.01))
            foot = _new_bone(arm_data, f"{prefix}Foot", ankle_p, foot_tail, shin)
            _new_bone(arm_data, f"{prefix}ToeBase", foot_tail, foot_tail + facing * foot_len * 0.6, foot)

        arm("l", landmarks["shoulder_l"], landmarks["elbow_l"], landmarks["wrist_l"], chest)
        arm("r", landmarks["shoulder_r"], landmarks["elbow_r"], landmarks["wrist_r"], chest)
        leg("l", landmarks["knee_l"], landmarks["ankle_l"], hips)
        leg("r", landmarks["knee_r"], landmarks["ankle_r"], hips)
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")
    return arm_obj


def skin_meshes(arm_obj, meshes):
    if not meshes:
        return "none"
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for obj in bpy.context.view_layer.objects:
        obj.select_set(False)
    for mesh in meshes:
        mesh.select_set(True)
    arm_obj.select_set(True)
    bpy.context.view_layer.objects.active = arm_obj
    override = {
        "object": arm_obj,
        "active_object": arm_obj,
        "selected_objects": [arm_obj, *meshes],
        "selected_editable_objects": [arm_obj, *meshes],
    }
    try:
        with bpy.context.temp_override(**override):
            bpy.ops.object.parent_set(type="ARMATURE_AUTO")
        return "自动权重"
    except RuntimeError as exc:
        print("[HumanoidRetarget] bone heat failed:", exc)
        with bpy.context.temp_override(**override):
            bpy.ops.object.parent_set(type="ARMATURE_ENVELOPE")
        return "包络权重"


def auto_rig_meshes(meshes):
    verts = mesh_world_vertices(meshes)
    landmarks = detect_landmarks(verts)
    arm_obj = build_skeleton(landmarks)
    weight_mode = skin_meshes(arm_obj, meshes)
    roles = classify_armature(arm_obj)
    missing = [role for role in CORE_ROLES if role not in roles]
    if missing:
        raise AutoRigError("自动骨架生成了，但身体部位不完整: " + ", ".join(missing))
    arm_obj["hr_autorig"] = True
    arm_obj["hr_weights"] = weight_mode
    return arm_obj, weight_mode, landmarks
