bl_info = {
    "name": "Character Locomotion v1.0.1",
    "author": "Blender Plugin",
    "version": (1, 0, 1),
    "blender": (5, 1, 0),
    "location": "View3D > Sidebar > 角色操控",
    "description": "方向键走、Shift 跑与可复用角色动画库",
    "category": "Animation",
}

import bpy
import unicodedata
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, FloatProperty, PointerProperty, StringProperty
from bpy.types import AddonPreferences, Operator, Panel, UIList
from bpy_extras.io_utils import ExportHelper, ImportHelper

from . import animation_library, locomotion


def character_changed(self, context):
    locomotion.stop_session()
    if self.cl_character:
        animation_library.refresh_compatibility(self.cl_character, self)


def editable_rig(context):
    rig = context.scene.cl_character
    if locomotion.active_session():
        raise ValueError("请先停止预览或操控")
    if not rig or rig.library or rig.override_library:
        raise ValueError("请选择本地可编辑角色")
    return rig


def preferences(context):
    addon = context.preferences.addons.get(__package__)
    return addon.preferences if addon else None


def draw_notice(layout, text, context):
    limit = max(18, int(context.region.width / (7 * context.preferences.system.ui_scale)))
    line = ""
    width = 0
    for character in text:
        size = 2 if unicodedata.east_asian_width(character) in {"W", "F"} else 1
        if width + size > limit:
            layout.label(text=line)
            line = ""
            width = 0
        line += character
        width += size
    if line:
        layout.label(text=line)


class CL_Preferences(AddonPreferences):
    bl_idname = __package__
    last_directory: StringProperty(subtype="DIR_PATH")

    def draw(self, context):
        self.layout.label(text="在 3D 视口 N 侧栏打开角色操控")


class CL_OT_use_selection(Operator):
    bl_idname = "character_locomotion.use_selection"
    bl_label = "使用当前选中角色"
    bl_options = {"UNDO"}

    def execute(self, context):
        try:
            locomotion.stop_session()
            rig = locomotion.resolve_character(context.active_object)
            if context.scene.objects.get(rig.name) != rig:
                raise ValueError("骨架不在当前场景")
            context.scene.cl_character = rig
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


def clip_choices(self, context):
    return getattr(self, "_items", [("CLEAR", "清空绑定", "保留库条目，停止自动回填")])


class CL_OT_bind(Operator):
    bl_idname = "character_locomotion.bind"
    bl_label = "选择兼容动画"
    bl_property = "choice"
    bl_options = {"UNDO"}
    role: EnumProperty(items=animation_library.KINDS)
    choice: EnumProperty(items=clip_choices)

    def invoke(self, context, event):
        try:
            rig = editable_rig(context)
            animation_library.refresh_compatibility(rig, context.scene)
            self._items = [(clip.clip_id, clip.name, animation_library.ROLE_LABELS[clip.kind]) for clip in rig.cl_clips if clip.kind == self.role and clip.compatible]
            self._items.append(("CLEAR", "清空绑定", "保留库条目，停止自动回填"))
            context.window_manager.invoke_search_popup(self)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"RUNNING_MODAL"}

    def execute(self, context):
        try:
            rig = editable_rig(context)
            identifier = "" if self.choice == "CLEAR" else self.choice
            if identifier and animation_library.find_clip(rig, identifier) is None:
                raise ValueError("片段已被移除，请重新选择")
            setattr(rig.cl_settings, self.role.lower() + "_id", identifier)
            rig.cl_settings.message = "已设置绑定，开始时将重新检查"
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


def candidate_changed(self, context):
    action = bpy.data.actions.get(self.action_name)
    if action:
        self.start, self.end = action.frame_range
        self.period = self.end - self.start
    self._slot_items = None


