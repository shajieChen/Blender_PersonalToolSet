"""Headless checks for humanoid import, auto-rig, retarget and export."""

import math
import os
import sys
import traceback

import bpy
from mathutils import Euler, Matrix, Vector

ROOT = r"H:\Blender_Plugin"
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import humanoid_retarget
from humanoid_retarget.classify import classify_armature
from humanoid_retarget.pipeline import export_armature, load_source, load_target_and_retarget, initial_filepath, set_armature_bones_visible, set_bone_sphere_display
from humanoid_retarget.mapping import load_preset, merge_preset, save_preset
from humanoid_retarget.retarget import RetargetOptions, bake_retarget, capture_reference

OUT = os.path.join(ROOT, "tests", "out")
os.makedirs(OUT, exist_ok=True)


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print("PASS", message)


def bone_dir(obj, bone_name):
    pose_bone = obj.pose.bones[bone_name]
    matrix = obj.matrix_world
    head = matrix @ pose_bone.head
    tail = matrix @ pose_bone.tail
    return (tail - head).normalized()


def build_biped(obj_name, names, arm_roll=0.0, scale=1.0):
    arm_data = bpy.data.armatures.new(obj_name)
    obj = bpy.data.objects.new(obj_name, arm_data)
    bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="EDIT")
    bones = arm_data.edit_bones

    def add(role, head, tail, parent=None, roll=0.0):
        bone = bones.new(names[role])
        bone.head = Vector(head) * scale
        bone.tail = Vector(tail) * scale
        bone.use_connect = False
        if parent is not None:
            bone.parent = bones[names[parent]]
        bone.roll = roll
        return bone

    add("hips", (0, 0, 0.95), (0, 0, 1.08))
    add("spine", (0, 0, 1.08), (0, 0, 1.28), "hips")
    add("chest", (0, 0, 1.28), (0, 0, 1.48), "spine")
    add("neck", (0, 0, 1.48), (0, 0, 1.58), "chest")
    add("head", (0, 0, 1.58), (0, 0, 1.75), "neck")
    add("shoulder_l", (0.02, 0, 1.46), (0.16, 0, 1.48), "chest")
    add("upperarm_l", (0.16, 0, 1.48), (0.46, 0, 1.48), "shoulder_l", arm_roll)
    add("forearm_l", (0.46, 0, 1.48), (0.72, 0, 1.48), "upperarm_l", arm_roll)
    add("hand_l", (0.72, 0, 1.48), (0.84, 0, 1.48), "forearm_l")
    add("shoulder_r", (-0.02, 0, 1.46), (-0.16, 0, 1.48), "chest")
    add("upperarm_r", (-0.16, 0, 1.48), (-0.46, 0, 1.48), "shoulder_r", arm_roll)
    add("forearm_r", (-0.46, 0, 1.48), (-0.72, 0, 1.48), "upperarm_r", arm_roll)
    add("hand_r", (-0.72, 0, 1.48), (-0.84, 0, 1.48), "forearm_r")
    add("thigh_l", (0.10, 0, 0.95), (0.12, 0, 0.52), "hips")
    add("shin_l", (0.12, 0, 0.52), (0.12, 0, 0.08), "thigh_l")
    add("foot_l", (0.12, 0, 0.08), (0.12, -0.14, 0.04), "shin_l")
    add("toe_l", (0.12, -0.14, 0.04), (0.12, -0.22, 0.03), "foot_l")
    add("thigh_r", (-0.10, 0, 0.95), (-0.12, 0, 0.52), "hips")
    add("shin_r", (-0.12, 0, 0.52), (-0.12, 0, 0.08), "thigh_r")
    add("foot_r", (-0.12, 0, 0.08), (-0.12, -0.14, 0.04), "shin_r")
    add("toe_r", (-0.12, -0.14, 0.04), (-0.12, -0.22, 0.03), "foot_r")
    bpy.ops.object.mode_set(mode="POSE")
    return obj


def animate(obj, names):
    upper = obj.pose.bones[names["upperarm_l"]]
    spine = obj.pose.bones[names["spine"]]
    hips = obj.pose.bones[names["hips"]]
    upper.rotation_mode = "XYZ"
    spine.rotation_mode = "XYZ"
    upper.rotation_euler = (0.0, 0.0, 0.0)
    spine.rotation_euler = (0.0, 0.0, 0.0)
    hips.location = (0.0, 0.0, 0.0)
    upper.keyframe_insert("rotation_euler", frame=1)
    spine.keyframe_insert("rotation_euler", frame=1)
    hips.keyframe_insert("location", frame=1)
    upper.rotation_euler = (math.radians(75), 0.0, 0.0)
    spine.rotation_euler = (math.radians(20), 0.0, 0.0)
    hips.location = (0.15, 0.25, 0.0)
    upper.keyframe_insert("rotation_euler", frame=10)
    spine.keyframe_insert("rotation_euler", frame=10)
    hips.keyframe_insert("location", frame=10)
    bpy.ops.object.mode_set(mode="OBJECT")


