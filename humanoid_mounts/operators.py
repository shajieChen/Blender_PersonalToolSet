import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty
from bpy.types import Operator

from . import mounts, placement, weapons


def run_action(context, action, *, fitting=False):
    settings = context.scene.hm_settings
    try:
        if settings.fitting_stage != "NONE" and not fitting:
            raise mounts.HumanoidMountError("请先保存或取消当前设置")
        for window in context.window_manager.windows:
            for operator in window.modal_operators:
                if operator.bl_idname.startswith(("hr.", "spring_bone.", "HR_OT_", "SPRING_BONE_OT_")):
                    raise mounts.HumanoidMountError("请先结束重定向或动态骨骼作业")
        message = action(settings)
        settings.status = message
        return {"FINISHED"}
    except mounts.HumanoidMountError as error:
        settings.status = str(error)
        return {"CANCELLED"}


def selected_mount(settings):
    mount = settings.mount
    owner = mounts.mount_owner(mount)
    if owner != settings.armature or mount.get("hm_part") != settings.part:
        raise mounts.HumanoidMountError("请选择当前人形和部位所属的挂点")
    return mount


def selected_grip(settings):
    root = settings.grip
    weapons.validate_grip(root)
    if root.parent is not None and root.parent.parent != settings.armature:
        raise mounts.HumanoidMountError("武器属于另一人形，请先明确切换角色")
    return root


class HM_OT_use_armature(Operator):
    bl_idname = "humanoid_mounts.use_armature"
    bl_label = "使用当前人形骨架"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        if context.scene.hm_settings.fitting_stage != "NONE":
            self.report({"WARNING"}, "请先保存或取消当前设置")
            return {"CANCELLED"}
        obj = context.object
        if obj is None or obj.type != "ARMATURE":
            self.report({"ERROR"}, "请明确选择人形骨架")
            return {"CANCELLED"}
        context.scene.hm_settings.armature = obj
        context.scene.hm_settings.mount = None
        if context.active_pose_bone is not None:
            context.scene.hm_settings.bone_name = context.active_pose_bone.name
        return {"FINISHED"}


class HM_OT_use_retarget_target(Operator):
    bl_idname = "humanoid_mounts.use_retarget_target"
    bl_label = "使用重定向目标"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        def use(settings):
            retarget = getattr(context.scene, "hr_settings", None)
            target = getattr(retarget, "target", None)
            mounts.editable_object(target)
            if target.type != "ARMATURE":
                raise mounts.HumanoidMountError("重定向目标不是人形骨架")
            settings.armature = target
            settings.mount = None
            settings.bone_name = ""
            return "已选择重定向目标，选择武器后可直接装备"

        result = run_action(context, use)
        self.report({"INFO"} if result == {"FINISHED"} else {"WARNING"}, context.scene.hm_settings.status)
        return result


class HM_OT_equip_weapon(Operator):
    bl_idname = "humanoid_mounts.equip_weapon"
    bl_label = "装备到当前部位"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        def equip(settings):
            obj = context.object
            if settings.equipment is not None:
                state = placement.equipment_status(settings)
                if state.step not in {"READY", "EQUIPPED"}:
                    raise mounts.HumanoidMountError(state.message)
                root = state.grip
            else:
                root = weapons.grip_from_object(obj) if obj is not None and obj != settings.armature else selected_grip(settings)
            preferred = settings.mount
            if preferred is not None and (preferred.parent != settings.armature or preferred.get("hm_part") != settings.part):
                preferred = None
            previous = mounts.mounts_for_armature(settings.armature, settings.part)
            mount = weapons.equip_weapon(root, settings.armature, settings.part, preferred)
            settings.mount = mount
            settings.mount_name = mount.name
            settings.grip = root
            if root.get("hm_source_file"):
                return "已贴合 " + settings.armature.name + " / " + mount.name + "；局部位移为0，可选调整握位"
            return "已装备；新挂点位于骨骼原点，首次请校准握位" if mount not in previous else "已装备，复用现有挂点和握持校准"

        result = run_action(context, equip)
        self.report({"INFO"} if result == {"FINISHED"} else {"WARNING"}, context.scene.hm_settings.status)
        return result


