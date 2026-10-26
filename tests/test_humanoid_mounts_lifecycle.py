import importlib
import pathlib
import unittest.mock

import bpy
from mathutils import Matrix

from test_humanoid_mounts_transform import MountFixture, evaluated_world, make_human, make_part

OUTPUT = pathlib.Path(__file__).resolve().parent / "out" / "humanoid_mounts"


class MountLifecycleTests(MountFixture):
    def setUp(self):
        super().setUp()
        self.package = importlib.import_module("humanoid_mounts")
        self.package.register()

    def tearDown(self):
        self.package.unregister()
        super().tearDown()

    def require_api(self, name):
        self.assertTrue(callable(getattr(self.mounts, name, None)), "Missing mount management contract: " + name)

    def test_five_parts_and_two_owners_are_isolated(self):
        self.require_api("mounts_for_armature")
        first, names = make_human("FirstHuman")
        second, other_names = make_human("SecondHuman")
        bindings = {"hand_r": "hand_r", "hand_l": "hand_l", "back": "chest", "waist": "hips", "head": "head"}
        created = [self.mounts.create_mount(first, names[role], part) for part, role in bindings.items()]
        other = self.mounts.create_mount(second, other_names["hand_r"], "hand_r")
        self.assertEqual(set(created), set(self.mounts.mounts_for_armature(first)))
        self.assertEqual([other], self.mounts.mounts_for_armature(second))
        settings = bpy.context.scene.hm_settings
        settings.armature = first
        bpy.context.view_layer.objects.active = other
        self.assertEqual(settings.armature, first)

    def test_copy_and_rename_do_not_copy_attachments(self):
        self.require_api("copy_mount")
        self.require_api("rename_mount")
        arm, names, mount, root, part = self.armed()
        self.weapons.bind_weapon(root, mount, "SNAP")
        copy = self.mounts.copy_mount(mount)
        self.assertNotEqual(copy, mount)
        self.assertEqual(copy.parent, arm)
        self.assertFalse(copy.children)
        self.assertMatrix(evaluated_world(copy), evaluated_world(mount))
        self.mounts.rename_mount(copy, "RightHandTool")
        self.assertEqual(copy.name, "RightHandTool")
        self.assertEqual(root.parent, mount)
        with self.assertRaises(self.mounts.HumanoidMountError):
            self.mounts.rename_mount(copy, "  ")
        self.assertEqual(copy.name, "RightHandTool")

    def test_reanchor_preserves_mount_and_attachment_world_pose(self):
        self.require_api("reanchor_mount")
        arm, names, mount, root, part = self.armed()
        self.weapons.bind_weapon(root, mount, "SNAP")
        mount_before = evaluated_world(mount)
        part_before = evaluated_world(part)
        self.mounts.reanchor_mount(mount, names["chest"])
        self.assertEqual(mount.parent_bone, names["chest"])
        self.assertMatrix(evaluated_world(mount), mount_before)
        self.assertMatrix(evaluated_world(part), part_before)

    def test_delete_keeps_weapons_and_foreign_objects(self):
        self.require_api("delete_mount")
        arm, names, mount, root, part = self.armed()
        self.weapons.bind_weapon(root, mount, "SNAP")
        foreign = make_part("UserAttachment")
        self.mounts.parent_at_world(foreign, mount, evaluated_world(foreign))
        before = {obj: evaluated_world(obj) for obj in (root, part, foreign)}
        name = mount.name
        self.mounts.delete_mount(mount)
        self.assertNotIn(name, bpy.data.objects)
        self.assertIsNone(root.parent)
        self.assertIsNone(foreign.parent)
        for obj, world in before.items():
            self.assertMatrix(evaluated_world(obj), world)

    def test_delete_preflight_does_not_partially_detach(self):
        self.require_api("delete_mount")
        arm, names, mount, root, part = self.armed()
        self.weapons.bind_weapon(root, mount, "SNAP")
        foreign = make_part("DrivenAttachment")
        self.mounts.parent_at_world(foreign, mount, evaluated_world(foreign))
        foreign.constraints.new("COPY_LOCATION")
        before = evaluated_world(root)
        with self.assertRaises(self.mounts.HumanoidMountError):
            self.mounts.delete_mount(mount)
        self.assertEqual(root.parent, mount)
        self.assertEqual(foreign.parent, mount)
        self.assertMatrix(evaluated_world(root), before)

    def test_bone_rename_is_native_and_missing_bone_can_detach(self):
        arm, names, mount, root, part = self.armed()
        arm.data.bones[names["hand_r"]].name = "RenamedHand"
        self.assertEqual(mount.parent_bone, "RenamedHand")
        self.weapons.bind_weapon(root, mount, "SNAP")
        bpy.context.view_layer.objects.active = arm
        bpy.ops.object.mode_set(mode="EDIT")
        arm.data.edit_bones.remove(arm.data.edit_bones["RenamedHand"])
        bpy.ops.object.mode_set(mode="OBJECT")
        with self.assertRaises(self.mounts.HumanoidMountError):
            self.mounts.validate_mount(mount)
        before = evaluated_world(root)
        self.weapons.detach_weapon(root)
        self.assertIsNone(root.parent)
        self.assertMatrix(evaluated_world(root), before)

    def test_unknown_schema_and_name_prefix_do_not_claim_user_data(self):
        arm, names, mount, root, part = self.armed()
        foreign = bpy.data.objects.new("Mount_hand_r_User", None)
        bpy.context.scene.collection.objects.link(foreign)
        with self.assertRaises(self.mounts.HumanoidMountError):
            self.mounts.validate_mount(foreign)
        mount["hm_schema"] = 900
        with self.assertRaises(self.mounts.HumanoidMountError):
            self.weapons.bind_weapon(root, mount, "SNAP")
        self.assertIsNone(root.parent)

    def test_partial_grip_preparation_restores_all_parts(self):
        parts = [make_part("PartA"), make_part("PartB", (2.0, 3.0, 1.0))]
        before = {part: evaluated_world(part) for part in parts}
        objects = set(bpy.data.objects)
        original = self.weapons.parent_at_world
        calls = []

        def fail_second(obj, parent, desired):
            calls.append(obj)
            if len(calls) == 2:
                raise RuntimeError("injected second-part failure")
            return original(obj, parent, desired)

        with unittest.mock.patch.object(self.weapons, "parent_at_world", side_effect=fail_second):
            with self.assertRaisesRegex(RuntimeError, "second-part"):
                self.weapons.prepare_grip_root(parts, Matrix.Identity(4))
        self.assertEqual(set(bpy.data.objects), objects)
        for part in parts:
            self.assertIsNone(part.parent)
            self.assertMatrix(evaluated_world(part), before[part])

    def test_partial_registration_failure_restores_registered_classes(self):
        self.package.unregister()
        original = bpy.utils.register_class
        calls = []

        def fail_third(cls):
            calls.append(cls)
            if len(calls) == 3:
                raise RuntimeError("injected registration failure")
            original(cls)

        with unittest.mock.patch.object(bpy.utils, "register_class", side_effect=fail_third):
            with self.assertRaisesRegex(RuntimeError, "registration"):
                self.package.register()
        self.assertFalse(hasattr(bpy.types.Scene, "hm_settings"))
        self.assertTrue(all("bl_rna" not in cls.__dict__ for cls in self.package.CLASSES))
        self.package.register()

    def test_repeated_registration_and_disable_keep_binding(self):
        arm, names, mount, root, part = self.armed()
        self.weapons.bind_weapon(root, mount, "SNAP")
        before = evaluated_world(part)
        self.package.register()
        self.package.unregister()
        self.package.unregister()
        self.assertEqual(root.parent, mount)
        self.assertEqual(mount.get("hm_kind"), "MOUNT")
        self.assertMatrix(evaluated_world(part), before)
        self.package.register()
        self.assertEqual(self.mounts.validate_mount(mount), arm)

    def test_failed_reanchor_keeps_native_parent_and_transform(self):
        self.require_api("reanchor_mount")
        arm, names, mount, root, part = self.armed()
        before = evaluated_world(mount)
        bone = mount.parent_bone
        with self.assertRaises(self.mounts.HumanoidMountError):
            self.mounts.reanchor_mount(mount, "not-a-bone")
        self.assertEqual(mount.parent_bone, bone)
        self.assertMatrix(evaluated_world(mount), before)

    def test_mark_existing_grip_is_explicit(self):
        self.assertTrue(callable(getattr(self.weapons, "register_grip_root", None)))
        part = make_part()
        root = bpy.data.objects.new("ExistingGrip", None)
        bpy.context.scene.collection.objects.link(root)
        self.mounts.parent_at_world(part, root, evaluated_world(part))
        self.assertNotIn("hm_kind", root)
        self.weapons.register_grip_root(root)
        self.assertEqual(root.get("hm_kind"), "GRIP")
        self.weapons.validate_grip(root)

    def test_operators_manage_mounts_through_current_human(self):
        arm, names, mount, root, part = self.armed()
        settings = bpy.context.scene.hm_settings
        settings.armature = arm
        settings.mount = mount
        settings.grip = root
        settings.bone_name = names["hand_r"]
        self.assertEqual(bpy.ops.humanoid_mounts.bind_weapon(rule="SNAP"), {"FINISHED"})
        self.assertTrue(hasattr(self.package.operators, "HM_OT_edit_mount"), "Management must be reachable in the UI")
        self.assertEqual(bpy.ops.humanoid_mounts.edit_mount(operation="COPY"), {"FINISHED"})
        copy = settings.mount
        self.assertNotEqual(copy, mount)
        settings.mount_name = "OperatorCopy"
        self.assertEqual(bpy.ops.humanoid_mounts.edit_mount(operation="RENAME"), {"FINISHED"})
        self.assertEqual(copy.name, "OperatorCopy")
        settings.bone_name = names["chest"]
        self.assertEqual(bpy.ops.humanoid_mounts.edit_mount(operation="REANCHOR"), {"FINISHED"})
        self.assertEqual(copy.parent_bone, names["chest"])
        self.assertEqual(bpy.ops.humanoid_mounts.edit_mount(operation="DELETE"), {"FINISHED"})
        self.assertEqual(root.parent, mount)

    def test_ui_rejects_a_mount_from_another_selected_human(self):
        arm, names, mount, root, part = self.armed()
        other, other_names = make_human("OtherUIHuman")
        settings = bpy.context.scene.hm_settings
        settings.armature = other
        settings.mount = mount
        settings.grip = root
        result = bpy.ops.humanoid_mounts.bind_weapon(rule="SNAP")
        self.assertEqual(result, {"CANCELLED"})
        self.assertIsNone(root.parent)
        self.assertEqual(settings.armature, other)

    def test_delete_midway_fault_restores_every_child(self):
        arm, names, mount, root, part = self.armed()
        self.weapons.bind_weapon(root, mount, "SNAP")
        foreign = make_part("SecondChild")
        self.mounts.parent_at_world(foreign, mount, evaluated_world(foreign))
        before = {obj: evaluated_world(obj) for obj in (root, foreign)}
        original = self.mounts.parent_at_world
        calls = []

        def fail_second(obj, parent, desired):
            calls.append(obj)
            if len(calls) == 2:
                raise RuntimeError("injected detach failure")
            return original(obj, parent, desired)

        with unittest.mock.patch.object(self.mounts, "parent_at_world", side_effect=fail_second):
            with self.assertRaisesRegex(RuntimeError, "detach failure"):
                self.mounts.delete_mount(mount)
        for obj, world in before.items():
            self.assertEqual(obj.parent, mount)
            self.assertMatrix(evaluated_world(obj), world)

    def test_create_failure_after_allocation_removes_only_new_mount(self):
        arm, names = make_human()
        before = set(bpy.data.objects)
        original = self.mounts.world_matrix

        def fail_mount(obj):
            if obj.get("hm_kind") == "MOUNT":
                raise RuntimeError("injected new-mount failure")
            return original(obj)

        with unittest.mock.patch.object(self.mounts, "world_matrix", side_effect=fail_mount):
            with self.assertRaisesRegex(RuntimeError, "new-mount"):
                self.mounts.create_mount(arm, names["hand_r"], "hand_r")
        self.assertEqual(set(bpy.data.objects), before)

    def test_reanchor_midway_failure_restores_parent_channels(self):
        arm, names, mount, root, part = self.armed()
        before = evaluated_world(mount)
        original = self.mounts.world_matrix
        calls = []

        def fail_changed_parent(obj):
            if obj == mount and obj.parent_bone == names["chest"]:
                calls.append(obj)
                raise RuntimeError("injected reanchor failure")
            return original(obj)

        with unittest.mock.patch.object(self.mounts, "world_matrix", side_effect=fail_changed_parent):
            with self.assertRaisesRegex(RuntimeError, "reanchor failure"):
                self.mounts.reanchor_mount(mount, names["chest"])
        self.assertTrue(calls)
        self.assertEqual(mount.parent_bone, names["hand_r"])
        self.assertMatrix(evaluated_world(mount), before)

    def test_ui_cannot_detach_another_humans_bound_weapon(self):
        arm, names, mount, root, part = self.armed()
        self.weapons.bind_weapon(root, mount, "SNAP")
        other, other_names = make_human("OtherDetachHuman")
        settings = bpy.context.scene.hm_settings
        settings.armature = other
        settings.grip = root
        before = evaluated_world(root)
        self.assertEqual(bpy.ops.humanoid_mounts.detach_weapon(), {"CANCELLED"})
        self.assertEqual(root.parent, mount)
        self.assertMatrix(evaluated_world(root), before)

    def test_ui_offset_poll_rejects_other_human_and_part(self):
        arm, names, mount, root, part = self.armed()
        self.weapons.bind_weapon(root, mount, "SNAP")
        other, other_names = make_human("OtherOffsetHuman")
        settings = bpy.context.scene.hm_settings
        settings.armature = other
        self.assertFalse(self.package.properties.mount_object(settings, mount))
        self.assertFalse(self.package.properties.grip_object(settings, root))
        settings.armature = arm
        settings.part = "head"
        self.assertFalse(self.package.properties.mount_object(settings, mount))

    def test_parent_cycle_is_rejected_before_native_mutation(self):
        arm, names, mount, root, part = self.armed()
        before = evaluated_world(root)
        with self.assertRaises(self.mounts.HumanoidMountError):
            self.mounts.parent_at_world(root, part, before)
        self.assertIsNone(root.parent)
        self.assertEqual(part.parent, root)
        self.assertMatrix(evaluated_world(root), before)

    def test_operator_right_hand_workflow_uses_cursor_without_switching_human(self):
        arm, names = make_human("OperatorWorkflowHuman")
        settings = bpy.context.scene.hm_settings
        settings.armature = arm
        settings.bone_name = names["hand_r"]
        self.assertEqual(bpy.ops.humanoid_mounts.create_mount(), {"FINISHED"})
        mount = settings.mount
        part = make_part("OperatorSword")
        before = evaluated_world(part)
        for obj in tuple(bpy.context.selected_objects):
            obj.select_set(False)
        part.select_set(True)
        bpy.context.view_layer.objects.active = part
        saved_cursor = bpy.context.scene.cursor.matrix.copy()
        try:
            bpy.context.scene.cursor.location = (3.0, 2.25, 0.5)
            anchor = bpy.context.scene.cursor.matrix.copy()
            self.assertEqual(bpy.ops.humanoid_mounts.prepare_grip(), {"FINISHED"})
            self.assertMatrix(evaluated_world(settings.grip), anchor)
            self.assertMatrix(evaluated_world(part), before)
            self.assertEqual(settings.armature, arm)
            self.assertEqual(bpy.ops.humanoid_mounts.bind_weapon(rule="SNAP"), {"FINISHED"})
            self.assertEqual(settings.grip.parent, mount)
            current = evaluated_world(settings.grip)
            self.assertEqual(bpy.ops.humanoid_mounts.detach_weapon(), {"FINISHED"})
            self.assertMatrix(evaluated_world(settings.grip), current)
        finally:
            bpy.context.scene.cursor.matrix = saved_cursor
