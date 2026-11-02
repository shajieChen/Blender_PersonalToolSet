import importlib
import json
import os
import pathlib
import subprocess
import unittest.mock

import bpy
from mathutils import Matrix, Vector

from test_humanoid_mounts_transform import MountFixture, evaluated_world, make_human, make_part


class LayoutRecorder:
    def __init__(self, events=None):
        self.events = events if events is not None else []
        self.enabled = True

    def row(self, **kwargs):
        return self

    def column(self, **kwargs):
        return self

    def box(self):
        return self

    def label(self, **kwargs):
        self.events.append(("label", kwargs.get("text", "")))

    def prop(self, obj, name, **kwargs):
        self.events.append(("prop", name))

    def prop_search(self, obj, name, *args, **kwargs):
        self.events.append(("prop", name))

    def operator(self, name, **kwargs):
        self.events.append(("operator", name))
        return type("OperatorProperties", (), {})()

    def panel(self, name, **kwargs):
        self.events.append(("panel", name))
        return self, self

    def separator(self, **kwargs):
        pass


class GuidedEquipmentTests(MountFixture):
    def setUp(self):
        super().setUp()
        self.assertIsNotNone(importlib.util.find_spec("humanoid_mounts.placement"), "Guided equipment must expose readonly readiness and cancellable fitting")
        self.placement = importlib.import_module("humanoid_mounts.placement")
        self.package = importlib.import_module("humanoid_mounts")
        self.package.register()
        self.settings = bpy.context.scene.hm_settings
        self.settings.part = "hand_r"
        self.settings.show_advanced = False

    def tearDown(self):
        try:
            self.package.unregister()
        finally:
            super().tearDown()

    def chosen(self, prepared=False):
        from humanoid_retarget.mapping import save_target_roles

        arm, names = make_human("GuidedHero")
        save_target_roles(arm, [(role, "Source_" + role, bone) for role, bone in names.items()])
        self.settings.armature = arm
        part = make_part("GuidedSword")
        root = self.weapons.prepare_grip_root([part], Matrix.Translation((3.0, 2.3, 0.5))) if prepared else None
        self.placement.select_equipment(self.settings, [part], part)
        return arm, names, root, part

    def fitted_mount(self, arm, names):
        mount = self.mounts.create_mount(arm, names["hand_r"], "hand_r")
        mount["hm_grip_fitted"] = True
        self.settings.mount = mount
        return mount

    def test_explicit_equipment_preserves_character_and_finds_prepared_root(self):
        arm, names, root, part = self.chosen(prepared=True)
        self.assertEqual(self.settings.armature, arm)
        self.assertEqual(self.settings.equipment, root)
        self.assertEqual(self.settings.grip, root)
        self.assertEqual([item.object for item in self.settings.equipment_parts], [root])

    def test_missing_role_fit_is_distinct_from_existing_mount(self):
        arm, names, root, part = self.chosen(prepared=True)
        mount = self.mounts.create_mount(arm, names["hand_r"], "hand_r")
        self.assertEqual(self.placement.equipment_status(self.settings).step, "FIT_CHARACTER")
        mount["hm_grip_fitted"] = True
        self.assertEqual(self.placement.equipment_status(self.settings).step, "READY")

    def test_readiness_does_not_write_scene_or_update_depsgraph(self):
        arm, names, root, part = self.chosen(prepared=True)
        before = set(bpy.data.objects)
        settings_before = self.settings.status
        with unittest.mock.patch.object(self.mounts, "world_matrix", side_effect=AssertionError("drawing updated dependency graph")):
            for unused in range(3):
                self.assertEqual(self.placement.equipment_status(self.settings).step, "FIT_CHARACTER")
        self.assertEqual(set(bpy.data.objects), before)
        self.assertEqual(self.settings.status, settings_before)

    def test_part_switch_ignores_stale_other_part_mount(self):
        arm, names, root, part = self.chosen(prepared=True)
        mount = self.fitted_mount(arm, names)
        self.settings.part = "head"
        state = self.placement.equipment_status(self.settings)
        self.assertEqual(state.step, "FIT_CHARACTER")
        self.assertIsNone(state.mount)
        self.assertNotIn(mount.name, state.message)

    def test_cancel_character_fit_removes_only_new_mount(self):
        arm, names, root, part = self.chosen()
        before = set(bpy.data.objects)
        self.placement.begin_fitting(self.settings, "CHARACTER")
        self.assertEqual(self.settings.fitting_stage, "CHARACTER")
        self.settings.fitting_mount.location.x += 0.1
        self.placement.cancel_fitting(self.settings)
        self.assertEqual(set(bpy.data.objects), before)
        self.assertEqual(self.settings.fitting_stage, "NONE")

    def test_cancel_existing_character_fit_restores_offset_and_attachments(self):
        arm, names, root, part = self.chosen(prepared=True)
        mount = self.fitted_mount(arm, names)
        self.weapons.bind_weapon(root, mount, "SNAP")
        before = evaluated_world(mount)
        part_before = evaluated_world(part)
        self.placement.begin_fitting(self.settings, "CHARACTER")
        mount.location.x += 0.12
        mount.rotation_euler.z += 0.3
        self.placement.cancel_fitting(self.settings)
        self.assertMatrix(evaluated_world(mount), before)
        self.assertMatrix(evaluated_world(part), part_before)
        self.assertTrue(mount["hm_grip_fitted"])

    def test_save_character_fit_confirms_without_setting_weapon_grip(self):
        arm, names, root, part = self.chosen()
        self.placement.begin_fitting(self.settings, "CHARACTER")
        mount = self.settings.fitting_mount
        mount.location.x += 0.1
        before = evaluated_world(mount)
        self.placement.save_fitting(self.settings)
        self.assertTrue(mount["hm_grip_fitted"])
        self.assertMatrix(evaluated_world(mount), before)
        self.assertEqual(self.placement.equipment_status(self.settings).step, "FIT_EQUIPMENT")
        self.assertIsNone(part.parent)

    def test_multicomponent_fit_cancel_restores_each_original_pose(self):
        arm, names, root, part = self.chosen()
        self.fitted_mount(arm, names)
        guard = make_part("GuidedGuard", (3.2, 2.0, 0.5))
        self.placement.select_equipment(self.settings, [part, guard], part)
        before = {obj: evaluated_world(obj) for obj in (part, guard)}
        self.placement.begin_fitting(self.settings, "EQUIPMENT")
        for obj in (part, guard):
            obj.location += Vector((0.2, -0.1, 0.3))
        self.placement.cancel_fitting(self.settings)
        for obj, world in before.items():
            self.assertIsNone(obj.parent)
            self.assertMatrix(evaluated_world(obj), world)

    def test_remember_current_pose_creates_grip_without_cursor_or_jump(self):
        arm, names, root, part = self.chosen()
        mount = self.fitted_mount(arm, names)
        guard = make_part("GuidedGuard", (3.2, 2.0, 0.5))
        self.placement.select_equipment(self.settings, [part, guard], part)
        self.placement.begin_fitting(self.settings, "EQUIPMENT")
        for obj in (part, guard):
            obj.location += Vector((-2.5, -2.0, 0.8))
        before = {obj: evaluated_world(obj) for obj in (part, guard)}
        cursor = bpy.context.scene.cursor.matrix.copy()
        self.placement.save_fitting(self.settings)
        root = self.settings.equipment
        self.assertEqual(root.get("hm_kind"), "GRIP")
        self.assertEqual(root.parent, mount)
        for obj, world in before.items():
            self.assertEqual(obj.parent, root)
            self.assertMatrix(evaluated_world(obj), world)
        self.assertMatrix(bpy.context.scene.cursor.matrix, cursor)
        self.assertEqual(self.placement.equipment_status(self.settings).step, "EQUIPPED")

    def test_adjust_existing_equipment_changes_weapon_calibration_only(self):
        arm, names, root, part = self.chosen(prepared=True)
        mount = self.fitted_mount(arm, names)
        self.weapons.bind_weapon(root, mount, "SNAP")
        mount_before = evaluated_world(mount)
        self.placement.begin_fitting(self.settings, "EQUIPMENT")
        root.location.x += 0.15
        desired = evaluated_world(part)
        self.placement.save_fitting(self.settings)
        self.assertMatrix(evaluated_world(mount), mount_before)
        self.assertMatrix(evaluated_world(part), desired)
        self.assertMatrix(evaluated_world(root), evaluated_world(mount))
        self.weapons.detach_weapon(root)
        self.weapons.equip_weapon(root, arm, "hand_r", mount)
        self.assertMatrix(evaluated_world(part), desired)

    def test_failed_grip_save_keeps_editing_pose_and_cancel_remains_available(self):
        arm, names, root, part = self.chosen()
        self.fitted_mount(arm, names)
        original = evaluated_world(part)
        self.placement.begin_fitting(self.settings, "EQUIPMENT")
        part.location.z += 0.2
        edited = evaluated_world(part)
        objects = set(bpy.data.objects)
        with unittest.mock.patch.object(self.weapons, "bind_weapon", side_effect=self.mounts.HumanoidMountError("injected fitting save failure")):
            with self.assertRaises(self.mounts.HumanoidMountError):
                self.placement.save_fitting(self.settings)
        self.assertEqual(self.settings.fitting_stage, "EQUIPMENT")
        self.assertEqual(set(bpy.data.objects), objects)
        self.assertIsNone(part.parent)
        self.assertMatrix(evaluated_world(part), edited)
        self.placement.cancel_fitting(self.settings)
        self.assertMatrix(evaluated_world(part), original)

    def test_autokey_and_foreign_context_are_rejected_without_losing_cancel(self):
        arm, names, root, part = self.chosen()
        tool = bpy.context.scene.tool_settings
        original = tool.use_keyframe_insert_auto
        try:
            tool.use_keyframe_insert_auto = True
            with self.assertRaises(self.mounts.HumanoidMountError):
                self.placement.begin_fitting(self.settings, "CHARACTER")
            self.assertFalse(self.mounts.mounts_for_armature(arm))
        finally:
            tool.use_keyframe_insert_auto = original
        self.placement.begin_fitting(self.settings, "CHARACTER")
        self.settings.part = "head"
        with self.assertRaises(self.mounts.HumanoidMountError):
            self.placement.save_fitting(self.settings)
        self.placement.cancel_fitting(self.settings)
        self.assertFalse(self.mounts.mounts_for_armature(arm))

    def test_unregister_cancels_unfinished_fit_before_removing_properties(self):
        arm, names, root, part = self.chosen()
        self.placement.begin_fitting(self.settings, "CHARACTER")
        self.package.unregister()
        self.assertFalse(self.mounts.mounts_for_armature(arm))
        self.assertFalse(hasattr(bpy.types.Scene, "hm_settings"))

    def test_legacy_expanded_panels_cannot_escape_advanced_gate(self):
        recorder = LayoutRecorder()
        self.settings.show_advanced = False
        panel = type("PanelInstance", (), {"layout": recorder})()
        self.package.panels.HM_PT_mounts.draw(panel, bpy.context)
        properties = [name for kind, name in recorder.events if kind == "prop"]
        self.assertIn("part", properties)
        self.assertNotIn("bone_name", properties)
        self.assertNotIn("mount", properties)
        self.assertNotIn("grip", properties)
        self.assertFalse(any(kind == "panel" for kind, name in recorder.events))
        self.settings.show_advanced = True
        recorder.events.clear()
        self.package.panels.HM_PT_mounts.draw(panel, bpy.context)
        self.assertIn(("prop", "bone_name"), recorder.events)

    def test_new_equipment_action_uses_explicit_input_instead_of_selected_marker(self):
        arm, names, root, part = self.chosen(prepared=True)
        mount = self.fitted_mount(arm, names)
        bpy.context.view_layer.objects.active = mount
        self.assertEqual(bpy.ops.humanoid_mounts.equip_weapon(), {"FINISHED"})
        self.assertEqual(root.parent, mount)
        self.assertEqual(self.settings.armature, arm)

    def test_reset_and_reanchor_invalidate_role_fit_confirmation(self):
        arm, names, root, part = self.chosen()
        mount = self.fitted_mount(arm, names)
        self.mounts.reset_mount(mount)
        self.assertFalse(mount.get("hm_grip_fitted", False))
        mount["hm_grip_fitted"] = True
        self.mounts.reanchor_mount(mount, names["chest"])
        self.assertFalse(mount.get("hm_grip_fitted", False))

    def test_cancel_preflights_all_records_before_restoring_any_part(self):
        arm, names, root, part = self.chosen()
        self.fitted_mount(arm, names)
        second = make_part("SnapshotGuard")
        self.placement.select_equipment(self.settings, [part, second], part)
        self.placement.begin_fitting(self.settings, "EQUIPMENT")
        for obj in (part, second):
            obj.location.z += 0.2
        edited = {obj: evaluated_world(obj) for obj in (part, second)}
        original = self.settings.fitting_snapshot
        records = json.loads(original)
        del records[1]["channels"]["scale"]
        self.settings.fitting_snapshot = json.dumps(records)
        try:
            with self.assertRaises(self.mounts.HumanoidMountError):
                self.placement.cancel_fitting(self.settings)
            for obj, world in edited.items():
                self.assertMatrix(evaluated_world(obj), world)
            self.assertEqual(self.settings.fitting_stage, "EQUIPMENT")
        finally:
            self.settings.fitting_snapshot = original

    def test_cancel_restore_failure_preserves_current_editing_pose(self):
        arm, names, root, part = self.chosen()
        self.fitted_mount(arm, names)
        second = make_part("RestoreGuard")
        self.placement.select_equipment(self.settings, [part, second], part)
        self.placement.begin_fitting(self.settings, "EQUIPMENT")
        for obj in (part, second):
            obj.location.z += 0.2
        edited = {obj: evaluated_world(obj) for obj in (part, second)}
        original = self.placement.restore_fitting_pose
        calls = []

        def fail_second(item, record):
            calls.append(item.object)
            if len(calls) == 2:
                raise RuntimeError("injected restore failure")
            original(item, record)

        with unittest.mock.patch.object(self.placement, "restore_fitting_pose", side_effect=fail_second):
            with self.assertRaisesRegex(RuntimeError, "restore failure"):
                self.placement.cancel_fitting(self.settings)
        for obj, world in edited.items():
            self.assertMatrix(evaluated_world(obj), world)
        self.assertEqual(self.settings.fitting_stage, "EQUIPMENT")

    def test_unprepared_input_change_is_reported_before_starting_fit(self):
        arm, names, root, part = self.chosen()
        self.fitted_mount(arm, names)
        self.settings.equipment = make_part("DifferentEquipment")
        self.assertEqual(self.placement.equipment_status(self.settings).step, "BLOCKED")
        objects = set(bpy.data.objects)
        with self.assertRaises(self.mounts.HumanoidMountError):
            self.placement.begin_fitting(self.settings, "EQUIPMENT")
        self.assertEqual(set(bpy.data.objects), objects)

    def test_full_main_draw_does_not_write_or_repeat_stale_status(self):
        arm, names, root, part = self.chosen(prepared=True)
        self.fitted_mount(arm, names)
        self.settings.status = "Old Pose Mode error"
        objects = set(bpy.data.objects)
        actor = self.settings.armature
        recorder = LayoutRecorder()
        panel = type("PanelInstance", (), {"layout": recorder})()
        with unittest.mock.patch.object(self.mounts, "world_matrix", side_effect=AssertionError("draw updated graph")):
            self.package.panels.HM_PT_mounts.draw(panel, bpy.context)
        self.assertEqual(set(bpy.data.objects), objects)
        self.assertEqual(self.settings.armature, actor)
        self.assertEqual(self.settings.status, "Old Pose Mode error")
        self.assertNotIn(("label", "Old Pose Mode error"), recorder.events)

    def test_choose_operator_keeps_character_and_locks_during_fitting(self):
        arm, names, root, part = self.chosen()
        for obj in tuple(bpy.context.selected_objects):
            obj.select_set(False)
        part.select_set(True)
        bpy.context.view_layer.objects.active = part
        self.assertEqual(bpy.ops.humanoid_mounts.choose_equipment(), {"FINISHED"})
        self.assertEqual(self.settings.armature, arm)
        self.placement.begin_fitting(self.settings, "CHARACTER")
        self.settings.show_advanced = True
        recorder = LayoutRecorder()
        panel = type("PanelInstance", (), {"layout": recorder})()
        self.package.panels.HM_PT_mounts.draw(panel, bpy.context)
        self.assertNotIn(("operator", "humanoid_mounts.create_mount"), recorder.events)
        self.assertEqual(bpy.ops.humanoid_mounts.choose_equipment(), {"CANCELLED"})

    def test_take_off_names_actual_source_and_uses_explicit_equipment(self):
        arm, names, root, part = self.chosen(prepared=True)
        mount = self.fitted_mount(arm, names)
        self.weapons.bind_weapon(root, mount, "SNAP")
        self.settings.part = "head"
        state = self.placement.equipment_status(self.settings)
        self.assertEqual(state.step, "BLOCKED")
        self.assertIn("右手", state.message)
        self.assertIn("头部", state.message)
        other = make_part("UnrelatedWeapon")
        unrelated = self.weapons.prepare_grip_root([other], Matrix.Identity(4))
        self.settings.grip = unrelated
        self.assertEqual(bpy.ops.humanoid_mounts.detach_weapon(use_equipment=True), {"FINISHED"})
        self.assertIsNone(root.parent)
        self.assertIsNone(unrelated.parent)

    def test_unregister_preflights_all_scenes_before_cancelling_any(self):
        arm, names, root, part = self.chosen()
        first_scene = bpy.context.scene
        first_settings = self.settings
        self.placement.begin_fitting(first_settings, "CHARACTER")
        first_mount = first_settings.fitting_mount
        second_scene = bpy.data.scenes.new("GuidedSecondScene")
        original_snapshot = None
        try:
            bpy.context.window.scene = second_scene
            self.settings = second_scene.hm_settings
            self.settings.part = "hand_r"
            self.chosen()
            self.placement.begin_fitting(self.settings, "CHARACTER")
            original_snapshot = self.settings.fitting_snapshot
            self.settings.fitting_snapshot = "broken"
            with self.assertRaises(self.mounts.HumanoidMountError):
                self.package.unregister()
            self.assertTrue(hasattr(bpy.types.Scene, "hm_settings"))
            self.assertEqual(first_settings.fitting_stage, "CHARACTER")
            self.assertIn(first_mount.name, bpy.data.objects)
        finally:
            if original_snapshot is not None:
                self.settings.fitting_snapshot = original_snapshot
                self.placement.cancel_fitting(self.settings)
            bpy.context.window.scene = first_scene
            self.settings = first_settings
            bpy.data.scenes.remove(second_scene)

    def test_equipment_fit_can_save_or_cancel_after_independent_reopen(self):
        arm, names, root, part = self.chosen()
        self.fitted_mount(arm, names)
        second = make_part("PersistentGuard")
        self.placement.select_equipment(self.settings, [part, second], part)
        before = {obj.name: [list(row) for row in evaluated_world(obj)] for obj in (part, second)}
        self.placement.begin_fitting(self.settings, "EQUIPMENT")
        for obj in (part, second):
            obj.location.z += 0.25
        edited = {obj.name: [list(row) for row in evaluated_world(obj)] for obj in (part, second)}
        repo = pathlib.Path(__file__).resolve().parents[1]
        out = repo / "tests/out/guided_mounts"
        out.mkdir(parents=True, exist_ok=True)
        path = out / "equipment-fitting-persistence.blend"
        bpy.ops.wm.save_as_mainfile(filepath=str(path))
        for operation, expected in (("cancel", before), ("save", edited)):
            code = "\n".join((
                "import sys, bpy",
                "sys.dont_write_bytecode=True",
                "sys.path.insert(0, " + repr(str(pathlib.Path(self.package.__file__).resolve().parent.parent)) + ")",
                "import humanoid_mounts",
                "from humanoid_mounts import placement, mounts",
                "humanoid_mounts.register()",
                "settings=bpy.context.scene.hm_settings",
                "assert settings.fitting_stage == 'EQUIPMENT'",
                "placement." + operation + "_fitting(settings)",
                "assert settings.fitting_stage == 'NONE'",
                "expected=" + repr(expected),
                "for name, matrix in expected.items():",
                "    actual=mounts.world_matrix(bpy.data.objects[name])",
                "    assert max(abs(actual[r][c]-matrix[r][c]) for r in range(4) for c in range(4)) <= 1e-5",
                "assert " + ("settings.equipment.parent == settings.mount" if operation == "save" else "bpy.data.objects[" + repr(part.name) + "].parent is None"),
                "print('GUIDED_EQUIPMENT_REOPEN_OK', " + repr(operation) + ", humanoid_mounts.__file__)",
            ))
            result = subprocess.run([bpy.app.binary_path, "--background", "--factory-startup", "--threads", "1", str(path), "--python-exit-code", "1", "--python-expr", code], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, timeout=60)
            (out / ("equipment-reopen-" + operation + ".log")).write_bytes(result.stdout)
            self.assertEqual(result.returncode, 0, result.stdout.decode("utf-8", errors="replace"))
            self.assertIn(b"GUIDED_EQUIPMENT_REOPEN_OK", result.stdout)

    def test_saved_fitting_can_cancel_in_an_independent_process(self):
        arm, names, root, part = self.chosen()
        self.placement.begin_fitting(self.settings, "CHARACTER")
        self.settings.fitting_mount.location.x += 0.2
        repo = pathlib.Path(__file__).resolve().parents[1]
        out = repo / "tests/out/guided_mounts"
        out.mkdir(parents=True, exist_ok=True)
        path = out / "fitting-persistence.blend"
        bpy.ops.wm.save_as_mainfile(filepath=str(path))
        code = "\n".join((
            "import sys, bpy",
            "sys.dont_write_bytecode=True",
            "sys.path.insert(0, " + repr(str(pathlib.Path(self.package.__file__).resolve().parent.parent)) + ")",
            "import humanoid_mounts",
            "from humanoid_mounts import placement, mounts",
            "humanoid_mounts.register()",
            "settings=bpy.context.scene.hm_settings",
            "assert settings.fitting_stage == 'CHARACTER'",
            "placement.cancel_fitting(settings)",
            "assert not mounts.mounts_for_armature(bpy.data.objects[" + repr(arm.name) + "])",
            "print('GUIDED_FITTING_REOPEN_OK', humanoid_mounts.__file__)",
        ))
        result = subprocess.run([bpy.app.binary_path, "--background", "--factory-startup", "--threads", "1", str(path), "--python-exit-code", "1", "--python-expr", code], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, timeout=60)
        (out / "reopen.log").write_bytes(result.stdout)
        self.assertEqual(result.returncode, 0, result.stdout.decode("utf-8", errors="replace"))
        self.assertIn(b"GUIDED_FITTING_REOPEN_OK", result.stdout)
