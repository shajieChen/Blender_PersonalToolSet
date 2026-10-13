"""Headless checks for humanoid import, auto-rig, retarget and export."""

import math
import os
import sys
import traceback

import bpy
from mathutils import Euler, Matrix, Quaternion, Vector

ROOT = r"H:\Blender_Plugin"
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import humanoid_retarget
from humanoid_retarget.classify import classify_armature, classify_by_name, correct_deform_pairs
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
    on_chosen = bone_dir(target, target_names["upperarm_r"]).dot(bone_dir(source, roles["upperarm_l"]))
    on_other = bone_dir(target, target_names["upperarm_l"]).dot(bone_dir(source, roles["upperarm_r"]))
    print("MAP", round(on_chosen, 3), round(on_other, 3))
    check(on_chosen > 0.95, "edited mapping plays the raised arm on the chosen bone")
    check(on_other > 0.95, "edited mapping points the other bone along the source bone it is mapped from")

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


def test_bake_displays_same_source_clip():
    print("--- bake displays the same source clip ---")
    from humanoid_retarget.retarget import ACTION_SEP, RetargetOptions, bake_retarget, collect_actions

    chain_links = (
        ("upperarm_l", "forearm_l"),
        ("forearm_l", "hand_l"),
        ("thigh_l", "shin_l"),
        ("spine", "chest"),
    )
    keyed_roles = ("upperarm_l", "forearm_l", "thigh_l", "spine")
    angles_a = ((0.2, 0.0, 0.0), (0.1, 0.0, 0.0), (0.15, 0.0, 0.0), (0.1, 0.0, 0.0))
    angles_b = ((-0.6, 0.0, 0.0), (-0.3, 0.0, 0.0), (-0.35, 0.0, 0.0), (-0.2, 0.0, 0.0))

    def new_slot(action, obj):
        try:
            return action.slots.new(id_type="OBJECT", name=obj.name)
        except TypeError:
            return action.slots.new("OBJECT", obj.name)

    def key_clip(obj, names, action, slot, frames, angles):
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode="POSE")
        anim = obj.animation_data or obj.animation_data_create()
        anim.action = action
        anim.action_slot = slot
        for frame in frames:
            for role, angle in zip(keyed_roles, angles):
                bone = obj.pose.bones[names[role]]
                bone.rotation_mode = "XYZ"
                bone.rotation_euler = angle
                bone.keyframe_insert("rotation_euler", frame=frame)
        bpy.ops.object.mode_set(mode="OBJECT")

    def world_head(obj, bone_name):
        return obj.matrix_world @ obj.pose.bones[bone_name].head

    def run_fixture(tag, key_b, entry_name, expect_name, expect_range, expect_count):
        source_names = _role_names(tag + "S")
        target_names = _role_names(tag + "T")
        source = build_biped(tag + "Source", source_names, arm_roll=0.0, scale=1.0)
        target = build_biped(tag + "Target", target_names, arm_roll=0.55, scale=1.0)
        bpy.context.view_layer.objects.active = source
        bpy.ops.object.mode_set(mode="OBJECT")
        action_a = bpy.data.actions.new(tag + "_A")
        action_b = bpy.data.actions.new(tag + "_B")
        action_a.use_fake_user = True
        action_b.use_fake_user = True
        slot_a = new_slot(action_a, source)
        # Blender 5.1 marks an action non-empty as soon as it has a slot, even with no curves.
        slot_b = new_slot(action_b, source) if key_b else None
        key_clip(source, source_names, action_a, slot_a, (1, 5), angles_a)
        if key_b:
            key_clip(source, source_names, action_b, slot_b, (11, 20), angles_b)
        else:
            check(action_b.is_empty, "fallback fixture B is empty")
        source["hr_actions"] = ACTION_SEP.join((action_a.name, action_b.name))
        anim = source.animation_data or source.animation_data_create()
        anim.use_nla = False
        if entry_name is None:
            anim.action = None
            entry_slot = None
        else:
            entry_action = action_a if entry_name == "A" else action_b
            entry_slot = slot_a if entry_name == "A" else slot_b
            anim.action = entry_action
            if entry_slot is not None:
                anim.action_slot = entry_slot
        scene = bpy.context.scene
        scene.frame_start = 0
        scene.frame_end = 100
        scene.frame_current = 99
        collected = collect_actions(source)
        check(len(collected) == expect_count, tag + " collects the bakeable clips")
        if expect_count == 2:
            check(collected[0] == action_a and collected[1] == action_b, tag + " keeps A then B")
        pairs = [(role, source_names[role], target_names[role]) for role in source_names]
        _report, baked = bake_retarget(source, target, RetargetOptions(pairs=pairs))
        check(len(baked) == expect_count, tag + " bakes every non-empty clip")
        check(target["hr_actions"] == ACTION_SEP.join(action.name for action in baked), tag + " keeps bake order")
        shown_source = action_a if expect_name == "A" else action_b
        shown_target = baked[0] if expect_name == "A" else baked[1]
        check(source.animation_data.action == shown_source, tag + " source shows the selected clip")
        check(target.animation_data.action == shown_target, tag + " target shows the same clip")
        check(target.animation_data.action_slot == shown_target.slots[0], tag + " target slot is the baked slot")
        if entry_name == expect_name:
            check(source.animation_data.action_slot == entry_slot, tag + " source keeps the entry slot")
        else:
            check(source.animation_data.action_slot == action_a.slots[0], tag + " fallback uses A's slot")
        check(scene.frame_start == expect_range[0], tag + " frame_start is the shown clip")
        check(scene.frame_end == expect_range[1], tag + " frame_end is the shown clip")
        check(scene.frame_current == expect_range[2], tag + " frame_current is the shown clip")
        check(source.animation_data.use_nla is False, tag + " source nla is off")
        check(target.animation_data.use_nla is False, tag + " target nla is off")
        for action in baked:
            check(action.use_fake_user, tag + " baked action keeps a fake user")
        strips = [strip for track in target.animation_data.nla_tracks for strip in track.strips]
        others = [action for action in baked if action != shown_target]
        check(len(strips) == len(others), tag + " only the other clips are nla strips")
        check(all(strip.action != shown_target for strip in strips), tag + " shown clip is not also a strip")
        for action in others:
            match = next(strip for strip in strips if strip.action == action)
            check(match.action_slot == action.slots[0], tag + " nla strip uses the action slot")
        for frame in (expect_range[0], expect_range[1]):
            scene.frame_set(frame)
            bpy.context.view_layer.update()
            for start_role, end_role in chain_links:
                start = world_head(source, source_names[end_role]) - world_head(source, source_names[start_role])
                finish = world_head(target, target_names[end_role]) - world_head(target, target_names[start_role])
                dot = start.normalized().dot(finish.normalized())
                check(abs(dot - 1.0) < 1.5e-7, tag + " " + start_role + " chain matches at " + str(frame))
            identity = Matrix.Identity(4)
            for role in ("hand_l", "hand_r"):
                basis = target.pose.bones[target_names[role]].matrix_basis
                error = max(abs(basis[row][col] - identity[row][col]) for row in range(4) for col in range(4))
                check(error < 1e-7, tag + " " + role + " stays at identity")
        scene.frame_set(expect_range[0])
        check(
            (scene.frame_start, scene.frame_end, scene.frame_current) == expect_range,
            tag + " timeline stays on the shown clip",
        )

    run_fixture("ClipA", True, "A", "A", (1, 5, 1), 2)
    run_fixture("ClipB", True, "B", "B", (11, 20, 11), 2)
    run_fixture("ClipEmpty", False, "B", "A", (1, 5, 1), 1)
    run_fixture("ClipNone", True, None, "A", (1, 5, 1), 2)
    print("PASS bake displays the same source clip")


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



