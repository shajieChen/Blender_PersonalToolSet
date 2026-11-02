import json
import os
from pathlib import Path

import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, IntProperty, StringProperty
from bpy.types import Operator, PropertyGroup, UIList

from . import bone_roles, equipment_orientation, library, mounts, placement


def settings_file():
    return Path(bpy.utils.user_resource("CONFIG")) / "humanoid_mounts_library.json"


def remembered_directory():
    try:
        return json.loads(settings_file().read_text(encoding="utf-8"))["directory"]
    except (OSError, ValueError, KeyError, TypeError):
        return "H:/SErsiko_ExtactedTool"


def directory_changed(self, context):
    self.items.clear()
    self.base = ""
    self.message = "目录已更改，请刷新道具列表"


class EquipmentLibraryEntry(PropertyGroup):
    relative_path: StringProperty()
    tier: StringProperty()


class EquipmentLibraryState(PropertyGroup):
    orientation: EnumProperty(name="朝向预设", items=equipment_orientation.PRESETS, default="AUTO")
    is_expanded: BoolProperty(name="外部道具库", default=True)
    directory: StringProperty(name="外部资源目录", subtype="DIR_PATH", default=remembered_directory(), update=directory_changed)
    base: StringProperty()
    items: CollectionProperty(type=EquipmentLibraryEntry)
    index: IntProperty(default=0)
    search: StringProperty(name="搜索", options={"TEXTEDIT_UPDATE"})
    tier: EnumProperty(name="分类", items=(("ALL", "全部", ""), ("std", "标准", ""), ("lod", "低模", ""), ("menu", "菜单", "")), default="std")
    message: StringProperty()


def refresh(state):
    directory = Path(bpy.path.abspath(state.directory)).resolve()
    base, rows = library.scan_library(directory)
    previous = state.items[state.index].relative_path if 0 <= state.index < len(state.items) else ""
    state.items.clear()
    state.base = str(base)
    for item in rows:
        entry = state.items.add()
        entry.name, entry.relative_path, entry.tier = item
    state.index = next((index for index, item in enumerate(state.items) if item.relative_path == previous), 0)
    state.message = "共 " + str(len(rows)) + " 个道具；可按名称或文件名搜索"
    target = settings_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps({"directory": str(directory)}, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, target)


class HM_OT_library_refresh(Operator):
    bl_idname = "humanoid_mounts.library_refresh"
    bl_label = "刷新并记住目录"

    def execute(self, context):
        state = context.window_manager.hm_library
        try:
            refresh(state)
            return {"FINISHED"}
        except (OSError, ValueError, SyntaxError, TypeError) as error:
            state.items.clear()
            state.base = ""
            state.message = str(error)
            self.report({"WARNING"}, state.message)
            return {"CANCELLED"}


class HM_OT_library_directory(Operator):
    bl_idname = "humanoid_mounts.library_directory"
    bl_label = "选择道具库目录"
    directory: StringProperty(subtype="DIR_PATH")
    filter_folder: BoolProperty(default=True, options={"HIDDEN"})

    def invoke(self, context, event):
        self.directory = context.window_manager.hm_library.directory
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        context.window_manager.hm_library.directory = self.directory
        return bpy.ops.humanoid_mounts.library_refresh()


class HM_OT_library_load(Operator):
    bl_idname = "humanoid_mounts.library_load"
    bl_label = "载入道具"
    bl_options = {"REGISTER", "UNDO"}
    attach: BoolProperty(default=False)

    def execute(self, context):
        from .operators import run_action

        def load(settings):
            state = context.window_manager.hm_library
            if not 0 <= state.index < len(state.items):
                raise ValueError("请先选择库中的道具")
            if not entry_visible(state, state.items[state.index]):
                raise ValueError("请在筛选结果中重新选择道具")
            root = library.load_equipment(context, state.base, state.items[state.index].relative_path, attach=self.attach, orientation=state.orientation)
            if self.attach:
                mount = settings.mount
                return "已绑定到" + settings.armature.name + " / " + mount.name + "；按模型原点对齐，首次请校准握位"
            return "已载入场景，尚未挂载；已设为当前装备"

        try:
            result = run_action(context, load)
        except Exception as error:
            self.report({"WARNING"}, "载入失败：" + str(error))
            return {"CANCELLED"}
        self.report({"INFO"} if result == {"FINISHED"} else {"WARNING"}, context.scene.hm_settings.status)
        return result



class HM_OT_library_orientation(Operator):
    bl_idname = "humanoid_mounts.library_orientation"
    bl_label = "应用道具朝向"
    bl_options = {"REGISTER", "UNDO"}
    save: BoolProperty(default=False)

    def execute(self, context):
        from .operators import run_action

        def orient(settings):
            root = settings.equipment
            if root is None:
                raise mounts.HumanoidMountError("请先从库载入道具")
            if root.parent is not None and (root.parent.parent != settings.armature or root.parent.get("hm_part") != settings.part):
                raise mounts.HumanoidMountError("请切回当前道具所属角色和部位")
            if self.save:
                equipment_orientation.save_orientation(root, settings.part)
                return "已记住这件道具在当前部位的朝向，下次自动使用"
            equipment_orientation.apply_preset(root, context.window_manager.hm_library.orientation, settings.part)
            return "已应用朝向，握位和位置保持原校准"

        try:
            result = run_action(context, orient)
        except (OSError, ValueError, TypeError) as error:
            self.report({"WARNING"}, str(error))
            return {"CANCELLED"}
        self.report({"INFO"} if result == {"FINISHED"} else {"WARNING"}, context.scene.hm_settings.status)
        return result


