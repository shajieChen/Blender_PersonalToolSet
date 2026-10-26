import json
import math
import os
import pathlib
import sys
import time

sys.dont_write_bytecode = True

import bpy
from mathutils import Euler, Matrix, Quaternion, Vector

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "tests" / "out" / "humanoid_mounts"
sys.path.insert(0, str(ROOT / "tests"))

from run_humanoid_mounts_tests import verify_sources

import humanoid_mounts
from humanoid_mounts import mounts, weapons

if "--installed" in sys.argv:
    expected = pathlib.Path(bpy.utils.user_resource("SCRIPTS")) / "addons" / "humanoid_mounts"
    assert pathlib.Path(humanoid_mounts.__file__).resolve().parent == expected.resolve()
    sys.path.insert(0, str(ROOT))

from test_humanoid_mounts_transform import make_human


def material(name, color):
    result = bpy.data.materials.new(name)
    result.diffuse_color = (*color, 1.0)
    return result


def box(name, center, size, color):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=center)
    obj = bpy.context.object
    obj.name = name
    obj.scale = size
    obj.data.materials.append(color)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    return obj


def parent_body(obj, armature, bone_name):
    desired = mounts.world_matrix(obj)
    obj.parent = armature
    obj.parent_type = "BONE"
    obj.parent_bone = bone_name
    obj.matrix_world = desired
    bpy.context.view_layer.update()


def make_body(armature, names):
    body = material("HumanBlue", (0.10, 0.34, 0.62))
    skin = material("HumanSkin", (0.72, 0.43, 0.23))
    torso = box("Torso", (0.0, 0.0, 1.24), (0.30, 0.18, 0.47), body)
    parent_body(torso, armature, names["chest"])
    head = box("Head", (0.0, 0.0, 1.67), (0.20, 0.18, 0.23), skin)
    parent_body(head, armature, names["head"])
    pelvis = box("Pelvis", (0.0, 0.0, 0.98), (0.28, 0.20, 0.18), body)
    parent_body(pelvis, armature, names["hips"])
    for side in ("l", "r"):
        for role in ("upperarm", "forearm", "hand", "thigh", "shin", "foot"):
            name = names[role + "_" + side]
            bone = armature.pose.bones[name]
            head_world = armature.matrix_world @ bone.head
            tail_world = armature.matrix_world @ bone.tail
            length = (tail_world - head_world).length
            obj = box(role + "_" + side, (head_world + tail_world) * 0.5, (0.085, length, 0.085), skin if role == "hand" else body)
            obj.rotation_mode = "QUATERNION"
            obj.rotation_quaternion = (tail_world - head_world).to_track_quat("Y", "Z")
            parent_body(obj, armature, name)


def animate_walk_run(armature, names):
    hips = armature.pose.bones[names["hips"]]
    for frame in range(1, 62):
        running = frame > 31
        phase = (frame - 1) * math.tau / (15.0 if running else 30.0)
        amplitude = 0.65 if running else 0.35
        hips.location = (0.035 * math.sin(phase), 0.0, 0.025 * abs(math.sin(phase)))
        hips.keyframe_insert("location", frame=frame)
        for side, sign in (("l", 1.0), ("r", -1.0)):
            thigh = armature.pose.bones[names["thigh_" + side]]
            shin = armature.pose.bones[names["shin_" + side]]
            thigh.rotation_mode = "XYZ"
            shin.rotation_mode = "XYZ"
            thigh.rotation_euler = (sign * amplitude * math.sin(phase), 0.0, 0.0)
            shin.rotation_euler = (max(-sign * math.sin(phase), 0.0) * amplitude, 0.0, 0.0)
            thigh.keyframe_insert("rotation_euler", frame=frame)
            shin.keyframe_insert("rotation_euler", frame=frame)
    armature.animation_data.action.name = "HumanoidMounts_WalkRun"


