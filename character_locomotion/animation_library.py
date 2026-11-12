import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import uuid

import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty, StringProperty
from bpy.types import PropertyGroup

SCHEMA = 1
ROLES = ("IDLE", "WALK", "RUN")
ROLE_LABELS = {"IDLE": "待机", "WALK": "行走", "RUN": "跑步", "OTHER": "其他"}
KINDS = [(kind, label, "") for kind, label in ROLE_LABELS.items()]
FIELDS = ("name", "clip_id", "action", "source_action", "slot_id", "source_slot", "start", "end", "fps", "fps_source", "period", "loop", "confirmed", "kind", "speed", "skeleton", "source_path", "library_id")


class CL_Clip(PropertyGroup):
    clip_id: StringProperty()
    action: PointerProperty(type=bpy.types.Action)
    source_action: PointerProperty(type=bpy.types.Action)
    slot_id: StringProperty()
    source_slot: StringProperty()
    start: FloatProperty(name="起始帧")
    end: FloatProperty(name="结束帧")
    fps: FloatProperty(name="素材帧率", default=30.0, min=0.01)
    fps_source: StringProperty(default="暂用场景帧率")
    period: FloatProperty(name="循环帧数", default=30.0, min=0.01)
    loop: BoolProperty(name="循环播放", default=True)
    confirmed: BoolProperty(name="已核对素材帧率及循环范围", default=False)
    kind: EnumProperty(name="用途", items=KINDS)
    speed: FloatProperty(name="标称速度 (m/s)", default=1.5, min=0.0)
    skeleton: StringProperty()
    source_path: StringProperty(name="素材来源", subtype="FILE_PATH")
    library_id: StringProperty()
    compatible: BoolProperty(default=False, options={"SKIP_SAVE"})


class CL_Settings(PropertyGroup):
    idle_id: StringProperty(default="UNSET")
    walk_id: StringProperty(default="UNSET")
    run_id: StringProperty(default="UNSET")
    walk_speed: FloatProperty(name="走速 (m/s)", default=1.5, min=0.01)
    run_speed: FloatProperty(name="跑速 (m/s)", default=4.0, min=0.01)
    blend: FloatProperty(name="过渡秒数", default=0.15, min=0.0, max=2.0)
    forward: EnumProperty(name="角色前向", items=[("Y", "+Y", ""), ("NEG_Y", "-Y", ""), ("X", "+X", ""), ("NEG_X", "-X", "")], default="Y")
    index: IntProperty(default=0)
    filter_kind: EnumProperty(name="用途筛选", items=[("ALL", "全部", "")] + KINDS)
    show_incompatible: BoolProperty(name="显示需重定向片段", default=False)
    message: StringProperty(default="请选择角色，并准备待机、行走和跑步动画", options={"SKIP_SAVE"})
    repair_clip_id: StringProperty(options={"SKIP_SAVE"})
    library_id: StringProperty()


def skeleton_record(rig, scene):
    bones = [(bone.name, bone.parent.name if bone.parent else "", [value for row in bone.matrix_local for value in row], bone.length) for bone in rig.data.bones]
    return json.dumps({"bones": bones, "units": scene.unit_settings.scale_length, "scale": list(rig.scale), "roles": rig.get("hr_bone_roles", ""), "forward": rig.cl_settings.forward}, ensure_ascii=False, sort_keys=True)


def compatible(record, rig, scene):
    try:
        left = json.loads(record)
        right = json.loads(skeleton_record(rig, scene))
        return abs(left["units"] - right["units"]) <= 1e-5 and len(left["bones"]) == len(right["bones"]) and all(a[:2] == b[:2] and len(a[2]) == 16 and max(abs(x - y) for x, y in zip(a[2], b[2])) <= 1e-5 and abs(a[3] - b[3]) <= 1e-5 for a, b in zip(left["bones"], right["bones"])) and max(abs(x - y) for x, y in zip(left["scale"], right["scale"])) <= 1e-5
    except (ValueError, TypeError, KeyError, IndexError):
        return False