def junk_names():
    roles = (
        "hips", "spine", "chest", "neck", "head",
        "shoulder_l", "upperarm_l", "forearm_l", "hand_l",
        "shoulder_r", "upperarm_r", "forearm_r", "hand_r",
        "thigh_l", "shin_l", "foot_l", "toe_l",
        "thigh_r", "shin_r", "foot_r", "toe_r",
    )
    return {role: f"Jnt_{index:02d}" for index, role in enumerate(roles)}


def test_geometry_and_bake():
    print("--- geometry retarget ---")
    src_names = junk_names()
    tgt_names = {role: f"Tgt_{role}" for role in src_names}
    source = build_biped("SourceRig", src_names, arm_roll=0.0, scale=1.0)
    animate(source, src_names)
    target = build_biped("TargetRig", tgt_names, arm_roll=0.55, scale=1.25)
    bpy.context.view_layer.objects.active = target
    bpy.ops.object.mode_set(mode="OBJECT")

    src_roles = classify_armature(source)
    tgt_roles = classify_armature(target)
    print("SRC", src_roles)
    print("TGT", tgt_roles)
    for role in ("hips", "spine", "chest", "head", "upperarm_l", "forearm_l", "thigh_l", "shin_l", "foot_l"):
        check(src_roles.get(role) == src_names[role], f"source {role}")
        check(tgt_roles.get(role) == tgt_names[role], f"target {role}")

    report, baked = bake_retarget(source, target)
    print(report)
    check(len(baked) == 1, "one baked action")

    scene = bpy.context.scene
    scene.frame_set(10)
    bpy.context.view_layer.update()
    src_arm = bone_dir(source, src_names["upperarm_l"])
    tgt_arm = bone_dir(target, tgt_names["upperarm_l"])
    print("ARM", src_arm, tgt_arm, "dot", src_arm.dot(tgt_arm))
    check(src_arm.dot(tgt_arm) > 0.9, "raised arm direction matches across different bone roll")

    src_spine = bone_dir(source, src_names["spine"])
    tgt_spine = bone_dir(target, tgt_names["spine"])
    print("SPINE", src_spine, tgt_spine, "dot", src_spine.dot(tgt_spine))
    check(src_spine.dot(tgt_spine) > 0.9, "spine bend matches")

    src_delta = source.pose.bones[src_names["hips"]].head.z - source.data.bones[src_names["hips"]].head_local.z
    tgt_delta = target.pose.bones[tgt_names["hips"]].head.z - target.data.bones[tgt_names["hips"]].head_local.z
    print("HIPS", src_delta, tgt_delta)
    check(src_delta > 0.05, "source hips moved up")
    check(abs(tgt_delta - src_delta * 1.25) < 0.02, "target hips keep scaled root motion")

    action = source.animation_data.action
    action.use_fake_user = True
    slot = source.animation_data.action_slot
    source.animation_data_clear()
    scene.frame_set(1)
    bpy.context.view_layer.update()
    rest_dir = bone_dir(target, tgt_names["upperarm_l"])
    scene.frame_set(10)
    bpy.context.view_layer.update()
    posed_dir = bone_dir(target, tgt_names["upperarm_l"])
    check(rest_dir.dot(posed_dir) < 0.85, "target animation plays after the source rig is cleared")
    source.animation_data_create()
    source.animation_data.action = action
    if slot is not None:
        source.animation_data.action_slot = slot
    return source, target


def test_mixamo_names():
    print("--- mixamo names ---")
    names = {
        "hips": "mixamorig:Hips",
        "spine": "mixamorig:Spine",
        "chest": "mixamorig:Spine2",
        "neck": "mixamorig:Neck",
        "head": "mixamorig:Head",
        "shoulder_l": "mixamorig:LeftShoulder",
        "upperarm_l": "mixamorig:LeftArm",
        "forearm_l": "mixamorig:LeftForeArm",
        "hand_l": "mixamorig:LeftHand",
        "shoulder_r": "mixamorig:RightShoulder",
        "upperarm_r": "mixamorig:RightArm",
        "forearm_r": "mixamorig:RightForeArm",
        "hand_r": "mixamorig:RightHand",
        "thigh_l": "mixamorig:LeftUpLeg",
        "shin_l": "mixamorig:LeftLeg",
        "foot_l": "mixamorig:LeftFoot",
        "toe_l": "mixamorig:LeftToeBase",
        "thigh_r": "mixamorig:RightUpLeg",
        "shin_r": "mixamorig:RightLeg",
        "foot_r": "mixamorig:RightFoot",
        "toe_r": "mixamorig:RightToeBase",
    }
    arm_data = bpy.data.armatures.new("NameOnly")
    obj = bpy.data.objects.new("NameOnly", arm_data)
    bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="EDIT")
    cursor = 0.0
    for role, bone_name in names.items():
        bone = arm_data.edit_bones.new(bone_name)
        bone.head = (0.0, 0.0, cursor)
        bone.tail = (0.0, 0.0, cursor + 0.1)
        cursor += 0.1
    bpy.ops.object.mode_set(mode="OBJECT")
    roles = classify_armature(obj)
    print("NAMES", roles)
    for role in ("hips", "upperarm_l", "upperarm_r", "thigh_l", "thigh_r", "shin_l"):
        check(roles.get(role) == names[role], f"named {role}")


