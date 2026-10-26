import json
import pathlib
import sys
import tempfile

import bpy


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
sys.dont_write_bytecode = True

from test_spring_bone_realtime import SpringBoneRealtime
from spring_bone.operators import active_session


SpringBoneRealtime.setUpClass()
case = SpringBoneRealtime()
case.setUp()
try:
    with tempfile.TemporaryDirectory(prefix="spring-realtime-lifecycle-") as folder:
        job = case._start()
        sampler_name, action_name = job.sampler.name, job.input_action.name
        path = str(pathlib.Path(folder) / "realtime-lifecycle.blend")
        bpy.ops.wm.save_as_mainfile(filepath=path)
        saved_clean = active_session() is None and sampler_name not in bpy.data.objects and action_name not in bpy.data.actions and not bpy.context.window_manager.sb_realtime_preview
        job = case._start()
        sampler_name, action_name = job.sampler.name, job.input_action.name
        bpy.ops.wm.open_mainfile(filepath=path)
        loaded_clean = active_session() is None and sampler_name not in bpy.data.objects and action_name not in bpy.data.actions and not bpy.context.window_manager.sb_realtime_preview
        result = {"status": "passed" if saved_clean and loaded_clean else "failed", "blender": bpy.app.version_string, "actual_save_clean": saved_clean, "actual_load_clean": loaded_clean}
        output = ROOT / "docs/superpowers/evidence/2026-10-26-spring-bone-realtime" / ("file-lifecycle-" + str(bpy.app.version[1]) + ".json")
        output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print("REALTIME_FILE_LIFECYCLE", json.dumps(result), flush=True)
        assert result["status"] == "passed"
finally:
    SpringBoneRealtime.tearDownClass()