def action_curves(action, identifier):
    if action is None:
        raise ValueError("动画引用已失效，请重新选择")
    slots = list(action.slots)
    if slots:
        slot = next((slot for slot in slots if slot.identifier == identifier and slot.target_id_type == "OBJECT"), None)
        if slot is None:
            raise ValueError("动画槽位失效，请重新选择槽位")
        curves = []
        for layer in action.layers:
            for strip in layer.strips:
                bag = strip.channelbag(slot)
                if bag:
                    curves.extend(bag.fcurves)
        return curves, slot
    return list(action.fcurves), None


def slot_identifier(action, requested=""):
    choices = [slot for slot in action.slots if slot.target_id_type == "OBJECT"]
    if requested:
        action_curves(action, requested)
        return requested
    if len(choices) > 1:
        raise ValueError("动画有多个骨架槽位，请在下拉框明确选择")
    return choices[0].identifier if choices else ""


def constant_curve(curve, start, end):
    if curve.modifiers or curve.sampled_points:
        return False
    value = curve.evaluate(start)
    if abs(curve.evaluate(end) - value) > 1e-5:
        return False
    points = list(curve.keyframe_points)
    if any(start <= point.co.x <= end and abs(point.co.y - value) > 1e-5 for point in points):
        return False
    for a, b in zip(points, points[1:]):
        if b.co.x <= start or a.co.x >= end:
            continue
        if a.interpolation == "CONSTANT":
            controls = [a.co.y]
        elif a.interpolation == "LINEAR":
            controls = [curve.evaluate(max(start, a.co.x)), curve.evaluate(min(end, b.co.x))]
        elif a.interpolation == "BEZIER":
            controls = [a.co.y, a.handle_right.y, b.handle_left.y, b.co.y]
        else:
            return False
        if any(abs(control - value) > 1e-5 for control in controls):
            return False
    return True


def validate_structure(clip):
    values = (clip.start, clip.end, clip.fps, clip.period, clip.speed)
    if not clip.clip_id or not all(math.isfinite(value) for value in values) or clip.end <= clip.start or clip.fps <= 0 or not 0 < clip.period <= clip.end - clip.start:
        raise ValueError("片段范围、素材帧率或循环周期无效")
    skeleton = json.loads(clip.skeleton)
    bones = skeleton.get("bones", [])
    if not bones or len({bone[0] for bone in bones}) != len(bones):
        raise ValueError("动画库缺少参考骨架")
    names = {bone[0] for bone in bones}
    for bone in bones:
        if len(bone) != 4 or len(bone[2]) != 16 or not all(math.isfinite(value) for value in (*bone[2], bone[3])) or bone[3] <= 0 or (bone[1] and bone[1] not in names):
            raise ValueError("动画库参考骨架数据无效")
    if not math.isfinite(skeleton["units"]) or skeleton["units"] <= 0 or len(skeleton["scale"]) != 3 or not all(math.isfinite(value) and value > 0 for value in skeleton["scale"]):
        raise ValueError("动画库单位或缩放无效")
    for action, slot in ((clip.action, clip.slot_id), (clip.source_action, clip.source_slot)):
        curves, chosen = action_curves(action, slot)
        if not curves:
            raise ValueError("动画槽位没有有效通道")
    return skeleton


def validate_clip_steps(clip, rig, scene):
    validate_structure(clip)
    if not compatible(clip.skeleton, rig, scene):
        raise ValueError("片段骨架或单位不匹配，请先重定向")
    if not clip.confirmed:
        raise ValueError("请先核对素材帧率及循环范围")
    if clip.kind in {"WALK", "RUN"} and clip.speed <= 0:
        raise ValueError("走跑片段的标称速度必须大于零")
    curves, slot = action_curves(clip.action, clip.slot_id)
    if rig.pose is None:
        raise ValueError("骨架尚未求值，请更新场景后重试")
    paths = {bone.path_from_id(): bone for bone in rig.pose.bones}
    for curve in curves:
        path, separator, channel = curve.data_path.rpartition(".")
        if not separator or path not in paths or channel not in {"location", "rotation_euler", "rotation_quaternion", "rotation_axis_angle", "scale"}:
            raise ValueError("动画含对象根运动或非骨骼通道，请准备原地动画")
        bone = paths[path]
        expected_rotation = "rotation_quaternion" if bone.rotation_mode == "QUATERNION" else "rotation_axis_angle" if bone.rotation_mode == "AXIS_ANGLE" else "rotation_euler"
        if channel.startswith("rotation") and channel != expected_rotation:
            raise ValueError("骨骼旋转模式与动画不一致，请先烘焙")
        if bone.parent is None:
            horizontal = False
            if channel == "location":
                axis = (rig.matrix_world.to_3x3() @ bone.bone.matrix_local.to_3x3()).col[curve.array_index]
                horizontal = axis.x * axis.x + axis.y * axis.y > 1e-10
            if (horizontal or channel.startswith("rotation")) and not constant_curve(curve, clip.start, clip.end):
                raise ValueError("根骨有水平位移或转向，请先生成原地动画")
        yield None


