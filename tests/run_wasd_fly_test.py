"""Headless checks for Unity-style viewport navigation."""

import math
import os
import sys

import bpy
from mathutils import Euler, Vector

ROOT = r"H:\Blender_Plugin"
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import wasd_fly_camera as fly


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print("PASS", message)


def level_rotation():
    """Level camera: look along +Y, right is +X, up is +Z."""
    return Euler((math.pi / 2.0, 0.0, 0.0), "XYZ").to_quaternion()


def test_level_axes():
    forward, right, up = fly.fly_axes(level_rotation())
    check(forward.dot(Vector((0.0, 1.0, 0.0))) > 0.999, "level camera looks along +Y")
    check(right.dot(Vector((1.0, 0.0, 0.0))) > 0.999, "level camera right is +X")
    check(up.dot(Vector((0.0, 0.0, 1.0))) > 0.999, "level camera up is +Z")


def test_wasd_matches_unity():
    rotation = level_rotation()
    forward = fly.fly_translation(rotation, {"W"}, 60.0, 1.0)
    back = fly.fly_translation(rotation, {"S"}, 60.0, 1.0)
    left = fly.fly_translation(rotation, {"A"}, 60.0, 1.0)
    right = fly.fly_translation(rotation, {"D"}, 60.0, 1.0)
    up = fly.fly_translation(rotation, {"E"}, 60.0, 1.0)
    down = fly.fly_translation(rotation, {"Q"}, 60.0, 1.0)
    check(forward.dot(Vector((0.0, 1.0, 0.0))) > 59.0, "W moves forward along the look direction")
    check(back.dot(Vector((0.0, -1.0, 0.0))) > 59.0, "S moves backward")
    check(right.dot(Vector((1.0, 0.0, 0.0))) > 59.0, "D moves right")
    check(left.dot(Vector((-1.0, 0.0, 0.0))) > 59.0, "A moves left")
    check(up.z > 59.0 and abs(up.x) < 1.0e-4, "E moves up on world Z")
    check(down.z < -59.0, "Q moves down on world Z")
    check(fly.fly_translation(rotation, set(), 60.0, 1.0).length < 1.0e-8, "no keys do not move")
    diagonal = fly.fly_translation(rotation, {"W", "D"}, 60.0, 1.0)
    check(abs(diagonal.length - 60.0) < 1.0e-4, "combined keys keep the requested speed")


def test_shift_and_scroll():
    check(fly.scaled_speed(4.0, False, 5.0) == 4.0, "normal speed stays at the base speed")
    check(fly.scaled_speed(4.0, True, 5.0) == 20.0, "shift multiplies the fly speed")
    faster = fly.scroll_speed(4.0, True)
    slower = fly.scroll_speed(4.0, False)
    check(faster > 4.0 and slower < 4.0, "scroll wheel changes fly speed in both directions")
    check(fly.scroll_speed(0.01, False) == 0.01, "speed does not fall below the minimum")
    check(fly.scroll_speed(1000.0, True) == 1000.0, "speed does not pass the maximum")


def test_mouse_look_locks_roll():
    rotation = level_rotation()
    looked = fly.fly_look(rotation, 80.0, 0.0, 0.003)
    forward, right, up = fly.fly_axes(looked)
    check(forward.x > 0.1, "moving the mouse right looks toward camera right")
    check(up.z > 0.9, "yaw keeps the camera upright")
    raised = fly.fly_look(rotation, 0.0, 80.0, 0.003)
    raised_forward, _right, raised_up = fly.fly_axes(raised)
    check(raised_forward.z > 0.1, "moving the mouse up looks up")
    check(raised_up.z > 0.0, "pitch does not roll the camera upside down")
    steep = rotation
    for _step in range(80):
        steep = fly.fly_look(steep, 0.0, 40.0, 0.003)
    steep_forward, _right, steep_up = fly.fly_axes(steep)
    check(steep_forward.normalized().dot(Vector((0.0, 0.0, 1.0))) < 0.996, "pitch stops before looking straight up")
    check(steep_up.z > 0.0, "the clamped look stays upright")


