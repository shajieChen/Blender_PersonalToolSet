import hashlib
import json
import math
import pathlib
import sys
import unittest

sys.dont_write_bytecode = True

import bpy
from mathutils import Euler, Matrix, Quaternion

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "tests/out/auto_mounts"
INSTALLED = "--installed" in sys.argv
PACKAGE_ROOT = pathlib.Path(bpy.utils.user_resource("SCRIPTS")) / "addons" if INSTALLED else ROOT
sys.path = [str(PACKAGE_ROOT), str(ROOT / "tests")] + [path for path in sys.path if pathlib.Path(path or ".").resolve() != ROOT]

import humanoid_mounts
import humanoid_retarget
from humanoid_mounts import mounts, weapons
from humanoid_retarget.pipeline import retarget_existing
from humanoid_retarget.retarget import RetargetOptions
from test_humanoid_mounts_transform import make_human


def verify_identity():
    for package in (humanoid_mounts, humanoid_retarget):
        actual = pathlib.Path(package.__file__).resolve()
        assert actual.parent == (PACKAGE_ROOT / package.__name__).resolve(), str(actual)
        print("AUTOMATIC_MOUNTS_PACKAGE", actual, flush=True)
    if INSTALLED:
        manifest = json.loads((ROOT / "docs/superpowers/evidence/2026-10-30-auto-mounts/install-manifest.json").read_text(encoding="utf-8"))
        for item in manifest:
            assert hashlib.sha256(pathlib.Path(item["installed"]).read_bytes()).hexdigest() == item["after_sha256"], item["file"]


def build_preview():
    from run_humanoid_mounts_demo import box, make_body, material

    humanoid_mounts.register()
    humanoid_retarget.register()
    scene = bpy.data.scenes.new("AutomaticMountsPreview")
    bpy.context.window.scene = scene
    source, source_names = make_human("AutomaticMounts_Source", roll=0.0)
    hand = source.pose.bones[source_names["hand_r"]]
    hand.rotation_mode = "XYZ"
    for frame, angle in ((1, -0.3), (31, 0.6), (61, -0.3)):
        hand.rotation_euler = (angle, 0.0, 0.0)
        hand.keyframe_insert("rotation_euler", frame=frame)
    source["hr_actions"] = source.animation_data.action.name
    target, names = make_human("AutomaticMounts_Hero", roll=0.15)
    make_body(target, names)
    options = RetargetOptions(pairs=[(role, source_names[role], names[role]) for role in names], foot_ik=False, hand_ik=False)
    retarget_existing(source, target, options)
    scene.frame_set(1)
    source.hide_set(True)
    bpy.context.scene.hr_settings.source = source
    bpy.context.scene.hr_settings.target = target
    assert bpy.ops.humanoid_mounts.use_retarget_target() == {"FINISHED"}
    steel = material("AutomaticMountsSteel", (0.65, 0.72, 0.80))
    gold = material("AutomaticMountsGuard", (0.88, 0.47, 0.05))
    leather = material("AutomaticMountsHandle", (0.12, 0.05, 0.02))
    blade = box("AutomaticMountsBlade", (2.0, 0.42, 0.0), (0.055, 0.65, 0.025), steel)
    guard = box("AutomaticMountsGuard", (2.0, 0.07, 0.0), (0.22, 0.04, 0.05), gold)
    handle = box("AutomaticMountsHandle", (2.0, -0.035, 0.0), (0.045, 0.17, 0.045), leather)
    root = weapons.prepare_grip_root([blade, guard, handle], Matrix.Translation((2.0, 0.0, 0.0)))
    root.name = "AutomaticMounts_Grip"
    settings = scene.hm_settings
    settings.bone_name = ""
    settings.part = "hand_r"
    bpy.context.view_layer.objects.active = blade
    assert bpy.ops.humanoid_mounts.equip_weapon() == {"FINISHED"}
    mount = settings.mount
    palm = target.matrix_world @ ((target.pose.bones[names["hand_r"]].head + target.pose.bones[names["hand_r"]].tail) * 0.5)
    mount.matrix_world = Matrix.Translation(palm) @ Euler((math.pi / 2.0, 0.0, 0.0)).to_matrix().to_4x4()
    weapons.detach_weapon(root)
    root.matrix_world = Matrix.Translation((1.4, 0.0, 0.7)) @ Euler((math.pi / 2.0, 0.0, 0.0)).to_matrix().to_4x4()
    settings.grip = None
    settings.status = "请选择右侧装备按钮：免选骨骼，复用角色和武器校准"
    target.hide_set(True)
    for selected in tuple(bpy.context.selected_objects):
        selected.select_set(False)
    blade.select_set(True)
    bpy.context.view_layer.objects.active = blade
    scene.frame_start = 1
    scene.frame_end = 61
    scene.render.fps = 24
    for area in bpy.context.screen.areas:
        if area.type == "VIEW_3D":
            space = area.spaces.active
            space.show_region_ui = True
            space.shading.type = "SOLID"
            space.shading.color_type = "MATERIAL"
            space.overlay.show_floor = False
            space.overlay.show_axis_x = False
            space.overlay.show_axis_y = False
            space.region_3d.view_rotation = Quaternion((1.0, 0.0, 0.0), math.pi / 2.0)
            space.region_3d.view_location = (0.4, 0.0, 0.9)
            space.region_3d.view_distance = 4.2
            space.region_3d.view_perspective = "ORTHO"
            area.tag_redraw()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    path = OUTPUT / "automatic-mounts-preview.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(path))
    return path


if __name__ == "__main__":
    verify_identity()
    if "--suite" in sys.argv:
        suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_humanoid_mounts_automatic.py")
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        print("AUTOMATIC_MOUNTS_SELECTED", result.testsRun, flush=True)
        sys.exit(0 if result.wasSuccessful() and result.testsRun > 0 and not result.skipped else 1)
    path = build_preview()
    print("AUTOMATIC_MOUNTS_PREVIEW", path, flush=True)
