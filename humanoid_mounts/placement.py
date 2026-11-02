import json
import math
from collections import namedtuple

import bpy
from mathutils import Matrix

from . import bone_roles, mounts, weapons
from .properties import PARTS, SCHEMA

EquipmentStatus = namedtuple("EquipmentStatus", "step message mount grip")
POSE_CHANNELS = ("location", "rotation_euler", "rotation_quaternion", "rotation_axis_angle", "scale", "delta_location", "delta_rotation_euler", "delta_rotation_quaternion", "delta_scale")


def part_name(part):
    return next((label for value, label, description in PARTS if value == part), "其他位置")


def current_mount(settings):
    preferred = settings.mount
    if preferred is not None and (preferred.parent != settings.armature or preferred.get("hm_part") != settings.part):
        preferred = None
    return mounts.mount_for_part(settings.armature, settings.part, preferred)


def equipment_status(settings):
    if settings.fitting_stage != "NONE":
        message = "把标记移到掌心或装备位置，然后保存" if settings.fitting_stage == "CHARACTER" else "移动或旋转装备，摆好后记住当前拿法"
        return EquipmentStatus("FITTING", message, settings.fitting_mount, None)
    if settings.armature is None:
        return EquipmentStatus("CHOOSE_CHARACTER", "先选择角色，或使用重定向角色", None, None)
    if settings.equipment is None:
        return EquipmentStatus("CHOOSE_EQUIPMENT", "选中装备，再点使用选中的物体", None, None)
    if bpy.context.mode != "OBJECT":
        return EquipmentStatus("BLOCKED", "请先切回物体模式", None, None)
    if bpy.context.scene.tool_settings.use_keyframe_insert_auto:
        return EquipmentStatus("BLOCKED", "请先关闭自动关键帧", None, None)
    try:
        mounts.editable_object(settings.armature)
        mounts.editable_object(settings.equipment)
        if settings.armature.type != "ARMATURE":
            raise mounts.HumanoidMountError("请选择人形角色")
        grip = weapons.find_grip_root(settings.equipment)
        if grip is not None and (grip.type != "EMPTY" or grip.get("hm_schema") != SCHEMA):
            raise mounts.HumanoidMountError("装备记录失效，请在高级设置中处理")
        mount = current_mount(settings)
        if mount is not None:
            mounts.mount_owner(mount)
            if mount.parent_bone not in settings.armature.data.bones:
                raise mounts.HumanoidMountError("安装位置已失效，请在高级设置中修复")
        else:
            bone_roles.resolve_bone(settings.armature, settings.part)
        if grip is None:
            unprepared_parts(settings)
        if grip is not None and grip.parent is not None and grip.parent != mount:
            owner = mounts.mount_owner(grip.parent)
            if owner != settings.armature:
                raise mounts.HumanoidMountError("装备属于另一角色，请先选择正确角色")
            message = "当前在" + part_name(grip.parent.get("hm_part")) + "，取下后可放到" + part_name(settings.part)
            return EquipmentStatus("BLOCKED", message, mount, grip)
        if grip is not None and grip.get("hm_source_file"):
            weapons.validate_grip(grip)
            if mount is not None and grip.parent == mount:
                return EquipmentStatus("EQUIPPED", "已贴合目标挂点；可选调整握位或道具位置", mount, grip)
            return EquipmentStatus("READY", "点击直接贴合，局部位移归零；握位可稍后调整", mount, grip)
        if mount is None or not mount.get("hm_grip_fitted", False):
            return EquipmentStatus("FIT_CHARACTER", "首次使用这个位置，先设置角色握位", mount, grip)
        if grip is None:
            return EquipmentStatus("FIT_EQUIPMENT", "首次使用这件装备，先设置拿法", mount, None)
        if grip.parent == mount:
            return EquipmentStatus("EQUIPPED", "已装备，可以播放动画检查", mount, grip)
        return EquipmentStatus("READY", "已准备好，可以放到指定位置", mount, grip)
    except mounts.HumanoidMountError as error:
        return EquipmentStatus("BLOCKED", str(error), None, None)


def select_equipment(settings, objects, active):
    if settings.fitting_stage != "NONE":
        raise mounts.HumanoidMountError("请先保存或取消当前设置")
    objects = tuple(objects)
    if active is None or active not in objects:
        raise mounts.HumanoidMountError("请先选中装备")
    root = weapons.find_grip_root(active)
    if root is not None:
        weapons.validate_grip(root)
        if root.parent is not None and mounts.mount_owner(root.parent) != settings.armature:
            raise mounts.HumanoidMountError("装备属于另一角色，请先取下")
        if any(weapons.find_grip_root(obj) != root for obj in objects):
            raise mounts.HumanoidMountError("请只选择同一件装备的部件")
        parts = (root,)
    else:
        parts = objects
        for obj in parts:
            weapons.validate_rigid(obj)
            if obj.parent is not None or obj.children:
                raise mounts.HumanoidMountError("装备已有层级，请在高级设置中指定")
    settings.equipment_parts.clear()
    for obj in parts:
        settings.equipment_parts.add().object = obj
    settings.equipment = root if root is not None else active
    settings.grip = root


