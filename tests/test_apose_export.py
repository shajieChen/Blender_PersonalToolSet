import math
import pathlib
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import bpy
from mathutils import Matrix, Vector

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import humanoid_retarget
from humanoid_retarget import pipeline
from io_scene_fbx import parse_fbx
from run_retarget_test import build_biped, junk_names


class AposeExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        humanoid_retarget.register()

    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.folder = tempfile.TemporaryDirectory(prefix="codex-apose-test-")
        self.addCleanup(self.folder.cleanup)
        roles = {role: role for role in junk_names()}
        self.arm = build_biped("AposeRig", roles)
        mesh = bpy.data.meshes.new("Body")
        mesh.from_pydata([(0.3, 0, 1.48), (0.35, 0, 1.48), (0.3, 0.05, 1.48)], [], [(0, 1, 2)])
        self.mesh = bpy.data.objects.new("Body", mesh)
        bpy.context.collection.objects.link(self.mesh)
        self.mesh.parent = self.arm
        self.mesh.vertex_groups.new(name="upperarm_l").add([0, 1, 2], 1.0, "REPLACE")
        self.mesh.modifiers.new("Skin", "ARMATURE").object = self.arm
        self.mesh.shape_key_add(name="Basis")
        smile = self.mesh.shape_key_add(name="Smile")
        smile.data[0].co.z += 0.02
        smile.value = 0.4
        upper = self.arm.pose.bones["upperarm_l"]
        upper.rotation_mode = "XYZ"
        upper.rotation_euler.z = 0.7
        upper.keyframe_insert("rotation_euler", frame=7)
        bpy.context.scene.frame_set(7)

    def path(self):
        return str(pathlib.Path(self.folder.name) / "character_APose.fbx")

    def data_ids(self):
        return {name: set(getattr(bpy.data, name))
                for name in ["objects", "meshes", "armatures", "shape_keys", "actions", "collections"]}

    def test_apose_rest_skin_and_shape_keys_roundtrip(self):
        pipeline.export_apose(self.arm, self.path())
        root, _version = parse_fbx.parse(self.path())
        objects = next(element for element in root.elems if element.id == b"Objects")
        self.assertFalse(any(element.id == b"AnimationStack" for element in objects.elems))
        before = set(bpy.data.objects)
        bpy.ops.import_scene.fbx(filepath=self.path(), use_anim=False)
        imported = [obj for obj in bpy.data.objects if obj not in before]
        arm = next(obj for obj in imported if obj.type == "ARMATURE")
        mesh = next(obj for obj in imported if obj.type == "MESH")
        down = Vector((0, 0, -1))
        for side in ["l", "r"]:
            for role in ["upperarm", "forearm", "hand"]:
                bone = arm.data.bones[f"{role}_{side}"]
                direction = (bone.tail_local - bone.head_local).normalized()
                self.assertAlmostEqual(direction.dot(down), math.sqrt(0.5), places=4)
        pivot = self.arm.data.bones["upperarm_l"].head_local
        rotation = Matrix.Rotation(math.pi / 4, 3, "Y")
        expected = pivot + rotation @ (self.mesh.data.vertices[0].co - pivot)
        self.assertLess((mesh.data.vertices[0].co - expected).length, 1e-5)
        self.assertEqual([key.name for key in mesh.data.shape_keys.key_blocks], ["Basis", "Smile"])
        expected_smile = pivot + rotation @ (self.mesh.data.shape_keys.key_blocks["Smile"].data[0].co - pivot)
        actual_smile = mesh.data.shape_keys.key_blocks["Smile"].data[0].co
        self.assertLess((actual_smile - expected_smile).length, 1e-5)
        self.assertEqual(mesh.vertex_groups[0].name, "upperarm_l")
        self.assertEqual(mesh.data.vertices[0].groups[0].weight, 1.0)

    def test_source_and_temporary_data_are_unchanged(self):
        before = self.data_ids()
        action = self.arm.animation_data.action
        poses = {bone.name: bone.matrix_basis.copy() for bone in self.arm.pose.bones}
        rests = {bone.name: bone.matrix_local.copy() for bone in self.arm.data.bones}
        vertices = [vertex.co.copy() for vertex in self.mesh.data.vertices]
        pipeline.export_apose(self.arm, self.path())
        self.assertEqual(self.data_ids(), before)
        self.assertIs(self.arm.animation_data.action, action)
        self.assertEqual(bpy.context.scene.frame_current, 7)
        self.assertEqual(bpy.context.mode, "POSE")
        self.assertIs(bpy.context.view_layer.objects.active, self.arm)
        self.assertAlmostEqual(self.mesh.data.shape_keys.key_blocks["Smile"].value, 0.4)
        for bone in self.arm.pose.bones:
            self.assertEqual(bone.matrix_basis, poses[bone.name])
            self.assertEqual(bone.bone.matrix_local, rests[bone.name])
        for vertex, expected in zip(self.mesh.data.vertices, vertices):
            self.assertEqual(vertex.co, expected)

    def test_failed_export_removes_all_copies(self):
        before = self.data_ids()
        with patch.object(pipeline, "_call_op", side_effect=RuntimeError("export failed")):
            with self.assertRaisesRegex(RuntimeError, "export failed"):
                pipeline.export_apose(self.arm, self.path())
        self.assertEqual(self.data_ids(), before)
        self.assertEqual(bpy.context.mode, "POSE")
        self.assertIs(bpy.context.view_layer.objects.active, self.arm)

    def test_modifier_bound_mesh_without_parent_is_included(self):
        self.mesh.parent = None
        pipeline.export_apose(self.arm, self.path())
        before = set(bpy.data.objects)
        bpy.ops.import_scene.fbx(filepath=self.path(), use_anim=False)
        meshes = [obj for obj in bpy.data.objects if obj not in before and obj.type == "MESH"]
        self.assertEqual(len(meshes), 1)

    def test_custom_normals_follow_the_apose_arm(self):
        normal = Vector((0, 1, 1)).normalized()
        self.mesh.data.polygons[0].use_smooth = True
        self.mesh.data.normals_split_custom_set([normal] * len(self.mesh.data.loops))
        pipeline.export_apose(self.arm, self.path())
        before = set(bpy.data.objects)
        bpy.ops.import_scene.fbx(filepath=self.path(), use_anim=False)
        mesh = next(obj for obj in bpy.data.objects if obj not in before and obj.type == "MESH")
        expected = Matrix.Rotation(math.pi / 4, 3, "Y") @ normal
        actual = mesh.data.corner_normals[0].vector
        self.assertGreater(actual.dot(expected), 1.0 - 1e-4)

    def test_button_defaults_to_apose_export(self):
        settings = bpy.context.scene.hr_settings
        settings.target = self.arm
        settings.export_format = "FBX"
        with patch.object(humanoid_retarget, "export_apose", create=True) as export:
            with patch.object(humanoid_retarget, "export_armature") as animated:
                result = bpy.ops.hr.export_result_file(filepath=self.path(), fbx_pose="A_POSE")
        self.assertEqual(result, {"FINISHED"})
        export.assert_called_once()
        animated.assert_not_called()

    def test_button_defaults_to_retargeted_animation(self):
        bpy.context.scene.hr_settings.target = self.arm
        dialog = unittest.mock.Mock(return_value={"RUNNING_MODAL"})
        context = types.SimpleNamespace(scene=bpy.context.scene,
                                        window_manager=types.SimpleNamespace(invoke_props_dialog=dialog))
        operator = types.SimpleNamespace(export_all_actions=False, fbx_pose="A_POSE")
        result = humanoid_retarget.HR_OT_export.invoke(operator, context, None)
        self.assertEqual(result, {"RUNNING_MODAL"})
        self.assertEqual(operator.fbx_pose, "ANIMATED")


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(AposeExportTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print(f"APOSE_EXPORT_SELECTED {result.testsRun}")
    sys.exit(0 if result.wasSuccessful() and result.testsRun > 0 else 1)