def add_box(name, center, size):
    bpy.ops.mesh.primitive_cube_add(location=center)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = size
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    return obj


def test_autorig_and_roundtrip(source):
    print("--- autorig ---")
    boxes = [
        add_box("Torso", (0.0, 0.0, 1.15), (0.16, 0.10, 0.28)),
        add_box("Head", (0.0, 0.0, 1.62), (0.10, 0.11, 0.12)),
        add_box("ArmL", (0.48, 0.0, 1.32), (0.26, 0.05, 0.05)),
        add_box("ArmR", (-0.48, 0.0, 1.32), (0.26, 0.05, 0.05)),
        add_box("LegL", (0.10, 0.0, 0.44), (0.06, 0.06, 0.42)),
        add_box("LegR", (-0.10, 0.0, 0.44), (0.06, 0.06, 0.42)),
    ]
    humanoid_retarget.register()
    settings = bpy.context.scene.hr_settings
    settings.source = source
    bpy.ops.object.select_all(action="DESELECT")
    for box in boxes:
        box.select_set(True)
    bpy.context.view_layer.objects.active = boxes[0]
    result = bpy.ops.hr.retarget_selected_mesh()
    check("FINISHED" in result, "mesh operator finished")
    target = settings.target
    print(settings.status)
    check(target is not None and target.type == "ARMATURE", "auto rig created an armature")
    roles = classify_armature(target)
    print("AUTO", roles)
    check("upperarm_l" in roles and "thigh_l" in roles, "auto rig classified limbs")

    scene = bpy.context.scene
    scene.frame_set(1)
    bpy.context.view_layer.update()
    rest = bone_dir(target, roles["upperarm_l"])
    scene.frame_set(10)
    bpy.context.view_layer.update()
    posed = bone_dir(target, roles["upperarm_l"])
    print("AUTO ARM", rest, posed, "dot", rest.dot(posed))
    check(rest.dot(posed) < 0.85, "auto-rigged character receives the arm motion")

    fbx_path = os.path.join(OUT, "source.fbx")
    obj_path = os.path.join(OUT, "target.obj")
    glb_path = os.path.join(OUT, "result.glb")
    export_armature(source, fbx_path)
    bpy.ops.object.select_all(action="DESELECT")
    for box in boxes:
        box.select_set(True)
    bpy.ops.wm.obj_export(filepath=obj_path, export_selected_objects=True)
    check(os.path.exists(fbx_path), "source fbx written")
    check(os.path.exists(obj_path), "target obj written")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    humanoid_retarget.register()
    loaded, summary = load_source(fbx_path)
    print(summary)
    check(loaded.animation_data and loaded.animation_data.action, "imported source keeps an action")
    armature, summary, baked, _auto = load_target_and_retarget(obj_path, loaded)
    print(summary)
    check(armature.get("hr_autorig") is True or "Hips" in armature.data.bones, "imported mesh was auto rigged")
    check(len(baked) >= 1, "roundtrip baked an action")
    export_armature(armature, glb_path)
    check(os.path.exists(glb_path) and os.path.getsize(glb_path) > 500, "glb download written")

    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=glb_path)
    imported = [obj for obj in bpy.data.objects if obj not in before and obj.type == "ARMATURE"]
    check(len(imported) == 1, "glb contains an armature")
    check(imported[0].animation_data and imported[0].animation_data.action, "glb keeps the baked animation")


def rest_direction(obj, bone_name):
    bone = obj.data.bones[bone_name]
    head = obj.matrix_world @ bone.head_local
    tail = obj.matrix_world @ bone.tail_local
    return (tail - head).normalized()


def world_head(obj, bone_name):
    return obj.matrix_world @ obj.pose.bones[bone_name].head


def aim_pose(obj, bone_name, direction):
    pose_bone = obj.pose.bones[bone_name]
    y_axis = direction.normalized()
    x_axis = Vector((0.0, 1.0, 0.0))
    x_axis = x_axis - y_axis * x_axis.dot(y_axis)
    if x_axis.length < 1e-6:
        x_axis = Vector((1.0, 0.0, 0.0))
    x_axis.normalize()
    z_axis = x_axis.cross(y_axis).normalized()
    x_axis = y_axis.cross(z_axis).normalized()
    head = obj.data.bones[bone_name].head_local.copy()
    pose_bone.rotation_mode = "QUATERNION"
    pose_bone.matrix = Matrix((
        (x_axis.x, y_axis.x, z_axis.x, head.x),
        (x_axis.y, y_axis.y, z_axis.y, head.y),
        (x_axis.z, y_axis.z, z_axis.z, head.z),
        (0.0, 0.0, 0.0, 1.0),
    ))


def _role_names(prefix):
    return {role: f"{prefix}_{role}" for role in junk_names()}