def unprepared_parts(settings):
    parts = tuple(item.object for item in settings.equipment_parts)
    if not parts or settings.equipment not in parts or len(set(parts)) != len(parts):
        raise mounts.HumanoidMountError("装备选择已失效，请重新选择")
    for obj in parts:
        mounts.editable_object(obj)
        if obj.parent is not None or obj.children:
            raise mounts.HumanoidMountError("装备层级已改变，请重新选择")
    return parts


def fitting_objects(settings):
    root = weapons.find_grip_root(settings.equipment)
    if root is not None:
        weapons.validate_grip(root)
        return (root,)
    parts = unprepared_parts(settings)
    for obj in parts:
        weapons.validate_rigid(obj)
    return parts


def check_fitting_mode():
    if bpy.context.mode != "OBJECT":
        raise mounts.HumanoidMountError("请先切回物体模式")
    if bpy.context.scene.tool_settings.use_keyframe_insert_auto:
        raise mounts.HumanoidMountError("请先关闭自动关键帧，再设置位置")


def pose_record(obj):
    return {
        "channels": {name: list(getattr(obj, name)) for name in POSE_CHANNELS},
        "rotation_mode": obj.rotation_mode,
        "parent_type": obj.parent_type,
        "parent_bone": obj.parent_bone,
        "had_parent": obj.parent is not None,
        "inverse": [list(row) for row in obj.matrix_parent_inverse],
    }


def clear_fitting(settings):
    settings.fitting_stage = "NONE"
    settings.fitting_snapshot = ""
    settings.fitting_objects.clear()
    settings.fitting_mount = None
    settings.fitting_armature = None
    settings.fitting_part = ""
    settings.fitting_created = False
    settings.fitting_previous_mount = None


def begin_fitting(settings, stage):
    check_fitting_mode()
    if settings.fitting_stage != "NONE":
        raise mounts.HumanoidMountError("请先保存或取消当前设置")
    if stage not in {"CHARACTER", "EQUIPMENT"}:
        raise mounts.HumanoidMountError("设置步骤无效")
    state = equipment_status(settings)
    if state.step in {"CHOOSE_CHARACTER", "CHOOSE_EQUIPMENT", "BLOCKED"}:
        raise mounts.HumanoidMountError(state.message)
    if stage == "EQUIPMENT" and state.step == "FIT_CHARACTER":
        raise mounts.HumanoidMountError("请先保存角色握位")
    if stage == "EQUIPMENT" and state.grip is not None and state.grip.get("hm_source_file") and state.step != "EQUIPPED":
        raise mounts.HumanoidMountError("请先直接贴合当前道具，再调整位置")
    mount = state.mount
    previous = settings.mount
    created = False
    try:
        if mount is None:
            mount = mounts.create_mount(settings.armature, bone_roles.resolve_bone(settings.armature, settings.part), settings.part)
            created = True
        mounts.validate_mount(mount)
        objects = (mount,) if stage == "CHARACTER" else fitting_objects(settings)
        for obj in objects:
            mounts.validate_parent_change(obj)
            if not obj.visible_get() or obj.hide_select:
                raise mounts.HumanoidMountError("对象被隐藏或禁止选择，请先在大纲中显示")
        snapshot = json.dumps([pose_record(obj) for obj in objects])
        settings.fitting_objects.clear()
        for obj in objects:
            item = settings.fitting_objects.add()
            item.object = obj
            item.parent = obj.parent
        settings.fitting_snapshot = snapshot
        settings.fitting_previous_mount = settings.mount
        settings.fitting_mount = mount
        settings.fitting_armature = settings.armature
        settings.fitting_part = settings.part
        settings.fitting_created = created
        settings.fitting_stage = stage
        settings.mount = mount
        for obj in tuple(bpy.context.selected_objects):
            obj.select_set(False)
        for obj in objects:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = objects[0]
    except Exception:
        if created:
            bpy.data.objects.remove(mount, do_unlink=True)
        clear_fitting(settings)
        settings.mount = previous
        raise


