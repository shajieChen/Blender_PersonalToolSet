import importlib
import json
import os
import pathlib
import subprocess

import bpy

from test_humanoid_mounts_transform import MountFixture, evaluated_world, make_human

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "tests" / "out" / "humanoid_mounts"


class MountCoexistenceTests(MountFixture):
    def test_save_and_reopen_in_a_new_process_preserves_native_bindings(self):
        package = importlib.import_module("humanoid_mounts")
        package.register()
        try:
            arm, names, mount, root, part = self.armed()
            self.weapons.bind_weapon(root, mount, "SNAP")
            bpy.context.scene.hm_settings.armature = arm
            bpy.context.scene.hm_settings.mount = mount
            bpy.context.scene.hm_settings.grip = root
            other_mounts = [self.mounts.create_mount(arm, names[role], part_name) for part_name, role in (("hand_l", "hand_l"), ("back", "chest"), ("waist", "hips"), ("head", "head"))]
            expectations = {"frame": bpy.context.scene.frame_current, "armature": arm.name, "objects": {}}
            for obj in (mount, root, part, *other_mounts):
                expectations["objects"][obj.name] = {"parent": obj.parent.name if obj.parent else None, "kind": obj.get("hm_kind"), "part": obj.get("hm_part"), "schema": obj.get("hm_schema"), "bone": obj.parent_bone, "world": [list(row) for row in evaluated_world(obj)]}
            bpy.context.scene["hm_saved_expectations"] = json.dumps(expectations)
            OUTPUT.mkdir(parents=True, exist_ok=True)
            path = OUTPUT / "persistence.blend"
            bpy.ops.wm.save_as_mainfile(filepath=str(path))
            command = [bpy.app.binary_path, "--background", "--factory-startup", str(path), "--python-exit-code", "1", "--python", str(ROOT / "tests" / "run_humanoid_mounts_tests.py"), "--", "--check-saved"]
            result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, timeout=60)
            (OUTPUT / "persistence-process.log").write_bytes(result.stdout)
            self.assertEqual(result.returncode, 0, result.stdout.decode("utf-8", errors="replace"))
            self.assertIn(b"HUMANOID_MOUNTS_REOPEN_OK 7", result.stdout)
        finally:
            package.unregister()

    def test_weapon_collection_append_has_no_old_character_reference(self):
        arm, names, mount, root, part = self.armed()
        self.weapons.bind_weapon(root, mount, "SNAP")
        self.weapons.detach_weapon(root)
        collection = bpy.data.collections.new("WeaponLibrary")
        bpy.context.scene.collection.children.link(collection)
        for obj in (root, part):
            collection.objects.link(obj)
        OUTPUT.mkdir(parents=True, exist_ok=True)
        path = OUTPUT / "weapon-library.blend"
        bpy.data.libraries.write(str(path), {collection})
        with bpy.data.libraries.load(str(path), link=False) as (source, destination):
            destination.collections = [collection.name]
        appended = destination.collections[0]
        bpy.context.scene.collection.children.link(appended)
        second, second_names = make_human("AppendHuman")
        target = self.mounts.create_mount(second, second_names["hand_l"], "hand_l")
        roots = [obj for obj in appended.objects if obj.get("hm_kind") == "GRIP"]
        self.assertEqual(len(roots), 1)
        appended_root = roots[0]
        self.assertIsNone(appended_root.parent)
        self.assertFalse(any(obj.type == "ARMATURE" for obj in appended.all_objects))
        self.weapons.bind_weapon(appended_root, target, "SNAP")
        self.assertMatrix(evaluated_world(appended_root), evaluated_world(target))
        self.assertIsNone(root.parent)
        self.assertEqual(len(appended_root.children), 1)

    def test_binding_does_not_write_pose_action_or_mesh_data(self):
        arm, names, mount, root, part = self.armed()
        hand = arm.pose.bones[names["hand_r"]]
        hand.rotation_mode = "XYZ"
        hand.rotation_euler = (0.2, 0.3, 0.4)
        hand.keyframe_insert("rotation_euler", frame=1)
        action = arm.animation_data.action
        slot = arm.animation_data.action_slot
        actions = set(bpy.data.actions)
        pose = {bone.name: bone.matrix_basis.copy() for bone in arm.pose.bones}
        vertices = tuple(tuple(vertex.co) for vertex in part.data.vertices)
        self.weapons.bind_weapon(root, mount, "SNAP")
        self.weapons.detach_weapon(root)
        self.assertEqual(set(bpy.data.actions), actions)
        self.assertEqual(arm.animation_data.action, action)
        self.assertEqual(arm.animation_data.action_slot, slot)
        self.assertEqual(vertices, tuple(tuple(vertex.co) for vertex in part.data.vertices))
        for bone in arm.pose.bones:
            self.assertMatrix(bone.matrix_basis, pose[bone.name])

    def test_other_plugins_can_be_enabled_without_shared_state(self):
        package = importlib.import_module("humanoid_mounts")
        retarget = importlib.import_module("humanoid_retarget")
        spring = importlib.import_module("spring_bone")
        package.register()
        retarget.register()
        spring.register()
        try:
            arm, names, mount, root, part = self.armed()
            before = arm.matrix_world.copy()
            self.weapons.bind_weapon(root, mount, "SNAP")
            self.assertMatrix(evaluated_world(root), evaluated_world(mount))
            self.assertMatrix(arm.matrix_world, before)
            self.assertTrue(hasattr(bpy.types.Scene, "hr_settings"))
            self.assertTrue(hasattr(bpy.types.Object, "sb_settings"))
        finally:
            spring.unregister()
            retarget.unregister()
            package.unregister()

    def test_final_bone_constraint_output_drives_mount(self):
        arm, names = make_human()
        target = bpy.data.objects.new("HandAim", None)
        bpy.context.scene.collection.objects.link(target)
        target.rotation_euler = (0.3, 0.2, 0.7)
        constraint = arm.pose.bones[names["hand_r"]].constraints.new("COPY_ROTATION")
        constraint.target = target
        bpy.context.view_layer.update()
        mount = self.mounts.create_mount(arm, names["hand_r"], "hand_r")
        for angle in (0.1, 0.9, -0.4):
            target.rotation_euler.z = angle
            bpy.context.view_layer.update()
            evaluated = arm.evaluated_get(bpy.context.evaluated_depsgraph_get())
            self.assertMatrix(evaluated_world(mount), evaluated.matrix_world @ evaluated.pose.bones[names["hand_r"]].matrix)

    def test_no_mount_callbacks_or_animation_state_are_added(self):
        package = importlib.import_module("humanoid_mounts")
        handlers = (bpy.app.handlers.frame_change_pre, bpy.app.handlers.frame_change_post, bpy.app.handlers.depsgraph_update_post, bpy.app.handlers.load_post, bpy.app.handlers.undo_pre)
        before = [tuple(items) for items in handlers]
        package.register()
        try:
            arm, names, mount, root, part = self.armed()
            self.weapons.bind_weapon(root, mount, "SNAP")
            self.assertEqual(before, [tuple(items) for items in handlers])
            self.assertIsNone(mount.animation_data)
            self.assertIsNone(root.animation_data)
            self.assertFalse(mount.constraints)
            self.assertFalse(root.constraints)
        finally:
            package.unregister()