def test_mapping_root_reference_and_ik():
    print("--- mapping, root, reference, ik ---")
    humanoid_retarget.register()
    settings = bpy.context.scene.hr_settings
    check(settings.root_motion == "KEEP", "root motion defaults to keeping displacement")
    check(settings.reference_pose == "REST", "reference pose defaults to rest")
    check(settings.use_foot_ik is False and settings.use_hand_ik is False, "ik stays off unless enabled")

    roles = _role_names("Map")
    target_names = _role_names("MapT")
    source = build_biped("MapSource", roles, arm_roll=0.0, scale=1.0)
    animate(source, roles)
    target = build_biped("MapTarget", target_names, arm_roll=0.0, scale=1.0)
    settings.source = source
    settings.target = target
    settings.mappings.clear()
    check("FINISHED" in bpy.ops.hr.build_mapping(), "build mapping operator finished")
    check(len(settings.mappings) >= 5, "mapping table lists the matched bones")

    for item in settings.mappings:
        if item.role == "upperarm_l":
            item.target_bone = target_names["upperarm_r"]
        elif item.role == "upperarm_r":
            item.target_bone = target_names["upperarm_l"]
    settings.preset_name = "feature_swap"
    check("FINISHED" in bpy.ops.hr.save_preset(), "save mapping preset")
    settings.mappings.clear()
    check("FINISHED" in bpy.ops.hr.load_preset(), "load mapping preset")
    loaded = {item.role: item.target_bone for item in settings.mappings}
    check(loaded.get("upperarm_l") == target_names["upperarm_r"], "preset restores the edited left-arm target")
    check(loaded.get("upperarm_r") == target_names["upperarm_l"], "preset restores the edited right-arm target")
    stored = load_preset("feature_swap")
    merged = merge_preset(
        [(item.role, item.source_bone, item.target_bone) for item in settings.mappings],
        stored,
        source,
        target,
    )
    check(any(role == "upperarm_l" and tgt == target_names["upperarm_r"] for role, _src, tgt in merged), "preset merge keeps an existing bone")

    check("FINISHED" in bpy.ops.hr.retarget_existing(), "retarget uses the edited mapping")
    scene = bpy.context.scene
    scene.frame_set(10)
    bpy.context.view_layer.update()
    quiet = bone_dir(target, target_names["upperarm_l"]).dot(rest_direction(target, target_names["upperarm_l"]))
    driven = bone_dir(target, target_names["upperarm_r"]).dot(rest_direction(target, target_names["upperarm_r"]))
    print("MAP", quiet, driven)
    check(quiet > 0.95, "edited mapping does not play the arm clip on the original left bone")
    check(driven < 0.8, "edited mapping plays the arm clip on the chosen bone")

    keep = build_biped("KeepRig", _role_names("Keep"), arm_roll=0.0, scale=1.0)
    stay = build_biped("StayRig", _role_names("Stay"), arm_roll=0.0, scale=1.0)
    bake_retarget(source, keep, RetargetOptions(root_motion="KEEP"))
    settings.source = source
    settings.target = stay
    settings.mappings.clear()
    settings.reference_pose = "REST"
    settings.reference_json = ""
    settings.root_motion = "IN_PLACE"
    settings.use_foot_ik = False
    settings.use_hand_ik = False
    check("FINISHED" in bpy.ops.hr.retarget_existing(), "in-place retarget operator finished")
    scene.frame_set(1)
    bpy.context.view_layer.update()
    keep_start = world_head(keep, "Keep_hips")
    stay_start = world_head(stay, "Stay_hips")
    scene.frame_set(10)
    bpy.context.view_layer.update()
    keep_delta = world_head(keep, "Keep_hips") - keep_start
    stay_delta = world_head(stay, "Stay_hips") - stay_start
    print("ROOT", keep_delta, stay_delta)
    check(abs(keep_delta.x) + abs(keep_delta.y) > 0.05, "keep mode still travels horizontally")
    check(abs(stay_delta.x) < 0.02 and abs(stay_delta.y) < 0.02, "in place drops horizontal travel")
    check(abs(stay_delta.z) > 0.05 and abs(stay_delta.z - keep_delta.z) < 0.02, "in place keeps the vertical bob")

    ref_names = _role_names("RefS")
    ref_target_names = _role_names("RefT")
    ref_source = build_biped("RefSource", ref_names, arm_roll=0.0, scale=1.0)
    ref_target = build_biped("RefTarget", ref_target_names, arm_roll=0.0, scale=1.0)
    bpy.context.view_layer.objects.active = ref_source
    bpy.ops.object.mode_set(mode="POSE")
    src_arm = ref_source.pose.bones[ref_names["upperarm_l"]]
    src_arm.rotation_mode = "XYZ"
    src_arm.rotation_euler = (math.radians(40.0), 0.0, 0.0)
    src_arm.keyframe_insert("rotation_euler", frame=1)
    src_arm.rotation_euler = (math.radians(70.0), 0.0, 0.0)
    src_arm.keyframe_insert("rotation_euler", frame=10)
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.context.view_layer.objects.active = ref_target
    bpy.ops.object.mode_set(mode="POSE")
    tgt_arm = ref_target.pose.bones[ref_target_names["upperarm_l"]]
    tgt_arm.rotation_mode = "XYZ"
    tgt_arm.rotation_euler = (math.radians(-25.0), 0.0, 0.0)
    bpy.ops.object.mode_set(mode="OBJECT")
    scene.frame_set(1)
    bpy.context.view_layer.update()
    captured_target = bone_dir(ref_target, ref_target_names["upperarm_l"]).copy()
    source_at_zero = bone_dir(ref_source, ref_names["upperarm_l"]).copy()
    check(captured_target.dot(source_at_zero) < 0.98, "captured poses start from different bends")
    settings.source = ref_source
    settings.target = ref_target
    settings.mappings.clear()
    settings.root_motion = "KEEP"
    settings.reference_json = ""
    check("FINISHED" in bpy.ops.hr.capture_reference(), "capture reference operator finished")
    check(settings.reference_pose == "CURRENT" and len(settings.reference_json) > 20, "capture stores the current pose")
    check("FINISHED" in bpy.ops.hr.retarget_existing(), "current-reference retarget finished")
    scene.frame_set(1)
    bpy.context.view_layer.update()
    current_zero = bone_dir(ref_target, ref_target_names["upperarm_l"]).copy()
    scene.frame_set(10)
    bpy.context.view_layer.update()
    current_extra = bone_dir(ref_target, ref_target_names["upperarm_l"]).copy()
    source_extra = bone_dir(ref_source, ref_names["upperarm_l"]).copy()
    settings.reference_pose = "REST"
    settings.reference_json = ""
    settings.mappings.clear()
    check("FINISHED" in bpy.ops.hr.retarget_existing(), "rest-reference retarget finished")
    scene.frame_set(1)
    bpy.context.view_layer.update()
    rest_zero = bone_dir(ref_target, ref_target_names["upperarm_l"]).copy()
    src_step = source_at_zero.dot(source_extra)
    tgt_step = current_zero.dot(current_extra)
    print("REF", current_zero.dot(captured_target), rest_zero.dot(source_at_zero), current_zero.dot(rest_zero), src_step, tgt_step)
    check(current_zero.dot(captured_target) > 0.99, "current reference keeps the captured target pose")
    check(rest_zero.dot(source_at_zero) > 0.99, "rest reference copies the source pose")
    check(current_zero.dot(rest_zero) < 0.95, "current reference stays on the captured pose instead of the source pose")
    check(abs(src_step - tgt_step) < 0.05, "current reference carries the same extra bend")

    ik_names = _role_names("IkS")
    ik_target_names = _role_names("IkT")
    ik_source = build_biped("IkSource", ik_names, arm_roll=0.0, scale=1.0)
    ik_fk = build_biped("IkFk", ik_target_names, arm_roll=0.0, scale=1.0)
    ik_on = build_biped("IkOn", _role_names("IkU"), arm_roll=0.0, scale=1.0)
    for rig, names in ((ik_fk, ik_target_names), (ik_on, _role_names("IkU"))):
        bpy.context.view_layer.objects.active = rig
        bpy.ops.object.mode_set(mode="EDIT")
        shin = rig.data.edit_bones[names["shin_l"]]
        lift = Vector((0.0, 0.0, 0.16))
        shin.tail += lift
        for role in ("foot_l", "toe_l"):
            bone = rig.data.edit_bones[names[role]]
            bone.head += lift
            bone.tail += lift
        forearm = rig.data.edit_bones[names["forearm_l"]]
        pull = Vector((-0.12, 0.0, 0.0))
        forearm.tail += pull
        for role in ("hand_l",):
            bone = rig.data.edit_bones[names[role]]
            bone.head += pull
            bone.tail += pull
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.context.view_layer.objects.active = ik_source
    bpy.ops.object.mode_set(mode="POSE")
    thigh = ik_source.pose.bones[ik_names["thigh_l"]]
    shin = ik_source.pose.bones[ik_names["shin_l"]]
    forearm = ik_source.pose.bones[ik_names["forearm_l"]]
    thigh.rotation_mode = "XYZ"
    shin.rotation_mode = "XYZ"
    forearm.rotation_mode = "XYZ"
    thigh.rotation_euler = (0.0, 0.0, 0.0)
    shin.rotation_euler = (0.0, 0.0, 0.0)
    forearm.rotation_euler = (0.0, 0.0, 0.0)
    thigh.keyframe_insert("rotation_euler", frame=1)
    shin.keyframe_insert("rotation_euler", frame=1)
    forearm.keyframe_insert("rotation_euler", frame=1)
    thigh.rotation_euler = (math.radians(20), 0.0, 0.0)
    shin.rotation_euler = (math.radians(80), 0.0, 0.0)
    forearm.rotation_euler = (0.0, 0.0, math.radians(60))
    thigh.keyframe_insert("rotation_euler", frame=10)
    shin.keyframe_insert("rotation_euler", frame=10)
    forearm.keyframe_insert("rotation_euler", frame=10)
    bpy.ops.object.mode_set(mode="OBJECT")
    bake_retarget(ik_source, ik_fk, RetargetOptions())
    bake_retarget(ik_source, ik_on, RetargetOptions(foot_ik=True, hand_ik=True))
    scene.frame_set(10)
    bpy.context.view_layer.update()

    def contact_error(src, tgt, src_names, tgt_names, end_role):
        src_hip = world_head(src, src_names["hips"])
        tgt_hip = world_head(tgt, tgt_names["hips"])
        src_end = world_head(src, src_names[end_role])
        tgt_end = world_head(tgt, tgt_names[end_role])
        desired = tgt_hip + (src_end - src_hip)
        return (tgt_end - desired).length

    fk_foot = contact_error(ik_source, ik_fk, ik_names, ik_target_names, "foot_l")
    ik_foot = contact_error(ik_source, ik_on, ik_names, _role_names("IkU"), "foot_l")
    fk_hand = contact_error(ik_source, ik_fk, ik_names, ik_target_names, "hand_l")
    ik_hand = contact_error(ik_source, ik_on, ik_names, _role_names("IkU"), "hand_l")
    print("IK", fk_foot, ik_foot, fk_hand, ik_hand)
    check(ik_foot < fk_foot - 0.02, "foot ik lands closer to the scaled source foot than fk")
    check(ik_hand < fk_hand - 0.02, "hand ik lands closer to the scaled source hand than fk")
    preset_path = save_preset("feature_swap", stored)
    if os.path.exists(preset_path):
        os.remove(preset_path)


