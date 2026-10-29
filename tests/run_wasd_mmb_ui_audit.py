import json
import math
import pathlib
import sys
import traceback
from time import perf_counter

import addon_utils
import bpy
from mathutils import Euler, Vector


ROOT = pathlib.Path(__file__).resolve().parents[1]
INSTALLED = "--installed" in sys.argv
PACKAGE_ROOT = pathlib.Path(bpy.utils.user_resource("SCRIPTS")) / "addons" if INSTALLED else ROOT
sys.path.insert(0, str(PACKAGE_ROOT))
sys.dont_write_bytecode = True
OUTPUT = ROOT / "docs/superpowers/evidence/2026-10-27-mmb-wasd"
OUTPUT.mkdir(parents=True, exist_ok=True)
bpy.context.preferences.view.show_splash = False
RESULT = {"status": "Running", "blender": bpy.app.version_string, "installed": INSTALLED, "checks": []}


def check(condition, message):
    RESULT["checks"].append({"name": message, "passed": bool(condition)})
    if not condition:
        raise AssertionError(message)
    print("UI_PASS", message, flush=True)


def send(window, event_type, value="PRESS", **fields):
    window.event_simulate(type=event_type, value=value, x=RESULT["mouse"][0], y=RESULT["mouse"][1], **fields)


