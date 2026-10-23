import bpy
from bpy.types import Panel, UIList

from .operators import active_session, last_message
from .targets import target_armature


def _running():
    session = active_session()
    return session is not None and session.job is not None and not session.job.finished


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
        target_row.enabled = not _running()
        target_row.prop(context.scene, "sb_target_armature", text="目标骨架")
        target = target_armature(context)
        if target is None:
            layout.label(text="请选择场景中的骨架")
            return
        if context.scene.sb_target_armature is None:
            layout.label(text=f"当前目标：{target.name}")
        settings = target.sb_settings
        if settings.schema_version != 1:
            layout.label(text="配置版本无法读取", icon="ERROR")
            return
        layout.prop(settings, "show_gizmos")
        if settings.show_gizmos:
            layout.label(text="青：骨骼  黄：当前链  粉：碰撞体")
            layout.label(text="穿透模型显示，远处混入灰色")
        session = active_session()
        if session is not None and session.job is not None:
            layout.label(text=f"{session.job.armature.name} {session.job.progress:.0%} {session.job.phase}")
        message = last_message()
        if message:
            layout.label(text=message)


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
    bl_order = 2

    @classmethod
    def poll(cls, context):
        return target_armature(context) is not None

    def draw(self, context):
        layout = self.layout
        settings = target_armature(context).sb_settings
        if settings.source_action is not None:
            layout.label(text=f"基础：{settings.source_action.name}")
        row = layout.row(align=True)
        row.prop(context.scene, "frame_start", text="开始")
        row.prop(context.scene, "frame_end", text="结束")
        row.enabled = not _running()
        actions = layout.column(align=True)
        actions.enabled = not _running()
        actions.operator("spring_bone.preview", text="生成预览", icon="PLAY")
        actions.operator("spring_bone.bake", text="烘焙新动作", icon="ACTION")
        layout.operator("spring_bone.stop_preview", text="停止预览", icon="PAUSE")


class SPRING_BONE_PT_result(Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_parent_id = "SPRING_BONE_PT_main"
    bl_label = "结果信息"
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = 3

    @classmethod
    def poll(cls, context):
        return target_armature(context) is not None

    def draw(self, context):
        settings = target_armature(context).sb_settings
        layout = self.layout
        if not settings.result_action_name:
            layout.label(text="尚未生成结果")
            return
        layout.label(text=settings.result_action_name, icon="ACTION")
        layout.label(text=f"范围：{settings.result_start} - {settings.result_end}")
        layout.label(text=f"残余穿深：{settings.result_penetration_m:.6f} m")