def validate_clip(clip, rig, scene):
    for step in validate_clip_steps(clip, rig, scene):
        pass


def find_clip(rig, identifier):
    return next((clip for clip in rig.cl_clips if clip.clip_id == identifier), None)


def refresh_compatibility(rig, scene):
    for clip in rig.cl_clips:
        clip.compatible = compatible(clip.skeleton, rig, scene)


def autofill(rig):
    for role in ROLES:
        field = role.lower() + "_id"
        choices = [clip for clip in rig.cl_clips if clip.kind == role and clip.compatible and clip.confirmed]
        if getattr(rig.cl_settings, field) == "UNSET" and len(choices) == 1:
            setattr(rig.cl_settings, field, choices[0].clip_id)


def add_clip(rig, scene, action, kind, slot="", confirmed=False):
    identifier = slot_identifier(action, slot)
    previous_library = rig.cl_settings.library_id
    clip = rig.cl_clips.add()
    try:
        clip.name = action.name
        clip.clip_id = uuid.uuid4().hex
        clip.action = action
        clip.source_action = action
        clip.slot_id = identifier
        clip.source_slot = identifier
        clip.start, clip.end = action.frame_range
        clip.period = clip.end - clip.start
        clip.fps = scene.render.fps / scene.render.fps_base
        clip.kind = kind
        clip.speed = 4.0 if kind == "RUN" else 1.5 if kind == "WALK" else 0.0
        clip.skeleton = skeleton_record(rig, scene)
        clip.source_path = "//" + Path(bpy.data.filepath).name if bpy.data.filepath else ""
        if not rig.cl_settings.library_id:
            rig.cl_settings.library_id = uuid.uuid4().hex
        clip.library_id = rig.cl_settings.library_id
        clip.confirmed = confirmed
        validate_structure(clip)
        clip.compatible = True
    except Exception:
        rig.cl_clips.remove(len(rig.cl_clips) - 1)
        rig.cl_settings.library_id = previous_library
        raise
    rig.cl_settings.index = len(rig.cl_clips) - 1
    autofill(rig)
    return clip


def copy_clip(source, target):
    for field in FIELDS:
        setattr(target, field, getattr(source, field))


def fingerprint(clip):
    metadata = {field: getattr(clip, field) for field in FIELDS if field not in {"name", "action", "source_action", "source_path", "library_id"}}
    for field, slot_field in (("action", "slot_id"), ("source_action", "source_slot")):
        curves, slot = action_curves(getattr(clip, field), getattr(clip, slot_field))
        metadata[field] = [(curve.data_path, curve.array_index, curve.extrapolation, [(tuple(point.co), tuple(point.handle_left), tuple(point.handle_right), point.interpolation, point.easing, point.amplitude, point.back, point.period) for point in curve.keyframe_points], [tuple(point.co) for point in curve.sampled_points], [(modifier.type, [(prop.identifier, str(getattr(modifier, prop.identifier))) for prop in modifier.bl_rna.properties if prop.identifier != "rna_type" and not prop.is_readonly]) for modifier in curve.modifiers]) for curve in sorted(curves, key=lambda item: (item.data_path, item.array_index))]
    return hashlib.sha256(json.dumps(metadata, sort_keys=True).encode("utf-8")).hexdigest()


def resolve_path(value):
    if value.startswith("//") and not bpy.data.filepath:
        raise ValueError("请先保存当前工程，或在文件选择器选定完整路径")
    if not value.startswith("//") and not os.path.isabs(value):
        raise ValueError("请选择文件，或使用相对当前 blend 的 // 路径")
    return Path(bpy.path.abspath(value)).resolve()