class HM_OT_library_clear(Operator):
    bl_idname = "humanoid_mounts.library_clear"
    bl_label = "清空当前角色全部挂载"
    bl_description = "删除当前角色所有挂载道具及本插件为该角色载入的未挂载道具，保留角色和挂点校准，可撤销"
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        from .operators import run_action

        def clear(settings):
            count = library.clear_character_equipment(settings)
            return "已从场景清理 " + str(count) + " 件道具；保留角色和挂点校准"

        result = run_action(context, clear)
        self.report({"INFO"} if result == {"FINISHED"} else {"WARNING"}, context.scene.hm_settings.status)
        return result


def entry_visible(state, item):
    query = state.search.strip().casefold()
    return (state.tier == "ALL" or item.tier == state.tier) and (not query or query in (item.name + " " + item.relative_path).casefold())


class HM_UL_library(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        layout.label(text=item.name, icon="MESH_DATA")

    def filter_items(self, context, data, propname):
        flags = [self.bitflag_filter_item if entry_visible(data, item) else 0 for item in data.items]
        return flags, []


def draw_library(layout, context):
    state = context.window_manager.hm_library
    settings = context.scene.hm_settings
    box = layout.box()
    box.prop(state, "is_expanded", text="外部道具库", icon="TRIA_DOWN" if state.is_expanded else "TRIA_RIGHT", emboss=False)
    if not state.is_expanded:
        return
    box.prop(state, "directory", text="目录")
    row = box.row(align=True)
    row.operator("humanoid_mounts.library_directory", text="选择目录", icon="FILE_FOLDER")
    row.operator("humanoid_mounts.library_refresh", text="刷新", icon="FILE_REFRESH")
    box.prop(state, "search", text="搜索", icon="VIEWZOOM")
    box.prop(state, "tier", text="分类")
    if state.items:
        box.template_list("HM_UL_library", "", state, "items", state, "index", rows=5)
    if state.message:
        from .panels import draw_message
        draw_message(box, state.message)
    if 0 <= state.index < len(state.items):
        item = state.items[state.index]
        box.label(text="已选：" + item.name)
        box.label(text=Path(item.relative_path).name, icon="FILE_3D")
        box.label(text="资源保留在外部；载入查看会添加到场景")
    box.prop(state, "orientation", text="朝向")
    row = box.row(align=True)
    row.enabled = 0 <= state.index < len(state.items) and entry_visible(state, state.items[state.index]) and settings.fitting_stage == "NONE"
    row.operator("humanoid_mounts.library_load", text="载入查看").attach = False
    attach = row.row(align=True)
    attach.enabled = settings.armature is not None
    attach.operator("humanoid_mounts.library_load", text="载入并挂载").attach = True
    snap = box.row()
    snap.enabled = settings.fitting_stage == "NONE" and placement.equipment_status(settings).step in {"READY", "EQUIPPED"}
    snap.operator("humanoid_mounts.equip_weapon", text="直接贴合当前道具到挂点", icon="CONSTRAINT_BONE")
    box.label(text="目标角色：" + (settings.armature.name if settings.armature else "请先选择角色"))
    box.label(text="目标部位：" + placement.part_name(settings.part))
    if settings.armature is not None:
        try:
            mount = placement.current_mount(settings)
            if len(mounts.mounts_for_armature(settings.armature, settings.part)) > 1 or settings.equipment is not None and settings.equipment.get("hm_source_file"):
                box.prop(settings, "mount", text="目标挂点")
            bone = mount.parent_bone if mount else bone_roles.resolve_bone(settings.armature, settings.part)
            box.label(text="目标骨骼：" + bone)
            box.label(text="目标挂点：" + (mount.name if mount else "自动创建"))
            if mount is None or not mount.get("hm_grip_fitted", False):
                box.label(text="可直接贴合；需要时再调整握位", icon="INFO")
            root = settings.equipment
            if root is not None and root.get("hm_kind") == "GRIP":
                if root.parent == mount and mount is not None:
                    box.label(text="当前装备已绑定此挂点；不准请调整位置")
                elif root.parent is None:
                    box.label(text="当前道具未挂载，点击上方直接贴合", icon="INFO")
        except mounts.HumanoidMountError as error:
            from .panels import draw_message
            draw_message(box, str(error))
            candidates = mounts.mounts_for_armature(settings.armature, settings.part)
            if len(candidates) > 1:
                box.prop(settings, "mount", text="目标挂点")
    orientation_row = box.row(align=True)
    orientation_row.enabled = settings.equipment is not None and settings.fitting_stage == "NONE"
    orientation_row.operator("humanoid_mounts.library_orientation", text="应用到当前道具").save = False
    orientation_row.operator("humanoid_mounts.library_orientation", text="记住当前朝向").save = True
    box.label(text="预设以挂点轴为准；握柄位置仍可调整")
    clear = box.row()
    clear.enabled = settings.armature is not None and settings.fitting_stage == "NONE"
    clear.operator("humanoid_mounts.library_clear", text="清空全部挂载并删除道具", icon="TRASH")


def initial_refresh():
    if hasattr(bpy.types.WindowManager, "hm_library"):
        state = bpy.context.window_manager.hm_library
        try:
            refresh(state)
        except (OSError, ValueError, SyntaxError, TypeError) as error:
            state.message = str(error)
    return None


CLASSES = (EquipmentLibraryEntry, EquipmentLibraryState, HM_OT_library_refresh, HM_OT_library_directory, HM_OT_library_load, HM_OT_library_clear, HM_OT_library_orientation, HM_UL_library)