def test_playback_switches_target_clip():
    print("--- playback switches the retargeted clip ---")
    from humanoid_retarget.retarget import ACTION_SEP, target_action_for_source_clip

    humanoid_retarget.register()
    tag = "Switch"
    source_names = _role_names(tag + "S")
    target_names = _role_names(tag + "T")
    source = build_biped(tag + "Source", source_names, arm_roll=0.0, scale=1.0)
    target = build_biped(tag + "Target", target_names, arm_roll=0.4, scale=1.0)
    action_a = bpy.data.actions.new(tag + "_A")
    action_b = bpy.data.actions.new(tag + "_B")
    action_a.use_fake_user = True
    action_b.use_fake_user = True

    def new_slot(action):
        try:
            return action.slots.new(id_type="OBJECT", name=source.name)
        except TypeError:
            return action.slots.new("OBJECT", source.name)

    def key_clip(action, slot, frames, angle):
        bpy.context.view_layer.objects.active = source
        bpy.ops.object.mode_set(mode="POSE")
        anim = source.animation_data or source.animation_data_create()
        anim.action = action
        anim.action_slot = slot
        bone = source.pose.bones[source_names["upperarm_l"]]
        bone.rotation_mode = "XYZ"
        for frame in frames:
            bone.rotation_euler = angle
            bone.keyframe_insert("rotation_euler", frame=frame)
        bpy.ops.object.mode_set(mode="OBJECT")

    slot_a = new_slot(action_a)
    slot_b = new_slot(action_b)
    key_clip(action_a, slot_a, (1, 5), (0.2, 0.0, 0.0))
    key_clip(action_b, slot_b, (11, 20), (-0.5, 0.0, 0.0))
    source["hr_actions"] = ACTION_SEP.join((action_a.name, action_b.name))
    anim = source.animation_data
    anim.action = action_a
    anim.action_slot = slot_a
    anim.use_nla = False
    pairs = [(role, source_names[role], target_names[role]) for role in source_names]
    _report, baked = bake_retarget(source, target, RetargetOptions(pairs=pairs))
    check(len(baked) == 2, "two clips are baked onto the target")
    check(target.animation_data.action == baked[0], "bake leaves the target on the entry clip")

    settings = bpy.context.scene.hr_settings
    settings.source = source
    settings.target = target
    settings.source_action = action_b.name
    scene = bpy.context.scene
    check(source.animation_data.action == action_b, "dropdown assigns the selected source clip")
    check(target.animation_data.action == baked[1], "dropdown assigns the matching baked clip")
    check(target.animation_data.action_slot == baked[1].slots[0], "switched clip uses its baked slot")
    check(target.animation_data.use_nla is False, "switched clip does not turn nla back on")
    check(scene.frame_start == 11 and scene.frame_end == 20, "timeline follows the selected clip")
    check(scene.frame_current == 11, "selecting a clip jumps to its first frame")

    settings.source_action = action_a.name
    check(target.animation_data.action == baked[0], "switching back restores the entry baked clip")
    check(scene.frame_start == 1 and scene.frame_end == 5, "timeline returns to the entry clip")

    settings.source_action = action_b.name
    result = bpy.ops.hr.play_source()
    check("FINISHED" in result, "play button finished on the second clip")
    check(target.animation_data.action == baked[1], "play keeps the matching baked clip")
    screen = bpy.context.screen
    if screen and screen.is_animation_playing:
        bpy.ops.screen.animation_play()

    baked[1].name = target.name + "_HR_HumanMetarig_" + action_b.name
    target["hr_actions"] = ACTION_SEP.join(action.name for action in baked)
    settings.source_action = action_a.name
    settings.source_action = action_b.name
    check(
        target.animation_data.action == baked[1],
        "a rigify hop name still selects the matching baked clip",
    )

    tiny = bpy.data.actions.new("Zed")
    longer = bpy.data.actions.new("YZed")
    tiny.use_fake_user = True
    longer.use_fake_user = True
    new_slot(tiny)
    new_slot(longer)
    hit = bpy.data.actions.new(target.name + "_Zed")
    miss = bpy.data.actions.new(target.name + "_YZed")
    hit.use_fake_user = True
    miss.use_fake_user = True
    source["hr_actions"] = ACTION_SEP.join((tiny.name, longer.name))
    target["hr_actions"] = ACTION_SEP.join((miss.name, hit.name))
    found = target_action_for_source_clip(source, target, tiny)
    check(found == hit, "a shorter clip name does not take the longer bake")
    print("PASS playback switches the retargeted clip")


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



def test_file_load_does_not_hide_bones_inside_the_pointer_callback():
    print("--- startup bone hide is deferred ---")
    humanoid_retarget.register()
    arm_data = bpy.data.armatures.new("LoadBones")
    arm = bpy.data.objects.new("LoadBones", arm_data)
    bpy.context.scene.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    arm.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bone = arm.data.edit_bones.new("Bone")
    bone.head = (0.0, 0.0, 0.0)
    bone.tail = (0.0, 0.0, 1.0)
    bpy.ops.object.mode_set(mode="OBJECT")
    settings = bpy.context.scene.hr_settings
    settings.show_bones = True
    settings.source = arm
    check(arm.data.bones["Bone"].hide is False, "restoring the source pointer does not rewrite bone visibility")
    settings.show_bones = False
    check(arm.data.bones["Bone"].hide is True, "turning the checkbox off still hides bones")


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
    check(arm.hide_get() is True, "octahedral bone cones are hidden with the armature")
    set_armature_bones_visible(arm, True)
    check(arm.data.bones["Visible"].hide is False, "bones can be shown again")
    check(arm.data.bones["Helper"].hide is True, "bones hidden before the tool stay hidden")
    check(arm.hide_get() is False, "showing bones reveals the armature again")
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



