"""Headless checks for Unity-style viewport navigation."""

import math
import os
import sys
from types import FunctionType, MethodType, SimpleNamespace
from unittest.mock import patch
from pathlib import Path

import bpy
from mathutils import Euler, Matrix, Vector

ROOT = str(Path(__file__).resolve().parents[1])
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import wasd_fly_camera as fly


_CHECKS = 0


def check(condition, message):
    global _CHECKS
    _CHECKS += 1
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
    fly._register_keymap("UNITY")
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


def mmb_event(event_type, value="PRESS", timer=None, **values):
    fields = dict(type=event_type, value=value, mouse_x=100, mouse_y=100, shift=False, ctrl=False, alt=False, oskey=False)
    fields.update(values)
    return SimpleNamespace(**fields)


def mmb_context():
    timers, headers, handlers = [], [], []
    area = SimpleNamespace(type="VIEW_3D", header_text_set=lambda text:headers.append(text), tag_redraw=lambda:None)
    screen = SimpleNamespace(areas=[area])
    window = SimpleNamespace(screen=screen, modal_operators=[])
    manager = SimpleNamespace(event_timer_add=lambda interval,window:timers.append(SimpleNamespace(time_duration=0.,time_delta=0.,time_step=interval)) or timers[-1], event_timer_remove=lambda timer:timers.remove(timer), modal_handler_add=lambda state:handlers.append(state))
    region_data = SimpleNamespace(view_perspective="PERSP", view_location=Vector((1.,2.,3.)), view_rotation=level_rotation(), view_distance=6., lock_rotation=False)
    context = SimpleNamespace(area=area, region=SimpleNamespace(type="WINDOW"), region_data=region_data, window=window, screen=screen, window_manager=manager, preferences=SimpleNamespace(inputs=SimpleNamespace(view_rotate_method="TURNTABLE")), space_data=SimpleNamespace(lock_object=None, lock_cursor=False), scene=SimpleNamespace(camera=SimpleNamespace(matrix_world=Matrix.Identity(4))))
    return context, timers, headers, handlers


def mmb_state():
    check(hasattr(fly, "WASD_OT_mmb_move"), "middle mouse WASD operator exists")
    cls = fly.WASD_OT_mmb_move
    state = SimpleNamespace(bl_idname=cls.bl_idname, report=lambda levels,message:None)
    for owner in (fly._ViewDrag, cls):
        for name, method in vars(owner).items():
            if isinstance(method, FunctionType):
                setattr(state,name,MethodType(method,state))
    return state


def mmb_tick(state, context, dt):
    state.timer.time_duration += dt
    state.timer.time_delta = dt
    with patch.object(fly,"perf_counter",return_value=state.last_time+dt):
        return state.modal(context,mmb_event("TIMER",timer=state.timer))


def test_mmb_translation_and_timer_isolation():
    context,timers,_headers,_handlers = mmb_context()
    state = mmb_state()
    check(state.invoke(context,mmb_event("MIDDLEMOUSE"))=={"RUNNING_MODAL"}, "plain MMB starts navigation")
    location = context.region_data.view_location.copy()
    rotation = context.region_data.view_rotation.copy()
    distance = context.region_data.view_distance
    eye = fly.view_eye(location,rotation,distance)
    state.modal(context,mmb_event("W"))
    state.modal(context,mmb_event("W"))
    state.modal(context,mmb_event("TIMER",timer=object()))
    check((context.region_data.view_location-location).length<1e-8,"foreign timer does not move viewport")
    mmb_tick(state,context,.025)
    delta = context.region_data.view_location-location
    check((delta-Vector((0.,.1,0.))).length<1e-5,"MMB W moves continuously without mouse motion")
    check(context.region_data.view_rotation==rotation and context.region_data.view_distance==distance,"keyboard translation preserves rotation and distance")
    check((fly.view_eye(context.region_data.view_location,rotation,distance)-eye-delta).length<1e-5,"eye and view center translate together")
    state.modal(context,mmb_event("W","RELEASE"))
    stopped = context.region_data.view_location.copy()
    mmb_tick(state,context,.025)
    check((context.region_data.view_location-stopped).length<1e-8,"key release stops translation")
    state.modal(context,mmb_event("MIDDLEMOUSE","RELEASE"))
    check(not timers,"MMB release removes its timer")


def test_mmb_release_cancel_and_mouse_rotation():
    context,timers,headers,_handlers = mmb_context()
    state = mmb_state()
    state.invoke(context,mmb_event("MIDDLEMOUSE"))
    initial = context.region_data.view_location.copy()
    rotation = context.region_data.view_rotation.copy()
    state.modal(context,mmb_event("MOUSEMOVE",mouse_x=125,mouse_y=115))
    check(context.region_data.view_rotation!=rotation,"MMB drag still rotates")
    check(context.region_data.view_location==initial,"mouse drag does not translate the view center")
    state.modal(context,mmb_event("D"))
    mmb_tick(state,context,.025)
    state.modal(context,mmb_event("ESC"))
    check(context.region_data.view_location==initial and context.region_data.view_rotation==rotation,"Esc restores the entry viewport")
    check(not timers and headers[-1] is None,"cancel releases timer and temporary header")
    state._finish()
    check(not timers,"finish is idempotent")
    state = mmb_state()
    state.invoke(context,mmb_event("MIDDLEMOUSE"))
    state.modal(context,mmb_event("W"))
    mmb_tick(state,context,.025)
    location = context.region_data.view_location.copy()
    state.modal(context,mmb_event("MIDDLEMOUSE","RELEASE"))
    result = state.modal(context,mmb_event("A"))
    check("PASS_THROUGH" in result,"finished navigation does not swallow later editor keys")
    check(context.region_data.view_location==location and not timers and not state.held,"MMB release stops even with W still held")