def candidate_slots(self, context):
    if getattr(self, "_slot_items", None) is None:
        action = bpy.data.actions.get(self.action_name)
        self._slot_items = [("AUTO", "单槽自动；多槽请明确选择", "")]
        if action:
            self._slot_items.extend((slot.identifier, slot.name_display, slot.identifier) for slot in action.slots if slot.target_id_type == "OBJECT")
    return self._slot_items


class CL_OT_add_clip(Operator):
    bl_idname = "character_locomotion.add_clip"
    bl_label = "从当前文件登记动画"
    bl_options = {"UNDO"}
    action_name: StringProperty(name="当前文件动画", update=candidate_changed)
    role: EnumProperty(name="用途", items=animation_library.KINDS)
    slot: EnumProperty(name="骨架槽位", items=candidate_slots)
    fps: FloatProperty(name="素材帧率", min=0.01, default=30)
    start: FloatProperty(name="起始帧", default=1)
    end: FloatProperty(name="结束帧", default=21)
    period: FloatProperty(name="循环帧数", default=20, min=0.01)
    confirmed: BoolProperty(name="已核对素材帧率及循环范围", default=False)

    def invoke(self, context, event):
        if locomotion.active_session():
            return {"CANCELLED"}
        self.fps = context.scene.render.fps / context.scene.render.fps_base
        return context.window_manager.invoke_props_dialog(self, width=380)

    def draw(self, context):
        layout = self.layout
        layout.prop_search(self, "action_name", bpy.data, "actions")
        layout.prop(self, "role")
        layout.prop(self, "slot")
        layout.label(text="暂用场景帧率，请按素材实际值核对")
        for field in ("fps", "start", "end", "period", "confirmed"):
            layout.prop(self, field)

    def execute(self, context):
        rig = None
        clip = None
        try:
            rig = editable_rig(context)
            action = bpy.data.actions.get(self.action_name)
            if not action:
                raise ValueError("请先选择当前文件中的动画")
            if not self.confirmed:
                raise ValueError("请核对并勾选素材帧率及循环范围")
            clip = animation_library.add_clip(rig, context.scene, action, self.role, "" if self.slot == "AUTO" else self.slot)
            clip.start, clip.end, clip.period = self.start, self.end, self.period
            clip.fps = self.fps
            clip.fps_source = "用户核对"
            clip.confirmed = True
            animation_library.validate_clip(clip, rig, context.scene)
            if self.role in animation_library.ROLES:
                setattr(rig.cl_settings, self.role.lower() + "_id", clip.clip_id)
            rig.cl_settings.message = "动画已登记，可以原地预览"
        except Exception as exc:
            if rig and clip:
                rig.cl_clips.remove(len(rig.cl_clips) - 1)
            if rig:
                rig.cl_settings.message = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CL_OT_remove_clip(Operator):
    bl_idname = "character_locomotion.remove_clip"
    bl_label = "移除库条目"
    bl_description = "只移除库条目，保留原始动画"
    bl_options = {"UNDO"}

    def execute(self, context):
        try:
            rig = editable_rig(context)
            index = rig.cl_settings.index
            if not 0 <= index < len(rig.cl_clips):
                raise ValueError("请选择库条目")
            rig.cl_clips.remove(index)
            rig.cl_settings.index = max(0, min(index, len(rig.cl_clips) - 1))
            rig.cl_settings.message = "库条目已移除，原始动画已保留"
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CL_OT_choose_slot(Operator):
    bl_idname = "character_locomotion.choose_slot"
    bl_label = "选择骨架槽位"
    bl_property = "choice"
    bl_options = {"UNDO"}
    choice: EnumProperty(items=clip_choices)
    source: BoolProperty(default=False)

    def invoke(self, context, event):
        try:
            rig = editable_rig(context)
            clip = rig.cl_clips[rig.cl_settings.index]
            action = clip.source_action if self.source else clip.action
            if action is None:
                raise ValueError("请先选择动画")
            self._items = [(slot.identifier, slot.name_display, slot.identifier) for slot in action.slots if slot.target_id_type == "OBJECT"]
            if not self._items:
                raise ValueError("这个动画没有可选骨架槽位")
            context.window_manager.invoke_search_popup(self)
            return {"RUNNING_MODAL"}
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

    def execute(self, context):
        try:
            rig = editable_rig(context)
            clip = rig.cl_clips[rig.cl_settings.index]
            setattr(clip, "source_slot" if self.source else "slot_id", self.choice)
            rig.cl_settings.message = "槽位已更改，开始前将重新检查"
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CL_OT_save_library(Operator, ExportHelper):
    bl_idname = "character_locomotion.save_library"
    bl_label = "保存当前角色动画库"
    filename_ext = ".blend"
    filter_glob: StringProperty(default="*.blend", options={"HIDDEN"})
    overwrite: BoolProperty(name="允许覆盖已有动画库", default=False)

    def invoke(self, context, event):
        prefs = preferences(context)
        if prefs and prefs.last_directory:
            self.filepath = bpy.path.ensure_ext(prefs.last_directory + "character_animations", ".blend")
        return ExportHelper.invoke(self, context, event)

    def draw(self, context):
        rig = context.scene.cl_character
        if rig:
            included = sum(clip.compatible for clip in rig.cl_clips)
            self.layout.label(text=f"包含 {included} 个；排除 {len(rig.cl_clips) - included} 个需重定向片段")
        self.layout.prop(self, "overwrite")

    def execute(self, context):
        try:
            rig = editable_rig(context)
            included, excluded = animation_library.save_library(rig, context.scene, self.filepath, self.overwrite)
            rig.cl_settings.message = f"已保存 {included} 个片段，{excluded} 个未导出片段仍保留在工程中"
            prefs = preferences(context)
            if prefs:
                prefs.last_directory = str(animation_library.resolve_path(self.filepath).parent) + "/"
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CL_OT_load_library(Operator, ImportHelper):
    bl_idname = "character_locomotion.load_library"
    bl_label = "载入动画库"
    bl_options = {"UNDO"}
    filter_glob: StringProperty(default="*.blend", options={"HIDDEN"})

    def invoke(self, context, event):
        prefs = preferences(context)
        if prefs and prefs.last_directory:
            self.filepath = prefs.last_directory
        return ImportHelper.invoke(self, context, event)

    def execute(self, context):
        try:
            rig = editable_rig(context)
            added = animation_library.load_library(rig, context.scene, self.filepath)
            rig.cl_settings.message = f"已载入 {added} 个片段，请检查三行绑定"
            prefs = preferences(context)
            if prefs:
                prefs.last_directory = str(animation_library.resolve_path(self.filepath).parent) + "/"
        except Exception as exc:
            if context.scene.cl_character:
                context.scene.cl_character.cl_settings.message = "载入失败，原配置保留：" + str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class CL_OT_control(Operator):
    bl_idname = "character_locomotion.control"
    bl_label = "检查并开始操控"
    bl_description = "检查动画后接管当前视口，方向键走、Shift 跑，Esc 停止并恢复"
    bl_options = {"BLOCKING"}
    preview_id: StringProperty(options={"HIDDEN", "SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        if context.area is None or context.area.type != "VIEW_3D" or context.scene.cl_character is None:
            cls.poll_message_set("请在 3D 视口指定角色")
            return False
        return True

    def invoke(self, context, event):
        existing = locomotion.active_session()
        if existing:
            if existing.preview_id:
                existing.close()
            else:
                self.report({"WARNING"}, "请先停止当前操控")
                return {"CANCELLED"}
        self.session = locomotion.LocomotionSession(context, self.preview_id)
        try:
            self.session.begin(context)
            context.window_manager.modal_handler_add(self)
            return {"RUNNING_MODAL"}
        except Exception as exc:
            self.session.close(str(exc))
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

    def modal(self, context, event):
        try:
            return self.session.event(event)
        except Exception as exc:
            self.session.close(str(exc))
            self.report({"WARNING"}, str(exc))
            return {"CANCELLED"}

    def cancel(self, context):
        self.session.close()


class CL_OT_stop(Operator):
    bl_idname = "character_locomotion.stop"
    bl_label = "停止并恢复"

    def execute(self, context):
        locomotion.stop_session()
        return {"FINISHED"}


class CL_OT_prepare_help(Operator):
    bl_idname = "character_locomotion.prepare_help"
    bl_label = "如何准备动画？"

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=380)

    def draw(self, context):
        for text in ("1. 启用 Humanoid Retarget，打开重定向侧栏", "2. 导入含动画的模型，选择目标骨架", "3. 根运动选择原地，再重定向到当前目标", "4. 回到角色操控，按用途登记结果动画", "无需重新导入已准备好的兼容动画库"):
            self.layout.label(text=text)


class CL_UL_clips(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        layout.label(text=item.name, icon="ACTION" if item.compatible else "ERROR")
        layout.label(text=animation_library.ROLE_LABELS[item.kind] if item.compatible else "需重定向")

    def filter_items(self, context, data, property):
        clips = getattr(data, property)
        flags = bpy.types.UI_UL_list.filter_items_by_name(self.filter_name, self.bitflag_filter_item, clips, "name") if self.filter_name else [self.bitflag_filter_item] * len(clips)
        settings = data.cl_settings
        for index, clip in enumerate(clips):
            if (not settings.show_incompatible and not clip.compatible) or (settings.filter_kind != "ALL" and clip.kind != settings.filter_kind):
                flags[index] = 0
        return flags, []


class CL_PT_character(Panel):
    bl_label = "角色操控 v" + ".".join(map(str, bl_info["version"]))
    bl_idname = "CL_PT_character"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "角色操控"

    def draw(self, context):
        layout = self.layout
        session = locomotion.active_session()
        if session:
            layout.label(text=session.status)
            layout.operator("character_locomotion.stop", icon="CANCEL")
            layout.label(text="将鼠标移入视口后按方向键")
            layout.label(text="方向键走 / Shift 跑 / Esc 停止")
            return
        layout.label(text="1 选择角色")
        layout.operator("character_locomotion.use_selection")
        layout.prop(context.scene, "cl_character", text="角色骨架")
        rig = context.scene.cl_character
        if not rig:
            layout.label(text="先选一个角色骨架或蒙皮网格", icon="INFO")
            return
        layout.label(text="2 准备动画")
        layout.operator("character_locomotion.load_library", icon="FILE_FOLDER")
        for role in animation_library.ROLES:
            clip = animation_library.find_clip(rig, getattr(rig.cl_settings, role.lower() + "_id"))
            row = layout.row(align=True)
            row.label(text=animation_library.ROLE_LABELS[role])
            operator = row.operator("character_locomotion.bind", text=clip.name if clip else "选择库片段")
            operator.role = role
            operator = row.operator("character_locomotion.add_clip", text="", icon="ADD")
            operator.role = role
            column = row.row(align=True)
            column.enabled = clip is not None
            operator = column.operator("character_locomotion.control", text="", icon="PLAY")
            operator.preview_id = clip.clip_id if clip else ""
        layout.operator("character_locomotion.prepare_help")
        reason = locomotion.readiness(rig)
        layout.label(text="3 开始操控")
        if reason:
            draw_notice(layout, reason, context)
        column = layout.column()
        column.enabled = not reason
        column.operator("character_locomotion.control", icon="PLAY")
        draw_notice(layout, rig.cl_settings.message, context)
        repair = animation_library.find_clip(rig, rig.cl_settings.repair_clip_id)
        if repair:
            box = layout.box()
            draw_notice(box, "修正片段：" + repair.name, context)
            if "帧率" in rig.cl_settings.message or "循环" in rig.cl_settings.message:
                for field in ("fps", "period", "confirmed"):
                    box.prop(repair, field)
            elif "槽位" in rig.cl_settings.message:
                box.label(text="在高级设置选择对应骨架槽位")
            else:
                box.operator("character_locomotion.prepare_help", text="查看原地动画准备步骤")
        layout.label(text="方向键走 / Shift 跑 / Esc 停止")
        layout.label(text="预览不录制，停止回到开始位置")


class CL_PT_library(Panel):
    bl_label = "动画库管理"
    bl_idname = "CL_PT_library"
    bl_parent_id = "CL_PT_character"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "角色操控"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return context.scene.cl_character is not None and locomotion.active_session() is None

    def draw(self, context):
        rig = context.scene.cl_character
        settings = rig.cl_settings
        layout = self.layout
        layout.prop(settings, "filter_kind")
        layout.prop(settings, "show_incompatible")
        other = sum(not clip.compatible for clip in rig.cl_clips)
        layout.label(text=f"共 {len(rig.cl_clips)} 个片段，{other} 个需重定向")
        layout.template_list("CL_UL_clips", "", rig, "cl_clips", settings, "index", rows=4)
        layout.operator("character_locomotion.remove_clip", icon="REMOVE")
        layout.operator("character_locomotion.save_library", icon="FILE_TICK")


class CL_PT_settings(Panel):
    bl_label = "高级设置 / 面向不对？"
    bl_idname = "CL_PT_settings"
    bl_parent_id = "CL_PT_character"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "角色操控"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return CL_PT_library.poll(context)

    def draw(self, context):
        rig = context.scene.cl_character
        settings = rig.cl_settings
        layout = self.layout
        for field in ("walk_speed", "run_speed", "forward", "blend"):
            layout.prop(settings, field)
        if 0 <= settings.index < len(rig.cl_clips):
            clip = rig.cl_clips[settings.index]
            layout.label(text="所选库片段")
            layout.prop(clip, "name", text="名称")
            layout.prop(clip, "kind")
            layout.prop(clip, "action", text="播放动画")
            layout.operator("character_locomotion.choose_slot", text="选择播放骨架槽位").source = False
            layout.prop(clip, "source_action", text="原始动画 (MM)")
            layout.operator("character_locomotion.choose_slot", text="选择原始动画槽位").source = True
            for field in ("start", "end", "fps", "period", "loop", "speed", "confirmed", "source_path"):
                layout.prop(clip, field)


@persistent
def stop_before_change(*args):
    locomotion.stop_session()


CLASSES = (CL_Preferences, CL_OT_use_selection, CL_OT_bind, CL_OT_add_clip, CL_OT_remove_clip, CL_OT_choose_slot, CL_OT_save_library, CL_OT_load_library, CL_OT_control, CL_OT_stop, CL_OT_prepare_help, CL_UL_clips, CL_PT_character, CL_PT_library, CL_PT_settings)
HANDLERS = (bpy.app.handlers.load_pre, bpy.app.handlers.save_pre, bpy.app.handlers.undo_pre, bpy.app.handlers.redo_pre)


def register():
    for cls in animation_library.CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Object.cl_clips = CollectionProperty(type=animation_library.CL_Clip)
    bpy.types.Object.cl_settings = PointerProperty(type=animation_library.CL_Settings)
    bpy.types.Scene.cl_character = PointerProperty(type=bpy.types.Object, poll=lambda self, obj: obj.type == "ARMATURE", update=character_changed)
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    for handlers in HANDLERS:
        if stop_before_change not in handlers:
            handlers.append(stop_before_change)


def unregister():
    locomotion.stop_session()
    for handlers in HANDLERS:
        if stop_before_change in handlers:
            handlers.remove(stop_before_change)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.cl_character
    del bpy.types.Object.cl_settings
    del bpy.types.Object.cl_clips
    for cls in reversed(animation_library.CLASSES):
        bpy.utils.unregister_class(cls)