def test_split_parent_orientation():
    print("--- body orientation across different parents ---")
    src_names = _role_names("SplitS")
    tgt_names = _role_names("SplitT")
    source = build_biped("SplitSource", src_names, arm_roll=0.0, scale=1.0)
    target = build_biped("SplitTarget", tgt_names, arm_roll=0.4, scale=1.0)
    bpy.context.view_layer.objects.active = source
    bpy.ops.object.mode_set(mode="EDIT")
    root = source.data.edit_bones.new("SplitRoot")
    root.head = Vector((0.0, 0.0, 0.8))
    root.tail = Vector((0.0, 0.0, 0.95))
    source.data.edit_bones[src_names["hips"]].parent = root
    source.data.edit_bones[src_names["spine"]].parent = root
    bpy.ops.object.mode_set(mode="POSE")
    root_pose = source.pose.bones["SplitRoot"]
    spine_pose = source.pose.bones[src_names["spine"]]
    arm_pose = source.pose.bones[src_names["upperarm_l"]]
    root_pose.rotation_mode = "XYZ"
    spine_pose.rotation_mode = "XYZ"
    arm_pose.rotation_mode = "XYZ"
    root_pose.rotation_euler = (0.0, 0.0, 0.0)
    spine_pose.rotation_euler = (0.0, 0.0, 0.0)
    arm_pose.rotation_euler = (0.0, 0.0, 0.0)
    root_pose.keyframe_insert("rotation_euler", frame=1)
    spine_pose.keyframe_insert("rotation_euler", frame=1)
    arm_pose.keyframe_insert("rotation_euler", frame=1)
    root_pose.rotation_euler = (0.6, 0.2, 0.8)
    spine_pose.rotation_euler = (0.4, 0.0, 0.3)
    arm_pose.rotation_euler = (0.0, 0.0, -1.1)
    root_pose.keyframe_insert("rotation_euler", frame=8)
    spine_pose.keyframe_insert("rotation_euler", frame=8)
    arm_pose.keyframe_insert("rotation_euler", frame=8)
    bpy.ops.object.mode_set(mode="OBJECT")

    pairs = [(role, src_names[role], tgt_names[role]) for role in src_names]
    options = RetargetOptions(pairs=pairs)
    bake_retarget(source, target, options)
    bpy.context.scene.frame_set(8)
    bpy.context.view_layer.update()

    def chain(arm, parent_name, child_name):
        direction = arm.pose.bones[child_name].head - arm.pose.bones[parent_name].head
        return direction.normalized()

    spine_dot = chain(source, src_names["spine"], src_names["chest"]).dot(
        chain(target, tgt_names["spine"], tgt_names["chest"])
    )
    arm_dot = chain(source, src_names["upperarm_l"], src_names["forearm_l"]).dot(
        chain(target, tgt_names["upperarm_l"], tgt_names["forearm_l"])
    )
    print("SPLIT", round(spine_dot, 3), round(arm_dot, 3))
    check(spine_dot > 0.98, "spine direction follows the source when its parent is not the hips")
    check(arm_dot > 0.98, "arm direction follows the source across a different parent chain")

    wrong = [(role, source_name, target_name) for role, source_name, target_name in pairs]
    wrong = [
        (role, source_name, "OffChest" if role == "chest" else target_name)
        for role, source_name, target_name in wrong
    ]
    bpy.context.view_layer.objects.active = target
    bpy.ops.object.mode_set(mode="EDIT")
    extra = target.data.edit_bones.new("OffChest")
    extra.head = Vector((0.4, 0.2, 1.2))
    extra.tail = Vector((0.4, 0.2, 1.45))
    extra.parent = target.data.edit_bones[tgt_names["hips"]]
    bpy.ops.object.mode_set(mode="OBJECT")
    replaced = RetargetOptions(pairs=wrong)
    bake_retarget(source, target, replaced)
    chest_targets = [target_name for role, _source_name, target_name in replaced.resolved_pairs if role == "chest"]
    check(chest_targets == [tgt_names["chest"]], "chest mapping moves off the side bone and onto the spine")


def _rest_body_yaw(obj, names):
    """Yaw of rest body-left about rest body-up after the hips pose delta."""
    bones = obj.data.bones
    up = bones[names["head"]].head_local - bones[names["hips"]].head_local
    up.normalize()
    left = bones[names["upperarm_l"]].head_local - bones[names["upperarm_r"]].head_local
    left = left - up * left.dot(up)
    left.normalize()
    pose = obj.pose.bones[names["hips"]]
    delta = pose.matrix.to_3x3() @ bones[names["hips"]].matrix_local.to_3x3().inverted()
    rotated = delta @ left
    projected = rotated - up * rotated.dot(up)
    projected.normalize()
    return math.atan2(up.dot(left.cross(projected)), left.dot(projected))


def _wrap_angle(angle):
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


def _armature_chain(obj, start_name, end_name):
    start = obj.pose.bones[start_name].head
    end = obj.pose.bones[end_name].head
    return (end - start).normalized()


def test_rest_hips_yaw_preserves_arm_chain():
    print("--- rest hips yaw preserves arm chain ---")
    source_names = _role_names("YawS")
    target_names = _role_names("YawT")
    source = build_biped("YawSource", source_names, arm_roll=0.0, scale=1.0)
    target = build_biped("YawTarget", target_names, arm_roll=0.9, scale=1.0)
    bpy.context.view_layer.objects.active = source
    bpy.ops.object.mode_set(mode="POSE")
    hips = source.pose.bones[source_names["hips"]]
    up = (
        source.data.bones[source_names["head"]].head_local
        - source.data.bones[source_names["hips"]].head_local
    ).normalized()
    rest = hips.bone.matrix_local.to_3x3()
    delta = Quaternion(up, math.radians(40.0)).to_matrix()
    hips.rotation_mode = "QUATERNION"
    hips.rotation_quaternion = (rest.inverted() @ delta @ rest).to_quaternion()
    hips.keyframe_insert("rotation_quaternion", frame=1)
    hips.keyframe_insert("rotation_quaternion", frame=4)
    bpy.ops.object.mode_set(mode="OBJECT")
    pairs = [(role, source_names[role], target_names[role]) for role in source_names]
    _report, baked = bake_retarget(
        source,
        target,
        RetargetOptions(pairs=pairs, reference="REST", root_motion="KEEP", foot_ik=False, hand_ik=False),
    )
    check(len(baked) == 1 and target.animation_data.action == baked[-1], "sample the baked action")
    bpy.context.scene.frame_set(4)
    bpy.context.view_layer.update()
    lost = _wrap_angle(_rest_body_yaw(source, source_names) - _rest_body_yaw(target, target_names))
    print("LOST_YAW_DEG", round(math.degrees(lost), 6))
    check(abs(lost) < math.radians(2.0), "rest hips yaw stays within 2 degrees")
    for start_role, end_role in (("upperarm_l", "forearm_l"), ("forearm_l", "hand_l")):
        direction = _armature_chain(source, source_names[start_role], source_names[end_role]).dot(
            _armature_chain(target, target_names[start_role], target_names[end_role])
        )
        print("ARM_CHAIN", start_role, round(direction, 6))
        check(abs(direction - 1.0) < 1.5e-3, start_role + " chain keeps the source direction")
    for role in ("hand_l", "hand_r"):
        angle = target.pose.bones[target_names[role]].rotation_quaternion.angle
        print("HAND_ANGLE", role, angle)
        check(angle < 1.0e-4, role + " stays at identity")


