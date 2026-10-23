bl_info = {
    "name": "Spring Bone",
    "author": "Blender Plugin",
    "version": (1, 0, 4),
    "blender": (5, 2, 0),
    "location": "View3D > Sidebar > 动态骨骼",
    "description": "为已有骨骼的裙摆、发束和饰物生成预览并烘焙二次运动",
    "category": "Animation",
}

import bpy

from . import gizmos, operators, panels, properties
from .targets import scene_armature

_CLASSES = (
    properties.SpringBoneBoneName,
    properties.SpringBoneChain,
    properties.SpringBoneCollider,
    properties.SpringBoneSettings,
    operators.SPRING_BONE_OT_add_chain,
    operators.SPRING_BONE_OT_remove_chain,
    operators.SPRING_BONE_OT_trim_tips,
    operators.SPRING_BONE_OT_add_collider,
    operators.SPRING_BONE_OT_remove_collider,
    operators.SPRING_BONE_OT_sync_colliders,
    operators.SPRING_BONE_OT_preview,
    operators.SPRING_BONE_OT_stop,
    operators.SPRING_BONE_OT_bake,
    panels.SPRING_BONE_UL_chains,
    panels.SPRING_BONE_UL_colliders,
    panels.SPRING_BONE_PT_main,
    panels.SPRING_BONE_PT_chains,
    panels.SPRING_BONE_PT_colliders,
    panels.SPRING_BONE_PT_playback,
    panels.SPRING_BONE_PT_result,
)


@bpy.app.handlers.persistent
def _load_pre(*_args):
    operators.stop_active_session()


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Object.sb_settings = bpy.props.PointerProperty(type=properties.SpringBoneSettings)
    bpy.types.Scene.sb_target_armature = bpy.props.PointerProperty(name="目标骨架", type=bpy.types.Object, poll=scene_armature)
    if _load_pre not in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.append(_load_pre)
    if _load_pre not in bpy.app.handlers.undo_pre:
        bpy.app.handlers.undo_pre.append(_load_pre)
    gizmos.register_draw()


def unregister():
    gizmos.unregister_draw()
    operators.stop_active_session()
    if _load_pre in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.remove(_load_pre)
    if _load_pre in bpy.app.handlers.undo_pre:
        bpy.app.handlers.undo_pre.remove(_load_pre)
    if hasattr(bpy.types.Object, "sb_settings"):
        del bpy.types.Object.sb_settings
    if hasattr(bpy.types.Scene, "sb_target_armature"):
        del bpy.types.Scene.sb_target_armature
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
