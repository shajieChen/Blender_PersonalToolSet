import json
from pathlib import Path
import sys
import traceback

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import bpy
import character_locomotion as plugin
from character_control_fixtures import CharacterTestCase

OUT = ROOT / "tests/out/character_control"
OUT.mkdir(parents=True, exist_ok=True)
bpy.context.preferences.view.show_splash = False
plugin.register()
fixture = CharacterTestCase()
fixture.setUp()
for index, clip in enumerate(fixture.rig.cl_clips):
    clip.name = "中文长名动作与重名显示测试角色动画片段_" + str(index)
window = bpy.context.window
area = next(area for area in window.screen.areas if area.type == "VIEW_3D")
area.spaces.active.show_region_ui = True
cases = [(320, 1.0), (480, 1.0), (320, 1.5), (480, 1.5)]
stage = 0
case_index = 0
drag_x = 0
results = {"blender": bpy.app.version_string, "cases": []}


def emit(kind, value, x, y):
    window.event_simulate(type=kind, value=value, x=int(x), y=int(y))


def tick():
    global stage, case_index, drag_x
    try:
        if case_index == len(cases):
            results["result"] = "Passed"
            (OUT / "layout-runtime.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
            print("LAYOUT_AUDIT_PASSED", flush=True)
            bpy.ops.wm.quit_blender()
            return None
        width, scale = cases[case_index]
        region = next(region for region in area.regions if region.type == "UI")
        if stage == 0:
            emit("ESC", "PRESS", area.x + 100, area.y + 100)
            region.active_panel_category = "角色操控"
            bpy.context.preferences.view.ui_scale = scale
        elif stage == 1:
            emit("MOUSEMOVE", "NOTHING", region.x + 2, region.y + region.height // 2)
        elif stage == 2:
            drag_x = region.x + 2 + region.width - width
            with bpy.context.temp_override(window=window, area=area, region=region):
                result = bpy.ops.screen.region_scale("INVOKE_DEFAULT")
            assert result == {"RUNNING_MODAL"}, result
        elif stage == 3:
            x = drag_x
            emit("MOUSEMOVE", "NOTHING", x, region.y + region.height // 2)
            emit("LEFTMOUSE", "RELEASE", x, region.y + region.height // 2)
        elif stage == 4:
            results["cases"].append({"requested_width": width, "actual_width": region.width, "scale": scale})
            assert abs(region.width - width) <= 16, results["cases"][-1]
            bpy.ops.screen.screenshot(filepath=str(OUT / f"layout-{width}-{scale}.png"))
            stage = -1
            case_index += 1
        stage += 1
        return 0.5
    except Exception:
        results["result"] = "Failed"
        results["error"] = traceback.format_exc()
        (OUT / "layout-runtime.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(results["error"], flush=True)
        bpy.ops.wm.quit_blender()
        return None


bpy.app.timers.register(tick, first_interval=2)
