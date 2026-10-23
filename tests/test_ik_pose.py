import math
import unittest

import bpy
from mathutils import Matrix, Quaternion, Vector

from humanoid_retarget.foot_ik import IKGoal, LimbReference
from humanoid_retarget.ik import _aim_joint, _solve_chain, _write_end_rotation
from humanoid_retarget.motion_space import MotionSpace


class IkPoseTests(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        data = bpy.data.armatures.new("Leg")
        self.rig = bpy.data.objects.new("Leg", data)
        bpy.context.collection.objects.link(self.rig)
        bpy.context.view_layer.objects.active = self.rig
        self.rig.select_set(True)
        bpy.ops.object.mode_set(mode="EDIT")
        upper = data.edit_bones.new("Thigh")
        upper.head = (0.0, 0.0, 2.0)
        upper.tail = (0.2, 0.0, 1.0)
        upper.roll = 0.4
        middle = data.edit_bones.new("Calf")
        middle.head = upper.tail
        middle.tail = (0.0, 0.0, 0.0)
        middle.parent = upper
        middle.roll = -0.7
        end = data.edit_bones.new("Foot")
        end.head = middle.tail
        end.tail = (0.0, -0.2, 0.0)
        end.parent = middle
        bpy.ops.object.mode_set(mode="OBJECT")
        self.space = MotionSpace(Matrix.Identity(3), Vector(), 1.0, Matrix.Identity(4))
        length = (Vector((0.2, 0.0, 1.0)) - Vector((0.0, 0.0, 2.0))).length
        rotation = self.rig.pose.bones["Foot"].matrix.to_quaternion()
        self.reference = LimbReference(
            roles=("thigh_l", "shin_l", "foot_l"),
            source_names=("Thigh", "Calf", "Foot"),
            target_names=("Thigh", "Calf", "Foot"),
            source_initial_length=2.0,
            target_initial_length=2.0,
            target_upper_length=length,
            target_lower_length=length,
            source_end_rotation=rotation,
            target_end_rotation=rotation,
            height_offset=0.0,
            source_rest_end_height=0.0,
            reference_pole=Vector((0.2, 0.0, 1.0)),
        )

    def test_explicit_source_pole_is_not_overridden_by_bind_side(self):
        goal = IKGoal(Vector((0.0, 0.0, 0.5)), self.reference.target_end_rotation)
        error = _solve_chain(self.rig, self.space, self.reference, goal, Vector((-1.0, 0.0, 1.0)))
        self.assertLess(self.rig.pose.bones["Calf"].head.x, -0.1)
        self.assertLess(error, 1e-5)

    def test_missing_source_pole_uses_bind_side(self):
        goal = IKGoal(Vector((0.0, 0.0, 0.5)), self.reference.target_end_rotation)
        error = _solve_chain(self.rig, self.space, self.reference, goal)
        self.assertGreater(self.rig.pose.bones["Calf"].head.x, 0.1)
        self.assertLess(error, 1e-5)

    def test_source_pole_applies_to_right_leg(self):
        self.reference.roles = ("thigh_r", "shin_r", "foot_r")
        goal = IKGoal(Vector((0.0, 0.0, 0.5)), self.reference.target_end_rotation)
        error = _solve_chain(self.rig, self.space, self.reference, goal, Vector((-1.0, 0.0, 1.0)))
        self.assertLess(self.rig.pose.bones["Calf"].head.x, -0.1)
        self.assertLess(error, 1e-5)

    def test_source_pole_applies_to_arm_chains(self):
        self.reference.roles = ("upperarm_l", "forearm_l", "hand_l")
        goal = IKGoal(Vector((0.0, 0.0, 0.5)), self.reference.target_end_rotation)
        error = _solve_chain(self.rig, self.space, self.reference, goal, Vector((-1.0, 0.0, 1.0)))
        self.assertLess(self.rig.pose.bones["Calf"].head.x, -0.1)
        self.assertLess(error, 1e-5)

    def test_joint_aim_preserves_existing_local_scale(self):
        pose = self.rig.pose.bones["Thigh"]
        pose.scale = (1.1, 0.9, 1.05)
        bpy.context.view_layer.update()
        original = tuple(pose.scale)
        for direction in ((0.6, 0.3, -0.7), (-0.4, 0.2, -0.8), (0.3, -0.5, -0.6)):
            _aim_joint(self.rig, "Thigh", "Calf", self.space, Vector(direction))
            bpy.context.view_layer.update()
            self.assertEqual(tuple(pose.scale), original)

    def test_end_rotation_preserves_existing_local_scale(self):
        pose = self.rig.pose.bones["Foot"]
        pose.scale = (1.1, 0.9, 1.05)
        bpy.context.view_layer.update()
        original = tuple(pose.scale)
        _write_end_rotation(self.rig, "Foot", self.space, Quaternion(Vector((0.2, 0.4, 0.7)).normalized(), 1.2))
        self.assertEqual(tuple(pose.scale), original)

    def test_uniform_small_local_scale_is_preserved(self):
        pose = self.rig.pose.bones["Foot"]
        pose.scale = (0.01, 0.01, 0.01)
        bpy.context.view_layer.update()
        original = tuple(pose.scale)
        _write_end_rotation(self.rig, "Foot", self.space, Quaternion(Vector((0.2, 0.4, 0.7)).normalized(), 1.2))
        self.assertEqual(tuple(pose.scale), original)

    def check_hinge_twist(self, twist, bend=0.0, off_axis=False):
        if off_axis:
            bpy.ops.object.mode_set(mode="EDIT")
            self.rig.data.edit_bones["Thigh"].tail = (0.4, 0.7, 2.1)
            self.rig.data.edit_bones["Calf"].tail = (-0.3, 0.6, 1.2)
            bpy.ops.object.mode_set(mode="OBJECT")
        calf = self.rig.pose.bones["Calf"]
        axis = calf.bone.matrix_local.to_3x3().inverted() @ (
            self.rig.data.bones["Foot"].head_local - calf.bone.head_local
        )
        axis.normalize()
        bend_axis = Vector((1.0, 0.0, 0.0)) if not off_axis else axis.orthogonal().normalized()
        calf.rotation_mode = "QUATERNION"
        calf.rotation_quaternion = Quaternion(bend_axis, bend) @ Quaternion(axis, twist)
        bpy.context.view_layer.update()
        goal = IKGoal(Vector((0.0, 0.3, 0.5)), self.reference.target_end_rotation)
        error = _solve_chain(self.rig, self.space, self.reference, goal, Vector((-1.0, -0.2, 1.0)))
        rotation = calf.rotation_quaternion.normalized()
        actual = 2.0 * math.atan2(Vector((rotation.x, rotation.y, rotation.z)).dot(axis), rotation.w)
        difference = (actual - twist + math.pi) % (2.0 * math.pi) - math.pi
        self.assertAlmostEqual(difference, 0.0, delta=1e-4)
        self.assertLess(error, 1e-5)

    def test_bend_plane_change_does_not_add_calf_twist(self):
        self.check_hinge_twist(0.0)

    def test_bend_plane_change_preserves_animated_calf_twist(self):
        self.check_hinge_twist(0.35)

    def test_prebent_calf_does_not_gain_axial_twist(self):
        self.check_hinge_twist(0.0, 0.9)

    def test_prebent_calf_keeps_animated_axial_twist(self):
        self.check_hinge_twist(0.35, 0.9)

    def test_off_axis_joints_do_not_gain_axial_twist(self):
        self.check_hinge_twist(0.0, 0.9, off_axis=True)

    def test_off_axis_joints_preserve_animated_axial_twist(self):
        self.check_hinge_twist(0.35, 0.9, off_axis=True)
