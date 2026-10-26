import importlib
import importlib.util
import math
import unittest

import bpy
from mathutils import Euler, Matrix, Vector


def evaluated_world(obj):
    bpy.context.view_layer.update()
    return obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).matrix_world.copy()


def matrix_error(actual, expected):
    return max(abs(actual[row][column] - expected[row][column]) for row in range(4) for column in range(4))


def make_human(name="Human", roll=0.35):
    from run_retarget_test import build_biped, junk_names

    names = junk_names()
    obj = build_biped(name, names, arm_roll=roll)
    bpy.ops.object.mode_set(mode="OBJECT")
    return obj, names


def make_part(name="Sword", location=(3.0, 2.0, 0.5)):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([(0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.1, 0.0, 0.0)], [], [(0, 1, 2)])
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = location
    bpy.context.view_layer.update()
    return obj


class MountFixture(unittest.TestCase):
    def setUp(self):
        self.before = set(bpy.data.objects)
        self.assertIsNotNone(importlib.util.find_spec("humanoid_mounts"), "humanoid_mounts must implement the mount contract")
        self.mounts = importlib.import_module("humanoid_mounts.mounts")
        self.weapons = importlib.import_module("humanoid_mounts.weapons")

    def tearDown(self):
        if bpy.context.object is not None and bpy.context.object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        for obj in tuple(bpy.data.objects):
            if obj not in self.before:
                data = obj.data
                bpy.data.objects.remove(obj, do_unlink=True)
                if data is not None and data.users == 0:
                    if isinstance(data, bpy.types.Mesh):
                        bpy.data.meshes.remove(data)
                    elif isinstance(data, bpy.types.Armature):
                        bpy.data.armatures.remove(data)

    def assertMatrix(self, actual, expected):
        self.assertLessEqual(matrix_error(actual, expected), 1e-5)

    def armed(self):
        arm, names = make_human()
        mount = self.mounts.create_mount(arm, names["hand_r"], "hand_r")
        part = make_part()
        anchor = Matrix.Translation((3.0, 2.3, 0.5)) @ Euler((0.2, 0.3, -0.4)).to_matrix().to_4x4()
        root = self.weapons.prepare_grip_root([part], anchor)
        return arm, names, mount, root, part


