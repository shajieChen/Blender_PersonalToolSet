import importlib
import json
import os
import pathlib
import subprocess
import unittest.mock

import bpy
from mathutils import Euler, Matrix

from test_humanoid_mounts_transform import MountFixture, evaluated_world, make_human, make_part


class AutomaticMountTests(MountFixture):
    def setUp(self):
        super().setUp()
        self.assertTrue(callable(getattr(self.weapons, "equip_weapon", None)), "One-click equipment must resolve the mapped bone without manual selection")
        self.mapping = importlib.import_module("humanoid_retarget.mapping")
        self.assertTrue(callable(getattr(self.mapping, "save_target_roles", None)))
        self.package = importlib.import_module("humanoid_mounts")
        self.package.register()
        self.addCleanup(self.package.unregister)

    def mapped(self, name="MappedHuman"):
        arm, names = make_human(name, roll=0.62)
        self.mapping.save_target_roles(arm, [(role, "Source_" + role, bone) for role, bone in names.items()])
        return arm, names

    def grip(self, name="MappedSword"):
        part = make_part(name)
        anchor = Matrix.Translation((3.0, 2.3, 0.5)) @ Euler((0.2, -0.4, 0.1)).to_matrix().to_4x4()
        root = self.weapons.prepare_grip_root([part], anchor)
        return root, part

    def test_right_hand_without_manual_bone_preserves_weapon_calibration(self):
        arm, names = self.mapped()
        root, part = self.grip()
        calibration = evaluated_world(root).inverted() @ evaluated_world(part)
        mount = self.weapons.equip_weapon(root, arm, "hand_r")
        self.assertEqual(mount.parent_bone, names["hand_r"])
        self.assertEqual(root.parent, mount)
        self.assertMatrix(evaluated_world(root), evaluated_world(mount))
        self.assertMatrix(evaluated_world(part), evaluated_world(root) @ calibration)
        self.assertEqual(bpy.context.scene.hm_settings.bone_name, "")

    def test_five_parts_use_target_roles_and_spine_fallback(self):
        arm, names = self.mapped()
        for part, role in (("hand_r", "hand_r"), ("hand_l", "hand_l"), ("back", "chest"), ("waist", "hips"), ("head", "head")):
            root, mesh = self.grip(part)
            mount = self.weapons.equip_weapon(root, arm, part)
            self.assertEqual(mount.parent_bone, names[role])
        second, other = self.mapped("SpineFallback")
        self.mapping.save_target_roles(second, [("spine", "SourceSpine", other["spine"])])
        root, mesh = self.grip("Backpack")
        self.assertEqual(self.weapons.equip_weapon(root, second, "back").parent_bone, other["spine"])

    def test_repeated_equipment_reuses_calibrated_mount(self):
        arm, names = self.mapped()
        mount = self.mounts.create_mount(arm, names["hand_r"], "hand_r")
        mount.location.x += 0.08
        mount.rotation_euler.z += 0.4
        before = evaluated_world(mount)
        root, part = self.grip()
        for unused in range(3):
            self.assertEqual(self.weapons.equip_weapon(root, arm, "hand_r"), mount)
        self.assertEqual(self.mounts.mounts_for_armature(arm, "hand_r"), [mount])
        self.assertMatrix(evaluated_world(mount), before)

    def test_existing_mount_works_without_retarget_plugin_or_snapshot(self):
        arm, names = make_human()
        mount = self.mounts.create_mount(arm, names["hand_l"], "hand_l")
        root, part = self.grip()
        self.assertEqual(self.weapons.equip_weapon(root, arm, "hand_l"), mount)
        self.assertFalse(hasattr(bpy.types.Scene, "hr_settings"))

    def test_multiple_mounts_require_explicit_selection(self):
        arm, names = self.mapped()
        first = self.mounts.create_mount(arm, names["hand_r"], "hand_r")
        second = self.mounts.copy_mount(first)
        root, part = self.grip()
        before = evaluated_world(root)
        with self.assertRaises(self.mounts.HumanoidMountError):
            self.weapons.equip_weapon(root, arm, "hand_r")
        self.assertIsNone(root.parent)
        self.assertMatrix(evaluated_world(root), before)
        self.assertEqual(self.weapons.equip_weapon(root, arm, "hand_r", second), second)

    def test_missing_roles_bad_schema_and_bad_json_leave_no_mount(self):
        arm, names = self.mapped()
        root, part = self.grip()
        for payload in ("broken", "[]", '{"schema":2,"roles":{}}', '{"schema":true,"roles":{}}', '{"schema":1,"roles":{}}', '{"schema":1,"roles":{"hand_r":"missing"}}'):
            arm["hr_bone_roles"] = payload
            before = set(bpy.data.objects)
            with self.assertRaises(self.mounts.HumanoidMountError):
                self.weapons.equip_weapon(root, arm, "hand_r")
            self.assertEqual(set(bpy.data.objects), before)
            self.assertIsNone(root.parent)

    def test_missing_one_part_does_not_block_other_parts(self):
        arm, names = self.mapped()
        self.mapping.save_target_roles(arm, [("head", "SourceHead", names["head"])])
        root, part = self.grip()
        self.assertEqual(self.weapons.equip_weapon(root, arm, "head").parent_bone, names["head"])

    def test_cross_character_equipment_is_rejected_without_empty_mount(self):
        first, names = self.mapped("First")
        second, other = self.mapped("Second")
        root, part = self.grip()
        mount = self.weapons.equip_weapon(root, first, "hand_r")
        before = set(bpy.data.objects)
        with self.assertRaises(self.mounts.HumanoidMountError):
            self.weapons.equip_weapon(root, second, "hand_r")
        self.assertEqual(root.parent, mount)
        self.assertEqual(set(bpy.data.objects), before)

    def test_failure_after_binding_restores_root_and_removes_new_mount(self):
        arm, names = self.mapped()
        root, part = self.grip()
        before = evaluated_world(root)
        objects = set(bpy.data.objects)
        original = self.weapons.bind_weapon

        def fail_after_bind(*args):
            original(*args)
            raise RuntimeError("injected equipment failure")

        with unittest.mock.patch.object(self.weapons, "bind_weapon", side_effect=fail_after_bind):
            with self.assertRaisesRegex(RuntimeError, "equipment failure"):
                self.weapons.equip_weapon(root, arm, "hand_r")
        self.assertEqual(set(bpy.data.objects), objects)
        self.assertIsNone(root.parent)
        self.assertMatrix(evaluated_world(root), before)

    def test_failure_keeps_existing_mount_and_calibration(self):
        arm, names = self.mapped()
        mount = self.mounts.create_mount(arm, names["hand_r"], "hand_r")
        mount.location.x += 0.04
        root, part = self.grip()
        before = evaluated_world(mount)
        with unittest.mock.patch.object(self.weapons, "bind_weapon", side_effect=RuntimeError("injected")):
            with self.assertRaises(RuntimeError):
                self.weapons.equip_weapon(root, arm, "hand_r")
        self.assertEqual(self.mounts.mounts_for_armature(arm), [mount])
        self.assertMatrix(evaluated_world(mount), before)

    def test_constraint_animation_and_relative_parenting_follow_final_bone(self):
        for relative in (False, True):
            arm, names = self.mapped("Animated")
            arm.matrix_world = Matrix.Translation((2.0, -1.0, 0.5)) @ Matrix.Scale(1.25, 4)
            arm.data.bones[names["hand_r"]].use_relative_parent = relative
            aim = bpy.data.objects.new("HandAim", None)
            bpy.context.scene.collection.objects.link(aim)
            constraint = arm.pose.bones[names["hand_r"]].constraints.new("COPY_ROTATION")
            constraint.target = aim
            root, part = self.grip()
            mount = self.weapons.equip_weapon(root, arm, "hand_r")
            for angle in (0.1, 0.7, -0.4):
                aim.rotation_euler.z = angle
                bpy.context.view_layer.update()
                evaluated = arm.evaluated_get(bpy.context.evaluated_depsgraph_get())
                self.assertMatrix(evaluated_world(root), evaluated.matrix_world @ evaluated.pose.bones[names["hand_r"]].matrix)
            self.assertEqual(arm.data.bones[names["hand_r"]].use_relative_parent, relative)

    def test_operator_uses_selected_weapon_child_without_manual_root_or_bone(self):
        arm, names = self.mapped()
        root, part = self.grip()
        for selected in tuple(bpy.context.selected_objects):
            selected.select_set(False)
        part.select_set(True)
        bpy.context.view_layer.objects.active = part
        settings = bpy.context.scene.hm_settings
        settings.armature = arm
        settings.grip = None
        settings.mount = None
        settings.part = "hand_r"
        settings.bone_name = ""
        self.assertEqual(bpy.ops.humanoid_mounts.equip_weapon(), {"FINISHED"})
        self.assertEqual(settings.grip, root)
        self.assertEqual(settings.mount.parent_bone, names["hand_r"])
        self.assertEqual(settings.armature, arm)

    def test_operator_does_not_use_stale_grip_for_unprepared_selected_weapon(self):
        arm, names = self.mapped()
        root, part = self.grip()
        unknown = make_part("UnknownSword")
        bpy.context.view_layer.objects.active = unknown
        settings = bpy.context.scene.hm_settings
        settings.armature = arm
        settings.grip = root
        self.assertEqual(bpy.ops.humanoid_mounts.equip_weapon(), {"CANCELLED"})
        self.assertIsNone(root.parent)
        self.assertIsNone(unknown.parent)
        self.assertFalse(self.mounts.mounts_for_armature(arm))

    def test_publisher_rejects_invalid_mapping_without_overwriting_snapshot(self):
        arm, names = self.mapped()
        before = arm["hr_bone_roles"]
        for pairs in ([("hand_r", "Source", "missing")], [("hand_r", "Source", names["hand_r"]), ("hand_r", "Source", names["hand_l"])], []):
            with self.assertRaises(self.mapping.PresetError):
                self.mapping.save_target_roles(arm, pairs)
            self.assertEqual(arm["hr_bone_roles"], before)

    def test_real_retarget_publishes_final_roles_and_failed_retarget_keeps_them(self):
        from humanoid_retarget.pipeline import PipelineError, retarget_existing
        from humanoid_retarget.retarget import RetargetOptions

        source, source_names = make_human("RealSource", roll=0.0)
        target, target_names = make_human("RealTarget", roll=0.6)
        for role, bone_name in tuple(target_names.items()):
            target.data.bones[bone_name].name = "Target_" + bone_name
            target_names[role] = "Target_" + bone_name
        hand = source.pose.bones[source_names["hand_r"]]
        hand.rotation_mode = "XYZ"
        for frame, angle in ((1, 0.0), (3, 0.6)):
            hand.rotation_euler.z = angle
            hand.keyframe_insert("rotation_euler", frame=frame)
        source["hr_actions"] = source.animation_data.action.name
        pairs = [(role, source_names[role], target_names[role]) for role in source_names]
        options = RetargetOptions(pairs=pairs, foot_ik=False, hand_ik=False)
        report, actions = retarget_existing(source, target, options)
        self.assertTrue(actions)
        snapshot = json.loads(target["hr_bone_roles"])
        self.assertEqual(snapshot["roles"], {role: bone for role, unused, bone in options.resolved_pairs})
        self.assertNotIn("hr_bone_roles", source)
        root, part = self.grip()
        mount = self.weapons.equip_weapon(root, target, "hand_r")
        for frame in (3, 1, 2):
            bpy.context.scene.frame_set(frame)
            self.assertMatrix(evaluated_world(root), evaluated_world(mount))
        before = target["hr_bone_roles"]
        with self.assertRaises(PipelineError):
            retarget_existing(target, target, options)
        self.assertEqual(target["hr_bone_roles"], before)

    def test_bone_rename_blocks_new_mount_but_preserves_existing_native_mount(self):
        arm, names = self.mapped()
        root, part = self.grip()
        arm.data.bones[names["hand_r"]].name = "RenamedRightHand"
        with self.assertRaises(self.mounts.HumanoidMountError):
            self.weapons.equip_weapon(root, arm, "hand_r")
        self.assertFalse(self.mounts.mounts_for_armature(arm))
        mount = self.mounts.create_mount(arm, "RenamedRightHand", "hand_r")
        arm.data.bones["RenamedRightHand"].name = "RenamedAgain"
        self.assertEqual(self.weapons.equip_weapon(root, arm, "hand_r"), mount)
        self.assertEqual(mount.parent_bone, "RenamedAgain")

    def test_use_retarget_target_keeps_role_mapping_owned_by_target(self):
        retarget = importlib.import_module("humanoid_retarget")
        retarget.register()
        try:
            source, source_names = make_human("ChosenSource")
            target, names = self.mapped("ChosenTarget")
            bpy.context.scene.hr_settings.source = source
            bpy.context.scene.hr_settings.target = target
            bpy.context.view_layer.objects.active = source
            self.assertEqual(bpy.ops.humanoid_mounts.use_retarget_target(), {"FINISHED"})
            self.assertEqual(bpy.context.scene.hm_settings.armature, target)
            self.assertEqual(bpy.context.scene.hm_settings.bone_name, "")
            self.assertNotIn("hr_bone_roles", source)
        finally:
            retarget.unregister()

    def test_duplicate_final_targets_fail_before_any_animation_mutation(self):
        from humanoid_retarget.pipeline import PipelineError, retarget_existing
        from humanoid_retarget.retarget import RetargetOptions

        source, source_names = make_human("InvalidSource")
        target, names = self.mapped("PreservedTarget")
        for arm, bone_name in ((source, source_names["hand_r"]), (target, names["hand_r"])):
            bone = arm.pose.bones[bone_name]
            bone.keyframe_insert("location", frame=1)
            bone.location.z = 0.1
            bone.keyframe_insert("location", frame=3)
            arm.animation_data.action.use_fake_user = True
        source["hr_actions"] = source.animation_data.action.name
        target["hr_actions"] = target.animation_data.action.name
        target["hr_retarget_from"] = "OriginalSource"
        old_action = target.animation_data.action
        old_slot = target.animation_data.action_slot
        old_track = target.animation_data.nla_tracks.new()
        old_track.name = "ExistingTrack"
        old_track.strips.new("ExistingStrip", 1, old_action)
        old_tracks = tuple((track.name, tuple((strip.name, strip.action.name) for strip in track.strips)) for track in target.animation_data.nla_tracks)
        old_properties = dict(target.items())
        old_actions = set(bpy.data.actions)
        old_range = (bpy.context.scene.frame_current, bpy.context.scene.frame_start, bpy.context.scene.frame_end)
        pairs = [(role, source_names[role], names[role]) for role in names]
        pairs = [(role, source_name, names["chest"] if role == "head" else bone_name) for role, source_name, bone_name in pairs]
        with self.assertRaises(PipelineError):
            retarget_existing(source, target, RetargetOptions(pairs=pairs, foot_ik=False, hand_ik=False))
        self.assertEqual(target.animation_data.action, old_action)
        self.assertEqual(target.animation_data.action_slot, old_slot)
        self.assertEqual(tuple((track.name, tuple((strip.name, strip.action.name) for strip in track.strips)) for track in target.animation_data.nla_tracks), old_tracks)
        self.assertEqual(dict(target.items()), old_properties)
        self.assertEqual(set(bpy.data.actions), old_actions)
        self.assertEqual((bpy.context.scene.frame_current, bpy.context.scene.frame_start, bpy.context.scene.frame_end), old_range)

    def test_invalid_mount_is_not_bypassed_or_replaced(self):
        arm, names = self.mapped()
        invalid = self.mounts.create_mount(arm, names["hand_r"], "hand_r")
        invalid["hm_schema"] = 99
        root, part = self.grip()
        objects = set(bpy.data.objects)
        before = evaluated_world(root)
        with self.assertRaises(self.mounts.HumanoidMountError):
            self.weapons.equip_weapon(root, arm, "hand_r")
        self.assertEqual(set(bpy.data.objects), objects)
        self.assertIsNone(root.parent)
        self.assertMatrix(evaluated_world(root), before)
        valid = self.mounts.create_mount(arm, names["hand_r"], "hand_r")
        with self.assertRaises(self.mounts.HumanoidMountError):
            self.weapons.equip_weapon(root, arm, "hand_r")
        self.assertEqual(self.weapons.equip_weapon(root, arm, "hand_r", valid), valid)

    def test_invalid_chest_does_not_silently_fallback_to_spine(self):
        arm, names = self.mapped()
        arm["hr_bone_roles"] = json.dumps({"schema": 1, "roles": {"chest": "missing", "spine": names["spine"]}})
        root, part = self.grip()
        with self.assertRaises(self.mounts.HumanoidMountError):
            self.weapons.equip_weapon(root, arm, "back")
        self.assertFalse(self.mounts.mounts_for_armature(arm))

    def test_operator_failure_restores_root_and_does_not_publish_mount_selection(self):
        arm, names = self.mapped()
        root, part = self.grip()
        bpy.context.view_layer.objects.active = part
        settings = bpy.context.scene.hm_settings
        settings.armature = arm
        settings.mount = None
        settings.grip = None
        objects = set(bpy.data.objects)
        before = evaluated_world(root)
        with unittest.mock.patch.object(self.weapons, "bind_weapon", side_effect=self.mounts.HumanoidMountError("injected domain failure")):
            self.assertEqual(bpy.ops.humanoid_mounts.equip_weapon(), {"CANCELLED"})
        self.assertEqual(set(bpy.data.objects), objects)
        self.assertIsNone(settings.mount)
        self.assertIsNone(settings.grip)
        self.assertIsNone(root.parent)
        self.assertMatrix(evaluated_world(root), before)

    def test_saved_record_and_equipment_work_in_new_process(self):
        arm, names = self.mapped("ReopenHuman")
        root, part = self.grip("ReopenSword")
        mount = self.weapons.equip_weapon(root, arm, "hand_r")
        repo = pathlib.Path(__file__).resolve().parents[1]
        output = repo / "tests/out/auto_mounts"
        output.mkdir(parents=True, exist_ok=True)
        path = output / "automatic-persistence.blend"
        bpy.ops.wm.save_as_mainfile(filepath=str(path))
        code = "\n".join((
            "import sys, bpy, json",
            "sys.dont_write_bytecode = True",
            "sys.path.insert(0, " + repr(str(pathlib.Path(self.package.__file__).resolve().parent.parent)) + ")",
            "import humanoid_mounts",
            "assert humanoid_mounts.__file__ == " + repr(self.package.__file__),
            "print('AUTOMATIC_MOUNTS_REOPEN_PACKAGE', humanoid_mounts.__file__)",
            "from humanoid_mounts.weapons import equip_weapon",
            "humanoid_mounts.register()",
            "arm = bpy.data.objects[" + repr(arm.name) + "]",
            "root = bpy.data.objects[" + repr(root.name) + "]",
            "mount = equip_weapon(root, arm, 'hand_r')",
            "assert root.parent == mount and mount.parent_bone == " + repr(names["hand_r"]),
            "assert json.loads(arm['hr_bone_roles'])['schema'] == 1",
            "assert not hasattr(bpy.types.Scene, 'hr_settings')",
            "print('AUTOMATIC_MOUNTS_REOPEN_OK')",
        ))
        result = subprocess.run([bpy.app.binary_path, "--background", "--factory-startup", str(path), "--python-exit-code", "1", "--python-expr", code], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, timeout=60)
        (output / "automatic-reopen.log").write_bytes(result.stdout)
        self.assertEqual(result.returncode, 0, result.stdout.decode("utf-8", errors="replace"))
        self.assertIn(b"AUTOMATIC_MOUNTS_REOPEN_OK", result.stdout)
