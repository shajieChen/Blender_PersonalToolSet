import importlib
import pathlib
import sys
import unittest

import bpy

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(pathlib.Path(bpy.utils.user_resource("SCRIPTS")) / "addons"))
sys.path.insert(1, str(ROOT / "tests"))
module = importlib.import_module("humanoid_mounts")
assert pathlib.Path(module.__file__).resolve().parent == (pathlib.Path(bpy.utils.user_resource("SCRIPTS")) / "addons" / "humanoid_mounts").resolve()
assert module.bl_info["version"] == (1, 2, 0)
assert module.bl_info["name"].endswith("v1.2.0")
assert module.panels.HM_PT_mounts.bl_label.endswith("v1.2.0")
case = importlib.import_module("test_humanoid_mounts_palm")
result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(case))
print("PALM_INSTALLED_SELECTED", result.testsRun)
if not result.wasSuccessful() or not result.testsRun or result.skipped:
    sys.exit(1)
print("PALM_INSTALLED_PASSED", result.testsRun)
