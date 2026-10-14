import pathlib
import sys
import types
import unittest

root = pathlib.Path(__file__).resolve().parents[1]
package = types.ModuleType("humanoid_retarget")
package.__path__ = [str(root / "humanoid_retarget")]
sys.modules["humanoid_retarget"] = package

arguments = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
pattern = arguments[0] if arguments else "test_*repulsion.py"
suite = unittest.defaultTestLoader.discover(
    str(root / "tests"), pattern=pattern
)
result = unittest.TextTestRunner(verbosity=2).run(suite)
selected = result.testsRun
print(f"POSE_CHANNEL_SELECTED {selected}")
if result.wasSuccessful() and selected > 0:
    print("POSE_CHANNEL_TEST_OK")
    sys.exit(0)
sys.exit(1)