def test_source_clip_picker():
    print("--- source clip picker ---")
    humanoid_retarget.register()
    roles = _role_names("Clip")
    source = build_biped("ClipSource", roles, arm_roll=0.0, scale=1.0)
    bpy.context.view_layer.objects.active = source
    bone = source.pose.bones[roles["upperarm_l"]]
    bone.rotation_mode = "XYZ"
    bone.rotation_euler = (0.0, 0.0, 0.0)
    bone.keyframe_insert("rotation_euler", frame=1)
    bone.rotation_euler = (0.4, 0.0, 0.0)
    bone.keyframe_insert("rotation_euler", frame=5)
    short = source.animation_data.action
    short.name = "Hero|Idle"
    long = bpy.data.actions.new("Hero|Walk")
    long.use_fake_user = True
    source.animation_data.action = long
    if getattr(long, "slots", None) is not None and len(long.slots) == 0:
        try:
            long.slots.new(id_type="OBJECT", name=source.name)
        except TypeError:
            long.slots.new("OBJECT", source.name)
    if source.animation_data.action_suitable_slots:
        source.animation_data.action_slot = source.animation_data.action_suitable_slots[0]
    bone.rotation_euler = (0.0, 0.0, 0.0)
    bone.keyframe_insert("rotation_euler", frame=1)
    bone.rotation_euler = (0.8, 0.0, 0.0)
    bone.keyframe_insert("rotation_euler", frame=20)
    bpy.ops.object.mode_set(mode="OBJECT")
    source["hr_actions"] = short.name + "\n" + long.name
    settings = bpy.context.scene.hr_settings
    settings.source = source
    check(settings.source_action in {short.name, long.name}, "dropdown lists an imported clip")
    settings.source_action = short.name
    check(source.animation_data.action == short, "choosing a clip assigns it to the source")
    check(bpy.context.scene.frame_start == 1 and bpy.context.scene.frame_end == 5, "short clip sets the timeline")
    settings.source_action = long.name
    check(source.animation_data.action == long, "second clip can be selected")
    check(bpy.context.scene.frame_end == 20, "long clip extends the timeline")
    result = bpy.ops.hr.play_source()
    check("FINISHED" in result, "play button finished")
    if bpy.context.screen and bpy.context.screen.is_animation_playing:
        bpy.ops.screen.animation_play()