def _body_basis(obj, names):
    bones = obj.data.bones
    up = bones[names["head"]].head_local - bones[names["hips"]].head_local
    up.normalize()
    left = bones[names["upperarm_l"]].head_local - bones[names["upperarm_r"]].head_local
    left = left - up * left.dot(up)
    left.normalize()
    forward = left.cross(up).normalized()
    left = up.cross(forward).normalized()
    return Matrix((
        (left.x, up.x, forward.x),
        (left.y, up.y, forward.y),
        (left.z, up.z, forward.z),
    ))


def _rest_delta(obj, bone_name):
    pose = obj.pose.bones[bone_name].matrix.to_3x3()
    rest = obj.data.bones[bone_name].matrix_local.to_3x3()
    return pose @ rest.inverted()


def _chain_twist_angle(obj, names, role, child_role):
    chain = obj.pose.bones[names[child_role]].head - obj.pose.bones[names[role]].head
    chain.normalize()
    rotation = _rest_delta(obj, names[role]).to_quaternion().normalized()
    if rotation.w < 0.0:
        rotation.negate()
    frame = Vector((0.0, 1.0, 0.0)).rotation_difference(chain)
    local = frame.inverted() @ rotation @ frame
    twist = local.to_swing_twist("Y")[1]
    return (twist + math.pi) % (2.0 * math.pi) - math.pi


def _body_delta_angle(source, target, source_names, target_names, role):
    source_body = _body_basis(source, source_names)
    target_body = _body_basis(target, target_names)
    source_delta = source_body.inverted() @ _rest_delta(source, source_names[role]) @ source_body
    target_delta = target_body.inverted() @ _rest_delta(target, target_names[role]) @ target_body
    return source_delta.to_quaternion().rotation_difference(target_delta.to_quaternion()).angle


def test_torso_twist_keeps_head_delta():
    print("--- torso twist keeps head delta ---")
    source_names = _role_names("TorS")
    target_names = _role_names("TorT")
    source = build_biped("TorsoSource", source_names, arm_roll=0.0, scale=1.0)
    target = build_biped("TorsoTarget", target_names, arm_roll=0.9, scale=1.0)
    bpy.context.view_layer.objects.active = source
    bpy.ops.object.mode_set(mode="POSE")
    spine = source.pose.bones[source_names["spine"]]
    head = source.pose.bones[source_names["head"]]
    spine.rotation_mode = "QUATERNION"
    head.rotation_mode = "QUATERNION"
    spine.rotation_quaternion = Quaternion((0.0, 1.0, 0.0), math.radians(40.0))
    head.rotation_quaternion = Quaternion((1.0, 0.0, 0.0), math.radians(25.0))
    for bone in (spine, head):
        bone.keyframe_insert("rotation_quaternion", frame=1)
        bone.keyframe_insert("rotation_quaternion", frame=4)
    bpy.ops.object.mode_set(mode="OBJECT")
    pairs = [(role, source_names[role], target_names[role]) for role in source_names]
    _report, baked = bake_retarget(
        source,
        target,
        RetargetOptions(pairs=pairs, reference="REST", root_motion="KEEP", foot_ik=False, hand_ik=False),
    )
    check(len(baked) == 1 and target.animation_data.action == baked[-1], "torso sample uses the baked action")
    bpy.context.scene.frame_set(4)
    bpy.context.view_layer.update()
    for role, child in (("spine", "chest"), ("chest", "neck"), ("neck", "head")):
        lost = _wrap_angle(
            _chain_twist_angle(source, source_names, role, child)
            - _chain_twist_angle(target, target_names, role, child)
        )
        print("TORSO_TWIST", role, round(math.degrees(lost), 6))
        check(abs(lost) < math.radians(2.0), role + " twist stays within 2 degrees")
    head_error = _body_delta_angle(source, target, source_names, target_names, "head")
    print("HEAD_DELTA_DEG", round(math.degrees(head_error), 6))
    check(head_error < math.radians(2.0), "head keeps its own rest-relative rotation")
    direction = _armature_chain(source, source_names["upperarm_l"], source_names["forearm_l"]).dot(
        _armature_chain(target, target_names["upperarm_l"], target_names["forearm_l"])
    )
    print("TORSO_ARM", round(direction, 6))
    check(abs(direction - 1.0) < 1.5e-3, "upper arm chain survives the torso twist")
    for role in ("hand_l", "hand_r"):
        angle = target.pose.bones[target_names[role]].rotation_quaternion.angle
        check(angle < 1.0e-4, role + " stays at identity")


def test_swing_preserves_target_roll():
    print("--- swing keeps target roll ---")
    source_names = _role_names("SwS")
    target_names = _role_names("SwT")
    source = build_biped("SwingSource", source_names, arm_roll=0.0, scale=1.0)
    target = build_biped("SwingTarget", target_names, arm_roll=0.9, scale=1.0)
    animate(source, source_names)
    pairs = [(role, source_names[role], target_names[role]) for role in source_names]
    bake_retarget(source, target, RetargetOptions(pairs=pairs))
    bpy.context.scene.frame_set(10)
    bpy.context.view_layer.update()
    direction = bone_dir(source, source_names["upperarm_l"]).dot(bone_dir(target, target_names["upperarm_l"]))
    print("SWING DIR", round(direction, 3))
    check(direction > 0.98, "swing matches the raised arm direction")
    pose = target.pose.bones[target_names["upperarm_l"]]
    bone = pose.bone
    rest_dir = (bone.tail_local - bone.head_local).normalized()
    pose_dir = (pose.tail - pose.head).normalized()
    swing = rest_dir.rotation_difference(pose_dir)
    expected = (swing.to_matrix() @ (bone.matrix_local.to_3x3() @ Vector((1.0, 0.0, 0.0)))).normalized()
    actual = (pose.matrix.to_3x3() @ Vector((1.0, 0.0, 0.0))).normalized()
    print("SWING ROLL", round(expected.dot(actual), 3))
    check(expected.dot(actual) > 0.98, "target arm roll stays on the bind instead of the source roll")