class HM_OT_choose_equipment(Operator):
    bl_idname = "humanoid_mounts.choose_equipment"
    bl_label = "使用选中的物体"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        def choose(settings):
            placement.select_equipment(settings, tuple(context.selected_objects), context.object)
            return "已选择装备，角色保持不变"

        result = run_action(context, choose)
        self.report({"INFO"} if result == {"FINISHED"} else {"WARNING"}, context.scene.hm_settings.status)
        return result


def activate_fitting_tool(context, tool="ROTATE", orientation="LOCAL"):
    window = context.window
    if window is None:
        raise mounts.HumanoidMountError("请在3D视图中调整握位")
    area = context.area if context.area is not None and context.area.type == "VIEW_3D" else next((area for area in window.screen.areas if area.type == "VIEW_3D"), None)
    if area is None:
        raise mounts.HumanoidMountError("请先打开3D视图")
    region = next(region for region in area.regions if region.type == "WINDOW")
    name = {"ROTATE": "builtin.rotate", "MOVE": "builtin.move"}[tool]
    try:
        with context.temp_override(window=window, area=area, region=region):
            result = bpy.ops.wm.tool_set_by_id(name=name)
    except RuntimeError as error:
        raise mounts.HumanoidMountError("无法启用场景调整工具：" + str(error)) from error
    if result != {"FINISHED"}:
        raise mounts.HumanoidMountError("场景调整工具未启用")
    area.spaces.active.show_gizmo = True
    area.spaces.active.show_gizmo_tool = True
    context.scene.transform_orientation_slots[0].type = orientation
    context.scene.tool_settings.transform_pivot_point = "ACTIVE_ELEMENT"
    area.tag_redraw()


class HM_OT_fit_equipment(Operator):
    bl_idname = "humanoid_mounts.fit_equipment"
    bl_label = "设置装备位置"
    bl_options = {"REGISTER", "UNDO"}
    operation: EnumProperty(items=(("CHARACTER", "设置角色握位", ""), ("EQUIPMENT", "设置装备拿法", ""), ("SAVE", "保存", ""), ("CANCEL", "取消", "")))

    def execute(self, context):
        def fit(settings):
            if self.operation == "CANCEL":
                placement.cancel_fitting(settings)
                return "已取消，进入设置前的位置已恢复"
            if self.operation == "SAVE":
                placement.save_fitting(settings)
                return "已保存，今后可以直接复用"
            placement.begin_fitting(settings, self.operation)
            try:
                activate_fitting_tool(context)
            except mounts.HumanoidMountError:
                placement.cancel_fitting(settings)
                raise
            return "拖动场景中的彩色圆环旋转，完成后保存，也可取消恢复"

        result = run_action(context, fit, fitting=True)
        self.report({"INFO"} if result == {"FINISHED"} else {"WARNING"}, context.scene.hm_settings.status)
        return result


class HM_OT_fitting_tool(Operator):
    bl_idname = "humanoid_mounts.fitting_tool"
    bl_label = "显示握位调整工具"
    tool: EnumProperty(items=(("ROTATE", "旋转圆环", ""), ("MOVE", "移动箭头", "")))
    orientation: EnumProperty(items=(("LOCAL", "局部", ""), ("GLOBAL", "世界", "")))

    def execute(self, context):
        def show(settings):
            if settings.fitting_stage == "NONE":
                raise mounts.HumanoidMountError("请先点击调整角色握位或调整位置")
            objects = tuple(item.object for item in settings.fitting_objects)
            for obj in objects:
                mounts.editable_object(obj)
                if not obj.visible_get() or obj.hide_select:
                    raise mounts.HumanoidMountError("调整对象已隐藏或禁止选择")
            if not objects:
                raise mounts.HumanoidMountError("调整对象已失效，请取消后重试")
            for obj in tuple(context.selected_objects):
                obj.select_set(False)
            for obj in objects:
                obj.select_set(True)
            context.view_layer.objects.active = objects[0]
            activate_fitting_tool(context, self.tool, self.orientation)
            return "拖动彩色圆环旋转" if self.tool == "ROTATE" else "拖动箭头移动"

        result = run_action(context, show, fitting=True)
        self.report({"INFO"} if result == {"FINISHED"} else {"WARNING"}, context.scene.hm_settings.status)
        return result