def run():
    yield .5
    window = bpy.context.window_manager.windows[0]
    area = next(area for area in window.screen.areas if area.type == "VIEW_3D")
    region = next(region for region in area.regions if region.type == "WINDOW")
    check(region.width > 100 and region.height > 100, "native viewport layout is ready")
    RESULT["mouse"] = [region.x + region.width // 2, region.y + region.height // 2]
    view = area.spaces.active.region_3d
    view.view_perspective = "PERSP"
    view.view_rotation = Euler((math.pi / 2., 0., 0.), "XYZ").to_quaternion()
    view.view_location = (0., 0., 0.)
    view.view_distance = 6.
    bpy.context.preferences.inputs.view_rotate_method = "TURNTABLE"
    fly = addon_utils.enable("wasd_fly_camera", default_set=True)
    check(fly is not None and pathlib.Path(fly.__file__).resolve().parent == (PACKAGE_ROOT / "wasd_fly_camera").resolve(), "native audit loads the intended package")
    RESULT["source"] = fly.__file__
    matrices = {obj.name: obj.matrix_world.copy() for obj in bpy.data.objects}
    actions = set(bpy.data.actions)
    selected = {obj.name for obj in bpy.context.selected_objects}
    with bpy.context.temp_override(window=window, area=area, region=region):
        RESULT["preflight"] = {"eligible":fly._mmb_view_available(bpy.context), "poll":fly.WASD_OT_mmb_move.poll(bpy.context), "mode":fly._navigation_mode(), "modals":[operator.bl_idname for operator in window.modal_operators], "perspective":view.view_perspective, "locked":view.lock_rotation, "keymaps":[[item.idname,item.type,item.value] for _keymap,item in fly._ADDON_KEYMAPS]}
    original_invoke = fly.WASD_OT_mmb_move.invoke
    original_modal_event = fly.WASD_OT_mmb_move._modal_event
    RESULT["event_trace"] = []
    def invoke(operator, context, event):
        entry = {"phase":"invoke", "event":event.type,"time":perf_counter()}
        RESULT["event_trace"].append(entry)
        try:
            result = original_invoke(operator, context, event)
            entry["result"] = sorted(result)
            return result
        except Exception:
            entry["error"] = traceback.format_exc()
            raise
    def modal_event(operator, context, event):
        counts = RESULT.setdefault("event_counts",{})
        counts[event.type] = counts.get(event.type,0) + 1
        own_timer = event.type == "TIMER" and event.timer == operator.timer
        if own_timer:
            RESULT["owned_timer_events"] = RESULT.get("owned_timer_events",0) + 1
            RESULT.setdefault("first_owned_timer_at",perf_counter())
        entry = {"phase":"modal", "event":event.type,"time":perf_counter(),"own_timer":own_timer}
        if event.type == "TIMER":
            entry["context"] = {"window":context.window==operator.window,"screen":context.window.screen==operator.screen if context.window else False,"area":context.area==operator.area,"region":context.region==operator.view_region,"region_data":context.region_data==operator.region,"region_type":context.region.type if context.region else None,"eligible":fly._mmb_view_available(context),"modals":[item.bl_idname for item in context.window.modal_operators] if context.window else []}
        RESULT["event_trace"].append(entry)
        try:
            result = original_modal_event(operator, context, event)
            entry["result"] = sorted(result)
            if event.type == "TIMER" and "CANCELLED" in result:
                RESULT["event_trace"].append(entry)
            return result
        except Exception:
            entry["error"] = traceback.format_exc()
            if event.type == "TIMER":RESULT["event_trace"].append(entry)
            raise
    fly.WASD_OT_mmb_move.invoke = invoke
    fly.WASD_OT_mmb_move._modal_event = modal_event
    area.tag_redraw()
    send(window, "MOUSEMOVE", "NOTHING")
    yield .1
    send(window, "MIDDLEMOUSE")
    deadline = perf_counter() + 6.
    while fly._active_navigation is None and perf_counter() < deadline:
        yield .05
    RESULT["after_mmb"] = {"modals":[operator.bl_idname for operator in window.modal_operators], "merged_mmb":[[item.idname,item.value,item.shift,item.ctrl,item.alt] for keymap in bpy.context.window_manager.keyconfigs.user.keymaps if keymap.name == "3D View" for item in keymap.keymap_items if item.type == "MIDDLEMOUSE"], "areas":[[item.type,item.x,item.y,item.width,item.height] for item in window.screen.areas]}
    check(fly._active_navigation is not None, "native MMB keymap starts the modal")
    initial_rotation = view.view_rotation.copy()
    initial_distance = view.view_distance
    for key in ("W", "S", "A", "D"):
        location = view.view_location.copy()
        eye = fly.view_eye(location, view.view_rotation, view.view_distance)
        send(window, key)
        yield .18
        delta = view.view_location - location
        direction = fly.fly_translation(initial_rotation, {key}, 1., 1.)
        active = fly._active_navigation
        RESULT["motion_state"] = {"active":active is not None,"held":sorted(active.held) if active else [],"timer_delta":active.timer.time_delta if active and active.timer else None,"timer_duration":active.timer.time_duration if active and active.timer else None,"delta":list(delta)}
        check(delta.length > .02 and delta.normalized().dot(direction) > .999, "native " + key + " moves in the view direction")
        check(abs(view.view_rotation.dot(initial_rotation)) > .999999 and view.view_distance == initial_distance, "native " + key + " preserves rotation and distance")
        check((fly.view_eye(view.view_location, view.view_rotation, view.view_distance) - eye - delta).length < 1e-5, "native " + key + " translates eye and view center together")
        check({obj.name for obj in bpy.context.selected_objects} == selected, "native " + key + " does not invoke editing shortcuts")
        send(window, key, "RELEASE")
        yield .06
        stopped = view.view_location.copy()
        yield .08
        check((view.view_location - stopped).length < 1e-7, "native " + key + " release stops movement")
    send(window, "W")
    yield .1
    send(window, "MIDDLEMOUSE", "RELEASE")
    yield .08
    stopped = view.view_location.copy()
    yield .12
    check(fly._active_navigation is None and (view.view_location - stopped).length < 1e-7, "MMB release stops while W remains held")
    send(window, "W", "RELEASE")
    send(window, "A")
    send(window, "A", "RELEASE")
    yield .08
    check(len(bpy.context.selected_objects) == len([obj for obj in bpy.context.view_layer.objects if not obj.hide_get()]), "A resumes native select all outside MMB")
    entry = view.view_location.copy()
    send(window, "MIDDLEMOUSE")
    yield .08
    send(window, "D")
    yield .12
    send(window, "ESC")
    send(window, "D", "RELEASE")
    send(window, "MIDDLEMOUSE", "RELEASE")
    yield .08
    check(fly._active_navigation is None and (view.view_location - entry).length < 1e-6, "native Esc restores the entry viewport")
    send(window, "MIDDLEMOUSE")
    yield .08
    rotation, location = view.view_rotation.copy(), view.view_location.copy()
    RESULT["mouse"][0] += 40
    RESULT["mouse"][1] += 15
    send(window, "MOUSEMOVE", "NOTHING")
    yield .08
    check(abs(view.view_rotation.dot(rotation)) < .99999 and (view.view_location - location).length < 1e-6, "native middle drag still rotates")
    send(window, "MIDDLEMOUSE", "RELEASE")
    yield .06
    send(window, "MIDDLEMOUSE")
    yield .08
    send(window, "W")
    send(window, "LEFT_SHIFT", shift=True)
    yield .08
    stopped = view.view_location.copy()
    yield .08
    check((view.view_location - stopped).length < 1e-7, "native modifier press pauses translation")
    send(window, "LEFT_SHIFT", "RELEASE")
    yield .1
    check((view.view_location - stopped).length > .01, "native modifier release resumes translation")
    send(window, "W", "RELEASE")
    send(window, "MIDDLEMOUSE", "RELEASE")
    yield .06
    send(window, "MIDDLEMOUSE")
    yield .08
    send(window, "WINDOW_DEACTIVATE", "NOTHING")
    yield .06
    check(fly._active_navigation is None, "native deactivation clears navigation")
    send(window, "MIDDLEMOUSE", "RELEASE")
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    cube = bpy.data.objects.get("Cube")
    cube.select_set(True)
    bpy.context.view_layer.objects.active = cube
    send(window, "G")
    yield .08
    check(any("translate" in operator.bl_idname.lower() for operator in window.modal_operators), "native transform modal starts")
    send(window, "MIDDLEMOUSE")
    yield .06
    check(fly._active_navigation is None, "native transform keeps middle mouse axis constraint")
    send(window, "MIDDLEMOUSE", "RELEASE")
    send(window, "ESC")
    yield .08
    send(window, "MIDDLEMOUSE")
    yield .08
    preferences = bpy.context.preferences.addons["wasd_fly_camera"].preferences
    preferences.navigation_mode = "UNITY"
    send(window, "MOUSEMOVE", "NOTHING")
    yield .08
    check(fly._active_navigation is None and len(fly._ADDON_KEYMAPS) == 5, "mode switch stops navigation and restores legacy bindings")
    preferences.navigation_mode = "BLENDER_MMB"
    send(window, "MIDDLEMOUSE", "RELEASE")
    yield .06
    send(window, "MIDDLEMOUSE")
    yield .08
    check(fly._active_navigation is not None, "middle navigation can restart after mode switch")
    addon_utils.disable("wasd_fly_camera", default_set=True)
    send(window, "MOUSEMOVE", "NOTHING")
    send(window, "MIDDLEMOUSE", "RELEASE")
    yield .08
    check(fly._active_navigation is None and not fly._ADDON_KEYMAPS, "disable releases owned state and keymaps")
    check(not any("mmb_wasd_move" in operator.bl_idname for operator in window.modal_operators), "disabled modal leaves the event queue")
    check(all(max(abs(obj.matrix_world[row][col] - matrices[obj.name][row][col]) for row in range(4) for col in range(4)) < 1e-6 for obj in bpy.data.objects), "viewport navigation preserves all object and camera matrices")
    check(set(bpy.data.actions) == actions, "viewport navigation creates no animation")


STEPS = run()


def advance():
    try:
        return next(STEPS)
    except StopIteration:
        RESULT["status"] = "Passed"
    except Exception:
        RESULT["status"] = "Failed"
        RESULT["error"] = traceback.format_exc()
        traceback.print_exc()
    module = sys.modules.get("wasd_fly_camera")
    if module is not None:
        module._stop_navigation()
    tag = str(bpy.app.version[0]) + "_" + str(bpy.app.version[1])
    name = "installed-ui-" if INSTALLED else "ui-"
    (OUTPUT / (name + tag + ".json")).write_text(json.dumps(RESULT, indent=2), encoding="utf-8")
    print("MMB_NATIVE_UI_RESULT", json.dumps(RESULT), flush=True)
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(advance, first_interval=.2)
