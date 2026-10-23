from __future__ import annotations

import bpy
from mathutils import Vector

from .classify import CORE_ROLES, classify_armature, rig_height
from .retarget import RetargetError, capture_reference


ROLE_TO_SAMPLE = {
    "hips": "spine",
    "spine": "spine.001",
    "chest": "spine.003",
    "neck": "spine.004",
    "head": "spine.006",
    "shoulder_l": "shoulder.L",
    "upperarm_l": "upper_arm.L",
    "forearm_l": "forearm.L",
    "hand_l": "hand.L",
    "shoulder_r": "shoulder.R",
    "upperarm_r": "upper_arm.R",
    "forearm_r": "forearm.R",
    "hand_r": "hand.R",
    "thigh_l": "thigh.L",
    "shin_l": "shin.L",
    "foot_l": "foot.L",
    "toe_l": "toe.L",
    "thigh_r": "thigh.R",
    "shin_r": "shin.R",
    "foot_r": "foot.R",
    "toe_r": "toe.R",
}

_EXCLUDED_HEADS = (
    "breast",
    "ear.",
    "face",
    "thumb",
    "palm",
    "forehead",
    "jaw",
    "f_index",
    "f_middle",
    "f_ring",
    "f_pinky",
    "nose",
    "lip",
    "teeth",
    "tongue",
    "brow",
    "lid",
    "cheek",
    "chin",
    "temple",
)
_SAMPLE_MODULE = "rigify.metarigs.human"


class MetarigBone:
    def __init__(self, name, parent, head, tail, roll):
        self.name = name
        self.parent = parent
        self.head = head
        self.tail = tail
        self.roll = roll


class HumanMetarigDefinition:
    def __init__(self, source_id, bones, roles):
        self.source_id = source_id
        self.bones = bones
        self.roles = roles


class MetarigHop:
    def __init__(self, definition, pairs, height_ratio):
        self.definition = definition
        self.pairs = pairs
        self.height_ratio = height_ratio


def _vector(values):
    return Vector(values)


def _length(bone):
    return (_vector(bone.tail) - _vector(bone.head)).length


def _select_only(obj):
    for other in list(bpy.context.view_layer.objects):
        if other is None:
            continue
        try:
            other.select_set(other == obj)
        except ReferenceError:
            pass
    bpy.context.view_layer.objects.active = obj


def _enable_human_sample():
    if "rigify" not in bpy.context.preferences.addons:
        try:
            bpy.ops.preferences.addon_enable(module="rigify")
        except Exception as exc:
            raise RetargetError("无法加载 Rigify human metarig。") from exc
    try:
        from rigify.metarigs import human as human_sample
    except Exception as exc:
        raise RetargetError("无法加载 Rigify human metarig。") from exc
    if human_sample.__name__ != _SAMPLE_MODULE:
        raise RetargetError("标准骨架必须是 rigify.metarigs.human。")
    return human_sample


def _delete_sample(obj):
    if obj is None:
        return
    data = obj.data
    if obj.name in bpy.data.objects:
        bpy.context.view_layer.objects.active = obj
        if bpy.context.object is not None and bpy.context.object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        bpy.data.objects.remove(obj, do_unlink=True)
    if data is not None and getattr(data, "users", 0) == 0:
        bpy.data.armatures.remove(data)


def _read_sample(obj):
    bpy.context.view_layer.objects.active = obj
    if bpy.context.object.mode != "EDIT":
        bpy.ops.object.mode_set(mode="EDIT")
    bones = {}
    for bone in obj.data.edit_bones:
        bones[bone.name] = MetarigBone(
            bone.name,
            bone.parent.name if bone.parent else "",
            (float(bone.head.x), float(bone.head.y), float(bone.head.z)),
            (float(bone.tail.x), float(bone.tail.y), float(bone.tail.z)),
            float(bone.roll),
        )
    return bones


def _body_bones(bones):
    missing = [name for name in ROLE_TO_SAMPLE.values() if name not in bones]
    if missing:
        raise RetargetError("human metarig 缺少身体骨骼: " + ", ".join(missing))
    kept = {}
    for name in ROLE_TO_SAMPLE.values():
        seen = set()
        current = name
        while current:
            if current in seen:
                raise RetargetError("human metarig 父级成环: " + current)
            seen.add(current)
            bone = bones.get(current)
            if bone is None:
                raise RetargetError("human metarig 缺少祖先: " + current)
            if _length(bone) < 1.0e-6:
                raise RetargetError("human metarig 骨骼长度为 0: " + current)
            kept[current] = bone
            current = bone.parent
    for name in kept:
        lower = name.lower()
        if lower == "face" or lower.startswith(_EXCLUDED_HEADS):
            raise RetargetError("human metarig 身体链包含排除骨骼: " + name)
    left = kept["upper_arm.L"].head[0]
    right = kept["upper_arm.R"].head[0]
    if not left > right:
        raise RetargetError("human metarig 左右臂位置不正确。")
    return kept


