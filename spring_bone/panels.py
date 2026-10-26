import bpy
from bpy.types import Panel, UIList

from .operators import active_session, last_message, realtime_running
from .targets import target_armature


def _running():
    session = active_session()
    return session is not None and session.job is not None and not session.job.finished and not realtime_running()


class SPRING_BONE_UL_chains(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        layout.prop(item, "name", text="", emboss=False, icon="BONE_DATA")
        layout.label(text=str(len(item.bone_names)))


class SPRING_BONE_UL_colliders(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        layout.prop(item, "name", text="", emboss=False, icon="MESH_UVSPHERE")
        layout.label(text="胶囊" if item.shape == "CAPSULE" else "球")


class SPRING_BONE_PT_main(Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "动态骨骼"
    bl_label = "动态骨骼"
    bl_idname = "SPRING_BONE_PT_main"

    @classmethod
    def poll(cls, context):
        return context.scene is not None

    def draw(self, context):
        layout = self.layout
        target_row = layout.row()
        target_row.enabled = active_session() is None
        target_row.prop(context.scene, "sb_target_armature", text="目标骨架")
        target = target_armature(context)
        if target is None:
            layout.label(text="请选择场景中的骨架")
            return
        if context.scene.sb_target_armature is None:
            layout.label(text=f"当前目标：{target.name}")
        settings = target.sb_settings
        if target.animation_data is not None:
            action_row = layout.row()
            action_row.enabled = active_session() is None
            action_row.prop(target.animation_data, "action", text="当前动作")
            action = target.animation_data.action
            if realtime_running():
                layout.label(text="实时重力与代理体碰撞；裙面防穿另行烘焙")
            elif action is not None and action.get("sb_contact_invalidated_reason"):
                layout.label(text="当前防穿结果因权重恢复已失效", icon="ERROR")
            elif action is not None and not action.get("sb_skin_contact"):
                layout.label(text="当前动作未进行裙面防穿修正", icon="ERROR")
            elif action is not None and action.get("sb_contact_coverage") != "all_garment_faces":
                layout.label(text="旧检测范围，请重新修正当前动作", icon="ERROR")
        if settings.schema_version != 1:
            layout.label(text="配置版本无法读取", icon="ERROR")
            return
        layout.prop(settings, "show_gizmos")
        realtime_row = layout.row()
        realtime_row.enabled = not _running()
        realtime_row.prop(context.window_manager, "sb_realtime_preview", text="实时预览")
        if settings.show_gizmos:
            layout.label(text="青：骨骼  黄：当前链  粉：碰撞体")
            layout.label(text="穿透模型显示，远处混入灰色")
        session = active_session()
        if session is not None and session.job is not None:
            if realtime_running():
                layout.label(text=f"实时：{session.job.armature.name} / {len(session.job.names)} 节")
            else:
                layout.label(text=f"{session.job.armature.name} {session.job.progress:.0%} {session.job.phase}")
        message = last_message()
        if message:
            layout.label(text=message)


class SPRING_BONE_PT_presets(Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_parent_id = "SPRING_BONE_PT_main"
    bl_label = "预设与自动匹配"
    bl_order = -1

    @classmethod
    def poll(cls, context):
        return target_armature(context) is not None

    def draw(self, context):
        layout = self.layout
        layout.enabled = active_session() is None
        settings = target_armature(context).sb_settings
        box = layout.box()
        box.prop(settings, "chain_preset")
        box.operator("spring_bone.apply_preset", text="识别匹配骨骼链").operation = "CHAINS"
        row = box.row()
        row.enabled = bool(settings.chains)
        row.operator("spring_bone.apply_preset", text="仅应用当前链参数").operation = "PARAMETERS"
        box = layout.box()
        box.prop(settings, "collider_preset")
        box.operator("spring_bone.apply_preset", text="匹配人形碰撞体").operation = "COLLIDERS"
        box.label(text="复用人形识别；尺寸按骨长估算")
        box = layout.box()
        box.prop(settings, "character_preset")
        box.operator("spring_bone.apply_preset", text="应用已保存角色配置").operation = "CHARACTER"
        box.operator("spring_bone.save_preset", text="保存当前配置为预设")
        box.operator("spring_bone.refresh_presets", text="刷新预设列表", icon="FILE_REFRESH")
        layout.label(text="先核对目标骨架；匹配后可逐项取消")


class SPRING_BONE_PT_chains(Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_parent_id = "SPRING_BONE_PT_main"
    bl_label = "骨骼链"
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = 0

    @classmethod
    def poll(cls, context):
        return target_armature(context) is not None

    def draw(self, context):
        layout = self.layout
        layout.enabled = not _running()
        settings = target_armature(context).sb_settings
        layout.template_list("SPRING_BONE_UL_chains", "", settings, "chains", settings, "active_chain", rows=3)
        row = layout.row(align=True)
        row.operator("spring_bone.add_chain", text="添加选中骨骼", icon="ADD")
        if not settings.chains:
            layout.label(text="姿态模式选择一条连续骨骼链")
            return
        index = max(0, min(settings.active_chain, len(settings.chains) - 1))
        chain = settings.chains[index]
        row.operator("spring_bone.remove_chain", text="移除", icon="REMOVE").index = index
        layout.operator("spring_bone.trim_unweighted_tips", text="按蒙皮修正全部链的末端")
        layout.label(text=f"{len(chain.bone_names)} 节 / {chain.bone_names[0].name if chain.bone_names else '空链'}")
        motion = layout.box()
        motion.label(text="运动与混合")
        motion.prop(chain, "stiffness")
        motion.prop(chain, "drag_force")
        motion.prop(chain, "weight")
        gravity = layout.box()
        gravity.label(text="重力与惯性")
        gravity.prop(chain, "gravity_power")
        gravity.row().prop(chain, "gravity_dir", text="方向")
        gravity.prop(chain, "inertia_space")
        if chain.inertia_space == "FOLLOW_TRANSLATION":
            gravity.prop_search(chain, "ancestor_name", target_armature(context).data, "bones")
        gravity.prop(chain, "warmup_seconds")
        collision = layout.box()
        collision.label(text="碰撞与角度限制")
        collision.prop(chain, "hit_radius_m")
        collision.prop(chain, "cone_enabled")
        if chain.cone_enabled:
            collision.prop(chain, "cone_angle_deg")


class SPRING_BONE_PT_colliders(Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_parent_id = "SPRING_BONE_PT_main"
    bl_label = "碰撞体"
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = 1

    @classmethod
    def poll(cls, context):
        return target_armature(context) is not None

    def draw(self, context):
        layout = self.layout
        layout.enabled = not _running()
        settings = target_armature(context).sb_settings
        layout.template_list("SPRING_BONE_UL_colliders", "", settings, "colliders", settings, "active_collider", rows=3)
        row = layout.row(align=True)
        row.operator("spring_bone.add_collider", text="添加代理体", icon="ADD")
        if not settings.colliders:
            layout.label(text="选择非模拟骨，添加球或胶囊")
            return
        index = max(0, min(settings.active_collider, len(settings.colliders) - 1))
        collider = settings.colliders[index]
        row.operator("spring_bone.remove_collider", text="移除", icon="REMOVE").index = index
        layout.prop(collider, "shape")
        layout.prop_search(collider, "bone_name", target_armature(context).data, "bones")
        layout.prop(collider, "radius_m")
        layout.row().prop(collider, "head_offset_m", text="起点")
        if collider.shape == "CAPSULE":
            layout.row().prop(collider, "tail_offset_m", text="终点")
        layout.operator("spring_bone.sync_colliders", text="更新代理体空物体")


class SPRING_BONE_PT_playback(Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_parent_id = "SPRING_BONE_PT_main"
    bl_label = "预览与烘焙"
    bl_order = 3

    @classmethod
    def poll(cls, context):
        return target_armature(context) is not None

    def draw(self, context):
        layout = self.layout
        settings = target_armature(context).sb_settings
        if realtime_running():
            layout.label(text="每条链的每节均参与重力求解")
            layout.label(text="可直接调整重力、刚度与拖曳")
        source = active_session().job.source_action if realtime_running() else settings.source_action
        if source is not None:
            layout.label(text=f"基础：{source.name}")
        row = layout.row(align=True)
        row.prop(context.scene, "frame_start", text="开始")
        row.prop(context.scene, "frame_end", text="结束")
        row.enabled = not _running()
        actions = layout.column(align=True)
        actions.enabled = active_session() is None
        actions.operator("spring_bone.preview", text="生成预览", icon="PLAY")
        actions.operator("spring_bone.bake", text="烘焙新动作", icon="ACTION")
        layout.operator("spring_bone.stop_preview", text="停止预览", icon="PAUSE")


class SPRING_BONE_PT_result(Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_parent_id = "SPRING_BONE_PT_main"
    bl_label = "结果信息"
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = 4

    @classmethod
    def poll(cls, context):
        return target_armature(context) is not None

    def draw(self, context):
        target = target_armature(context)
        settings = target.sb_settings
        layout = self.layout
        if realtime_running():
            layout.label(text="实时预览中，尚未烘焙")
            layout.label(text="停止实时预览后可生成烘焙动作")
            return
        action = target.animation_data.action if target.animation_data else None
        if action is not None and action.get("sb_contact_invalidated_reason"):
            layout.label(text="当前防穿结果已失效，请重新生成", icon="ERROR")
            return
        if action is None or not action.get("sb_generated"):
            layout.label(text="当前动作没有动态骨骼结果", icon="ERROR")
            if settings.result_action_name:
                layout.label(text=f"上次结果（未启用）：{settings.result_action_name}")
            return
        layout.label(text=action.name, icon="ACTION")
        layout.label(text=f"范围：{action.get('sb_frame_start', settings.result_start)} - {action.get('sb_frame_end', settings.result_end)}")
        if action is not None and action.get("sb_skin_contact"):
            if action.get("sb_contact_coverage") != "all_garment_faces":
                layout.label(text="旧结果未检查完整边界与帧间，请重新修正", icon="ERROR")
                return
            layout.label(text=f"采样裙面穿插：{action.get('sb_contact_triangle_pairs', 0)} 对")
            layout.label(text=f"复核步长：{action.get('sb_contact_validation_step', 0):g} 帧")
            layout.label(text="修正已写入骨骼关键帧，可随 FBX 导出")
            repaired = action.get("sb_quaternion_sign_repairs", 0)
            if repaired:
                layout.label(text=f"已修复 {repaired} 个旋转符号键，原动作保留")
        else:
            layout.label(text=f"骨尖代理残余：{settings.result_penetration_m:.6f} m")


class SPRING_BONE_PT_contact(Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_parent_id = "SPRING_BONE_PT_main"
    bl_label = "裙面防穿"
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = 2

    @classmethod
    def poll(cls, context):
        return target_armature(context) is not None

    def draw(self, context):
        layout = self.layout
        layout.enabled = not _running()
        settings = target_armature(context).sb_settings
        layout.prop(settings, "contact_garment")
        layout.prop(settings, "contact_body")
        layout.prop(settings, "contact_margin_m")
        layout.prop(settings, "contact_frame_step")
        layout.prop(settings, "contact_root_offset_m")
        layout.label(text="检查碰撞骨及其子骨的身体蒙皮")
        layout.label(text="包含同角色所有受动态链驱动的网格")
        layout.label(text="生成后细分复核，穿插时加密关键帧")
        layout.label(text="保留裙长，将活动动作修正为新骨骼动作")
        layout.operator("spring_bone.contact_bake")
