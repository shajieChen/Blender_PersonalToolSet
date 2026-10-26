import ast
import hashlib
import importlib.util
import io
import json
import pathlib
import sys
import tokenize
import unittest

sys.dont_write_bytecode = True

import bpy

ROOT = pathlib.Path(__file__).resolve().parents[1]
ARGUMENTS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
if "--installed" in ARGUMENTS:
    sys.path = [path for path in sys.path if pathlib.Path(path or ".").resolve() != ROOT]
    sys.path.insert(0, str(pathlib.Path(bpy.utils.user_resource("SCRIPTS")) / "addons"))
else:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))


def verify_sources():
    files = list((ROOT / "humanoid_mounts").glob("*.py")) + list((ROOT / "tests").glob("*humanoid_mounts*.py"))
    for path in files:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        assert not any(token.type == tokenize.COMMENT for token in tokenize.generate_tokens(io.StringIO(source).readline)), str(path)
        assert not any(ast.get_docstring(node) for node in ast.walk(tree) if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef))), str(path)
        assert not any(line.rstrip() != line for line in source.splitlines()), str(path)
        compile(tree, str(path), "exec")
    print("HUMANOID_MOUNTS_STATIC_OK", len(files))


def verify_saved():
    import humanoid_mounts

    humanoid_mounts.register()
    expectations = json.loads(bpy.context.scene["hm_saved_expectations"])
    bpy.context.scene.frame_set(expectations["frame"])
    bpy.context.view_layer.update()
    for name, expected in expectations["objects"].items():
        obj = bpy.data.objects[name]
        assert (obj.parent.name if obj.parent else None) == expected["parent"], name
        assert obj.get("hm_kind") == expected["kind"], name
        assert obj.get("hm_part") == expected["part"], name
        assert obj.get("hm_schema") == expected["schema"], name
        assert obj.parent_bone == expected["bone"], name
        actual = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).matrix_world
        assert max(abs(actual[row][column] - expected["world"][row][column]) for row in range(4) for column in range(4)) <= 1e-5, name
    assert bpy.context.scene.hm_settings.armature.name == expectations["armature"]
    print("HUMANOID_MOUNTS_REOPEN_FILE", bpy.data.filepath)
    print("HUMANOID_MOUNTS_REOPEN_OK", len(expectations["objects"]))
    return 0


def verify_installed():
    import addon_utils

    addon_utils.enable("humanoid_mounts", default_set=False, persistent=False)
    import humanoid_mounts

    expected = pathlib.Path(bpy.utils.user_resource("SCRIPTS")) / "addons" / "humanoid_mounts"
    actual = pathlib.Path(humanoid_mounts.__file__).resolve().parent
    assert actual == expected.resolve(), str(actual)
    for source in (ROOT / "humanoid_mounts").glob("*.py"):
        assert hashlib.sha256(source.read_bytes()).digest() == hashlib.sha256((actual / source.name).read_bytes()).digest(), source.name
    print("HUMANOID_MOUNTS_INSTALLED_FILE", humanoid_mounts.__file__)
    verify_saved()
    mount = bpy.context.scene.hm_settings.mount
    root = bpy.context.scene.hm_settings.grip
    addon_utils.disable("humanoid_mounts", default_set=False)
    assert root.parent == mount
    assert mount.get("hm_kind") == "MOUNT"
    addon_utils.enable("humanoid_mounts", default_set=False, persistent=False)
    assert root.parent == mount
    print("HUMANOID_MOUNTS_INSTALLED_OK")
    return 0


def main():
    arguments = ARGUMENTS
    verify_sources()
    pattern = arguments[0] if arguments else "test_humanoid_mounts_*.py"
    print("HUMANOID_MOUNTS_BLENDER", bpy.app.version_string, bpy.app.build_hash)
    print("HUMANOID_MOUNTS_FILTER", pattern)
    spec = importlib.util.find_spec("humanoid_mounts")
    print("HUMANOID_MOUNTS_FILE", spec.origin if spec else "MISSING")
    if "--installed" in arguments:
        return verify_installed()
    if "--check-saved" in arguments:
        return verify_saved()
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern=pattern)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print("HUMANOID_MOUNTS_SELECTED", result.testsRun)
    if result.wasSuccessful() and result.testsRun > 0 and not result.skipped and not result.expectedFailures:
        print("HUMANOID_MOUNTS_TEST_OK")
        return 0
    print("HUMANOID_MOUNTS_TEST_FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