def test_mmb_timing_and_modifiers():
    positions = []
    for hz in (30,60,120):
        context,timers,_headers,_handlers = mmb_context()
        state = mmb_state()
        state.invoke(context,mmb_event("MIDDLEMOUSE"))
        initial = context.region_data.view_location.copy()
        state.modal(context,mmb_event("W"))
        state.modal(context,mmb_event("D"))
        for index in range(hz):
            mmb_tick(state,context,1./hz)
        positions.append(context.region_data.view_location-initial)
        state.modal(context,mmb_event("MIDDLEMOUSE","RELEASE"))
    check(all(abs(value.length-4.)<1e-5 for value in positions),"diagonal speed is normalized")
    check(max((value-positions[0]).length for value in positions)<1e-5,"30 60 120 Hz produce equal movement")
    context,timers,_headers,_handlers = mmb_context()
    state = mmb_state()
    state.invoke(context,mmb_event("MIDDLEMOUSE"))
    initial = context.region_data.view_location.copy()
    state.modal(context,mmb_event("W"))
    state.modal(context,mmb_event("LEFT_SHIFT",shift=True))
    mmb_tick(state,context,.02)
    check(context.region_data.view_location==initial,"modifier key pauses movement")
    state.modal(context,mmb_event("LEFT_SHIFT","RELEASE"))
    mmb_tick(state,context,.5)
    check(abs((context.region_data.view_location-initial).length-.2)<1e-5,"long stalls are capped to 0.05 seconds")
    state.modal(context,mmb_event("WINDOW_DEACTIVATE"))
    check(not timers and not state.held,"focus loss clears timer and keys")


def test_mmb_context_guards_and_lifecycle():
    for attribute,value in (("view_perspective","CAMERA"),("lock_rotation",True)):
        context,timers,_headers,_handlers = mmb_context()
        setattr(context.region_data,attribute,value)
        state = mmb_state()
        check("PASS_THROUGH" in state.invoke(context,mmb_event("MIDDLEMOUSE")),"protected viewport is not intercepted: "+attribute)
        check(not timers,"protected viewport creates no timer")
    context,timers,_headers,_handlers = mmb_context()
    context.window.modal_operators=[SimpleNamespace(bl_idname="TRANSFORM_OT_translate")]
    state = mmb_state()
    check("PASS_THROUGH" in state.invoke(context,mmb_event("MIDDLEMOUSE")),"G R S modal tools keep their middle mouse input")
    context.window.modal_operators=[]
    check("PASS_THROUGH" in state.invoke(context,mmb_event("MIDDLEMOUSE",shift=True)),"initial Shift MMB keeps native pan")
    check(not timers,"modifier gesture does not start a timer")
    for index in range(10):
        state = mmb_state()
        state.invoke(context,mmb_event("MIDDLEMOUSE"))
        state.modal(context,mmb_event("MIDDLEMOUSE","RELEASE"))
    check(not timers,"ten navigation sessions leave no timers")
    state = mmb_state()
    state.invoke(context,mmb_event("MIDDLEMOUSE"))
    context.area=SimpleNamespace(type="VIEW_3D")
    state.modal(context,mmb_event("TIMER",timer=state.timer))
    check(not timers,"changing viewport releases the captured session")


class NativeAreaCollection:
    def __init__(self, areas):
        self.areas = areas

    def __iter__(self):
        return iter(self.areas)

    def __contains__(self, value):
        if not isinstance(value, str):
            raise TypeError("RNA collection membership requires a string")
        return False


def test_mmb_rna_area_collection():
    context,timers,headers,_handlers = mmb_context()
    context.screen.areas = NativeAreaCollection([context.area])
    state = mmb_state()
    state.invoke(context,mmb_event("MIDDLEMOUSE"))
    check(state._context_valid(context),"native RNA area collections accept the captured area")
    state._finish()
    check(not timers and headers[-1] is None,"RNA area cleanup clears header and timer")
    state._finish()
    check(not timers,"RNA area cleanup remains idempotent")


def test_mmb_default_keymap():
    fly.register()
    try:
        items=[item for _keymap,item in fly._ADDON_KEYMAPS]
        check(len(items)==1 and items[0].type=="MIDDLEMOUSE" and items[0].idname=="view3d.mmb_wasd_move","default mode registers only plain middle mouse")
        check(not any(item.type in {"W","A","S","D","RIGHTMOUSE"} for item in items),"default mode does not bind global WASD or right mouse")
    finally:
        fly.unregister()


if __name__ == "__main__":
    try:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        selected = 0
        for case in (test_level_axes,test_wasd_matches_unity,test_shift_and_scroll,test_mouse_look_locks_roll,test_preview_fly_turns_around_the_eye,test_unity_viewport_gestures,test_mmb_translation_and_timer_isolation,test_mmb_release_cancel_and_mouse_rotation,test_mmb_timing_and_modifiers,test_mmb_context_guards_and_lifecycle,test_mmb_default_keymap,test_mmb_rna_area_collection,test_registration):
            selected += 1
            print("WASD_TEST",case.__name__)
            case()
        check(selected>0,"selected test groups are positive")
        print("WASD_FLY_TEST_OK")
    except Exception:
        import traceback
        traceback.print_exc()
        print("WASD_FLY_TEST_FAIL")
        raise

    finally:
        print("WASD_FLY_SELECTED",locals().get("selected",0))
        print("WASD_FLY_CHECKS",_CHECKS)
