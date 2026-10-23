import pathlib
import sys
import unittest

sys.dont_write_bytecode = True

import bpy

root = pathlib.Path(__file__).resolve().parents[1]
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

import spring_bone

arguments = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
pattern = arguments[0] if arguments else "test_spring_bone_*.py"
print(
    "SPRING_BONE_BLENDER",
    bpy.app.version_string,
    getattr(bpy.app, "build_hash", ""),
)
print("SPRING_BONE_FILE", spring_bone.__file__)
suite = unittest.defaultTestLoader.discover(str(root / "tests"), pattern=pattern)
result = unittest.TextTestRunner(verbosity=2).run(suite)
selected = result.testsRun
print(f"SPRING_BONE_SELECTED {selected}")
if result.wasSuccessful() and selected > 0:
    print("SPRING_BONE_TEST_OK")
    sys.exit(0)
sys.exit(1)
