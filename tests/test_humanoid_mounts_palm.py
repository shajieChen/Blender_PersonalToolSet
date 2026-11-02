import importlib
import unittest.mock

import bpy
from mathutils import Vector

from test_humanoid_mounts_transform import MountFixture, make_human


class PalmPositionTests(MountFixture):
    def setUp(self):
        super().setUp()
        self.package = importlib.import_module("humanoid_mounts")
        self.package.register()
        self.settings = bpy.context.scene.hm_settings
        self.arm, self.names = make_human("PalmPositionHero")
        self.settings.armature = self.arm
        self.settings.part = "hand_r"
        bpy.context.view_layer.objects.active = self.arm
        bpy.ops.object.mode_set(mode="EDIT")
        hand = self.arm.data.edit_bones[self.names["hand_r"]]
        for index, name in enumerate(("index_proximal.R", "middle_proximal.R", "ring_proximal.R", "little_proximal.R")):
            bone = self.arm.data.edit_bones.new(name)
            bone.head = hand.head + Vector((0.1, 0.1 + index * 0.01, 0.02))
            bone.tail = bone.head + Vector((0, 0.05, 0))
            bone.parent = hand
        bpy.ops.object.mode_set(mode="OBJECT")
        self.mount = self.mounts.create_mount(self.arm, self.names["hand_r"], "hand_r")
        self.settings.mount = self.mount
        self.mount.rotation_euler = (0.1, 0.3, -0.2)
        self.mount["hm_grip_fitted"] = True
        bpy.context.view_layer.update()

    def tearDown(self):
        try:
            self.package.unregister()
        finally:
            super().tearDown()

    def expected_palm(self):
        evaluated = self.arm.evaluated_get(bpy.context.evaluated_depsgraph_get())
        hand = evaluated.pose.bones[self.names["hand_r"]]
        children = [child for child in hand.children if any(key in child.name.lower() for key in ("index", "middle", "ring", "little"))]
        center = sum((evaluated.matrix_world @ child.head for child in children), Vector()) / len(children)
        return (evaluated.matrix_world @ hand.head + center) * 0.5

    def test_estimate_moves_mount_to_pose_palm_preserving_rotation_and_parent(self):
        hand = self.arm.pose.bones[self.names["hand_r"]]
        hand.rotation_mode = "XYZ"
        hand.rotation_euler = (0.3, -0.2, 0.4)
        bpy.context.view_layer.update()
        expected = self.expected_palm()
        before = self.mount.matrix_basis.copy()
        self.assertEqual(bpy.ops.humanoid_mounts.estimate_palm(), {"FINISHED"})
        self.assertLess((self.mounts.world_matrix(self.mount).translation - expected).length, 1e-5)
        self.assertEqual(self.mount.parent, self.arm)
        self.assertEqual(self.mount.parent_bone, self.names["hand_r"])
        self.assertLess(max(abs(self.mount.matrix_basis[r][c] - before[r][c]) for r in range(3) for c in range(3)), 1e-5)
        self.assertFalse(self.mount["hm_grip_fitted"])

    def test_insufficient_fingers_leaves_existing_mount_untouched(self):
        bpy.context.view_layer.objects.active = self.arm
        bpy.ops.object.mode_set(mode="EDIT")
        for name in ("middle_proximal.R", "ring_proximal.R", "little_proximal.R"):
            self.arm.data.edit_bones.remove(self.arm.data.edit_bones[name])
        bpy.ops.object.mode_set(mode="OBJECT")
        before = self.mounts.world_matrix(self.mount)
        self.assertEqual(bpy.ops.humanoid_mounts.estimate_palm(), {"CANCELLED"})
        self.assertMatrix(self.mounts.world_matrix(self.mount), before)
        self.assertTrue(self.mount["hm_grip_fitted"])

    def test_non_hand_and_fitting_rejected_without_change(self):
        before = self.mounts.world_matrix(self.mount)
        self.settings.part = "head"
        self.assertEqual(bpy.ops.humanoid_mounts.estimate_palm(), {"CANCELLED"})
        self.settings.part = "hand_r"
        self.settings.fitting_stage = "CHARACTER"
        self.assertEqual(bpy.ops.humanoid_mounts.estimate_palm(), {"CANCELLED"})
        self.settings.fitting_stage = "NONE"
        self.assertMatrix(self.mounts.world_matrix(self.mount), before)

    def test_main_panel_exposes_estimate_button(self):
        from test_humanoid_mounts_guided import LayoutRecorder
        recorder = LayoutRecorder()
        panel = type("PanelInstance", (), {"layout": recorder})()
        self.package.panels.HM_PT_mounts.draw(panel, bpy.context)
        self.assertIn(("operator", "humanoid_mounts.estimate_palm"), recorder.events)

    def test_failure_after_reposition_restores_mount_and_calibration(self):
        before = self.mounts.world_matrix(self.mount)
        original = self.mounts.world_matrix
        calls = []
        def fail_after_move(obj):
            result = original(obj)
            if obj == self.mount:
                calls.append(obj)
                if len(calls) == 2:
                    raise self.mounts.HumanoidMountError("injected failure")
            return result
        with unittest.mock.patch.object(self.mounts, "world_matrix", side_effect=fail_after_move):
            self.assertEqual(bpy.ops.humanoid_mounts.estimate_palm(), {"CANCELLED"})
        self.assertMatrix(self.mounts.world_matrix(self.mount), before)
        self.assertTrue(self.mount["hm_grip_fitted"])
        self.assertEqual(self.settings.mount, self.mount)

    def test_multiple_mounts_require_explicit_choice(self):
        self.mounts.create_mount(self.arm, self.names["hand_r"], "hand_r")
        self.settings.mount = None
        before = self.mounts.world_matrix(self.mount)
        self.assertEqual(bpy.ops.humanoid_mounts.estimate_palm(), {"CANCELLED"})
        self.assertMatrix(self.mounts.world_matrix(self.mount), before)

    def test_attached_grip_follows_palm_mount(self):
        from test_humanoid_mounts_transform import make_part
        from mathutils import Matrix
        root = self.weapons.prepare_grip_root((make_part("PalmAttachedWeapon"),), Matrix.Identity(4))
        self.weapons.bind_weapon(root, self.mount, "SNAP")
        self.assertEqual(bpy.ops.humanoid_mounts.estimate_palm(), {"FINISHED"})
        self.assertEqual(root.parent, self.mount)
        self.assertMatrix(self.mounts.world_matrix(root), self.mounts.world_matrix(self.mount))
        self.assertLess((self.mounts.world_matrix(root).translation - self.expected_palm()).length, 1e-5)

    def test_missing_mount_uses_retargeted_hand_and_creates_one(self):
        from humanoid_retarget.mapping import save_target_roles
        save_target_roles(self.arm, (("hand_r", "SourceHand", self.names["hand_r"]),))
        bpy.data.objects.remove(self.mount, do_unlink=True)
        self.settings.mount = None
        expected = self.expected_palm()
        self.assertEqual(bpy.ops.humanoid_mounts.estimate_palm(), {"FINISHED"})
        self.mount = self.settings.mount
        self.assertEqual(self.mount.parent_bone, self.names["hand_r"])
        self.assertLess((self.mounts.world_matrix(self.mount).translation - expected).length, 1e-5)

    def test_duplicate_finger_names_are_rejected(self):
        bpy.context.view_layer.objects.active = self.arm
        bpy.ops.object.mode_set(mode="EDIT")
        hand = self.arm.data.edit_bones[self.names["hand_r"]]
        bone = self.arm.data.edit_bones.new("R_Finger1")
        bone.head = hand.head + Vector((0.1, 0.1, 0.02))
        bone.tail = bone.head + Vector((0, 0.05, 0))
        bone.parent = hand
        bpy.ops.object.mode_set(mode="OBJECT")
        before = self.mounts.world_matrix(self.mount)
        self.assertEqual(bpy.ops.humanoid_mounts.estimate_palm(), {"CANCELLED"})
        self.assertMatrix(self.mounts.world_matrix(self.mount), before)
