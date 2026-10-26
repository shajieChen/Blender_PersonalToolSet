import hashlib
import pathlib
import sys
import unittest

sys.dont_write_bytecode = True

import bpy

root = pathlib.Path(__file__).resolve().parents[1]
arguments = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
package_root = pathlib.Path(bpy.utils.user_resource("SCRIPTS")) / "addons" if "--installed" in arguments else root
sys.path.insert(0, str(package_root))

import spring_bone

if "--installed" in arguments:
    assert pathlib.Path(spring_bone.__file__).resolve().parent == (package_root / "spring_bone").resolve()
    sources = [*(root / "spring_bone").glob("*.py"), root / "spring_bone/preset_data/builtin.json"]
    for source in sources:
        relative = source.relative_to(root / "spring_bone")
        assert hashlib.sha256(source.read_bytes()).digest() == hashlib.sha256((package_root / "spring_bone" / relative).read_bytes()).digest(), str(relative)
patterns = [argument for argument in arguments if argument != "--installed"]
pattern = patterns[0] if patterns else "test_spring_bone_*.py"
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