def test_hide_bone_spheres():
    print("--- hide bone spheres ---")
    humanoid_retarget.register()
    roles = _role_names("Ball")
    arm = build_biped("SphereArm", roles)
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=0.05, location=(0.0, 0.0, 0.0))
    shape = bpy.context.active_object
    shape.name = "BoneBall"
    bone = arm.pose.bones[roles["hips"]]
    bone.custom_shape = shape
    arm.data.show_bone_custom_shapes = True
    arm.data.display_type = "ENVELOPE"
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=0.08, location=(1.0, 0.0, 0.0))
    child = bpy.context.active_object
    child.name = "LooseBall"
    child.parent = arm
    bpy.ops.mesh.primitive_cube_add(location=(2.0, 0.0, 1.0))
    body = bpy.context.active_object
    body.name = "BodyBox"
    body.scale = (0.2, 0.2, 1.2)
    bpy.ops.object.transform_apply(scale=True)
    body.parent = arm
    settings = bpy.context.scene.hr_settings
    settings.show_bone_spheres = False
    set_bone_sphere_display(arm, False)
    check(arm.data.show_bone_custom_shapes is False, "bone sphere shapes are hidden")
    check(arm.data.display_type == "OCTAHEDRAL", "envelope display is turned off")
    check(child.hide_viewport is True, "loose collision sphere is hidden")
    check(body.hide_viewport is False, "non-sphere mesh stays visible")
    settings.show_bone_spheres = True
    set_bone_sphere_display(arm, True)
    check(arm.data.show_bone_custom_shapes is True, "bone sphere shapes can be shown again")
    check(arm.data.display_type == "ENVELOPE", "previous bone display is restored")
    check(child.hide_viewport is False, "collision sphere can be shown again")
    settings.show_bone_spheres = False




