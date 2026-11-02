bl_info = {
    "name": "Humanoid Mounts v1.1.0",
    "author": "Blender Plugin",
    "version": (1, 1, 0),
    "blender": (5, 1, 2),
    "location": "View3D > Sidebar > 人形挂载",
    "description": "为人形骨骼设置挂点并挂载刚性武器和道具",
    "category": "Rigging",
}

import bpy

from . import library_browser, operators, panels, properties

CLASSES = (properties.EquipmentObject, properties.HumanoidMountSettings,) + operators.CLASSES + panels.CLASSES + library_browser.CLASSES


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
        bpy.types.WindowManager.hm_library = bpy.props.PointerProperty(type=library_browser.EquipmentLibraryState)
        bpy.app.timers.register(library_browser.initial_refresh, first_interval=0.5)
    except Exception:
        if hasattr(bpy.types.WindowManager, "hm_library"):
            del bpy.types.WindowManager.hm_library
        if hasattr(bpy.types.Scene, "hm_settings"):
            del bpy.types.Scene.hm_settings
        for cls in reversed(registered):
            bpy.utils.unregister_class(cls)
        raise


def unregister():
    if hasattr(bpy.types.Scene, "hm_settings"):
        for scene in bpy.data.scenes:
            operators.placement.fitting_restore_records(scene.hm_settings)
        for scene in bpy.data.scenes:
            operators.placement.cancel_fitting(scene.hm_settings)
        del bpy.types.Scene.hm_settings
    if bpy.app.timers.is_registered(library_browser.initial_refresh):
        bpy.app.timers.unregister(library_browser.initial_refresh)
    if hasattr(bpy.types.WindowManager, "hm_library"):
        del bpy.types.WindowManager.hm_library
    for cls in reversed(CLASSES):
        if "bl_rna" in cls.__dict__:
            bpy.utils.unregister_class(cls)
