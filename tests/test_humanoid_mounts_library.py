import importlib
import pathlib
import tempfile
import unittest.mock

import bpy
from mathutils import Matrix

from test_humanoid_mounts_transform import MountFixture, make_part, make_human


class EquipmentLibraryTests(MountFixture):
    def setUp(self):
        super().setUp()
        self.assertIsNotNone(importlib.util.find_spec("humanoid_mounts.library"), "External equipment library is missing")
        self.library = importlib.import_module("humanoid_mounts.library")
        self.package = importlib.import_module("humanoid_mounts")
        self.package.register()
        self.settings = bpy.context.scene.hm_settings
        bpy.context.window_manager.hm_library.is_expanded = True
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)

    def tearDown(self):
        package = importlib.import_module("humanoid_mounts")
        package.unregister()
        super().tearDown()

    def test_tool_config_resolves_relative_to_tool_and_reads_names_without_execution(self):
        tool = self.root / "tool"
        tool.mkdir()
        (tool / "preview").mkdir()
        (tool / "preview" / "server.py").write_text("ITEM_NAMES = {'0300': 'Test Sword'}\nraise RuntimeError('must not execute')", encoding="utf-8")
        (tool / "config.json").write_text('{"resourceDir": "../assets"}', encoding="utf-8")
        model = self.root / "assets/preview/parts/wp_a_0300.partsbnd/parts/Weapon/WP_A_0300.glb"
        model.parent.mkdir(parents=True)
        model.touch()
        base, rows = self.library.scan_library(tool)
        self.assertEqual(base, (self.root / "assets/preview").resolve())
        self.assertEqual(len(rows), 1)
        self.assertIn("Test Sword", rows[0].name)
        self.assertFalse(pathlib.Path(rows[0].relative_path).is_absolute())

    def test_external_directory_and_missing_directory(self):
        (self.root / "sword.glb").touch()
        (self.root / "ignore.txt").touch()
        base, rows = self.library.scan_library(self.root)
        self.assertEqual(len(rows), 1)
        with self.assertRaises(ValueError):
            self.library.scan_library(self.root / "missing")

    def test_real_tool_lists_items_and_keeps_all_resources_external(self):
        base, rows = self.library.scan_library(pathlib.Path("H:/SErsiko_ExtactedTool"))
        self.assertGreater(len(rows), 0)
        self.assertTrue(any("楔丸" in item.name for item in rows))
        self.assertTrue(all((base / item.relative_path).is_file() for item in rows))
        self.assertTrue(all(item.relative_path.startswith("parts/wp_a_") for item in rows))

    def test_load_real_sword_and_mount_preserves_character(self):
        from humanoid_retarget.mapping import save_target_roles
        base, rows = self.library.scan_library(pathlib.Path("H:/SErsiko_ExtactedTool"))
        sword = next(item for item in rows if item.relative_path.endswith("WP_A_0300.glb") and item.tier == "std")
        arm, names = make_human("LibraryHero")
        save_target_roles(arm, [(role, "Source_" + role, bone) for role, bone in names.items()])
        self.settings.armature = arm
        self.settings.part = "hand_r"
        self.library.load_equipment(bpy.context, base, sword.relative_path, attach=True)
        root = self.settings.equipment
        self.assertEqual(self.settings.armature, arm)
        self.assertEqual(root.parent, self.settings.mount)
        self.assertEqual(root.parent.parent, arm)
        self.assertTrue(any(obj.type == "MESH" for obj in root.children_recursive))
        self.assertTrue(root.get("hm_source_file"))
        self.weapons.validate_grip(root)

    def test_failed_import_restores_objects_selection_and_settings(self):
        obj = make_part("ExistingSelection")
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        before = set(bpy.data.objects)
        def fail(**kwargs):
            make_part("PartialImport")
            raise RuntimeError("broken file")
        with unittest.mock.patch.object(self.library, "import_gltf", side_effect=fail):
            with self.assertRaises(RuntimeError):
                self.library.load_equipment(bpy.context, self.root, "bad.glb", attach=False)
        self.assertEqual(set(bpy.data.objects), before)
        self.assertEqual(bpy.context.object, obj)
        self.assertEqual(tuple(bpy.context.selected_objects), (obj,))

    def test_path_escape_is_rejected(self):
        with self.assertRaises(ValueError):
            self.library.load_equipment(bpy.context, self.root, "../outside.glb", attach=False)

    def test_directory_memory_filter_and_unregister_lifecycle(self):
        from humanoid_mounts import library_browser
        state = bpy.context.window_manager.hm_library
        state.directory = str(self.root)
        (self.root / "Sword.glb").touch()
        config = self.root / "settings.json"
        with unittest.mock.patch.object(library_browser, "settings_file", return_value=config):
            library_browser.refresh(state)
            self.assertEqual(library_browser.remembered_directory(), str(self.root.resolve()))
        self.assertEqual(len(state.items), 1)
        state.search = "sword"
        self.assertTrue(library_browser.entry_visible(state, state.items[0]))
        state.search = "absent"
        self.assertFalse(library_browser.entry_visible(state, state.items[0]))
        self.assertEqual(bpy.ops.humanoid_mounts.library_load(), {"CANCELLED"})
        state.directory = str(self.root / "missing")
        self.assertEqual(len(state.items), 0)
        self.package.unregister()
        self.assertFalse(hasattr(bpy.types.WindowManager, "hm_library"))
        self.assertFalse(bpy.app.timers.is_registered(library_browser.initial_refresh))
        self.package.register()

    def test_failure_after_mount_restores_equipment_and_removes_new_mount(self):
        from humanoid_retarget.mapping import save_target_roles
        base, rows = self.library.scan_library(pathlib.Path("H:/SErsiko_ExtactedTool"))
        sword = next(item for item in rows if item.relative_path.endswith("WP_A_0300.glb") and item.tier == "std")
        arm, names = make_human("FailureHero")
        save_target_roles(arm, [(role, "Source_" + role, bone) for role, bone in names.items()])
        self.settings.armature = arm
        original = make_part("PreviousEquipment")
        self.library.placement.select_equipment(self.settings, (original,), original)
        before = set(bpy.data.objects)
        with unittest.mock.patch.object(self.library.placement, "select_equipment", side_effect=RuntimeError("publish failure")):
            with self.assertRaises(RuntimeError):
                self.library.load_equipment(bpy.context, base, sword.relative_path, attach=True)
        self.assertEqual(set(bpy.data.objects), before)
        self.assertEqual(self.settings.equipment, original)
        self.assertEqual([item.object for item in self.settings.equipment_parts], [original])
        self.assertIsNone(self.settings.mount)

    def test_collapsed_library_draws_only_title(self):
        from humanoid_mounts import library_browser
        from test_humanoid_mounts_guided import LayoutRecorder
        state = bpy.context.window_manager.hm_library
        state.is_expanded = False
        recorder = LayoutRecorder()
        library_browser.draw_library(recorder, bpy.context)
        self.assertIn(("prop", "is_expanded"), recorder.events)
        self.assertNotIn(("prop", "directory"), recorder.events)
        self.assertFalse(any(kind == "operator" for kind, name in recorder.events))

    def test_import_snaps_to_explicit_offset_mount_on_moved_character(self):
        from humanoid_retarget.mapping import save_target_roles
        arm, names = make_human("MovedLibraryHero")
        arm.location = (7, -3, 2)
        save_target_roles(arm, [(role, "Source_" + role, bone) for role, bone in names.items()])
        self.settings.armature = arm
        self.settings.part = "hand_r"
        other = self.mounts.create_mount(arm, names["hand_r"], "hand_r")
        target = self.mounts.create_mount(arm, names["hand_r"], "hand_r")
        target.location.x += 0.4
        target["hm_grip_fitted"] = True
        self.settings.mount = target
        base, rows = self.library.scan_library(pathlib.Path("H:/SErsiko_ExtactedTool"))
        sword = next(item for item in rows if item.relative_path.endswith("WP_A_0300.glb") and item.tier == "std")
        root = self.library.load_equipment(bpy.context, base, sword.relative_path, attach=True)
        self.assertEqual(root.parent, target)
        self.assertNotEqual(root.parent, other)
        self.assertMatrix(self.mounts.world_matrix(root), self.mounts.world_matrix(target))
        self.assertTrue(target["hm_grip_fitted"])

    def test_clear_removes_all_equipment_only_from_current_character(self):
        arm, names = make_human("ClearHero")
        other, other_names = make_human("OtherClearHero")
        self.settings.armature = arm
        keep = make_part("UnrelatedObject")
        first = self.mounts.create_mount(arm, names["hand_r"], "hand_r")
        second = self.mounts.create_mount(arm, names["head"], "head")
        foreign = self.mounts.create_mount(other, other_names["hand_r"], "hand_r")
        first["hm_grip_fitted"] = True
        roots = []
        for mount in (first, second, foreign):
            part = make_part("ClearPart")
            root = self.weapons.prepare_grip_root((part,), Matrix.Identity(4))
            self.weapons.bind_weapon(root, mount, "SNAP")
            roots.append(root)
        removed = {obj.name for root in roots[:2] for obj in (root, *root.children_recursive)}
        self.library.placement.select_equipment(self.settings, (roots[0],), roots[0])
        self.assertEqual(self.library.clear_character_equipment(self.settings), 2)
        self.assertFalse(removed.intersection(bpy.data.objects.keys()))
        self.assertEqual(roots[2].parent, foreign)
        self.assertIn(keep.name, bpy.data.objects)
        self.assertTrue(first["hm_grip_fitted"])
        self.assertIn(second.name, bpy.data.objects)
        self.assertIsNone(self.settings.equipment)
        self.assertEqual(self.library.clear_character_equipment(self.settings), 0)

    def test_clear_preflight_failure_does_not_delete_any_equipment(self):
        arm, names = make_human("ClearFailureHero")
        self.settings.armature = arm
        mount = self.mounts.create_mount(arm, names["hand_r"], "hand_r")
        part = make_part("RetainedPart")
        root = self.weapons.prepare_grip_root((part,), Matrix.Identity(4))
        self.weapons.bind_weapon(root, mount, "SNAP")
        camera = bpy.data.objects.new("UnexpectedCamera", bpy.data.cameras.new("UnexpectedCamera"))
        bpy.context.scene.collection.objects.link(camera)
        camera.parent = mount
        before = set(bpy.data.objects)
        with self.assertRaises(self.mounts.HumanoidMountError):
            self.library.clear_character_equipment(self.settings)
        self.assertEqual(before, set(bpy.data.objects))

    def test_clear_includes_owned_preview_but_preserves_unowned_preview(self):
        arm, names = make_human("PreviewClearHero")
        self.settings.armature = arm
        base, rows = self.library.scan_library(pathlib.Path("H:/SErsiko_ExtactedTool"))
        sword = next(item for item in rows if item.relative_path.endswith("WP_A_0300.glb") and item.tier == "std")
        root = self.library.load_equipment(bpy.context, base, sword.relative_path, attach=False)
        self.assertEqual(root.get("hm_library_owner"), arm)
        owned_names = {obj.name for obj in (root, *root.children_recursive)}
        unowned = self.weapons.prepare_grip_root((make_part("UnownedPreview"),), Matrix.Identity(4))
        self.assertEqual(self.library.clear_character_equipment(self.settings), 1)
        self.assertFalse(owned_names.intersection(bpy.data.objects.keys()))
        self.assertIn(unowned.name, bpy.data.objects)

    def test_clear_rejects_objects_shared_with_other_scene(self):
        arm, names = make_human("SharedClearHero")
        self.settings.armature = arm
        mount = self.mounts.create_mount(arm, names["hand_r"], "hand_r")
        root = self.weapons.prepare_grip_root((make_part("SharedPart"),), Matrix.Identity(4))
        self.weapons.bind_weapon(root, mount, "SNAP")
        scene = bpy.data.scenes.new("OtherEquipmentScene")
        try:
            scene.collection.objects.link(root)
            before = set(bpy.data.objects)
            with self.assertRaises(self.mounts.HumanoidMountError):
                self.library.clear_character_equipment(self.settings)
            self.assertEqual(set(bpy.data.objects), before)
        finally:
            bpy.data.scenes.remove(scene)

    def test_library_shows_target_and_confirmed_sheath_name(self):
        from humanoid_mounts import library_browser
        from test_humanoid_mounts_guided import LayoutRecorder
        base, rows = self.library.scan_library(pathlib.Path("H:/SErsiko_ExtactedTool"))
        self.assertTrue(any("剑鞘" in item.name and "WP_A_0300_1" in item.name for item in rows))
        arm, names = make_human("TargetLabelHero")
        self.settings.armature = arm
        self.settings.part = "hand_r"
        target = self.mounts.create_mount(arm, names["hand_r"], "hand_r")
        self.settings.mount = target
        bpy.context.window_manager.hm_library.is_expanded = True
        recorder = LayoutRecorder()
        library_browser.draw_library(recorder, bpy.context)
        self.assertIn(("label", "目标角色：" + arm.name), recorder.events)
        self.assertIn(("label", "目标骨骼：" + target.parent_bone), recorder.events)
        self.assertIn(("label", "目标挂点：" + target.name), recorder.events)
        self.assertIn(("operator", "humanoid_mounts.library_clear"), recorder.events)

    def test_orientation_presets_are_absolute_and_preserve_mount(self):
        self.assertIsNotNone(importlib.util.find_spec("humanoid_mounts.equipment_orientation"))
        from humanoid_mounts import equipment_orientation
        from mathutils import Quaternion, Vector
        arm, names = make_human("OrientationHero")
        self.settings.armature = arm
        self.settings.part = "hand_r"
        target = self.mounts.create_mount(arm, names["hand_r"], "hand_r")
        self.settings.mount = target
        base, rows = self.library.scan_library(pathlib.Path("H:/SErsiko_ExtactedTool"))
        sword = next(item for item in rows if item.relative_path.endswith("WP_A_0300.glb") and item.tier == "std")
        root = self.library.load_equipment(bpy.context, base, sword.relative_path, attach=True)
        before = self.mounts.world_matrix(target)
        equipment_orientation.apply_preset(root, "X_POS", "hand_r")
        pose = equipment_orientation.current_correction(root)
        expected = Quaternion(Vector((1, 0, 0)), 1.5707963267948966)
        self.assertLess(pose.to_quaternion().rotation_difference(expected).angle, 1e-5)
        equipment_orientation.apply_preset(root, "X_POS", "hand_r")
        self.assertMatrix(equipment_orientation.current_correction(root), pose)
        self.assertMatrix(self.mounts.world_matrix(target), before)
        equipment_orientation.apply_preset(root, "ORIGINAL", "hand_r")
        self.assertMatrix(equipment_orientation.current_correction(root), Matrix.Identity(4))

    def test_saved_orientation_survives_fitting_bake_and_new_import(self):
        self.assertIsNotNone(importlib.util.find_spec("humanoid_mounts.equipment_orientation"))
        from humanoid_mounts import equipment_orientation
        arm, names = make_human("SavedOrientationHero")
        self.settings.armature = arm
        self.settings.part = "hand_r"
        target = self.mounts.create_mount(arm, names["hand_r"], "hand_r")
        target["hm_grip_fitted"] = True
        self.settings.mount = target
        base, rows = self.library.scan_library(pathlib.Path("H:/SErsiko_ExtactedTool"))
        sword = next(item for item in rows if item.relative_path.endswith("WP_A_0300.glb") and item.tier == "std")
        root = self.library.load_equipment(bpy.context, base, sword.relative_path, attach=True)
        equipment_orientation.apply_preset(root, "X_POS", "hand_r")
        self.library.placement.begin_fitting(self.settings, "EQUIPMENT")
        root.rotation_euler.z += 0.3
        self.library.placement.save_fitting(self.settings)
        expected = equipment_orientation.current_correction(root).to_quaternion()
        with unittest.mock.patch.object(equipment_orientation, "profile_file", return_value=self.root / "orientations.json"):
            equipment_orientation.save_orientation(root, "hand_r")
            other = self.library.load_equipment(bpy.context, base, sword.relative_path, attach=True, orientation="AUTO")
            actual = equipment_orientation.current_correction(other).to_quaternion()
            self.assertLess(actual.rotation_difference(expected).angle, 1e-5)
            equipment_orientation.apply_preset(other, "AUTO", "head")
            self.assertMatrix(equipment_orientation.current_correction(other), Matrix.Identity(4))

    def test_orientation_failure_restores_all_parts_and_bad_profile_changes_nothing(self):
        from humanoid_mounts import equipment_orientation
        base, rows = self.library.scan_library(pathlib.Path("H:/SErsiko_ExtactedTool"))
        sword = next(item for item in rows if item.relative_path.endswith("WP_A_0300.glb") and item.tier == "std")
        root = self.library.load_equipment(bpy.context, base, sword.relative_path, attach=False)
        before = {obj: self.mounts.world_matrix(obj) for obj in root.children}
        original = self.mounts.parent_at_world
        calls = []
        def fail(obj, parent, desired):
            calls.append(obj)
            if len(calls) == 2:
                raise RuntimeError("orientation failure")
            return original(obj, parent, desired)
        with unittest.mock.patch.object(self.mounts, "parent_at_world", side_effect=fail):
            with self.assertRaises(RuntimeError):
                equipment_orientation.apply_preset(root, "X_POS", "hand_r")
        self.assertGreaterEqual(len(calls), 2)
        for obj, pose in before.items():
            self.assertMatrix(self.mounts.world_matrix(obj), pose)
        profile = self.root / "bad-orientation.json"
        profile.write_text("[]", encoding="utf-8")
        with unittest.mock.patch.object(equipment_orientation, "profile_file", return_value=profile):
            with self.assertRaises(ValueError):
                equipment_orientation.apply_preset(root, "AUTO", "hand_r")
        for obj, pose in before.items():
            self.assertMatrix(self.mounts.world_matrix(obj), pose)

    def test_library_current_equipment_snaps_without_calibration_on_sheared_rig(self):
        from humanoid_retarget.mapping import save_target_roles
        from mathutils import Euler
        arm, names = make_human("ShearedLibraryHero")
        arm.location = (4, -2, 1)
        arm.scale = (0.2, 0.35, 0.5)
        hand = arm.pose.bones[names["hand_r"]]
        hand.rotation_mode = "XYZ"
        hand.rotation_euler = (0.3, 0.5, -0.4)
        save_target_roles(arm, [(role, "Source_" + role, bone) for role, bone in names.items()])
        self.settings.armature = arm
        self.settings.part = "hand_r"
        expected = self.mounts.world_matrix(arm) @ arm.evaluated_get(bpy.context.evaluated_depsgraph_get()).pose.bones[hand.name].matrix
        with self.assertRaises(self.mounts.HumanoidMountError):
            self.mounts.validate_matrix(expected)
        base, rows = self.library.scan_library(pathlib.Path("H:/SErsiko_ExtactedTool"))
        item = next(item for item in rows if item.relative_path.endswith("WP_A_0301_1.glb") and item.tier == "std")
        root = self.library.load_equipment(bpy.context, base, item.relative_path, attach=False)
        root.delta_location = (0.2, -0.1, 0.3)
        root.delta_rotation_euler = (0.1, 0.2, 0.3)
        root.delta_scale = (1.1, 0.9, 1.2)
        before = set(bpy.data.objects)
        result = bpy.ops.humanoid_mounts.equip_weapon()
        self.assertEqual(result, {"FINISHED"})
        self.assertEqual(len(set(bpy.data.objects) - before), 1)
        mount = self.settings.mount
        self.assertEqual(root.parent, mount)
        self.assertEqual(tuple(root.location), (0, 0, 0))
        self.assertMatrix(root.matrix_basis, Matrix.Identity(4))
        self.assertMatrix(root.matrix_parent_inverse, Matrix.Identity(4))
        self.assertMatrix(self.mounts.world_matrix(root), self.mounts.world_matrix(mount))
        self.assertMatrix(self.mounts.world_matrix(mount), expected)
        self.weapons.validate_grip(root)
        hand.rotation_euler.z += 0.4
        self.assertMatrix(self.mounts.world_matrix(root), self.mounts.world_matrix(mount))
        self.assertEqual(self.library.placement.equipment_status(self.settings).step, "EQUIPPED")
        with self.assertRaises(self.mounts.HumanoidMountError):
            self.weapons.detach_weapon(root)
        self.assertEqual(root.parent, mount)
        self.assertEqual(self.library.clear_character_equipment(self.settings), 1)

    def test_library_load_and_orientation_work_under_sheared_mount(self):
        from humanoid_retarget.mapping import save_target_roles
        from humanoid_mounts import equipment_orientation
        arm, names = make_human("ShearedImportHero")
        arm.scale = (0.2, 0.35, 0.5)
        save_target_roles(arm, [(role, "Source_" + role, bone) for role, bone in names.items()])
        self.settings.armature = arm
        self.settings.part = "hand_r"
        hand = arm.pose.bones[names["hand_r"]]
        hand.rotation_mode = "XYZ"
        hand.rotation_euler = (0.3, 0.5, -0.4)
        mount = self.mounts.create_mount(arm, names["hand_r"], "hand_r")
        self.settings.mount = mount
        base, rows = self.library.scan_library(pathlib.Path("H:/SErsiko_ExtactedTool"))
        item = next(item for item in rows if item.relative_path.endswith("WP_A_0300.glb") and item.tier == "std")
        root = self.library.load_equipment(bpy.context, base, item.relative_path, attach=True, orientation="X_POS")
        self.assertEqual(root.parent, mount)
        self.assertMatrix(root.matrix_basis, Matrix.Identity(4))
        self.assertMatrix(self.mounts.world_matrix(root), self.mounts.world_matrix(mount))
        equipment_orientation.apply_preset(root, "Z_POS", "hand_r")
        self.assertMatrix(root.matrix_basis, Matrix.Identity(4))

    def test_current_snap_button_is_visible_for_loaded_library_prop(self):
        from humanoid_mounts import library_browser
        from test_humanoid_mounts_guided import LayoutRecorder
        arm, names = make_human("SnapButtonHero")
        self.settings.armature = arm
        self.settings.mount = self.mounts.create_mount(arm, names["hand_r"], "hand_r")
        root = self.weapons.prepare_grip_root((make_part("SnapButtonPart"),), Matrix.Identity(4))
        root["hm_source_file"] = "fixture.glb"
        self.library.placement.select_equipment(self.settings, (root,), root)
        recorder = LayoutRecorder()
        library_browser.draw_library(recorder, bpy.context)
        self.assertIn(("operator", "humanoid_mounts.equip_weapon"), recorder.events)
        self.assertEqual(self.library.placement.equipment_status(self.settings).step, "READY")

    def test_zero_snap_failure_restores_all_delta_channels(self):
        arm, names = make_human("SnapFailureHero")
        mount = self.mounts.create_mount(arm, names["hand_r"], "hand_r")
        root = self.weapons.prepare_grip_root((make_part("SnapFailurePart"),), Matrix.Identity(4))
        root.delta_location = (0.2, -0.1, 0.4)
        root.delta_rotation_euler = (0.1, 0.3, 0.2)
        root.delta_scale = (1.1, 0.9, 1.2)
        before = self.mounts.world_matrix(root)
        delta = (tuple(root.delta_location), tuple(root.delta_rotation_euler), tuple(root.delta_scale))
        with unittest.mock.patch.object(self.weapons, "world_matrix", side_effect=RuntimeError("post-snap failure")):
            with self.assertRaises(RuntimeError):
                self.weapons.bind_weapon(root, mount, "SNAP")
        self.assertIsNone(root.parent)
        self.assertMatrix(self.mounts.world_matrix(root), before)
        self.assertEqual((tuple(root.delta_location), tuple(root.delta_rotation_euler), tuple(root.delta_scale)), delta)

    def test_unbound_library_equipment_fitting_fails_before_creating_mount(self):
        from humanoid_retarget.mapping import save_target_roles
        arm, names = make_human("UnboundFitHero")
        save_target_roles(arm, [(role, "Source_" + role, bone) for role, bone in names.items()])
        self.settings.armature = arm
        root = self.weapons.prepare_grip_root((make_part("UnboundFitPart"),), Matrix.Identity(4))
        root["hm_source_file"] = "fixture.glb"
        self.library.placement.select_equipment(self.settings, (root,), root)
        before = set(bpy.data.objects)
        with self.assertRaises(self.mounts.HumanoidMountError):
            self.library.placement.begin_fitting(self.settings, "EQUIPMENT")
        self.assertEqual(self.settings.fitting_stage, "NONE")
        self.assertEqual(set(bpy.data.objects), before)
