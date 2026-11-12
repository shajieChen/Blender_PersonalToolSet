import json
from pathlib import Path
import sys
import traceback
from time import perf_counter

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import bpy
from mathutils import Vector
import character_locomotion as plugin
from character_locomotion import locomotion
from character_control_fixtures import CharacterTestCase

OUT = ROOT / "tests" / "out" / "character_control"
OUT.mkdir(parents=True, exist_ok=True)
bpy.context.preferences.view.show_splash = False
plugin.register()
fixture = CharacterTestCase()
fixture.setUp()
rig = fixture.rig
rig.animation_data.action = fixture.clips["IDLE"].action
rig.animation_data.action_slot = rig.animation_data.action.slots[0]
bpy.context.scene.frame_set(1)
window = bpy.context.window
area = next(area for area in window.screen.areas if area.type == "VIEW_3D")
region = next(region for region in area.regions if region.type == "WINDOW")
area.spaces.active.show_region_ui = True
area.spaces.active.region_3d.view_distance = 8
area.spaces.active.region_3d.view_location = Vector((0, 0, 1))
rig.show_in_front = True
rig.data.display_type = "OCTAHEDRAL"
original = rig.matrix_world.copy()
original_action = rig.animation_data.action
baseline_actions = len(bpy.data.actions)
results = {"blender": bpy.app.version_string, "steps": []}
stage = -1
performance_start = None
tick_costs = []
original_tick = locomotion.LocomotionSession.tick


def measured_tick(self, dt):
    started = perf_counter()
    result = original_tick(self, dt)
    tick_costs.append(perf_counter() - started)
    return result


locomotion.LocomotionSession.tick = measured_tick


def emit(kind, value="PRESS", inside=True):
    x = region.x + region.width // 2 if inside else area.x + area.width - 5
    window.event_simulate(type=kind, value=value, x=x, y=region.y + region.height // 2)


def tick():
    global stage, performance_start
    try:
        session = locomotion.active_session()
        if stage == -1:
            emit("ESC")
        elif stage == 0:
            with bpy.context.temp_override(window=window, area=area, region=region):
                result = bpy.ops.character_locomotion.control("INVOKE_DEFAULT")
            assert result == {"RUNNING_MODAL"}, result
            emit("MOUSEMOVE", "NOTHING")
        elif stage == 1:
            assert session and session.player, rig.cl_settings.message
            emit("UP_ARROW")
        elif stage == 2:
            assert session.player.state == "WALK", session.status
            assert (rig.matrix_world.translation - original.translation).length > 0.05
            results["steps"].append({"state": "WALK", "position": list(rig.location)})
            emit("LEFT_SHIFT")
            emit("RIGHT_SHIFT")
        elif stage == 3:
            assert session.player.state == "RUN"
            emit("LEFT_SHIFT", "RELEASE")
        elif stage == 4:
            assert session.player.state == "RUN"
            results["steps"].append({"state": "RUN", "position": list(rig.location)})
            emit("UP_ARROW", "RELEASE")
        elif stage == 5:
            assert session.player.state == "IDLE"
            emit("MOUSEMOVE", "NOTHING", inside=False)
        elif stage == 6:
            assert not session.held
            results["steps"].append({"state": "PAUSED", "status": session.status})
            emit("MOUSEMOVE", "NOTHING")
            emit("ESC")
        elif stage == 7:
            assert session is None
            assert max(abs(rig.matrix_world[row][column] - original[row][column]) for row in range(4) for column in range(4)) < 1e-5
            assert rig.animation_data.action == original_action
            assert len(rig.animation_data.nla_tracks) == 0
            assert len(bpy.data.actions) == baseline_actions
            for region_item in area.regions:
                if region_item.type == "UI":
                    region_item.active_panel_category = "角色操控"
            bpy.ops.wm.save_as_mainfile(filepath=str(OUT / "character-control-preview.blend"))
        elif stage == 8:
            bpy.ops.screen.screenshot(filepath=str(OUT / "main-panel.png"))
            with bpy.context.temp_override(window=window, area=area, region=region):
                result = bpy.ops.character_locomotion.control("INVOKE_DEFAULT", preview_id=fixture.clips["WALK"].clip_id)
            assert result == {"RUNNING_MODAL"}
            emit("MOUSEMOVE", "NOTHING")
        elif stage == 9:
            assert session and session.player and session.player.state == "PREVIEW"
            assert (rig.matrix_world.translation - original.translation).length < 1e-5
            bpy.ops.wm.save_as_mainfile(filepath=str(OUT / "save-during-preview.blend"))
            assert locomotion.active_session() is None
            assert len(rig.animation_data.nla_tracks) == 0
            emit("MOUSEMOVE", "NOTHING")
        elif stage == 10:
            with bpy.context.temp_override(window=window, area=area, region=region):
                result = bpy.ops.character_locomotion.control("INVOKE_DEFAULT")
            assert result == {"RUNNING_MODAL"}
            emit("MOUSEMOVE", "NOTHING")
        elif stage == 11:
            assert session and session.player
            emit("UP_ARROW")
            performance_start = perf_counter()
            tick_costs.clear()
        elif stage == 12:
            assert session and session.player
            assert len(rig.animation_data.nla_tracks) == 2
            assert len(bpy.data.actions) == baseline_actions + 4
            elapsed = perf_counter() - performance_start
            if elapsed < 60:
                return 0.5
            results["synthetic_performance"] = {"seconds": elapsed, "timer_samples": len(tick_costs), "mean_tick_ms": sum(tick_costs) * 1000 / len(tick_costs), "max_tick_ms": max(tick_costs) * 1000, "scope": "two-bone fixture; timer handler only, excludes deferred evaluation/render"}
            emit("ESC")
        elif stage == 13:
            assert session is None
            assert len(bpy.data.actions) == baseline_actions
            assert len(rig.animation_data.nla_tracks) == 0
            results["result"] = "Passed"
            (OUT / "ui-runtime.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
            print("NATIVE_EVENTS_PASSED", flush=True)
            bpy.ops.wm.quit_blender()
            return None
        stage += 1
        return 0.5
    except Exception:
        results["result"] = "Failed"
        results["stage"] = stage
        results["error"] = traceback.format_exc()
        (OUT / "ui-runtime.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(results["error"], flush=True)
        locomotion.stop_session()
        bpy.ops.wm.quit_blender()
        return None


bpy.app.timers.register(tick, first_interval=2)