def test_skinned_duplicate_bone():
    print("--- skinned duplicate ---")
    arm_data = bpy.data.armatures.new("SkinPick")
    arm = bpy.data.objects.new("SkinPick", arm_data)
    bpy.context.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    decoy = arm_data.edit_bones.new("bip Head")
    decoy.head = Vector((0.0, 0.0, 1.5))
    decoy.tail = Vector((0.0, 0.0, 1.7))
    real = arm_data.edit_bones.new("Head")
    real.head = Vector((0.0, 0.0, 1.5))
    real.tail = Vector((0.0, 0.0, 1.7))
    bpy.ops.object.mode_set(mode="OBJECT")
    mesh_data = bpy.data.meshes.new("SkinPickMesh")
    mesh_data.from_pydata([(0, 0, 0), (0, 0.1, 0), (0.1, 0, 0), (0, 0, 0.1)], [], [(0, 1, 2), (0, 2, 3)])
    mesh = bpy.data.objects.new("SkinPickMesh", mesh_data)
    bpy.context.collection.objects.link(mesh)
    mesh.parent = arm
    modifier = mesh.modifiers.new("Armature", "ARMATURE")
    modifier.object = arm
    group = mesh.vertex_groups.new(name="Head")
    group.add([0, 1, 2, 3], 1.0, "REPLACE")
    found = classify_by_name(arm)
    check(found.get("head") == "Head", "name match prefers the bone that deforms the mesh")

    source_names = _role_names("DuS")
    target_names = _role_names("DuT")
    source = build_biped("DupSource", source_names, arm_roll=0.0, scale=1.0)
    target = build_biped("DupTarget", target_names, arm_roll=0.0, scale=1.0)
    target.data.bones[target_names["head"]].name = "Head"
    bpy.context.view_layer.objects.active = target
    bpy.ops.object.mode_set(mode="EDIT")
    extra = target.data.edit_bones.new("bip Head")
    extra.head = Vector((0.3, 0.0, 1.5))
    extra.tail = Vector((0.3, 0.0, 1.7))
    extra.parent = target.data.edit_bones[target_names["chest"]]
    bpy.ops.object.mode_set(mode="OBJECT")
    body = bpy.data.meshes.new("DupBody")
    body.from_pydata([(0, 0, 0), (0, 0.1, 0), (0.1, 0, 0), (0, 0, 0.1)], [], [(0, 1, 2), (0, 2, 3)])
    body_obj = bpy.data.objects.new("DupBody", body)
    bpy.context.collection.objects.link(body_obj)
    body_obj.parent = target
    body_mod = body_obj.modifiers.new("Armature", "ARMATURE")
    body_mod.object = target
    body_group = body_obj.vertex_groups.new(name="Head")
    body_group.add([0, 1, 2, 3], 1.0, "REPLACE")
    pairs = [(role, source_names[role], target_names[role] if role != "head" else "bip Head") for role in source_names]
    resolved = {role: target_name for role, _source_name, target_name in correct_deform_pairs(source, target, pairs)}
    check(resolved.get("head") == "Head", "a preset duplicate is replaced by the weighted head bone")


def test_bone_gizmos():
    print("--- bone gizmos ---")
    humanoid_retarget.register()
    check(bpy.context.scene.hr_settings.draw_bone_gizmos is True, "bone gizmos default to on")
    names = _role_names("Gz")
    arm = build_biped("GizmoRig", names, arm_roll=0.0, scale=1.0)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    hips = arm.data.edit_bones[names["hips"]]
    hips.tail = hips.head + Vector((0.45, 0.0, 0.0))
    bpy.ops.object.mode_set(mode="OBJECT")
    from humanoid_retarget.gizmos import gizmo_links
    roles = {role: names[role] for role in names}
    links = gizmo_links(arm, roles)
    hips_link = next(item for item in links if item[0] == "hips" and item[1] == "spine")
    spine_head = arm.matrix_world @ arm.pose.bones[names["spine"]].head
    check((hips_link[3] - spine_head).length < 1e-4, "gizmo ends on the child joint")
    direction = (hips_link[3] - hips_link[2]).normalized()
    print("GIZMO", tuple(round(v, 3) for v in direction))
    check(direction.z > 0.9, "gizmo follows the body chain when bone Y points sideways")
    check(any(role == "upperarm_l" for role, _child, _start, _end in links), "gizmo draws the left arm")


METARIG_TESTS = []


def _metarig_mark(name):
    print(name)
    METARIG_TESTS.append(name)


class _LayoutRecord:
    def __init__(self):
        self.events = []

    def prop(self, _data, prop, text="", **_kwargs):
        self.events.append(("prop", prop, text))
        return self

    def label(self, text="", **_kwargs):
        self.events.append(("label", text))
        return self

    def box(self):
        self.events.append(("box",))
        return self

    def row(self, **_kwargs):
        return self

    def column(self, **_kwargs):
        return self

    def separator(self, **_kwargs):
        return self

    def operator(self, *_args, **_kwargs):
        return self

    def template_list(self, *_args, **_kwargs):
        return self

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        def _call(*_args, **_kwargs):
            return self

        return _call


def _matrix_close(left, right):
    return max(abs(left[row][col] - right[row][col]) for row in range(4) for col in range(4)) < 1.0e-6


def _near(actual, expected, tol=1.0e-3):
    return all(abs(left - right) < tol for left, right in zip(actual, expected))


def _object_names():
    return {obj.name for obj in bpy.data.objects}


def _action_names():
    return {action.name for action in bpy.data.actions}


def test_standard_skeleton_selector():
    _metarig_mark("test_standard_skeleton_selector")
    from humanoid_retarget.retarget import RetargetError, RetargetOptions

    humanoid_retarget.register()
    settings = bpy.context.scene.hr_settings
    prop = settings.bl_rna.properties["standard_skeleton"]
    identifiers = [item.identifier for item in prop.enum_items]
    check(identifiers[0] == "RIGIFY_HUMAN_METARIG", "Rigify human metarig is the first standard")
    check("DIRECT" in identifiers, "direct mapping remains available")
    check(settings.standard_skeleton == "DIRECT", "existing scenes keep direct mapping")
    check(RetargetOptions().standard_skeleton == "DIRECT", "omitted standard stays direct")
    rejected = False
    try:
        RetargetOptions(standard_skeleton="MIXAMO")
    except RetargetError:
        rejected = True
    check(rejected, "an unknown standard is rejected")


def test_standard_skeleton_panel_order():
    _metarig_mark("test_standard_skeleton_panel_order")
    from humanoid_retarget import HR_PT_panel

    humanoid_retarget.register()
    panel = type("PanelHarness", (), {"layout": _LayoutRecord()})()
    HR_PT_panel.draw(panel, bpy.context)
    events = panel.layout.events
    stand = next(index for index, event in enumerate(events) if event[:2] == ("prop", "stand_layout"))
    standard = next(index for index, event in enumerate(events) if event[:2] == ("prop", "standard_skeleton"))
    source = next(index for index, event in enumerate(events) if event[0] == "label" and event[1] == "1. 动画来源")
    check(stand < standard < source, "the standard sits between the stand selector and step 1")
    check(events[standard][2] == "标准人形骨架", "the standard selector uses the standard-skeleton label")


