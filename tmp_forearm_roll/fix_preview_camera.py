"""Hide the solve rig and frame the five preview characters."""
from __future__ import annotations

import bpy
from mathutils import Vector

BLEND = r"H:\Blender_Plugin\tmp_forearm_roll\preview_swing_compare.blend"
FRAMES = r"H:\Blender_Plugin\tmp_forearm_roll\preview_frames\frame_"


def main():
    bpy.ops.wm.open_mainfile(filepath=BLEND)
    scene = bpy.context.scene
    for name in ("Bip01", "body00", "Icosphere"):
        obj = bpy.data.objects.get(name)
        if obj is not None:
            obj.hide_render = True
            obj.hide_viewport = True
    labels = (
        ("Label_SRC", "SRC", -2.2),
        ("Label_A", "A", 0.0),
        ("Label_B", "B", 2.2),
        ("Label_C", "C", 4.4),
        ("Label_D", "D", 6.6),
    )
    for name, body, x in labels:
        obj = bpy.data.objects.get(name)
        if obj is None:
            curve = bpy.data.curves.new(name, "FONT")
            obj = bpy.data.objects.new(name, curve)
            scene.collection.objects.link(obj)
        obj.data.body = body
        obj.data.size = 0.45
        obj.data.align_x = "CENTER"
        obj.location = (x, 0.0, 2.05)
        obj.rotation_euler = (1.15, 0.0, 0.0)
    camera = scene.camera
    camera.data.lens = 18
    camera.location = (2.2, -9.0, 1.8)
    target = Vector((2.2, 0.0, 0.55))
    direction = target - camera.location
    camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    scene.render.filepath = FRAMES
    scene.render.image_settings.file_format = "PNG"
    bpy.ops.wm.save_as_mainfile(filepath=BLEND)
    bpy.ops.render.render(animation=True)
    print("RERENDERED")


if __name__ == "__main__":
    main()
