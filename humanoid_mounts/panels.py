from bpy.types import Panel

from .mounts import HumanoidMountError, mounts_for_armature
from .bone_roles import resolve_bone
from .properties import PARTS, SCHEMA, grip_object, mount_object
from . import bl_info, placement

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
    row = box.row(align=True)
    row.operator("humanoid_mounts.use_armature", text="使用当前骨架")
    row.operator("humanoid_mounts.use_retarget_target")
    draw_message(box, "仅人形；左右以角色自身为准")
    box.row(align=True).prop(settings, "part", expand=True)
    armature = settings.armature
    existing = mounts_for_armature(armature, settings.part)
    if existing:
        has_invalid = any(mount.get("hm_schema") != SCHEMA or mount.parent_type != "BONE" or mount.parent_bone not in armature.data.bones for mount in existing)
        if has_invalid:
            draw_message(box, "存在失效挂点，请在挂点管理中修复或选择有效点")
        elif len(existing) > 1:
            draw_message(box, "存在多个挂点，请在挂点管理中选择")
        else:
            draw_message(box, "已有挂点，装备时保留校准")
    else:
        try:
            draw_message(box, "已映射：" + resolve_bone(armature, settings.part))
            draw_message(box, "首次创建位于骨骼原点，需校准握位")
        except HumanoidMountError as error:
            draw_message(box, str(error))
    header, custom = box.panel("hm_bone_custom", default_closed=True)
    header.label(text="自定义骨骼")
    if custom is None:
        return
    box = custom
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
    header, box = layout.panel("hm_mount_list", default_closed=True)
    header.label(text="挂点管理")
    if box is None:
        return
    items = mounts_for_armature(settings.armature, settings.part)
    box.label(text="当前部位挂点：" + str(len(items)))
    if mount_object(settings, settings.mount):
        box.prop(settings, "mount")
    else:
        draw_message(box, "请选择当前位置的安装位置")
    box.operator("humanoid_mounts.use_mount")
    for mount in items[:VISIBLE_MOUNT_ROWS]:
        state = "已绑定" if mount.children else "空闲"
        if mount.parent_type != "BONE" or mount.parent_bone not in mount.parent.pose.bones or mount.get("hm_schema") != SCHEMA:
            state = "失效"
        box.operator("humanoid_mounts.use_mount", text=mount.name + " · " + state).name = mount.name
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
    draw_message(box, "选中已校准武器或其部件，一键装备")
    box.operator("humanoid_mounts.equip_weapon")
    box.prop(settings, "grip", text="武器根")
    box.operator("humanoid_mounts.detach_weapon")
    header, custom = box.panel("hm_grip_custom", default_closed=True)
    header.label(text="自定义握持校准与绑定")
    if custom is None:
        return
    box = custom
    draw_message(box, "首次：将 3D 光标位置和方向设为握位")
    box.operator("humanoid_mounts.prepare_grip")
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
    if settings.edit_target == "GRIP" and obj.parent is not None and obj.parent.get("hm_part") != settings.part:
        draw_message(box, "装备位于" + placement.part_name(obj.parent.get("hm_part")) + "，切回该位置后调整")
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


def draw_equipment_steps(layout, settings):
    state = placement.equipment_status(settings)
    is_fitting = settings.fitting_stage != "NONE"
    inputs = layout.column()
    inputs.enabled = not is_fitting
    inputs.label(text="1. 选择角色")
    inputs.prop(settings, "armature", text="角色")
    inputs.operator("humanoid_mounts.use_retarget_target", text="使用重定向角色")
    inputs.label(text="2. 选择装备")
    inputs.label(text=settings.equipment.name if settings.equipment is not None else "尚未选择装备")
    inputs.operator("humanoid_mounts.choose_equipment")
    inputs.label(text="3. 放到哪里")
    inputs.prop(settings, "part", text="位置")
    layout.separator()
    draw_message(layout, state.message)
    if is_fitting:
        draw_message(layout, "拖动场景红绿蓝圆环旋转武器")
        row = layout.row(align=True)
        local = row.operator("humanoid_mounts.fitting_tool", text="局部旋转", icon="DRIVER_ROTATIONAL_DIFFERENCE")
        local.tool = "ROTATE"
        local.orientation = "LOCAL"
        world = row.operator("humanoid_mounts.fitting_tool", text="世界旋转")
        world.tool = "ROTATE"
        world.orientation = "GLOBAL"
        move = row.operator("humanoid_mounts.fitting_tool", text="移动箭头", icon="ORIENTATION_LOCAL")
        move.tool = "MOVE"
        move.orientation = "LOCAL"
        row = layout.row(align=True)
        label = "保存角色握位" if settings.fitting_stage == "CHARACTER" else "记住当前拿法"
        row.operator("humanoid_mounts.fit_equipment", text=label).operation = "SAVE"
        row.operator("humanoid_mounts.fit_equipment", text="取消并恢复").operation = "CANCEL"
        return
    if state.step in {"FIT_CHARACTER", "FIT_EQUIPMENT"}:
        label = "设置角色握位..." if state.step == "FIT_CHARACTER" else "设置装备拿法..."
        operation = "CHARACTER" if state.step == "FIT_CHARACTER" else "EQUIPMENT"
        layout.operator("humanoid_mounts.fit_equipment", text=label).operation = operation
    else:
        row = layout.row()
        row.scale_y = 1.3
        row.enabled = state.step == "READY"
        part_name = next(label for value, label, description in PARTS if value == settings.part)
        row.operator("humanoid_mounts.equip_weapon", text="已放到" + part_name if state.step == "EQUIPPED" else "直接贴合到" + part_name)
    if state.step == "BLOCKED":
        draw_message(layout, "可在下方高级设置中处理")
        if len(mounts_for_armature(settings.armature, settings.part)) > 1:
            for mount in mounts_for_armature(settings.armature, settings.part):
                layout.operator("humanoid_mounts.use_mount", text=mount.name).name = mount.name
    if state.grip is not None and state.grip.get("hm_source_file") and state.step in {"READY", "EQUIPPED"}:
        row = layout.row()
        row.operator("humanoid_mounts.fit_equipment", text="调整角色握位（可选）...").operation = "CHARACTER"
    row = layout.row(align=True)
    row.enabled = state.step in {"READY", "EQUIPPED"} and (state.grip is None or not state.grip.get("hm_source_file") or state.step == "EQUIPPED")
    row.operator("humanoid_mounts.fit_equipment", text="调整位置...").operation = "EQUIPMENT"
    row = layout.row()
    grip = state.grip
    row.enabled = grip is not None and grip_object(settings, grip) and grip.parent is not None
    label = "从" + placement.part_name(grip.parent.get("hm_part")) + "取下" if row.enabled else "取下"
    row.operator("humanoid_mounts.detach_weapon", text=label).use_equipment = True


class HM_PT_mounts(Panel):
    bl_label = "人形挂载 v" + ".".join(str(number) for number in bl_info["version"])
    bl_idname = "HM_PT_mounts"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "人形挂载"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.hm_settings
        draw_equipment_steps(layout, settings)
        advanced = layout.column()
        advanced.enabled = settings.fitting_stage == "NONE"
        advanced.prop(settings, "show_advanced", toggle=True)
        if settings.show_advanced and settings.fitting_stage == "NONE":
            draw_character(advanced, settings)
            draw_weapon(advanced, settings)
            draw_mount_list(advanced, settings)
            draw_offset(advanced, settings)
            if settings.status:
                draw_message(advanced, "上次操作：" + settings.status)

        from .library_browser import draw_library
        draw_library(layout, context)


CLASSES = (HM_PT_mounts,)