class MountTransformTests(MountFixture):
    def test_create_at_final_bone_origin_preserves_relative_parenting(self):
        for relative in (False, True):
            arm, names = make_human("RelativeHuman", roll=0.6)
            arm.matrix_world = Matrix.Translation((2.0, -3.0, 0.7)) @ Euler((0.2, 0.4, 0.6)).to_matrix().to_4x4() @ Matrix.Scale(1.25, 4)
            bone = arm.data.bones[names["hand_r"]]
            bone.use_relative_parent = relative
            pose = arm.pose.bones[names["forearm_r"]]
            pose.rotation_mode = "XYZ"
            pose.rotation_euler = (0.3, -0.2, 0.5)
            bpy.context.view_layer.update()
            expected = evaluated_world(arm) @ arm.evaluated_get(bpy.context.evaluated_depsgraph_get()).pose.bones[bone.name].matrix
            mount = self.mounts.create_mount(arm, bone.name, "hand_r")
            self.assertEqual(mount.parent, arm)
            self.assertEqual(mount.parent_type, "BONE")
            self.assertEqual(mount.parent_bone, bone.name)
            self.assertEqual(bone.use_relative_parent, relative)
            self.assertMatrix(evaluated_world(mount), expected)

    def test_grip_preparation_preserves_parts_and_source_data(self):
        part = make_part()
        second = make_part("Guard", (3.2, 2.4, 0.6))
        before = {obj: evaluated_world(obj) for obj in (part, second)}
        vertices = [tuple(vertex.co) for vertex in part.data.vertices]
        anchor = Matrix.Translation((3.0, 2.3, 0.5)) @ Euler((0.1, -0.4, 0.3)).to_matrix().to_4x4()
        root = self.weapons.prepare_grip_root([part, second], anchor)
        self.assertMatrix(evaluated_world(root), anchor)
        for obj in (part, second):
            self.assertEqual(obj.parent, root)
            self.assertMatrix(evaluated_world(obj), before[obj])
        self.assertEqual(vertices, [tuple(vertex.co) for vertex in part.data.vertices])

    def test_snap_preserves_grip_calibration_and_follows_animation(self):
        arm, names, mount, root, part = self.armed()
        calibration = evaluated_world(root).inverted() @ evaluated_world(part)
        self.weapons.bind_weapon(root, mount, "SNAP")
        self.assertMatrix(evaluated_world(root), evaluated_world(mount))
        self.assertMatrix(evaluated_world(part), evaluated_world(root) @ calibration)
        hand = arm.pose.bones[names["hand_r"]]
        hand.rotation_mode = "XYZ"
        for frame, angle in ((1, 0.0), (11, math.pi / 2.0)):
            hand.rotation_euler = (angle, 0.1, 0.0)
            hand.keyframe_insert("rotation_euler", frame=frame)
        for frame in (11, 1, 6, 11):
            bpy.context.scene.frame_set(frame)
            self.assertMatrix(evaluated_world(root), evaluated_world(mount))
            self.assertMatrix(evaluated_world(part), evaluated_world(root) @ calibration)

    def test_keep_world_and_detach_preserve_current_pose_and_delta(self):
        arm, names, mount, root, part = self.armed()
        root.delta_location = (0.1, -0.2, 0.05)
        root.delta_rotation_euler = (0.1, 0.0, 0.0)
        before = evaluated_world(root)
        self.weapons.bind_weapon(root, mount, "KEEP_WORLD")
        self.assertMatrix(evaluated_world(root), before)
        arm.pose.bones[names["hand_r"]].rotation_mode = "XYZ"
        arm.pose.bones[names["hand_r"]].rotation_euler = (0.5, 0.2, -0.4)
        current = evaluated_world(root)
        part_before = evaluated_world(part)
        self.weapons.detach_weapon(root)
        self.assertIsNone(root.parent)
        self.assertMatrix(evaluated_world(root), current)
        self.assertMatrix(evaluated_world(part), part_before)
        self.assertEqual(tuple(root.delta_location), (0.10000000149011612, -0.20000000298023224, 0.05000000074505806))

    def test_invalid_bone_and_singular_input_do_not_create_objects(self):
        arm, names = make_human()
        before = set(bpy.data.objects)
        with self.assertRaises(self.mounts.HumanoidMountError):
            self.mounts.create_mount(arm, "missing", "hand_r")
        self.assertEqual(before, set(bpy.data.objects))
        part = make_part()
        before = set(bpy.data.objects)
        with self.assertRaises(self.mounts.HumanoidMountError):
            self.weapons.prepare_grip_root([part], Matrix.Scale(0.0, 4))
        self.assertEqual(before, set(bpy.data.objects))
        self.assertIsNone(part.parent)

    def test_unsupported_weapon_state_is_rejected_without_mutation(self):
        arm, names, mount, root, part = self.armed()
        root.constraints.new("COPY_LOCATION")
        before = evaluated_world(root)
        with self.assertRaises(self.mounts.HumanoidMountError):
            self.weapons.bind_weapon(root, mount, "SNAP")
        self.assertIsNone(root.parent)
        self.assertMatrix(evaluated_world(root), before)

    def test_empty_animation_container_is_not_treated_as_an_animated_weapon(self):
        part = make_part("PreviouslyKeyedPart")
        part.animation_data_create()
        before = evaluated_world(part)
        root = self.weapons.prepare_grip_root([part], Matrix.Identity(4))
        self.assertEqual(part.parent, root)
        self.assertMatrix(evaluated_world(part), before)
        self.assertIsNone(part.animation_data.action)