class HM_OT_create_mount(Operator):
    bl_idname = "humanoid_mounts.create_mount"
    bl_label = "从实际骨骼创建挂点"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        def create(settings):
            settings.mount = mounts.create_mount(settings.armature, settings.bone_name, settings.part)
            settings.mount_name = settings.mount.name
            return "已创建挂点，请校准掌心或装备位置"

        return run_action(context, create)


class HM_OT_prepare_grip(Operator):
    bl_idname = "humanoid_mounts.prepare_grip"
    bl_label = "从选中部件创建握持根"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        parts = tuple(context.selected_objects)
        anchor = context.scene.cursor.matrix.copy()

        def prepare(settings):
            settings.grip = weapons.prepare_grip_root(parts, anchor)
            return "握持根位于 3D 光标，武器部件位置已保留"

        return run_action(context, prepare)


class HM_OT_bind_weapon(Operator):
    bl_idname = "humanoid_mounts.bind_weapon"
    bl_label = "绑定武器"
    bl_options = {"REGISTER", "UNDO"}
    rule: EnumProperty(items=(("SNAP", "吸附", ""), ("KEEP_WORLD", "保持位置", "")))

    def execute(self, context):
        def bind(settings):
            weapons.bind_weapon(selected_grip(settings), selected_mount(settings), self.rule)
            return "已吸附到挂点" if self.rule == "SNAP" else "已绑定并保持当前位置"

        return run_action(context, bind)


class HM_OT_detach_weapon(Operator):
    bl_idname = "humanoid_mounts.detach_weapon"
    bl_label = "解除并保持位置"
    bl_options = {"REGISTER", "UNDO"}
    use_equipment: BoolProperty(default=False, options={"HIDDEN"})

    def execute(self, context):
        def detach(settings):
            root = weapons.grip_from_object(settings.equipment) if self.use_equipment else selected_grip(settings)
            if root.parent is not None and mounts.mount_owner(root.parent) != settings.armature:
                raise mounts.HumanoidMountError("装备属于另一角色，请先选择正确角色")
            weapons.detach_weapon(root)
            return "已解除，保留当前世界姿势"

        result = run_action(context, detach)
        self.report({"INFO"} if result == {"FINISHED"} else {"WARNING"}, context.scene.hm_settings.status)
        return result


class HM_OT_edit_mount(Operator):
    bl_idname = "humanoid_mounts.edit_mount"
    bl_label = "编辑人形挂点"
    bl_options = {"REGISTER", "UNDO"}
    operation: EnumProperty(items=(("COPY", "复制", "不复制附件"), ("RENAME", "改名", ""), ("REANCHOR", "换骨骼", "保持世界姿势"), ("DELETE", "删除挂点", "保留所有附件")))

    def execute(self, context):
        def edit(settings):
            mount = selected_mount(settings)
            if self.operation == "COPY":
                settings.mount = mounts.copy_mount(mount)
                settings.mount_name = settings.mount.name
                return "已复制挂点，未复制附件"
            if self.operation == "RENAME":
                settings.mount_name = mounts.rename_mount(mount, settings.mount_name)
                return "已修改挂点名称"
            if self.operation == "REANCHOR":
                mounts.reanchor_mount(mount, settings.bone_name)
                return "已换骨骼并保持世界姿势"
            mounts.delete_mount(mount)
            settings.mount = None
            return "已删除挂点，所有附件保留并解除"

        return run_action(context, edit)