def test_human_metarig_definition():
    _metarig_mark("test_human_metarig_definition")
    from humanoid_retarget.rigify_metarig import load_human_metarig_definition

    before_objects = _object_names()
    definition = load_human_metarig_definition()
    check(_object_names() == before_objects, "the sample armature is removed after loading")
    check(definition.source_id == "rigify.metarigs.human", "the standard is the full human metarig")
    spine = definition.bones["spine"]
    thigh = definition.bones["thigh.L"]
    check(_near(spine.head, (0.0, 0.0552, 1.0099)), "spine head comes from the human sample")
    check(_near(spine.tail, (0.0, 0.0172, 1.1573)), "spine tail comes from the human sample")
    check(abs(spine.roll) < 1.0e-3, "spine roll comes from the human sample")
    check(thigh.parent == "spine", "thigh.L keeps its sample parent")
    check(_near(thigh.head, (0.0980, 0.0124, 1.0720)), "thigh.L head comes from the human sample")
    check(abs(definition.bones["upper_arm.L"].roll - 2.0724) < 1.0e-3, "upper_arm.L roll comes from the human sample")
    check(abs(definition.bones["forearm.L"].roll - 2.1535) < 1.0e-3, "forearm.L roll comes from the human sample")
    check(abs(definition.bones["hand.L"].roll - 2.2103) < 1.0e-3, "hand.L roll comes from the human sample")
    check(definition.roles["hips"] == "spine", "hips is the sample root, not a name guess")
    check(definition.roles["upperarm_l"] == "upper_arm.L", "left arm maps to the left sample bone")
    check(definition.roles["upperarm_r"] == "upper_arm.R", "right arm maps to the right sample bone")
    check(definition.bones["upper_arm.L"].head[0] > 0 > definition.bones["upper_arm.R"].head[0], "left and right arms stay on their sides")
    check(definition.bones["spine.003"].parent == "spine.002", "chest keeps the sample spine ancestor")
    check(definition.bones["spine.002"].parent == "spine.001", "the middle spine ancestor is kept")
    def _excluded(name):
        lower = name.lower()
        heads = ("breast", "ear.", "face", "thumb", "palm", "forehead", "jaw", "f_index", "f_middle", "f_ring", "f_pinky")
        return lower == "face" or lower.startswith(heads)

    check(
        all(not _excluded(name) for name in definition.bones),
        "face, breast, ear and fingers are outside the first body definition",
    )


def _rest_signature(obj):
    active = bpy.context.view_layer.objects.active
    mode = bpy.context.object.mode if bpy.context.object is not None else "OBJECT"
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="EDIT")
    rows = [
        (
            bone.name,
            bone.parent.name if bone.parent else "",
            tuple(round(value, 5) for value in bone.head),
            tuple(round(value, 5) for value in bone.tail),
            round(bone.roll, 5),
        )
        for bone in obj.data.edit_bones
    ]
    bpy.ops.object.mode_set(mode="OBJECT")
    if active is not None and active.name in bpy.data.objects:
        bpy.context.view_layer.objects.active = active
        if mode != "OBJECT":
            bpy.ops.object.mode_set(mode=mode)
    return rows


def test_metarig_calibration_keeps_rest():
    _metarig_mark("test_metarig_calibration_keeps_rest")
    from humanoid_retarget.rigify_metarig import (
        calibrate_source_to_metarig,
        calibrate_target_to_metarig,
        create_human_metarig_armature,
        load_human_metarig_definition,
    )

    definition = load_human_metarig_definition()
    source_names = junk_names()
    target_names = {role: "Tgt_" + role for role in source_names}
    source = build_biped("CalSource", source_names, arm_roll=0.2, scale=1.0)
    target = build_biped("CalTarget", target_names, arm_roll=-0.4, scale=1.3)
    bpy.ops.object.mode_set(mode="OBJECT")
    source.matrix_world = Matrix.Translation((3.0, 0.0, 0.0)) @ Matrix.Rotation(0.3, 4, "Z")
    target.matrix_world = Matrix.Translation((-2.0, 1.0, 0.0))
    bpy.context.view_layer.update()
    source_rest = _rest_signature(source)
    target_rest = _rest_signature(target)
    source_world = source.matrix_world.copy()
    target_world = target.matrix_world.copy()
    pairs = [(role, source_names[role], target_names[role]) for role in source_names]
    options = RetargetOptions(pairs=pairs)
    source_hop = calibrate_source_to_metarig(source, definition, options)
    target_hop = calibrate_target_to_metarig(target, definition, options)
    check(source_hop.definition is definition and target_hop.definition is definition, "both hops use the same definition")
    check(_rest_signature(source) == source_rest, "source rest stays unchanged")
    check(_rest_signature(target) == target_rest, "target rest stays unchanged")
    check(_matrix_close(source.matrix_world, source_world), "source world matrix stays unchanged")
    check(_matrix_close(target.matrix_world, target_world), "target world matrix stays unchanged")
    source_roles = {role: metarig_name for role, _source_name, metarig_name in source_hop.pairs}
    target_roles = {role: metarig_name for role, metarig_name, _target_name in target_hop.pairs}
    check(source_roles["upperarm_l"] == "upper_arm.L", "source calibration keeps the left arm on the left")
    check(target_roles["upperarm_r"] == "upper_arm.R", "target calibration keeps the right arm on the right")
    check(source_roles["hips"] == "spine" and target_roles["hips"] == "spine", "both hops use the same hips bone")
    metarig = create_human_metarig_armature(definition)
    try:
        bpy.context.view_layer.objects.active = metarig
        bpy.ops.object.mode_set(mode="EDIT")
        check(metarig.data.edit_bones["thigh.L"].parent.name == "spine", "the owned armature keeps the sample parent")
        check(abs(metarig.data.edit_bones["hand.L"].roll - definition.bones["hand.L"].roll) < 1.0e-4, "the owned armature keeps the sample roll")
        bpy.ops.object.mode_set(mode="OBJECT")
    finally:
        bpy.data.objects.remove(metarig, do_unlink=True)


def _chain_dot(source, target, source_name, target_name, child_source, child_target):
    start = (source.matrix_world @ source.pose.bones[child_source].head) - (source.matrix_world @ source.pose.bones[source_name].head)
    finish = (target.matrix_world @ target.pose.bones[child_target].head) - (target.matrix_world @ target.pose.bones[target_name].head)
    return start.normalized().dot(finish.normalized())


def test_metarig_two_hop_bake():
    _metarig_mark("test_metarig_two_hop_bake")
    from humanoid_retarget.pipeline import retarget_existing

    source_names = junk_names()
    target_names = {role: "Tgt_" + role for role in source_names}
    source = build_biped("HopSource", source_names, arm_roll=0.0, scale=1.0)
    animate(source, source_names)
    target = build_biped("HopTarget", target_names, arm_roll=0.55, scale=1.25)
    bpy.ops.object.mode_set(mode="OBJECT")
    pairs = [(role, source_names[role], target_names[role]) for role in source_names]
    options = RetargetOptions(pairs=pairs, standard_skeleton="RIGIFY_HUMAN_METARIG")
    before_objects = _object_names()
    before_actions = _action_names()
    _report, baked = retarget_existing(source, target, options)
    check(len(baked) == 1, "one source clip produces one target clip")
    check(baked[0].frame_range[0] == 1 and baked[0].frame_range[1] == 10, "the target clip keeps the source frame range")
    check(_object_names() == before_objects, "the intermediate armature is released")
    new_actions = _action_names() - before_actions
    check(new_actions == {baked[0].name}, "only the delivered target action remains")
    for role, source_name, target_name in options.resolved_pairs:
        check(source_name == source_names[role], "resolved source bones stay on the original rig")
        check(target_name == target_names[role], "resolved target bones stay on the original rig")
    scene = bpy.context.scene
    scene.frame_set(10)
    bpy.context.view_layer.update()
    dot = _chain_dot(
        source,
        target,
        source_names["upperarm_l"],
        target_names["upperarm_l"],
        source_names["forearm_l"],
        target_names["forearm_l"],
    )
    check(abs(dot - 1.0) < 1.5e-3, "the two-hop arm chain points with the source")


