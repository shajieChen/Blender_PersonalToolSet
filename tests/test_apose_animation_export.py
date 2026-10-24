import math
import pathlib
import sys
import unittest
from unittest.mock import patch

import bpy

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

import humanoid_retarget
from humanoid_retarget import pipeline
from io_scene_fbx import parse_fbx
from test_apose_export import AposeExportTests


class AposeAnimationExportTests(AposeExportTests):
    def make_clips(self):
        old = self.arm.animation_data.action
        old.name = "ObsoleteBake"
        old.use_fake_user = True
        actions = []
        for name, amount in [("RetargetFirst", 0.3), ("RetargetCurrent", 0.7)]:
            self.arm.animation_data.action = None
            for frame in [1, 2, 3]:
                upper = self.arm.pose.bones["upperarm_l"]
                upper.rotation_euler.z = amount * frame / 3
                upper.keyframe_insert("rotation_euler", frame=frame)
                hips = self.arm.pose.bones["hips"]
                hips.location.x = amount * frame / 10
                hips.keyframe_insert("location", frame=frame)
            action = self.arm.animation_data.action
            action.name = name
            action.use_fake_user = True
            actions.append(action)
        self.arm["hr_actions"] = "\n".join(action.name for action in actions)
        self.mesh.data.shape_keys.key_blocks["Smile"].value = 0.0
        bpy.context.scene.frame_set(2)
        return actions

    def takes(self):
        root, _version = parse_fbx.parse(self.path())
        objects = next(element for element in root.elems if element.id == b"Objects")
        return [element.props[1].decode("utf8").split("\x00")[0]
                for element in objects.elems if element.id == b"AnimationStack"]

    def test_retarget_motion_and_apose_reference_are_both_exported(self):
        actions = self.make_clips()
        expected = {}
        for action in actions:
            self.arm.animation_data.action = action
            self.arm.animation_data.action_slot = action.slots[0]
            for frame in [1, 2, 3]:
                bpy.context.scene.frame_set(frame)
                expected[action.name, frame] = {bone.name: bone.matrix.copy() for bone in self.arm.pose.bones}
        pipeline.export_apose_animations(self.arm, self.path())
        self.assertEqual(self.takes(), [actions[1].name, actions[0].name])
        before = set(bpy.data.objects)
        bpy.ops.import_scene.fbx(filepath=self.path(), use_anim=False)
        reference = next(obj for obj in bpy.data.objects if obj not in before and obj.type == "ARMATURE")
        bone = reference.pose.bones["upperarm_l"]
        direction = (bone.tail - bone.head).normalized()
        self.assertAlmostEqual(-direction.z, math.sqrt(0.5), places=4)
        bind = reference.data.bones["upperarm_l"].matrix_local
        expected_bind = self.arm.data.bones["upperarm_l"].matrix_local
        self.assertLess(max(abs(bind[row][column] - expected_bind[row][column])
                            for row in range(4) for column in range(4)), 1e-5)
        objects, imported_actions = pipeline.import_model(self.path())
        imported = next(obj for obj in objects if obj.type == "ARMATURE")
        for action in actions:
            clip = next(clip for clip in imported_actions if clip.name.endswith("|" + action.name)
                        and clip.slots and clip.slots[0].target_id_type == "OBJECT")
            imported.animation_data.action = clip
            imported.animation_data.action_slot = clip.slots[0]
            imported.animation_data.use_nla = False
            for frame in [1, 2, 3]:
                bpy.context.scene.frame_set(frame)
                for name, matrix in expected[action.name, frame].items():
                    actual = imported.pose.bones[name].matrix
                    error = max(abs(actual[row][column] - matrix[row][column])
                                for row in range(4) for column in range(4))
                    self.assertLess(error, 1e-5, (action.name, frame, name, error))

    def test_current_animation_only_omits_other_clips(self):
        actions = self.make_clips()
        pipeline.export_apose_animations(self.arm, self.path(), export_all_actions=False)
        self.assertEqual(self.takes(), [actions[-1].name])

    def test_mixed_shoulder_weights_preserve_retargeted_vertices(self):
        actions = self.make_clips()
        self.mesh.vertex_groups["upperarm_l"].add([0, 1, 2], 0.5, "REPLACE")
        self.mesh.vertex_groups.new(name="shoulder_l").add([0, 1, 2], 0.5, "REPLACE")
        expected = {}
        for frame in [1, 2, 3]:
            bpy.context.scene.frame_set(frame)
            evaluated = self.mesh.evaluated_get(bpy.context.evaluated_depsgraph_get())
            mesh = evaluated.to_mesh()
            expected[frame] = [evaluated.matrix_world @ vertex.co for vertex in mesh.vertices]
            evaluated.to_mesh_clear()
        pipeline.export_apose_animations(self.arm, self.path(), export_all_actions=False)
        objects, clips = pipeline.import_model(self.path())
        arm = next(obj for obj in objects if obj.type == "ARMATURE")
        obj = next(obj for obj in objects if obj.type == "MESH")
        clip = next(action for action in clips if action.name.endswith("|" + actions[-1].name)
                    and action.slots and action.slots[0].target_id_type == "OBJECT")
        arm.animation_data.action = clip
        arm.animation_data.action_slot = clip.slots[0]
        arm.animation_data.use_nla = False
        for frame in [1, 2, 3]:
            bpy.context.scene.frame_set(frame)
            evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
            mesh = evaluated.to_mesh()
            for vertex, position in zip(mesh.vertices, expected[frame]):
                self.assertLess(((evaluated.matrix_world @ vertex.co) - position).length, 1e-5)
            evaluated.to_mesh_clear()

    def test_animated_export_restores_source_and_removes_temp_actions(self):
        actions = self.make_clips()
        before = self.data_ids()
        poses = {bone.name: bone.matrix_basis.copy() for bone in self.arm.pose.bones}
        pipeline.export_apose_animations(self.arm, self.path())
        self.assertEqual(self.data_ids(), before)
        self.assertIs(self.arm.animation_data.action, actions[-1])
        self.assertEqual(bpy.context.scene.frame_current, 2)
        self.assertEqual(bpy.context.mode, "POSE")
        for bone in self.arm.pose.bones:
            self.assertEqual(bone.matrix_basis, poses[bone.name])

    def test_animated_export_failure_removes_temp_actions(self):
        self.make_clips()
        before = self.data_ids()
        with patch.object(pipeline, "_call_op", side_effect=RuntimeError("export failed")):
            with self.assertRaisesRegex(RuntimeError, "export failed"):
                pipeline.export_apose_animations(self.arm, self.path())
        self.assertEqual(self.data_ids(), before)
        self.assertEqual(bpy.context.scene.frame_current, 2)
        self.assertEqual(bpy.context.mode, "POSE")

    def test_reference_node_failure_restores_source_and_copies(self):
        import io_scene_fbx.export_fbx_bin as export_bin
        actions = self.make_clips()
        before = self.data_ids()
        original_writer = export_bin.fbx_data_object_elements
        with patch.object(export_bin, "fbx_data_object_elements", side_effect=RuntimeError("node failed")):
            with self.assertRaises(RuntimeError):
                pipeline.export_apose_animations(self.arm, self.path())
        self.assertEqual(self.data_ids(), before)
        self.assertIs(self.arm.animation_data.action, actions[-1])
        self.assertIs(export_bin.fbx_data_object_elements, original_writer)
        self.assertEqual(bpy.context.scene.frame_current, 2)

    def test_partial_native_bake_restores_source_and_actions(self):
        actions = self.make_clips()
        before = self.data_ids()

        def fail_bake(*args, **kwargs):
            bpy.context.scene.frame_set(3)
            raise RuntimeError("bake failed")

        with patch("humanoid_retarget.apose_export.bake_action_objects", side_effect=fail_bake):
            with self.assertRaisesRegex(RuntimeError, "bake failed"):
                pipeline.export_apose_animations(self.arm, self.path())
        self.assertEqual(self.data_ids(), before)
        self.assertIs(self.arm.animation_data.action, actions[-1])
        self.assertEqual(bpy.context.scene.frame_current, 2)

    def test_unkeyed_preview_edit_on_animated_bone_is_preserved(self):
        self.make_clips()
        bone = self.arm.pose.bones["upperarm_l"]
        bone.rotation_euler.z += 0.123
        expected = bone.rotation_euler.copy()
        pipeline.export_apose_animations(self.arm, self.path())
        self.assertEqual(bone.rotation_euler, expected)

    def test_button_defaults_to_model_and_retargeted_animation(self):
        self.make_clips()
        settings = bpy.context.scene.hr_settings
        settings.target = self.arm
        settings.export_format = "FBX"
        with patch.object(humanoid_retarget, "export_apose_animations", create=True) as export:
            result = bpy.ops.hr.export_result_file(filepath=self.path())
        self.assertEqual(result, {"FINISHED"})
        export.assert_called_once()
        self.assertTrue(export.call_args.kwargs["export_all_actions"])


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(AposeAnimationExportTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print(f"APOSE_ANIMATION_SELECTED {result.testsRun}")
    sys.exit(0 if result.wasSuccessful() and result.testsRun > 0 else 1)
