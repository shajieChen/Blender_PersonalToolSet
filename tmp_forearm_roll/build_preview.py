"""Bake a side-by-side preview of algorithms A-D. Does not touch official files."""
from __future__ import annotations

import csv
import math
import sys

import bpy
from mathutils import Quaternion, Vector

COPY = r"H:\Blender_Plugin\tmp_forearm_roll"
SOURCE = r"h:\SErsiko_ExtactedTool\output\c0000_突刺_wp_a_0300.glb"
TARGET = r"c:\Users\chenshajie1\Downloads\body.FBX"
ACTION = "a050_300000"
BLEND = r"H:\Blender_Plugin\tmp_forearm_roll\preview_swing_compare.blend"
VIDEO = r"H:\Blender_Plugin\tmp_forearm_roll\preview_swing_compare.mp4"
CSV = r"H:\Blender_Plugin\tmp_forearm_roll\preview_swing_compare.csv"


def wrap(angle):
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


def qdeg(a, b):
    a = a.normalized()
    b = b.normalized()
    return math.degrees(2.0 * math.acos(min(1.0, abs(max(-1.0, min(1.0, a.dot(b)))))))


def main():
    sys.path.insert(0, COPY)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    from humanoid_retarget.mapping import build_pairs
    from humanoid_retarget import pipeline
    import humanoid_retarget.retarget as retarget

    source, _ = pipeline.load_source(SOURCE)
    objects, _ = pipeline.import_model(TARGET)
    target = pipeline.pick_armature(objects)
    mesh = next(obj for obj in objects if obj.type == "MESH" and obj.parent == target)
    action = next(item for item in retarget.collect_actions(source) if item.name == ACTION)
    retarget._assign_action(source, action)
    pairs = build_pairs(source, target)
    roles = {role: (source_name, target_name) for role, source_name, target_name in pairs}
    src_roles = {role: pair[0] for role, pair in roles.items()}
    tgt_roles = {role: pair[1] for role, pair in roles.items()}
    source_body = retarget._body_matrix(source, retarget._anatomical_roles(source, src_roles))
    target_body = retarget._body_matrix(target, retarget._anatomical_roles(target, tgt_roles))
    chain_child = {"upperarm_l": "forearm_l", "forearm_l": "hand_l"}
    options = retarget.RetargetOptions(
        pairs=pairs, forearm_chain_twist=True, foot_ik=False, hand_ik=False, reference="REST",
    )
    options.forearm_roll_continuity = False

    def rest_chain(role):
        child = chain_child[role]
        return (
            target.data.bones[roles[child][1]].head_local - target.data.bones[roles[role][1]].head_local
        ).normalized()

    def rest_matrix(role):
        return target.pose.bones[roles[role][1]].bone.matrix_local.to_3x3()

    rests = {role: rest_chain(role) for role in chain_child}
    rest_orients = {role: rest_matrix(role) for role in chain_child}
    bone_rest = {role: retarget._rot3(target.data.bones[roles[role][1]].matrix_local) for role in chain_child}
    parent_rest = {
        role: retarget._rot3(target.pose.bones[roles[role][1]].parent.bone.matrix_local) for role in chain_child
    }

    scene = bpy.context.scene
    collection = scene.collection

    def spawn(name, x, color):
        arm = target.copy()
        arm.data = target.data.copy()
        arm.name = name
        arm.location = (x, 0.0, 0.0)
        arm.animation_data_clear()
        collection.objects.link(arm)
        body = mesh.copy()
        body.data = mesh.data.copy()
        body.name = name + "_mesh"
        body.parent = arm
        body.location = mesh.location.copy()
        body.rotation_euler = mesh.rotation_euler.copy()
        body.scale = mesh.scale.copy()
        body.color = color
        for modifier in body.modifiers:
            if modifier.type == "ARMATURE":
                modifier.object = arm
        collection.objects.link(body)
        material = bpy.data.materials.new(name + "_mat")
        material.diffuse_color = color
        body.data.materials.clear()
        body.data.materials.append(material)
        return arm

    clones = {
        "A": spawn("Preview_A", 0.0, (0.75, 0.75, 0.78, 1)),
        "B": spawn("Preview_B", 2.2, (0.35, 0.65, 0.95, 1)),
        "C": spawn("Preview_C", 4.4, (0.35, 0.80, 0.45, 1)),
        "D": spawn("Preview_D", 6.6, (0.90, 0.55, 0.25, 1)),
    }
    source.location = (-2.2, 0.0, 0.0)
    for obj in list(scene.objects):
        if obj.type == "MESH" and obj.parent == source:
            obj.location = source.matrix_world.translation * 0
            obj.name = "Preview_Source_mesh"

    def desired_and_twist(role):
        child = chain_child[role]
        src_chain = (
            source.pose.bones[roles[child][0]].head - source.pose.bones[roles[role][0]].head
        ).normalized()
        desired = (target_body @ (source_body.inverted() @ src_chain)).normalized()
        twist = retarget._source_chain_twist(source, roles[role][0], src_chain)
        return desired, twist

    def pose_a(role, desired, twist):
        swing = rests[role].rotation_difference(desired)
        orient = (swing.to_matrix() @ rest_orients[role]).to_quaternion()
        if role == "forearm_l":
            orient = (Quaternion(desired, twist) @ orient).normalized()
        return orient

    def basis_of(role, orient, parent_rotation):
        if hasattr(parent_rotation, "to_matrix"):
            parent_rotation = parent_rotation.to_matrix()
        return (
            bone_rest[role].inverted() @ parent_rest[role] @ parent_rotation.inverted() @ orient.to_matrix()
        ).to_quaternion()

    state = {mode: {} for mode in clones}
    rows = []
    previous = {mode: None for mode in clones}
    for frame in range(0, 53):
        scene.frame_set(frame)
        retarget._apply_body_orientations(source, target, pairs, options)
        bpy.context.view_layer.update()
        base = {
            bone.name: bone.matrix_basis.to_quaternion().copy()
            for bone in target.pose.bones
        }
        shoulder = retarget._rot3(target.pose.bones[roles["shoulder_l"][1]].matrix)
        item = {}
        for role in chain_child:
            desired, twist = desired_and_twist(role)
            item[role] = {"desired": desired, "twist": twist}
        for mode, arm in clones.items():
            orients = {}
            for role in ("upperarm_l", "forearm_l"):
                prior = state[mode].get(role)
                if prior is None or mode == "A":
                    orient = pose_a(role, item[role]["desired"], item[role]["twist"])
                    swing = rests[role].rotation_difference(item[role]["desired"])
                elif mode == "B":
                    orient = (prior["desired"].rotation_difference(item[role]["desired"]) @ prior["orient"]).normalized()
                    swing = orient
                elif mode == "C":
                    carried = prior["desired"].rotation_difference(item[role]["desired"]) @ prior["orient"]
                    orient = (Quaternion(item[role]["desired"], wrap(item[role]["twist"] - prior["twist"])) @ carried).normalized()
                    swing = orient
                else:
                    carried_swing = prior["desired"].rotation_difference(item[role]["desired"]) @ prior["swing"]
                    base_orient = (carried_swing.to_matrix() @ rest_orients[role]).to_quaternion()
                    twist = item[role]["twist"] if role == "forearm_l" else 0.0
                    orient = (Quaternion(item[role]["desired"], twist) @ base_orient).normalized()
                    swing = carried_swing
                orients[role] = orient
                state[mode][role] = {
                    "desired": item[role]["desired"].copy(),
                    "orient": orient.copy(),
                    "twist": item[role]["twist"],
                    "swing": swing.copy(),
                }
            upper_basis = basis_of("upperarm_l", orients["upperarm_l"], shoulder)
            forearm_basis = basis_of("forearm_l", orients["forearm_l"], orients["upperarm_l"])
            for bone_name, quat in base.items():
                pose = arm.pose.bones[bone_name]
                pose.rotation_mode = "QUATERNION"
                if bone_name == roles["upperarm_l"][1]:
                    quat = upper_basis
                elif bone_name == roles["forearm_l"][1]:
                    quat = forearm_basis
                pose.rotation_quaternion = quat
                pose.keyframe_insert(data_path="rotation_quaternion", frame=frame)
            if previous[mode] is not None:
                rows.append({
                    "frame": frame,
                    "mode": mode,
                    "upper_basis": round(qdeg(previous[mode]["upper"], upper_basis), 4),
                    "forearm_basis": round(qdeg(previous[mode]["forearm"], forearm_basis), 4),
                })
            previous[mode] = {"upper": upper_basis.copy(), "forearm": forearm_basis.copy()}
    with open(CSV, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["frame", "mode", "upper_basis", "forearm_basis"])
        writer.writeheader()
        writer.writerows(rows)

    camera_data = bpy.data.cameras.new("PreviewCamera")
    camera = bpy.data.objects.new("PreviewCamera", camera_data)
    camera.location = (2.2, -8.5, 2.4)
    camera.rotation_euler = (math.radians(78), 0.0, 0.0)
    collection.objects.link(camera)
    light_data = bpy.data.lights.new("PreviewLight", "SUN")
    light = bpy.data.objects.new("PreviewLight", light_data)
    light.rotation_euler = (math.radians(50), 0.0, math.radians(20))
    collection.objects.link(light)
    scene.camera = camera
    scene.frame_start = 0
    scene.frame_end = 52
    scene.render.resolution_x = 1600
    scene.render.resolution_y = 720
    scene.render.fps = 24
    try:
        scene.render.engine = "BLENDER_EEVEE"
    except TypeError:
        scene.render.engine = "BLENDER_EEVEE_NEXT"
    frames = r"H:\Blender_Plugin\tmp_forearm_roll\preview_frames\frame_"
    scene.render.filepath = frames
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    bpy.ops.wm.save_as_mainfile(filepath=BLEND)
    print("SAVED", BLEND)
    bpy.ops.render.render(animation=True)
    print("RENDERED", frames)
    print("DONE")


if __name__ == "__main__":
    main()