def test_preview_fly_turns_around_the_eye():
    rotation = level_rotation()
    location = Vector((1.0, 2.0, 3.0))
    distance = 6.0
    eye = fly.view_eye(location, rotation, distance)
    turned = fly.fly_look(rotation, 40.0, 15.0, 0.003)
    moved = fly.location_for_eye(eye, turned, distance)
    stayed = fly.view_eye(moved, turned, distance)
    check((stayed - eye).length < 1.0e-5, "mouse look keeps the preview eye fixed")
    check((moved - location).length > 0.1, "the orbit pivot shifts so the eye can stay put")
    delta = fly.fly_translation(turned, {"W"}, 3.0, 1.0)
    flown = eye + delta
    placed = fly.location_for_eye(flown, turned, distance)
    check((fly.view_eye(placed, turned, distance) - flown).length < 1.0e-5, "flight moves the preview eye")
    check((flown - eye).dot(fly.fly_axes(turned)[0]) > 2.0, "W carries the eye forward")


def test_unity_viewport_gestures():
    check(fly.right_drag_mode("PERSP") == "FLY", "perspective right-drag flies")
    check(fly.right_drag_mode("CAMERA") == "FLY", "camera view right-drag flies")
    check(fly.right_drag_mode("ORTHO") == "ORBIT", "orthographic right-drag orbits")
    rotation = level_rotation()
    sideways = fly.pan_offset(rotation, 10.0, 0.0, 5.0, 0.1)
    vertical = fly.pan_offset(rotation, 0.0, 10.0, 5.0, 0.1)
    check(sideways.x < -1.0 and abs(sideways.y) < 1.0e-6, "dragging right pans the camera left")
    check(vertical.z < -1.0 and abs(vertical.y) < 1.0e-6, "dragging up pans the camera down")
    closer = fly.zoom_distance(10.0, 20.0, 0.01)
    farther = fly.zoom_distance(10.0, -20.0, 0.01)
    check(closer < 10.0 and farther > 10.0, "dragging up zooms toward the pivot")
    check(fly.zoom_distance(0.01, 1000.0, 0.01) == 0.01, "zoom distance does not collapse")
    check(fly.zoom_distance(10000.0, -1000.0, 0.01) == 10000.0, "zoom distance stays finite")
    eye = Vector((0.0, 0.0, 0.0))
    distance = 6.0
    forward, _right, _up = fly.fly_axes(rotation)
    pivot = eye + forward * distance
    new_eye, turned = fly.orbit_eye(eye, rotation, 80.0, 0.0, 0.003, distance)
    new_forward, _right, _up = fly.fly_axes(turned)
    check(abs((new_eye - pivot).length - distance) < 1.0e-4, "orbit keeps the pivot distance")
    check((pivot - new_eye).normalized().dot(new_forward) > 0.999, "orbit still looks at the pivot")
    check((new_eye - eye).length > 0.1, "orbit moves the eye around the pivot")


def test_registration():
    fly.register()
    check(hasattr(bpy.types, "WASD_PT_fly_camera"), "the fly panel is registered")
    check(hasattr(bpy.types, "VIEW3D_OT_wasd_fly_camera"), "the fly operator is registered")
    check(hasattr(bpy.types, "VIEW3D_OT_unity_scene_nav"), "viewport pan orbit and zoom are registered")
    check(hasattr(bpy.types, "VIEW3D_OT_unity_frame_selected"), "frame selected is registered")
    found = []
    for keymap in bpy.context.window_manager.keyconfigs.addon.keymaps:
        for item in keymap.keymap_items:
            action = getattr(item.properties, "action", "")
            found.append((item.idname, item.type, bool(item.alt), action))
    check(("view3d.wasd_fly_camera", "RIGHTMOUSE", False, "") in found, "right mouse press starts flythrough")
    check(("view3d.unity_scene_nav", "MIDDLEMOUSE", False, "PAN") in found, "middle mouse pans")
    check(("view3d.unity_scene_nav", "LEFTMOUSE", True, "ORBIT") in found, "alt left mouse orbits")
    check(("view3d.unity_scene_nav", "RIGHTMOUSE", True, "ZOOM") in found, "alt right mouse zooms")
    check(("view3d.unity_frame_selected", "F", False, "") in found, "F frames the selection")
    fly.unregister()
    print("WASD_FLY_TEST_OK")


if __name__ == "__main__":
    try:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        test_level_axes()
        test_wasd_matches_unity()
        test_shift_and_scroll()
        test_mouse_look_locks_roll()
        test_preview_fly_turns_around_the_eye()
        test_unity_viewport_gestures()
        test_registration()
    except Exception:
        import traceback
        traceback.print_exc()
        print("WASD_FLY_TEST_FAIL")
        raise