def fitting_restore_records(settings):
    if settings.fitting_stage == "NONE":
        return ()
    try:
        records = json.loads(settings.fitting_snapshot)
        items = tuple(settings.fitting_objects)
        if not isinstance(records, list) or not items or len(items) != len(records):
            raise ValueError("incomplete fitting records")
        for item, record in zip(items, records):
            obj = item.object
            if obj is None or obj.library is not None or obj.override_library is not None or not obj.is_editable:
                raise ValueError("fitting object unavailable")
            if type(record["had_parent"]) is not bool or (record["had_parent"] and item.parent is None):
                raise ValueError("original parent unavailable")
            if set(record["channels"]) != set(POSE_CHANNELS):
                raise ValueError("missing transform channels")
            for name, values in record["channels"].items():
                if len(values) != len(getattr(obj, name)) or any(type(value) not in (int, float) or not math.isfinite(value) for value in values):
                    raise ValueError("invalid transform channel")
            inverse = Matrix(record["inverse"])
            if len(inverse) != 4 or len(inverse[0]) != 4 or any(not math.isfinite(value) for row in inverse for value in row):
                raise ValueError("invalid parent inverse")
            if record["rotation_mode"] not in obj.bl_rna.properties["rotation_mode"].enum_items.keys() or record["parent_type"] not in obj.bl_rna.properties["parent_type"].enum_items.keys():
                raise ValueError("invalid transform mode")
            if not isinstance(record["parent_bone"], str):
                raise ValueError("invalid parent bone")
            if record["parent_type"] == "BONE" and (item.parent is None or item.parent.type != "ARMATURE" or record["parent_bone"] not in item.parent.data.bones):
                raise ValueError("original bone unavailable")
            if item.parent is not None:
                mounts.validate_parent(obj, item.parent)
    except (ValueError, TypeError, KeyError, AttributeError, ReferenceError) as error:
        raise mounts.HumanoidMountError("设置恢复记录或原对象失效，不能自动取消") from error
    if settings.fitting_created:
        mount = settings.fitting_mount
        if mount is None or len(items) != 1 or items[0].object != mount or not mounts.is_mount(mount):
            raise mounts.HumanoidMountError("本次创建的位置已改变，不能自动删除")
        if mount.children:
            raise mounts.HumanoidMountError("新位置出现额外附件，请先处理后再取消")
    return tuple(zip(items, records))


def restore_fitting_pose(item, record):
    obj = item.object
    obj.parent = item.parent
    obj.parent_type = record["parent_type"]
    obj.parent_bone = record["parent_bone"]
    obj.matrix_parent_inverse = Matrix(record["inverse"])
    obj.rotation_mode = record["rotation_mode"]
    for name, values in record["channels"].items():
        setattr(obj, name, values)


def cancel_fitting(settings):
    if settings.fitting_stage == "NONE":
        return
    records = fitting_restore_records(settings)
    saved = [mounts.ParentPose(item.object) for item, record in records]
    try:
        for item, record in records:
            restore_fitting_pose(item, record)
        if settings.fitting_created:
            bpy.data.objects.remove(settings.fitting_mount, do_unlink=True)
    except Exception:
        for pose in saved:
            pose.restore()
        raise
    settings.mount = settings.fitting_previous_mount
    clear_fitting(settings)
    bpy.context.view_layer.update()


def save_fitting(settings):
    check_fitting_mode()
    stage = settings.fitting_stage
    if stage == "NONE":
        raise mounts.HumanoidMountError("没有正在进行的设置")
    if settings.armature != settings.fitting_armature or settings.part != settings.fitting_part:
        raise mounts.HumanoidMountError("角色或位置已改变，请先取消当前设置")
    mount = settings.fitting_mount
    mounts.validate_mount(mount)
    if mounts.mount_owner(mount) != settings.fitting_armature or mount.get("hm_part") != settings.fitting_part:
        raise mounts.HumanoidMountError("安装位置已改变，请先取消当前设置")
    if stage == "CHARACTER":
        mount["hm_grip_fitted"] = True
    else:
        objects = fitting_objects(settings)
        if objects != tuple(item.object for item in settings.fitting_objects):
            raise mounts.HumanoidMountError("装备选择已改变，请先取消当前设置")
        root = weapons.find_grip_root(settings.equipment)
        if root is not None:
            weapons.remember_grip(root, mount)
        else:
            saved = [mounts.ParentPose(obj) for obj in objects]
            root = weapons.prepare_grip_root(objects, mounts.world_matrix(mount))
            try:
                weapons.bind_weapon(root, mount, "SNAP")
            except Exception:
                for pose in saved:
                    pose.restore()
                bpy.data.objects.remove(root, do_unlink=True)
                raise
        settings.equipment = root
        settings.grip = root
        settings.equipment_parts.clear()
        settings.equipment_parts.add().object = root
    settings.mount = mount
    settings.mount_name = mount.name
    clear_fitting(settings)