def test_import_buttons_remember_paths():
    print("--- import paths ---")
    import tempfile
    from pathlib import Path

    check(initial_filepath("") == "", "an empty path opens the default browser")
    missing = os.path.join(tempfile.gettempdir(), "hr-missing-folder", "hero.fbx")
    check(initial_filepath(missing) == "", "a deleted folder is not reused")
    folder = tempfile.mkdtemp(prefix="hr-path-")
    source = os.path.join(folder, "hero.fbx")
    target = os.path.join(folder, "body.glb")
    Path(source).write_bytes(b"x")
    check(initial_filepath(source) == source, "an existing folder keeps the last file")
    humanoid_retarget.register()
    humanoid_retarget._remember_filepath(bpy.context, "last_source_path", source)
    humanoid_retarget._remember_filepath(bpy.context, "last_target_path", target)
    check(
        humanoid_retarget._recall_filepath(bpy.context, "last_source_path") == source,
        "the animation import remembers its own file",
    )
    check(
        humanoid_retarget._recall_filepath(bpy.context, "last_target_path") == target,
        "the target import remembers its own file",
    )
    check(
        bpy.context.scene.hr_settings.last_source_path != bpy.context.scene.hr_settings.last_target_path,
        "the two import buttons keep separate paths",
    )


def test_hide_imported_bones():
    print("--- hide imported bones ---")
    arm_data = bpy.data.armatures.new("HideBones")
    arm = bpy.data.objects.new("HideBones", arm_data)
    bpy.context.scene.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    visible = arm.data.edit_bones.new("Visible")
    visible.head = (0.0, 0.0, 0.0)
    visible.tail = (0.0, 0.0, 1.0)
    helper = arm.data.edit_bones.new("Helper")
    helper.head = (0.2, 0.0, 0.0)
    helper.tail = (0.2, 0.0, 1.0)
    bpy.ops.object.mode_set(mode="OBJECT")
    arm.data.bones["Helper"].hide = True
    bpy.ops.mesh.primitive_cube_add(size=1.0)
    mesh = bpy.context.active_object
    mesh.name = "HideBonesMesh"
    mesh.parent = arm
    set_armature_bones_visible(arm, False)
    set_armature_bones_visible(arm, False)
    check(arm.data.bones["Visible"].hide is True, "imported bones are hidden")
    check(arm.data.bones["Helper"].hide is True, "already hidden bones stay hidden")
    check(mesh.hide_get() is False, "mesh stays visible while bones are hidden")
    set_armature_bones_visible(arm, True)
    check(arm.data.bones["Visible"].hide is False, "bones can be shown again")
    check(arm.data.bones["Helper"].hide is True, "bones hidden before the tool stay hidden")
    check(mesh.hide_get() is False, "showing bones leaves the mesh visible")


def _count_imported_gltf_actions(path):
    before = {action.name for action in bpy.data.actions}
    before_objects = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    imported = [obj for obj in bpy.data.objects if obj not in before_objects and obj.type == "ARMATURE"]
    new_actions = [action for action in bpy.data.actions if action.name not in before and not action.is_empty]
    nla = 0
    if imported and imported[0].animation_data:
        nla = len(imported[0].animation_data.nla_tracks)
        if imported[0].animation_data.action and imported[0].animation_data.action not in new_actions:
            new_actions.append(imported[0].animation_data.action)
    return len(new_actions), nla, imported