def test_metarig_swing_limits():
    _metarig_mark("test_metarig_swing_limits")
    from humanoid_retarget.pipeline import bake_retarget, retarget_through_human_metarig

    source_names = junk_names()
    target_names = {role: "Tgt_" + role for role in source_names}
    source = build_biped("LimitSource", source_names)
    target = build_biped("LimitTarget", target_names, arm_roll=0.4)
    bpy.context.view_layer.objects.active = source
    bpy.ops.object.mode_set(mode="POSE")
    hips = source.pose.bones[source_names["hips"]]
    hand = source.pose.bones[source_names["hand_l"]]
    hips.rotation_mode = "XYZ"
    hand.rotation_mode = "XYZ"
    hips.rotation_euler = (0.0, 0.0, math.radians(40.0))
    hand.rotation_euler = (1.0, 0.4, 0.2)
    hips.keyframe_insert("rotation_euler", frame=1)
    hand.keyframe_insert("rotation_euler", frame=1)
    hips.keyframe_insert("rotation_euler", frame=4)
    hand.keyframe_insert("rotation_euler", frame=4)
    bpy.ops.object.mode_set(mode="OBJECT")
    pairs = [(role, source_names[role], target_names[role]) for role in source_names]
    options = RetargetOptions(pairs=pairs, standard_skeleton="RIGIFY_HUMAN_METARIG", foot_ik=False, hand_ik=False)
    seen = []
    real_bake = bake_retarget

    def _record(src, tgt, bake_options=None):
        result = real_bake(src, tgt, bake_options)
        bpy.context.scene.frame_set(4)
        bpy.context.view_layer.update()
        hands = []
        for role in ("hand_l", "hand_r"):
            name = next(target_name for pair_role, _source_name, target_name in bake_options.pairs if pair_role == role)
            hands.append(tgt.pose.bones[name].rotation_quaternion.copy())
        hip_name = next(target_name for pair_role, _source_name, target_name in bake_options.pairs if pair_role == "hips")
        rest = tgt.data.bones[hip_name].matrix_local.to_3x3()
        posed = tgt.pose.bones[hip_name].matrix.to_3x3()
        delta = (posed @ rest.inverted()).to_quaternion()
        seen.append(abs(delta.to_swing_twist("Z")[1]))
        seen.append(hands)
        return result

    import humanoid_retarget.pipeline as pipeline_module

    pipeline_module.bake_retarget = _record
    try:
        retarget_through_human_metarig(source, target, options)
    finally:
        pipeline_module.bake_retarget = real_bake
    check(len(seen) == 4, "each hop records hips and hands")
    for index in (1, 3):
        for quat in seen[index]:
            check(quat.angle < 1.0e-4, "each hop leaves the hand at identity")
    check(seen[0] < math.radians(20.0), "the metarig hop does not restore the source hips yaw")
    check(seen[2] < math.radians(5.0), "the target hop does not keep hips yaw")


def test_metarig_same_clip():
    _metarig_mark("test_metarig_same_clip")
    from humanoid_retarget.pipeline import retarget_existing
    from humanoid_retarget.retarget import ACTION_SEP, collect_actions

    source_names = junk_names()
    target_names = {role: "Tgt_" + role for role in source_names}
    source = build_biped("ClipSource", source_names)
    target = build_biped("ClipTarget", target_names, arm_roll=0.2)
    bpy.ops.object.mode_set(mode="OBJECT")
    action_a = bpy.data.actions.new("ClipA")
    action_b = bpy.data.actions.new("ClipB")
    action_a.use_fake_user = True
    action_b.use_fake_user = True

    def _key(action, frame, angle):
        anim = source.animation_data or source.animation_data_create()
        anim.action = action
        if action.slots:
            try:
                slot = action.slots.new(id_type="OBJECT", name=source.name)
            except TypeError:
                slot = action.slots.new("OBJECT", source.name)
            anim.action_slot = slot
        bone = source.pose.bones[source_names["upperarm_l"]]
        bone.rotation_mode = "XYZ"
        bone.rotation_euler = (angle, 0.0, 0.0)
        bone.keyframe_insert("rotation_euler", frame=frame)

    bpy.context.view_layer.objects.active = source
    bpy.ops.object.mode_set(mode="POSE")
    _key(action_a, 1, 0.2)
    _key(action_b, 3, -0.4)
    bpy.ops.object.mode_set(mode="OBJECT")
    source["hr_actions"] = ACTION_SEP.join((action_a.name, action_b.name))
    source.animation_data.action = action_b
    source.animation_data.use_nla = False
    pairs = [(role, source_names[role], target_names[role]) for role in source_names]
    retarget_existing(source, target, RetargetOptions(pairs=pairs, standard_skeleton="RIGIFY_HUMAN_METARIG"))
    shown = collect_actions(source)
    check(source.animation_data.action == action_b, "the source still shows the entry clip")
    check(all(action in {action_a, action_b} for action in shown), "intermediate actions are not source clips")
    check("ClipB" in target.animation_data.action.name, "the target shows the same entry clip")
    check(bpy.context.scene.frame_start == 3 and bpy.context.scene.frame_end == 3, "the timeline is the entry clip")