def load_human_metarig_definition():
    human_sample = _enable_human_sample()
    arm_data = bpy.data.armatures.new("HR_MetarigSample")
    obj = bpy.data.objects.new("HR_MetarigSample", arm_data)
    bpy.context.scene.collection.objects.link(obj)
    try:
        _select_only(obj)
        human_sample.create(obj)
        bones = _body_bones(_read_sample(obj))
    finally:
        _delete_sample(obj)
    return HumanMetarigDefinition(_SAMPLE_MODULE, bones, dict(ROLE_TO_SAMPLE))


def create_human_metarig_armature(definition):
    if definition is None or definition.source_id != _SAMPLE_MODULE:
        raise RetargetError("标准骨架必须是 rigify.metarigs.human。")
    arm_data = bpy.data.armatures.new("HR_HumanMetarig")
    obj = bpy.data.objects.new("HR_HumanMetarig", arm_data)
    bpy.context.scene.collection.objects.link(obj)
    _select_only(obj)
    bpy.ops.object.mode_set(mode="EDIT")
    edit_bones = arm_data.edit_bones
    pending = dict(definition.bones)
    created = set()
    while pending:
        ready = [name for name, bone in pending.items() if not bone.parent or bone.parent in created]
        if not ready:
            bpy.ops.object.mode_set(mode="OBJECT")
            raise RetargetError("human metarig 父级不完整。")
        for name in ready:
            bone = pending.pop(name)
            edit = edit_bones.new(name)
            edit.use_connect = False
            edit.head = bone.head
            edit.tail = bone.tail
            edit.roll = bone.roll
            created.add(name)
    for bone in definition.bones.values():
        if not bone.parent:
            continue
        edit_bones[bone.name].parent = edit_bones[bone.parent]
        edit_bones[bone.name].use_connect = False
        edit_bones[bone.name].head = bone.head
        edit_bones[bone.name].tail = bone.tail
        edit_bones[bone.name].roll = bone.roll
    bpy.ops.object.mode_set(mode="OBJECT")
    return obj


def _roles_on_armature(arm, options, which):
    if options is not None and options.pairs:
        found = {}
        for role, source_name, target_name in options.pairs:
            found[role] = source_name if which == "source" else target_name
        return found
    return classify_armature(arm)


def _hop_pairs(arm, definition, options, which):
    found = _roles_on_armature(arm, options, which)
    missing = [role for role in CORE_ROLES if role not in found or found[role] not in arm.data.bones]
    if missing:
        raise RetargetError("这些主骨没有同时映射到: " + ", ".join(missing))
    pairs = []
    for role, sample_name in definition.roles.items():
        arm_name = found.get(role)
        if not arm_name or arm_name not in arm.data.bones or sample_name not in definition.bones:
            continue
        if which == "source":
            pairs.append((role, arm_name, sample_name))
        else:
            pairs.append((role, sample_name, arm_name))
    return pairs


def _ratio(arm, roles, definition):
    hips = definition.bones[definition.roles["hips"]]
    head = definition.bones[definition.roles["head"]]
    standard_height = max(head.tail[2] - hips.head[2], 1.0e-4)
    arm_roles = {role: roles[role] for role in roles if role in ("hips", "head")}
    if "hips" in roles and "head" in roles:
        arm_roles = {"hips": roles["hips"], "head": roles["head"]}
    return standard_height / rig_height(arm, arm_roles)


def calibrate_source_to_metarig(source, definition, options=None):
    found = _roles_on_armature(source, options, "source")
    pairs = _hop_pairs(source, definition, options, "source")
    return MetarigHop(definition, pairs, _ratio(source, found, definition))


def calibrate_target_to_metarig(target, definition, options=None):
    found = _roles_on_armature(target, options, "target")
    pairs = _hop_pairs(target, definition, options, "target")
    return MetarigHop(definition, pairs, _ratio(target, found, definition))


def capture_hop_references(source, metarig, target, source_pairs, target_pairs, frame):
    scene = bpy.context.scene
    scene.frame_set(frame)
    bpy.context.view_layer.update()
    return (
        capture_reference(source, metarig, source_pairs),
        capture_reference(metarig, target, target_pairs),
    )