def build_scene():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    scene = bpy.data.scenes.new("HumanoidMountsDemo")
    bpy.context.window.scene = scene
    bpy.context.view_layer.update()
    humanoid_mounts.register()
    armature, names = make_human("HeroRig", roll=0.15)
    make_body(armature, names)
    mount = mounts.create_mount(armature, names["hand_r"], "hand_r")
    mount.name = "WeaponGrip_R"
    hand_pose = armature.pose.bones[names["hand_r"]]
    palm_center = armature.matrix_world @ ((hand_pose.head + hand_pose.tail) * 0.5)
    desired = Matrix.Translation(palm_center) @ Euler((math.pi / 2.0, 0.0, 0.0)).to_matrix().to_4x4()
    mount.matrix_world = desired
    steel = material("SwordSteel", (0.65, 0.72, 0.80))
    gold = material("SwordGuard", (0.88, 0.47, 0.05))
    leather = material("SwordGrip", (0.12, 0.05, 0.02))
    blade = box("SwordBlade", (2.0, 0.42, 0.0), (0.055, 0.65, 0.025), steel)
    guard = box("SwordGuard", (2.0, 0.07, 0.0), (0.22, 0.04, 0.05), gold)
    handle = box("SwordHandle", (2.0, -0.035, 0.0), (0.045, 0.17, 0.045), leather)
    anchor = Matrix.Translation((2.0, 0.0, 0.0))
    root = weapons.prepare_grip_root([blade, guard, handle], anchor)
    root.name = "GripRoot_Sword"
    weapons.bind_weapon(root, mount, "SNAP")
    targets = {"hand_l": "hand_l", "back": "chest", "waist": "hips", "head": "head"}
    other_mounts = {}
    for part, role in targets.items():
        other_mounts[part] = mounts.create_mount(armature, names[role], part)
    for part, position in (("back", (0.0, 0.16, 1.36)), ("waist", (0.18, 0.0, 1.0)), ("head", (0.0, 0.0, 1.82))):
        other_mounts[part].matrix_world = Matrix.Translation(position)
    shield_color = material("ShieldRed", (0.65, 0.10, 0.07))
    shield = box("ShieldFace", (3.0, 0.0, 0.0), (0.32, 0.07, 0.43), shield_color)
    shield_root = weapons.prepare_grip_root([shield], Matrix.Translation((3.0, 0.0, 0.0)))
    shield_root.name = "GripRoot_Shield"
    other_mounts["hand_l"].matrix_world = Matrix.Translation((0.79, 0.0, 1.48))
    weapons.bind_weapon(shield_root, other_mounts["hand_l"], "SNAP")
    settings = bpy.context.scene.hm_settings
    settings.armature = armature
    settings.mount = mount
    settings.grip = root
    settings.bone_name = names["hand_r"]
    settings.mount_name = mount.name
    settings.status = "五部位挂点；右手剑、左手盾；骨骼原生跟随"
    hand = armature.pose.bones[names["hand_r"]]
    hand.rotation_mode = "XYZ"
    for frame, angle in ((1, -0.5), (31, 0.65), (61, -0.5)):
        hand.rotation_euler = (angle, 0.0, 0.0)
        hand.keyframe_insert("rotation_euler", frame=frame)
    animate_walk_run(armature, names)
    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = 61
    scene.render.fps = 24
    scene.frame_set(1)
    bpy.ops.object.select_all(action="DESELECT")
    root.select_set(True)
    bpy.context.view_layer.objects.active = root
    armature.hide_set(True)
    for area in bpy.context.screen.areas:
        if area.type == "VIEW_3D":
            space = area.spaces.active
            space.shading.type = "SOLID"
            space.shading.color_type = "MATERIAL"
            space.overlay.show_floor = False
            space.overlay.show_axis_x = False
            space.overlay.show_axis_y = False
            space.show_region_ui = True
            space.region_3d.view_rotation = Quaternion((1.0, 0.0, 0.0), math.pi / 2.0)
            space.region_3d.view_location = (0.0, 0.0, 0.9)
            space.region_3d.view_distance = 3.2
            space.region_3d.view_perspective = "ORTHO"
    filepath = OUTPUT / "humanoid-mounts-preview.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(filepath))
    print("HUMANOID_MOUNTS_DEMO", filepath, flush=True)
    print("HUMANOID_MOUNTS_IDENTITY", os.getpid(), bpy.app.version_string, humanoid_mounts.__file__, flush=True)
    return filepath


