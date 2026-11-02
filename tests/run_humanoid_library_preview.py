import pathlib
import sys

import bpy
import addon_utils

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
addon_utils.enable("humanoid_mounts", default_set=False, persistent=False)
import humanoid_mounts
from humanoid_mounts import library_browser
from test_humanoid_mounts_transform import make_human
from humanoid_retarget.mapping import save_target_roles

expected = pathlib.Path(bpy.utils.user_resource("SCRIPTS")) / "addons/humanoid_mounts"
assert pathlib.Path(humanoid_mounts.__file__).resolve().parent == expected.resolve()
for source in (ROOT / "humanoid_mounts").glob("*.py"):
    assert source.read_bytes() == (expected / source.name).read_bytes(), source.name
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
arm, names = make_human("LibraryPreviewHero")
if "--verify-shear" in sys.argv:
    arm.scale = (0.2, 0.35, 0.5)
    hand = arm.pose.bones[names["hand_r"]]
    hand.rotation_mode = "XYZ"
    hand.rotation_euler = (0.3, 0.5, -0.4)
save_target_roles(arm, [(role, "Source_" + role, bone) for role, bone in names.items()])
bpy.context.scene.hm_settings.armature = arm
state = bpy.context.window_manager.hm_library
state.directory = "H:/SErsiko_ExtactedTool"
library_browser.refresh(state)
state.index = next(index for index, item in enumerate(state.items) if item.relative_path.endswith("WP_A_0300.glb") and item.tier == "std")
assert bpy.ops.humanoid_mounts.library_load(attach="--verify-shear" not in sys.argv) == {"FINISHED"}
if "--verify-shear" in sys.argv:
    from humanoid_mounts import mounts
    from mathutils import Matrix
    assert bpy.ops.humanoid_mounts.equip_weapon() == {"FINISHED"}
    root = bpy.context.scene.hm_settings.equipment
    mount = bpy.context.scene.hm_settings.mount
    assert tuple(root.location) == (0, 0, 0)
    assert mounts.matrix_distance(root.matrix_basis, Matrix.Identity(4)) <= 1e-5
    assert mounts.matrix_distance(mounts.world_matrix(root), mounts.world_matrix(mount)) <= 1e-5
    print("LIBRARY_INSTALLED_ZERO_SNAP_SHEAR_OK")
print("LIBRARY_INSTALLED_RUNTIME_OK", bpy.app.version_string, len(state.items), humanoid_mounts.__file__)


if "--verify-grip-tool" in sys.argv:
    root = bpy.context.scene.hm_settings.equipment
    from humanoid_mounts import mounts
    before = mounts.world_matrix(root)
    assert bpy.ops.humanoid_mounts.fit_equipment(operation="CHARACTER") == {"FINISHED"}
    assert bpy.context.workspace.tools.from_space_view3d_mode("OBJECT", create=False).idname == "builtin.rotate"
    area = next(area for area in bpy.context.screen.areas if area.type == "VIEW_3D")
    assert area.spaces.active.show_gizmo and area.spaces.active.show_gizmo_tool
    assert bpy.context.object == bpy.context.scene.hm_settings.fitting_mount
    assert bpy.ops.humanoid_mounts.fit_equipment(operation="CANCEL") == {"FINISHED"}
    assert mounts.matrix_distance(before, mounts.world_matrix(root)) <= 1e-5
    print("LIBRARY_INSTALLED_GRIP_ROTATION_TOOL_OK")


if "--verify-orientation" in sys.argv:
    from humanoid_mounts import equipment_orientation
    state.orientation = "X_POS"
    assert bpy.ops.humanoid_mounts.library_orientation() == {"FINISHED"}
    root = bpy.context.scene.hm_settings.equipment
    actual = equipment_orientation.current_correction(root).to_quaternion()
    expected = equipment_orientation.preset_rotation(root, "X_POS", "hand_r")
    assert actual.rotation_difference(expected).angle < 1e-5
    print("LIBRARY_INSTALLED_ORIENTATION_OK")


if "--verify-clear" in sys.argv:
    armature = bpy.context.scene.hm_settings.armature
    mount = bpy.context.scene.hm_settings.mount
    assert bpy.ops.humanoid_mounts.library_clear() == {"FINISHED"}
    assert bpy.context.scene.hm_settings.armature == armature
    assert mount.parent == armature
    assert not mount.children
    assert bpy.context.scene.hm_settings.equipment is None
    print("LIBRARY_INSTALLED_CLEAR_OK")


def show_panel():
    for area in bpy.context.screen.areas:
        if area.type == "VIEW_3D":
            area.spaces.active.show_region_ui = True
            area.spaces.active.region_3d.view_distance = 3.5
            area.spaces.active.region_3d.view_location = (0, 0, 1)
    return None


if not bpy.app.background:
    bpy.app.timers.register(show_panel, first_interval=1)
