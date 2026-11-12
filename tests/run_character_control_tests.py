import ast
import io
import pathlib
import sys
import tokenize
import unittest
import hashlib

sys.dont_write_bytecode = True
ROOT = pathlib.Path(__file__).resolve().parents[1]
INSTALLED = "--installed" in sys.argv
if INSTALLED:
    sys.path = [value for value in sys.path if pathlib.Path(value or ".").resolve() != ROOT]
else:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import bpy

if INSTALLED:
    sys.path.insert(0, str(pathlib.Path(bpy.utils.user_resource("SCRIPTS")) / "addons"))


def main():
    patterns = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    patterns = [pattern for pattern in patterns if pattern != "--installed"]
    patterns = patterns or ["test_locomotion.py", "test_animation_playback.py", "test_animation_library.py"]
    for path in (ROOT / "character_locomotion").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        compile(tree, str(path), "exec")
        assert not any(token.type == tokenize.COMMENT for token in tokenize.generate_tokens(io.StringIO(source).readline)), str(path)
        assert not any(ast.get_docstring(node) for node in ast.walk(tree) if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef))), str(path)
        assert all(line == line.rstrip() for line in source.splitlines()), str(path)
    import character_locomotion as plugin
    print("SOURCE", plugin.__file__, "VERSION", plugin.bl_info["version"], flush=True)
    if INSTALLED:
        installed = pathlib.Path(plugin.__file__).parent
        assert installed != ROOT / "character_locomotion"
        for source in (ROOT / "character_locomotion").glob("*.py"):
            assert hashlib.sha256(source.read_bytes()).digest() == hashlib.sha256((installed / source.name).read_bytes()).digest(), source.name
    suite = unittest.TestSuite()
    for pattern in patterns:
        found = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern=pattern)
        if found.countTestCases() == 0:
            raise RuntimeError("Zero selected tests: " + pattern)
        suite.addTests(found)
    print("BLENDER", bpy.app.version_string, "FILTER", patterns, flush=True)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print("SELECTED", result.testsRun, "SUCCESS", result.wasSuccessful(), flush=True)
    return 0 if result.wasSuccessful() and result.testsRun > 0 and not result.skipped and not result.expectedFailures else 1


if __name__ == "__main__":
    sys.exit(main())