def verify_undo():
    area = next(area for area in bpy.context.screen.areas if area.type == "VIEW_3D")
    region = next(region for region in area.regions if region.type == "WINDOW")
    with bpy.context.temp_override(area=area, region=region):
        bpy.ops.ed.undo_push(message="HumanoidMountsBeforeCopy")
        assert bpy.ops.humanoid_mounts.edit_mount(operation="COPY") == {"FINISHED"}
        copied = bpy.context.scene.hm_settings.mount.name
        bpy.ops.ed.undo_push(message="HumanoidMountsAfterCopy")
        assert bpy.ops.ed.undo() == {"FINISHED"}
        assert copied not in bpy.data.objects, "Undo did not remove copied mount"
        assert bpy.ops.ed.redo() == {"FINISHED"}
        assert copied in bpy.data.objects, "Redo did not restore copied mount"
        settings = bpy.context.scene.hm_settings
        settings.mount = bpy.data.objects[copied]
        assert bpy.ops.humanoid_mounts.edit_mount(operation="DELETE") == {"FINISHED"}
        settings.mount = bpy.data.objects["WeaponGrip_R"]
        settings.mount_name = settings.mount.name
        settings.status = "五部位已准备，右手剑与左手盾原生跟随"
    print("HUMANOID_MOUNTS_UNDO_REDO_OK", flush=True)


def verify_frontend(filepath):
    started = time.monotonic()
    frames = []
    screenshots = []
    errors = []
    checked = []
    phases = []
    capture_frames = []

    def advance():
        try:
            elapsed = time.monotonic() - started
            if not checked:
                verify_undo()
                bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=1)
                for area in bpy.context.screen.areas:
                    if area.type == "VIEW_3D":
                        region = next(region for region in area.regions if region.type == "UI")
                        with bpy.context.temp_override(area=area, region=region):
                            region.active_panel_category = "人形挂载"
                checked.append("Undo/Redo")
                bpy.ops.wm.save_as_mainfile(filepath=str(filepath))
            scene = bpy.context.scene
            if not bpy.context.screen.is_animation_playing:
                bpy.ops.screen.animation_play()
            frames.append(scene.frame_current)
            phases.append("run" if scene.frame_current > 31 else "walk")
            capture_walk = not screenshots and elapsed >= 2.0 and scene.frame_current <= 31
            capture_run = len(screenshots) == 1 and elapsed >= 4.0 and scene.frame_current > 31
            if capture_walk or capture_run:
                target = OUTPUT / ("humanoid-mounts-ui-" + str(len(screenshots) + 1) + ".png")
                bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=1)
                bpy.ops.screen.screenshot(filepath=str(target))
                screenshots.append(str(target))
                capture_frames.append(scene.frame_current)
            if elapsed < 8.0:
                return 0.25
            bpy.ops.screen.animation_cancel(restore_frame=False)
            assert len(screenshots) == 2 and {"walk", "run"}.issubset(phases), "Missing walk/run visual evidence"
        except Exception as error:
            errors.append(repr(error))
        result = {"pid": os.getpid(), "file": str(filepath), "plugin": humanoid_mounts.__file__, "frames": frames, "phases": phases, "screenshots": screenshots, "capture_frames": capture_frames, "checks": checked, "errors": errors}
        (OUTPUT / "humanoid-mounts-ui-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print("HUMANOID_MOUNTS_UI_DONE", len(set(frames)), len(screenshots), checked, errors, flush=True)
        bpy.ops.wm.quit_blender()
        return None

    bpy.app.timers.register(advance, first_interval=1.0)


if __name__ == "__main__":
    verify_sources()
    path = build_scene()
    if "--verify-ui" in sys.argv:
        if bpy.app.background:
            raise RuntimeError("UI verification requires a foreground Blender")
        verify_frontend(path)