def save_library(rig, scene, value, overwrite=False):
    path = resolve_path(value)
    if path.suffix.lower() != ".blend" or not path.parent.is_dir():
        raise ValueError("请选择已有目录中的 .blend 文件")
    if path.exists() and not overwrite:
        raise ValueError("文件已存在，请明确允许覆盖")
    if bpy.data.filepath and path == Path(bpy.data.filepath).resolve():
        raise ValueError("不能覆盖当前工程文件")
    clips = [clip for clip in rig.cl_clips if compatible(clip.skeleton, rig, scene)]
    if not clips:
        raise ValueError("当前角色没有可保存的动画")
    for clip in clips:
        validate_structure(clip)
    reference = bpy.data.objects.new("CharacterAnimationLibrary", rig.data.copy())
    reference.data.animation_data_clear()
    temporary = None
    try:
        reference["cl_schema"] = SCHEMA
        reference["cl_library_id"] = rig.cl_settings.library_id or uuid.uuid4().hex
        reference["cl_reference_name"] = reference.name
        for clip in clips:
            stored = reference.cl_clips.add()
            copy_clip(clip, stored)
            if clip.source_path:
                stored.source_path = os.path.relpath(bpy.path.abspath(clip.source_path), path.parent).replace(os.sep, "/")
        descriptor, temporary = tempfile.mkstemp(suffix=".blend", dir=path.parent)
        os.close(descriptor)
        bpy.data.libraries.write(temporary, {reference}, fake_user=True, compress=True)
        with bpy.data.libraries.load(temporary) as (source, target):
            if reference.name not in source.objects:
                raise ValueError("动画库写入校验失败")
        os.replace(temporary, path)
    finally:
        data = reference.data
        bpy.data.objects.remove(reference, do_unlink=True)
        if data.users == 0:
            bpy.data.armatures.remove(data)
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
    return len(clips), len(rig.cl_clips) - len(clips)


def load_library(rig, scene, value):
    path = resolve_path(value)
    baseline = {name: set(getattr(bpy.data, name)) for name in ("objects", "armatures", "actions")}
    count = len(rig.cl_clips)
    previous_settings = {field: getattr(rig.cl_settings, field) for field in ("idle_id", "walk_id", "run_id", "library_id", "index")}
    success = False
    try:
        with bpy.data.libraries.load(str(path), link=False) as (source, target):
            names = [name for name in source.objects if name.startswith("CharacterAnimationLibrary")]
            if len(names) != 1:
                raise ValueError("文件不是单骨架角色动画库")
            target.objects = names
        reference = target.objects[0]
        if reference.get("cl_schema") != SCHEMA or not reference.get("cl_library_id") or not reference.cl_clips:
            raise ValueError("动画库版本不支持或内容不完整")
        known = {clip.clip_id: clip for clip in rig.cl_clips}
        incoming = {}
        for clip in reference.cl_clips:
            validate_structure(clip)
            digest = fingerprint(clip)
            if clip.clip_id in incoming and incoming[clip.clip_id] != digest:
                raise ValueError("库内片段 ID 冲突")
            incoming[clip.clip_id] = digest
            if clip.clip_id in known and fingerprint(known[clip.clip_id]) != digest:
                raise ValueError("片段 ID 相同但内容不同，本次载入已取消")
        for clip in reference.cl_clips:
            if clip.clip_id not in known:
                item = rig.cl_clips.add()
                copy_clip(clip, item)
                if clip.source_path:
                    absolute_source = str((path.parent / clip.source_path).resolve())
                    item.source_path = bpy.path.relpath(absolute_source) if bpy.data.filepath else absolute_source
                known[clip.clip_id] = item
        refresh_compatibility(rig, scene)
        autofill(rig)
        if not rig.cl_settings.library_id:
            rig.cl_settings.library_id = reference["cl_library_id"]
        success = True
    finally:
        if not success:
            while len(rig.cl_clips) > count:
                rig.cl_clips.remove(len(rig.cl_clips) - 1)
            for field, value in previous_settings.items():
                setattr(rig.cl_settings, field, value)
        for name in ("objects", "armatures", "actions"):
            collection = getattr(bpy.data, name)
            for item in set(collection) - baseline[name]:
                if name == "objects" or item.users == int(item.use_fake_user) or (name == "actions" and not success):
                    collection.remove(item, do_unlink=True)
    return len(rig.cl_clips) - count


CLASSES = (CL_Clip, CL_Settings)
