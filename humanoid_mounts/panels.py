from bpy.types import Panel

from .mounts import mounts_for_armature
from .properties import SCHEMA, grip_object, mount_object

VISIBLE_MOUNT_ROWS = 8


def draw_message(layout, text):
    for index in range(0, len(text), 18):
        layout.label(text=text[index:index + 18])


def draw_character(layout, settings):
    header, box = layout.panel("hm_character", default_closed=False)
    header.label(text="人形与骨骼")
    if box is None:
        return
    box.prop(settings, "armature")
    box.operator("humanoid_mounts.use_armature")
    draw_message(box, "仅人形；左右以角色自身为准")
    box.row(align=True).prop(settings, "part", expand=True)
    armature = settings.armature
    if armature is not None and armature.type == "ARMATURE":
        box.prop_search(settings, "bone_name", armature.data, "bones")
    else:
        box.prop(settings, "bone_name")
    box.operator("humanoid_mounts.use_bone")
    valid = armature is not None and armature.type == "ARMATURE" and settings.bone_name in armature.data.bones
    row = box.row()
    row.enabled = valid
    row.operator("humanoid_mounts.create_mount")
    if not valid:
        draw_message(box, "请先选择人形和对应实际骨骼")


def draw_mount_list(layout, settings):
    header, box = layout.panel("hm_mount_list", default_closed=False)
    header.label(text="挂点管理")
    if box is None:
        return
    items = mounts_for_armature(settings.armature, settings.part)
    box.label(text="当前部位挂点：" + str(len(items)))
    box.prop(settings, "mount")
    box.operator("humanoid_mounts.use_mount")
    for mount in items[:VISIBLE_MOUNT_ROWS]:
        state = "已绑定" if mount.children else "空闲"
        if mount.parent_bone not in mount.parent.pose.bones or mount.get("hm_schema") != SCHEMA:
            state = "失效"
        box.label(text=mount.name + " · " + state)
    if len(items) > VISIBLE_MOUNT_ROWS:
        draw_message(box, "更多挂点请使用上方选择框")
    mount = settings.mount
    valid = mount is not None and mount.parent == settings.armature and mount.get("hm_part") == settings.part
    controls = box.column()
    controls.enabled = valid
    controls.prop(settings, "mount_name", text="改名为")
    controls.operator("humanoid_mounts.edit_mount", text="修改名称").operation = "RENAME"
    row = controls.row(align=True)
    row.operator("humanoid_mounts.edit_mount", text="复制挂点").operation = "COPY"
    row.operator("humanoid_mounts.edit_mount", text="换到指定骨骼").operation = "REANCHOR"
    controls.operator("humanoid_mounts.edit_mount", text="删除挂点，保留附件").operation = "DELETE"


def draw_weapon(layout, settings):
    header, box = layout.panel("hm_weapon", default_closed=False)
    header.label(text="武器绑定")
    if box is None:
        return
    draw_message(box, "将 3D 光标位置和方向设为握位")
    box.operator("humanoid_mounts.prepare_grip")
    box.prop(settings, "grip", text="武器根")
    row = box.row(align=True)
    row.operator("humanoid_mounts.use_grip", text="取当前根")
    row.operator("humanoid_mounts.register_grip", text="登记当前 Empty")
    row = box.row(align=True)
    row.enabled = settings.mount is not None and settings.grip is not None
    row.operator("humanoid_mounts.bind_weapon", text="吸附到挂点").rule = "SNAP"
    row.operator("humanoid_mounts.bind_weapon", text="保持位置绑定").rule = "KEEP_WORLD"
    row = box.row()
    row.enabled = settings.grip is not None
    row.operator("humanoid_mounts.detach_weapon")


def draw_offset(layout, settings):
    header, box = layout.panel("hm_offset", default_closed=True)
    header.label(text="偏移与显示")
    if box is None:
        return
    box.row(align=True).prop(settings, "edit_target", expand=True)
    obj = settings.mount if settings.edit_target == "MOUNT" else settings.grip
    if obj is None:
        draw_message(box, "先选择要编辑的挂点或握持根")
        return
    matches = mount_object(settings, obj) if settings.edit_target == "MOUNT" else grip_object(settings, obj)
    if not matches or obj.get("hm_schema") != SCHEMA:
        draw_message(box, "请选择当前人形所属的有效对象")
        return
    if settings.edit_target == "MOUNT" and obj.parent_bone not in obj.parent.data.bones:
        draw_message(box, "骨骼已失效，请先换到有效骨骼")
        return
    box.label(text=obj.name)
    draw_message(box, "校准时请关闭自动关键帧")
    box.operator("humanoid_mounts.select_edit_target")
    box.prop(obj, "location", text="局部位置")
    rotation = "rotation_quaternion" if obj.rotation_mode == "QUATERNION" else "rotation_axis_angle" if obj.rotation_mode == "AXIS_ANGLE" else "rotation_euler"
    box.prop(obj, rotation, text="局部旋转")
    box.prop(obj, "scale", text="局部缩放")
    box.operator("humanoid_mounts.reset_offset")
    row = box.row(align=True)
    row.prop(obj, "show_name", text="名称")
    row.prop(obj, "show_axis", text="轴")
    row.prop(obj, "show_in_front", text="置前")
    box.prop(obj, "empty_display_size", text="标记大小")


class HM_PT_mounts(Panel):
    bl_label = "人形挂载"
    bl_idname = "HM_PT_mounts"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "人形挂载"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.hm_settings
        draw_character(layout, settings)
        draw_mount_list(layout, settings)
        draw_weapon(layout, settings)
        draw_offset(layout, settings)
        draw_message(layout, settings.status or "通过 Blender 时间轴播放动画")


CLASSES = (HM_PT_mounts,)
