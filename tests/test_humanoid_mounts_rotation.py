import importlib
import unittest.mock

import bpy
from mathutils import Matrix

from test_humanoid_mounts_transform import MountFixture, make_human, make_part


class GripRotationTests(MountFixture):
    def setUp(self):
        super().setUp()
        self.package = importlib.import_module("humanoid_mounts")
        self.package.register()
        self.settings = bpy.context.scene.hm_settings
        arm, names = make_human("RotationToolHero")
        self.settings.armature = arm
        self.settings.part = "hand_r"
        self.mount = self.mounts.create_mount(arm, names["hand_r"], "hand_r")
        self.settings.mount = self.mount
        self.part = make_part("RotationToolSword")
        self.root = self.weapons.prepare_grip_root((self.part,), Matrix.Identity(4))
        self.root["hm_source_file"] = "rotation-tool-fixture.glb"
        self.weapons.bind_weapon(self.root, self.mount, "SNAP")
        self.package.operators.placement.select_equipment(self.settings, (self.root,), self.root)
        self.area = next(area for area in bpy.context.screen.areas if area.type == "VIEW_3D")
        self.region = next(region for region in self.area.regions if region.type == "WINDOW")
        self.orientation = bpy.context.scene.transform_orientation_slots[0].type
        self.pivot = bpy.context.scene.tool_settings.transform_pivot_point
        self.flags = (self.area.spaces.active.show_gizmo, self.area.spaces.active.show_gizmo_tool)
        self.area.spaces.active.show_gizmo = False
        self.area.spaces.active.show_gizmo_tool = False
        with bpy.context.temp_override(area=self.area, region=self.region):
            bpy.ops.wm.tool_set_by_id(name="builtin.select_box")

    def tearDown(self):
        try:
            self.package.unregister()
            self.area.spaces.active.show_gizmo, self.area.spaces.active.show_gizmo_tool = self.flags
            bpy.context.scene.transform_orientation_slots[0].type = self.orientation
            bpy.context.scene.tool_settings.transform_pivot_point = self.pivot
            with bpy.context.temp_override(area=self.area, region=self.region):
                bpy.ops.wm.tool_set_by_id(name="builtin.select_box")
        finally:
            super().tearDown()

    def current_tool(self):
        return bpy.context.workspace.tools.from_space_view3d_mode("OBJECT", create=False).idname

    def test_role_grip_button_activates_native_rotation_and_weapon_follows(self):
        before = self.mounts.world_matrix(self.part)
        with bpy.context.temp_override(area=self.area, region=self.region):
            self.assertEqual(bpy.ops.humanoid_mounts.fit_equipment(operation="CHARACTER"), {"FINISHED"})
        self.assertEqual(self.current_tool(), "builtin.rotate")
        self.assertTrue(self.area.spaces.active.show_gizmo)
        self.assertTrue(self.area.spaces.active.show_gizmo_tool)
        self.assertEqual(bpy.context.scene.transform_orientation_slots[0].type, "LOCAL")
        self.assertEqual(tuple(bpy.context.selected_objects), (self.mount,))
        self.assertEqual(bpy.context.object, self.mount)
        self.mount.rotation_euler.z += 0.5
        self.assertGreater(self.mounts.matrix_distance(self.mounts.world_matrix(self.part), before), 0.01)
        self.assertEqual(bpy.ops.humanoid_mounts.fit_equipment(operation="CANCEL"), {"FINISHED"})
        self.assertMatrix(self.mounts.world_matrix(self.part), before)

    def test_tool_controls_switch_move_and_world_rotation_without_transforming(self):
        self.assertIsNotNone(getattr(self.package.operators, "HM_OT_fitting_tool", None))
        with bpy.context.temp_override(area=self.area, region=self.region):
            bpy.ops.humanoid_mounts.fit_equipment(operation="CHARACTER")
            before = self.mounts.world_matrix(self.mount)
            self.assertEqual(bpy.ops.humanoid_mounts.fitting_tool(tool="MOVE", orientation="LOCAL"), {"FINISHED"})
            self.assertEqual(self.current_tool(), "builtin.move")
            self.assertEqual(bpy.ops.humanoid_mounts.fitting_tool(tool="ROTATE", orientation="GLOBAL"), {"FINISHED"})
            self.assertEqual(self.current_tool(), "builtin.rotate")
            self.assertEqual(bpy.context.scene.transform_orientation_slots[0].type, "GLOBAL")
            self.assertMatrix(self.mounts.world_matrix(self.mount), before)
            self.assertEqual(bpy.ops.humanoid_mounts.fit_equipment(operation="SAVE"), {"FINISHED"})
        self.assertTrue(self.mount["hm_grip_fitted"])

    def test_failed_tool_activation_cancels_fitting_and_restores_pose(self):
        self.assertTrue(hasattr(self.package.operators, "activate_fitting_tool"))
        before = self.mounts.world_matrix(self.mount)
        with unittest.mock.patch.object(self.package.operators, "activate_fitting_tool", side_effect=self.mounts.HumanoidMountError("tool unavailable")):
            self.assertEqual(bpy.ops.humanoid_mounts.fit_equipment(operation="CHARACTER"), {"CANCELLED"})
        self.assertEqual(self.settings.fitting_stage, "NONE")
        self.assertMatrix(self.mounts.world_matrix(self.mount), before)

    def test_panel_exposes_rotation_controls_only_during_fitting(self):
        from test_humanoid_mounts_guided import LayoutRecorder
        self.package.operators.placement.begin_fitting(self.settings, "CHARACTER")
        recorder = LayoutRecorder()
        panel = type("PanelInstance", (), {"layout": recorder})()
        self.package.panels.HM_PT_mounts.draw(panel, bpy.context)
        self.assertIn(("operator", "humanoid_mounts.fitting_tool"), recorder.events)