def test_metarig_root_reference_and_ik():
    _metarig_mark("test_metarig_root_reference_and_ik")
    from humanoid_retarget.classify import rig_height
    from humanoid_retarget.pipeline import bake_retarget, retarget_through_human_metarig

    source_names = junk_names()
    target_names = {role: "Tgt_" + role for role in source_names}
    source = build_biped("RootSource", source_names, scale=1.0)
    animate(source, source_names)
    target = build_biped("RootTarget", target_names, arm_roll=0.3, scale=1.25)
    bpy.ops.object.mode_set(mode="OBJECT")
    pairs = [(role, source_names[role], target_names[role]) for role in source_names]
    sentinel = {"source_basis": {"missing": []}, "target_basis": {"missing": []}, "source_matrix": {}, "target_matrix": {}}
    options = RetargetOptions(
        pairs=pairs,
        standard_skeleton="RIGIFY_HUMAN_METARIG",
        reference="CURRENT",
        reference_data=sentinel,
        root_motion="IN_PLACE",
        foot_ik=True,
        hand_ik=True,
    )
    calls = []
    ratios = []
    real_bake = bake_retarget

    def _record(src, tgt, bake_options=None):
        calls.append(bake_options)
        source_roles = {role: source_name for role, source_name, _target_name in bake_options.pairs}
        target_roles = {role: target_name for role, _source_name, target_name in bake_options.pairs}
        ratios.append(rig_height(tgt, target_roles) / rig_height(src, source_roles))
        return real_bake(src, tgt, bake_options)

    import humanoid_retarget.pipeline as pipeline_module

    pipeline_module.bake_retarget = _record
    try:
        retarget_through_human_metarig(source, target, options)
    finally:
        pipeline_module.bake_retarget = real_bake
    check(len(calls) == 2, "the standard mode bakes two hops")
    check(calls[0].root_motion == "KEEP" and calls[1].root_motion == "IN_PLACE", "in-place root motion is only the final hop")
    check(calls[0].foot_ik is False and calls[0].hand_ik is False, "the first hop does not run IK")
    check(calls[1].foot_ik is True and calls[1].hand_ik is True, "IK runs once on the final hop")
    check(calls[0].reference_data is not sentinel and calls[1].reference_data is not sentinel, "current-pose reference is captured per hop")
    check(calls[0].reference_data is not calls[1].reference_data, "the two hops do not share one reference")
    source_height = rig_height(source, {role: source_names[role] for role in source_names})
    target_height = rig_height(target, {role: target_names[role] for role in target_names})
    expected = target_height / source_height
    def _hip_world(frame):
        bpy.context.scene.frame_set(frame)
        bpy.context.view_layer.update()
        return target.matrix_world @ target.pose.bones[target_names["hips"]].head

    delta = _hip_world(10) - _hip_world(1)
    check(abs(delta.x) < 1.0e-3 and abs(delta.y) < 1.0e-3, "the final hop removes horizontal root travel")
    check(abs(ratios[0] * ratios[1] - expected) < 1.0e-4, "the two hop scales multiply to the direct height ratio")


def test_metarig_failure_cleanup():
    _metarig_mark("test_metarig_failure_cleanup")
    from humanoid_retarget.pipeline import PipelineError, retarget_existing
    from humanoid_retarget.retarget import RetargetError
    import humanoid_retarget.pipeline as pipeline_module
    import humanoid_retarget.rigify_metarig as metarig_module

    source_names = junk_names()
    target_names = {role: "Tgt_" + role for role in source_names}
    source = build_biped("FailSource", source_names)
    animate(source, source_names)
    target = build_biped("FailTarget", target_names)
    bpy.ops.object.mode_set(mode="OBJECT")
    pairs = [(role, source_names[role], target_names[role]) for role in source_names]
    options = RetargetOptions(pairs=pairs, standard_skeleton="RIGIFY_HUMAN_METARIG")
    original_action = target.animation_data.action if target.animation_data else None
    active = bpy.context.view_layer.objects.active
    frame = bpy.context.scene.frame_current

    def _run(label, mutate):
        before_objects = _object_names()
        before_actions = _action_names()
        mutate()
        failed = False
        try:
            retarget_existing(source, target, options)
        except PipelineError:
            failed = True
        finally:
            metarig_module.load_human_metarig_definition = _run.loader
            pipeline_module.bake_retarget = _run.bake
        check(failed, label + " fails closed")
        check(_object_names() == before_objects, label + " removes owned armatures")
        extra = _action_names() - before_actions
        check(not extra, label + " removes undelivered actions")
        current = target.animation_data.action if target.animation_data else None
        check(current == original_action, label + " restores the target action")
        check(bpy.context.view_layer.objects.active == active, label + " restores the active object")
        check(bpy.context.scene.frame_current == frame, label + " restores the frame")

    _run.loader = metarig_module.load_human_metarig_definition
    _run.bake = pipeline_module.bake_retarget

    def _fail_loader():
        def _boom():
            raise RetargetError("loader failed")

        metarig_module.load_human_metarig_definition = _boom

    def _fail_first():
        def _boom(src, tgt, bake_options=None):
            raise RetargetError("first hop failed")

        pipeline_module.bake_retarget = _boom

    def _fail_second():
        def _boom(src, tgt, bake_options=None):
            _boom.n += 1
            if _boom.n == 2:
                bpy.data.actions.new("PartialHop")
                tgt.animation_data_clear()
                raise RetargetError("second hop failed")
            return _run.bake(src, tgt, bake_options)

        _boom.n = 0
        pipeline_module.bake_retarget = _boom

    _run("loader", _fail_loader)
    _run("first hop", _fail_first)
    _run("second hop", _fail_second)


def test_direct_mode_without_rigify():
    _metarig_mark("test_direct_mode_without_rigify")
    from humanoid_retarget.pipeline import retarget_existing
    from humanoid_retarget.retarget import RetargetError, bake_retarget
    import humanoid_retarget.rigify_metarig as metarig_module

    source_names = junk_names()
    target_names = {role: "Tgt_" + role for role in source_names}
    source = build_biped("DirectSource", source_names)
    animate(source, source_names)
    target = build_biped("DirectTarget", target_names, arm_roll=0.25, scale=1.1)
    bpy.ops.object.mode_set(mode="OBJECT")
    pairs = [(role, source_names[role], target_names[role]) for role in source_names]
    calls = []
    original = metarig_module.load_human_metarig_definition

    def _boom():
        calls.append("loader")
        raise RetargetError("loader must not run")

    metarig_module.load_human_metarig_definition = _boom
    try:
        report, baked = retarget_existing(source, target, RetargetOptions(pairs=pairs, standard_skeleton="DIRECT"))
    finally:
        metarig_module.load_human_metarig_definition = original
    check(calls == [], "direct mode does not load the metarig")
    check(len(baked) == 1, "direct mode still bakes the source clip")
    check(source.animation_data.action is not None and target.animation_data.action == baked[-1], "direct mode keeps same-clip display")
    check("loader must not run" not in report, "direct mode does not report a metarig failure")


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    test_standard_skeleton_selector()
    test_standard_skeleton_panel_order()
    test_human_metarig_definition()
    test_metarig_calibration_keeps_rest()
    test_metarig_two_hop_bake()
    test_metarig_swing_limits()
    test_metarig_same_clip()
    test_metarig_root_reference_and_ik()
    test_metarig_failure_cleanup()
    test_direct_mode_without_rigify()
    print("METARIG_TEST_COUNT", len(METARIG_TESTS))
    _source, _target = test_geometry_and_bake()
    test_mixamo_names()
    test_autorig_and_roundtrip(_source)
    test_mapping_root_reference_and_ik()
    test_bake_displays_same_source_clip()
    test_source_clip_picker()
    test_playback_switches_target_clip()
    test_hide_bone_spheres()
    test_import_buttons_remember_paths()
    test_file_load_does_not_hide_bones_inside_the_pointer_callback()
    test_hide_imported_bones()
    test_gltf_animation_scope()
    test_stand_layout()
    test_rest_hips_yaw_preserves_arm_chain()
    test_torso_twist_keeps_head_delta()
    test_swing_preserves_target_roll()
    test_skinned_duplicate_bone()
    test_bone_gizmos()
    test_split_parent_orientation()
    print("RETARGET_TEST_OK")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        print("RETARGET_TEST_FAIL")
        sys.exit(1)
