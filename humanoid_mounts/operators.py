import bpy
from bpy.props import EnumProperty
from bpy.types import Operator

from . import mounts, weapons


def run_action(context, action):
    settings = context.scene.hm_settings
    try:
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
        obj = context.object
        if obj is None or obj.type != "ARMATURE":
            self.report({"ERROR"}, "请明确选择人形骨架")
            return {"CANCELLED"}
        context.scene.hm_settings.armature = obj
        context.scene.hm_settings.mount = None
        if context.active_pose_bone is not None:
            context.scene.hm_settings.bone_name = context.active_pose_bone.name
        return {"FINISHED"}


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

    def execute(self, context):
        def detach(settings):
            weapons.detach_weapon(selected_grip(settings))
            return "已解除，保留当前世界姿势"

        return run_action(context, detach)


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

    def execute(self, context):
        def use(settings):
            mount = context.object
            owner = mounts.mount_owner(mount)
            settings.armature = owner
            settings.part = mount["hm_part"]
            settings.mount = mount
            settings.mount_name = mount.name
            settings.bone_name = mount.parent_bone
            return "已选择该挂点所属的人形和部位"

        return run_action(context, use)


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


CLASSES = (HM_OT_use_armature, HM_OT_create_mount, HM_OT_prepare_grip, HM_OT_bind_weapon, HM_OT_detach_weapon, HM_OT_edit_mount, HM_OT_use_mount, HM_OT_use_bone, HM_OT_use_grip, HM_OT_register_grip, HM_OT_select_edit_target, HM_OT_reset_offset)