class HM_OT_use_mount(Operator):
    bl_idname = "humanoid_mounts.use_mount"
    bl_label = "使用当前挂点"
    bl_options = {"REGISTER", "UNDO"}
    name: StringProperty()

    def execute(self, context):
        def use(settings):
            mount = bpy.data.objects.get(self.name) if self.name else context.object
            owner = mounts.mount_owner(mount)
            if self.name and (owner != settings.armature or mount.get("hm_part") != settings.part):
                raise mounts.HumanoidMountError("安装位置已改变，请重新选择")
            settings.armature = owner
            settings.part = mount["hm_part"]
            settings.mount = mount
            settings.mount_name = mount.name
            settings.bone_name = mount.parent_bone
            return "已选择该挂点所属的人形和部位"

        result = run_action(context, use)
        self.report({"INFO"} if result == {"FINISHED"} else {"WARNING"}, context.scene.hm_settings.status)
        return result


class HM_OT_use_bone(Operator):
    bl_idname = "humanoid_mounts.use_bone"
    bl_label = "取当前骨骼"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        def use(settings):
            if context.object != settings.armature or context.active_pose_bone is None:
                raise mounts.HumanoidMountError("请在当前人形 Pose Mode 中选择实际骨骼")
            settings.bone_name = context.active_pose_bone.name
            return "已读取当前实际骨骼"

        return run_action(context, use)


class HM_OT_use_grip(Operator):
    bl_idname = "humanoid_mounts.use_grip"
    bl_label = "取当前握持根"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        def use(settings):
            weapons.validate_grip(context.object)
            if context.object.parent is not None and context.object.parent.parent != settings.armature:
                raise mounts.HumanoidMountError("握持根属于另一人形，请先切换角色")
            settings.grip = context.object
            return "已选择武器根，人形选择保持不变"

        return run_action(context, use)


class HM_OT_register_grip(Operator):
    bl_idname = "humanoid_mounts.register_grip"
    bl_label = "登记当前 Empty 为握持根"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        def register(settings):
            weapons.register_grip_root(context.object)
            settings.grip = context.object
            return "已显式登记握持根"

        return run_action(context, register)


class HM_OT_select_edit_target(Operator):
    bl_idname = "humanoid_mounts.select_edit_target"
    bl_label = "选中并编辑"

    def execute(self, context):
        def select(settings):
            obj = selected_mount(settings) if settings.edit_target == "MOUNT" else selected_grip(settings)
            mounts.editable_object(obj)
            if context.object is not None and context.object.mode != "OBJECT":
                raise mounts.HumanoidMountError("请先退出 Pose/Edit Mode 再编辑 Empty")
            if not obj.visible_get():
                raise mounts.HumanoidMountError("目标不可见，请先在 Outliner 中显示")
            if obj.hide_select:
                raise mounts.HumanoidMountError("目标禁止选择，请先在 Outliner 中解除")
            for selected in tuple(context.selected_objects):
                selected.select_set(False)
            obj.select_set(True)
            context.view_layer.objects.active = obj
            return "使用 Blender 原生变换控件调整偏移"

        return run_action(context, select)


class HM_OT_reset_offset(Operator):
    bl_idname = "humanoid_mounts.reset_offset"
    bl_label = "重置当前偏移"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        def reset(settings):
            if settings.edit_target == "MOUNT":
                mounts.reset_mount(selected_mount(settings))
                return "已回到骨骼原点，请重新校准掌心"
            root = selected_grip(settings)
            if root.parent != selected_mount(settings):
                raise mounts.HumanoidMountError("道具未绑定在当前挂点")
            weapons.bind_weapon(root, root.parent, "SNAP")
            return "已重置道具相对挂点的偏移"

        return run_action(context, reset)


CLASSES = (HM_OT_choose_equipment, HM_OT_fit_equipment, HM_OT_fitting_tool, HM_OT_use_armature, HM_OT_use_retarget_target, HM_OT_equip_weapon, HM_OT_create_mount, HM_OT_prepare_grip, HM_OT_bind_weapon, HM_OT_detach_weapon, HM_OT_edit_mount, HM_OT_use_mount, HM_OT_use_bone, HM_OT_use_grip, HM_OT_register_grip, HM_OT_select_edit_target, HM_OT_reset_offset)