def test_gltf_animation_scope():
    print("--- gltf animation scope ---")
    humanoid_retarget.register()
    prop = bpy.ops.hr.export_result.get_rna_type().properties["export_all_actions"]
    check(prop.default is True, "full animation export is the default")
    roles = _role_names("Exp")
    arm = build_biped("ExportRig", roles)
    bpy.context.view_layer.objects.active = arm
    bone = arm.pose.bones[roles["upperarm_l"]]
    bone.rotation_mode = "XYZ"
    bone.rotation_euler = (0.0, 0.0, 0.0)
    bone.keyframe_insert("rotation_euler", frame=1)
    bone.rotation_euler = (0.4, 0.0, 0.0)
    bone.keyframe_insert("rotation_euler", frame=4)
    action_a = arm.animation_data.action
    action_a.name = "ClipCurrent"
    action_b = bpy.data.actions.new("ClipOther")
    action_b.use_fake_user = True
    try:
        slot_b = action_b.slots.new(id_type="OBJECT", name=arm.name)
    except TypeError:
        slot_b = action_b.slots.new("OBJECT", arm.name)
    arm.animation_data.action = action_b
    if arm.animation_data.action_suitable_slots:
        arm.animation_data.action_slot = arm.animation_data.action_suitable_slots[0]
    bone.rotation_euler = (0.0, 0.0, 0.0)
    bone.keyframe_insert("rotation_euler", frame=1)
    bone.rotation_euler = (1.2, 0.0, 0.0)
    bone.keyframe_insert("rotation_euler", frame=9)
    bpy.ops.object.mode_set(mode="OBJECT")
    arm.animation_data.action = action_a
    if arm.animation_data.action_suitable_slots:
        arm.animation_data.action_slot = arm.animation_data.action_suitable_slots[0]
    track = arm.animation_data.nla_tracks.new()
    track.name = action_b.name
    strip = track.strips.new(action_b.name, 1, action_b)
    try:
        strip.action_slot = slot_b
    except Exception as exc:
        print("slot assign", exc)
    arm.animation_data.use_nla = False
    all_path = os.path.join(OUT, "all_anims.glb")
    current_path = os.path.join(OUT, "current_anim.glb")
    export_armature(arm, all_path, export_all_actions=True)
    export_armature(arm, current_path, export_all_actions=False)
    all_actions, all_nla, _all_arms = _count_imported_gltf_actions(all_path)
    current_actions, current_nla, _current_arms = _count_imported_gltf_actions(current_path)
    print("GLTF SCOPE", all_actions, all_nla, current_actions, current_nla)
    check(all_actions >= 2, "full export keeps every clip")
    check(current_actions == 1, "unchecked export keeps only the current clip")
    check(current_actions < all_actions, "current export is smaller than the full export")



def test_stand_layout():
    from humanoid_retarget.pipeline import apply_stand_layout, stand_positions

    humanoid_retarget.register()
    settings = bpy.context.scene.hr_settings
    check(settings.stand_layout == "SIDE", "default stand is left source and right target")

    left, right = stand_positions("SIDE", 1.0, 0.2, 1.2, 0.3, gap=0.25)
    check(left[0] < 0 < right[0] and left[1] == 0.0 and right[1] == 0.0, "side places source on the left")
    check(stand_positions("OVERLAP", 1.0, 1.0, 1.0, 1.0) == ((0.0, 0.0), (0.0, 0.0)), "overlap shares the origin")
    stayed, beside = stand_positions("SOURCE_ORIGIN", 1.0, 0.2, 1.2, 0.3, gap=0.25)
    check(stayed == (0.0, 0.0) and beside[0] > 1.0, "source can stay at the origin")
    beside, stayed = stand_positions("TARGET_ORIGIN", 1.0, 0.2, 1.2, 0.3, gap=0.25)
    check(stayed == (0.0, 0.0) and beside[0] < 0, "target can stay at the origin")
    front, back = stand_positions("DEPTH", 1.0, 0.4, 1.2, 0.5, gap=0.25)
    check(front[1] < 0 < back[1] and front[0] == 0.0 and back[0] == 0.0, "depth places source in front")
    swapped_source, swapped_target = stand_positions("SWAP", 1.0, 0.2, 1.2, 0.3, gap=0.25)
    check(swapped_source[0] > 0 > swapped_target[0], "swap puts the target on the left")

    names = junk_names()
    source = build_biped("StandSource", names)
    target = build_biped("StandTarget", names)
    bpy.ops.object.mode_set(mode="OBJECT")
    loose_mesh = bpy.data.meshes.new("StandLoose")
    loose = bpy.data.objects.new("StandLoose", loose_mesh)
    source_collection = bpy.data.collections.new("HR_Source")
    bpy.context.scene.collection.children.link(source_collection)
    for owner in list(source.users_collection):
        owner.objects.unlink(source)
    source_collection.objects.link(source)
    source_collection.objects.link(loose)
    bystander = bpy.data.objects.new("StandBystander", bpy.data.meshes.new("StandBystander"))
    bpy.context.scene.collection.objects.link(bystander)

    apply_stand_layout(source, target, "SIDE")
    check(source.location.x < 0 < target.location.x, "armatures stand on opposite sides of the origin")
    check(abs(loose.location.x - source.location.x) < 1e-6, "imported mesh follows the source")
    check(abs(bystander.location.x) < 1e-6, "an unrelated object stays put")
    apply_stand_layout(source, target, "OVERLAP")
    check(abs(source.location.x) < 1e-6 and abs(target.location.x) < 1e-6, "overlap clears the side offset")
    check(abs(source.location.y) < 1e-6 and abs(target.location.y) < 1e-6, "overlap clears the depth offset")
    settings.source = source
    settings.target = target
    settings.stand_layout = "DEPTH"
    check(source.location.y < 0 < target.location.y, "the selector moves existing rigs")
    print("STAND", round(source.location.x, 3), round(target.location.x, 3))


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    _source, _target = test_geometry_and_bake()
    test_mixamo_names()
    test_autorig_and_roundtrip(_source)
    test_mapping_root_reference_and_ik()
    test_source_clip_picker()
    test_hide_bone_spheres()
    test_import_buttons_remember_paths()
    test_hide_imported_bones()
    test_gltf_animation_scope()
    test_stand_layout()
    print("RETARGET_TEST_OK")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        print("RETARGET_TEST_FAIL")
        sys.exit(1)
