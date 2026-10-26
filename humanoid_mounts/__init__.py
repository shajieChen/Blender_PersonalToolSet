bl_info = {
    "name": "Humanoid Mounts",
    "author": "Blender Plugin",
    "version": (1, 0, 0),
    "blender": (5, 2, 1),
    "location": "View3D > Sidebar > 人形挂载",
    "description": "为人形骨骼设置挂点并挂载刚性武器和道具",
    "category": "Rigging",
}

import bpy

from . import operators, panels, properties

CLASSES = (properties.HumanoidMountSettings,) + operators.CLASSES + panels.CLASSES


def register():
    if hasattr(bpy.types.Scene, "hm_settings"):
        if all("bl_rna" in cls.__dict__ for cls in CLASSES):
            return
        raise RuntimeError("Humanoid Mounts registration state is inconsistent")
    registered = []
    try:
        for cls in CLASSES:
            bpy.utils.register_class(cls)
            registered.append(cls)
        bpy.types.Scene.hm_settings = bpy.props.PointerProperty(type=properties.HumanoidMountSettings)
    except Exception:
        if hasattr(bpy.types.Scene, "hm_settings"):
            del bpy.types.Scene.hm_settings
        for cls in reversed(registered):
            bpy.utils.unregister_class(cls)
        raise


def unregister():
    if hasattr(bpy.types.Scene, "hm_settings"):
        del bpy.types.Scene.hm_settings
    for cls in reversed(CLASSES):
        if "bl_rna" in cls.__dict__:
            bpy.utils.unregister_class(cls)
