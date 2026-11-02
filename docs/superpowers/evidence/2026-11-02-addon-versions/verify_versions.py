import ast
import importlib
import json
import pathlib
import sys

import bpy

ROOT = pathlib.Path(__file__).resolve().parents[4]
if "--installed" in sys.argv:
    sys.path.insert(0, str(pathlib.Path(bpy.utils.user_resource("SCRIPTS")) / "addons"))
else:
    sys.path.insert(0, str(ROOT))
TARGETS = (
    ("humanoid_mounts", "panels.HM_PT_mounts"),
    ("humanoid_retarget", "HR_PT_panel"),
    ("shortcut_hint", "SHORTCUT_PT_hint"),
    ("spring_bone", "panels.SPRING_BONE_PT_main"),
    ("wasd_fly_camera", "WASD_PT_fly_camera"),
)
rows = []
for name, panel_path in TARGETS:
    module = importlib.import_module(name)
    if "--installed" in sys.argv:
        assert pathlib.Path(module.__file__).resolve().parent == (pathlib.Path(bpy.utils.user_resource("SCRIPTS")) / "addons" / name).resolve()
    source = ROOT / name / "__init__.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    info = ast.literal_eval(next(node.value for node in tree.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "bl_info" for target in node.targets)))
    assert len(info["version"]) == 3 and all(type(value) is int and value >= 0 for value in info["version"])
    version = ".".join(map(str, info["version"]))
    assert info["name"].endswith(" v" + version)
    assert module.bl_info == info
    panel = module
    for attribute in panel_path.split("."):
        panel = getattr(panel, attribute)
    assert panel.bl_label.endswith(" v" + version), panel.bl_label
    module.register()
    try:
        assert "bl_rna" in panel.__dict__
        registered_label = panel.bl_label
    finally:
        module.unregister()
    assert "bl_rna" not in panel.__dict__
    rows.append({"module": name, "name": info["name"], "version": version, "panel": registered_label, "registration": "Passed", "unregistration": "Passed"})
print("ADDON_VERSIONS_SELECTED", len(rows))
print("ADDON_VERSIONS_PASSED", len(rows))
print(json.dumps(rows, ensure_ascii=False))
