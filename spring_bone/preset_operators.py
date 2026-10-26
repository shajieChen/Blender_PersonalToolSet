import json

import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, StringProperty
from bpy.types import Operator, PropertyGroup

from . import presets
from .operators import active_session, set_message
from .solver import SpringBoneError
from .targets import target_armature


class SpringBonePresetCandidate(PropertyGroup):
    enabled: BoolProperty(name="应用", default=True)
    summary: StringProperty(name="匹配结果")
    payload: StringProperty(options={"HIDDEN"})


def _target_ready(context):
    target = target_armature(context)
    return target is not None and target.mode != "EDIT" and not target.library and not target.data.library and active_session() is None


def _build_plan(armature, context, operation):
    settings = armature.sb_settings
    if operation == "COLLIDERS":
        return presets.build_collider_plan(armature, presets.load_preset(settings.collider_preset), context.scene)
    if operation == "CHARACTER":
        return presets.build_character_plan(armature, presets.load_preset(settings.character_preset), context.scene)
    preset = presets.load_preset(settings.chain_preset)
    if operation == "PARAMETERS":
        return presets.build_parameter_plan(armature, preset, context.scene)
    return presets.build_chain_plan(armature, preset, context.scene)


class SPRING_BONE_OT_apply_preset(Operator):
    bl_idname = "spring_bone.apply_preset"
    bl_label = "确认预设匹配结果"
    bl_options = {"REGISTER", "UNDO"}

    operation: EnumProperty(items=(("CHAINS", "识别骨骼链", ""), ("PARAMETERS", "应用当前链参数", ""), ("COLLIDERS", "匹配人形碰撞体", ""), ("CHARACTER", "应用角色配置", "")))
    plan_json: StringProperty(options={"HIDDEN", "SKIP_SAVE"})
    candidates: CollectionProperty(type=SpringBonePresetCandidate, options={"HIDDEN", "SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return _target_ready(context)

    def invoke(self, context, event):
        try:
            plan = _build_plan(target_armature(context), context, self.operation)
            self.plan_json = json.dumps(plan, ensure_ascii=True, allow_nan=False)
            self.candidates.clear()
            for row in plan["entries"]:
                item = self.candidates.add()
                item.summary = row["bone_name"] + " / " + row["shape"] + " / " + format(row["radius_m"], ".4f") + " m" if row["kind"] == "collider" else row["name"] + " / " + str(len(row["bone_names"])) + " 节"
                item.payload = json.dumps(row, ensure_ascii=True, allow_nan=False)
            return context.window_manager.invoke_props_dialog(self, width=500)
        except (SpringBoneError, OSError, ValueError, KeyError, TypeError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

    def draw(self, context):
        plan = json.loads(self.plan_json)
        layout = self.layout
        layout.label(text="目标：" + plan["target"])
        layout.label(text="匹配 " + str(len(self.candidates)) + " 项；仅添加勾选项")
        for item in self.candidates:
            layout.prop(item, "enabled", text=item.summary)
        for notice in plan["notices"][:12]:
            layout.label(text=notice, icon="INFO")
        if len(plan["notices"]) > 12:
            layout.label(text="另有 " + str(len(plan["notices"]) - 12) + " 项跳过")
        layout.label(text="参数是初始模板，应用后请调整碰撞范围")

    def execute(self, context):
        try:
            armature = target_armature(context)
            if self.plan_json:
                plan = json.loads(self.plan_json)
                plan["entries"] = [json.loads(item.payload) for item in self.candidates if item.enabled]
            else:
                plan = _build_plan(armature, context, self.operation)
            if not plan["entries"]:
                self.report({"WARNING"}, "没有可应用的新项；请核对目标骨架、骨名或已有配置")
                return {"CANCELLED"}
            count = presets.apply_plan(armature, plan)
            message = "已应用 " + str(count) + " 项预设：" + armature.name
            set_message(message)
            self.report({"INFO"}, message)
            return {"FINISHED"}
        except (SpringBoneError, OSError, ValueError, KeyError, TypeError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}


class SPRING_BONE_OT_save_preset(Operator):
    bl_idname = "spring_bone.save_preset"
    bl_label = "保存当前角色配置为预设"
    preset_name: StringProperty(name="预设名称", default="MySpringSetup", maxlen=48)

    @classmethod
    def poll(cls, context):
        return _target_ready(context)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        try:
            target = target_armature(context)
            path = presets.save_character_preset(target, context.scene, self.preset_name)
            target.sb_settings.character_preset = "user_" + self.preset_name
            self.report({"INFO"}, "已保存：" + str(path))
            return {"FINISHED"}
        except (SpringBoneError, OSError, ValueError, KeyError, TypeError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}


class SPRING_BONE_OT_refresh_presets(Operator):
    bl_idname = "spring_bone.refresh_presets"
    bl_label = "刷新预设列表"

    def execute(self, context):
        presets.refresh_catalog()
        errors = presets._catalog_data()[1]
        if errors:
            self.report({"WARNING"}, "；".join(errors))
        return {"FINISHED"}


CLASSES = (SpringBonePresetCandidate, SPRING_BONE_OT_apply_preset, SPRING_BONE_OT_save_preset, SPRING_BONE_OT_refresh_presets)
