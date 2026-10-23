import math
import unittest
from unittest.mock import patch

import bpy
from mathutils import Matrix, Quaternion, Vector

from humanoid_retarget import foot_ik
from humanoid_retarget.foot_ik import FootIKSettings, LimbReference, PelvisReference, RetargetGeometry
from humanoid_retarget.ik import apply_contact_ik
from humanoid_retarget import ik
from humanoid_retarget.motion_space import MotionSpace, build_motion_space
from humanoid_retarget.retarget import RetargetError, RetargetOptions, _prepare_retarget_geometry, _solve_pose_channel_chain


class PelvisIkTests(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.source = self.make_rig("Input", 0.0)
        self.target = self.make_rig("Output", 0.3)
        self.space = MotionSpace(Matrix.Identity(3), Vector(), 1.0, Matrix.Identity(4))
        limbs = []
        for side in ("L", "R"):
            names = tuple(side + name for name in ("Upper", "Knee", "Ankle"))
            rotation = self.target.pose.bones[names[2]].matrix.to_quaternion()
            limbs.append(LimbReference(
                ("thigh_" + side.lower(), "shin_" + side.lower(), "foot_" + side.lower()),
                names, names, 2.0, 2.0, math.sqrt(1.04), math.sqrt(1.04),
                rotation, rotation, 0.3, 0.0, Vector((0.0, -0.2, 1.0)),
            ))
        self.geometry = RetargetGeometry(
            self.space, self.space,
            PelvisReference("Body", "Body", Vector((0.0, 0.0, 2.0)), Vector((0.0, 0.0, 2.3)), 0.5, Vector()),
            tuple(limbs),
        )
        self.settings = FootIKSettings(maintain_height_offset=0.0, planting_enabled=False)

    def make_rig(self, name, height):
        data = bpy.data.armatures.new(name)
        rig = bpy.data.objects.new(name, data)
        bpy.context.collection.objects.link(rig)
        bpy.context.view_layer.objects.active = rig
        rig.select_set(True)
        bpy.ops.object.mode_set(mode="EDIT")
        body = data.edit_bones.new("Body")
        body.head = (0.0, 0.0, 2.0 + height)
        body.tail = (0.0, 0.0, 2.2 + height)
        for side, x in (("L", -0.2), ("R", 0.2)):
            upper = data.edit_bones.new(side + "Upper")
            upper.head = (x, 0.0, 2.0 + height)
            upper.tail = (x, -0.2, 1.0 + height)
            upper.parent = body
            knee = data.edit_bones.new(side + "Knee")
            knee.head = upper.tail
            knee.tail = (x, 0.0, height)
            knee.parent = upper
            foot = data.edit_bones.new(side + "Ankle")
            foot.head = knee.tail
            foot.tail = (x, -0.3, height)
            foot.parent = knee
        bpy.ops.object.mode_set(mode="OBJECT")
        rig.select_set(False)
        return rig

    def solve(self):
        apply_contact_ik(self.source, self.target, self.geometry, self.settings, {}, {}, Vector(), 1.0 / 30.0)

    def geometry_options(self):
        pairs = [("hips", "Body", "Body")]
        for limb in self.geometry.limbs:
            pairs.extend(zip(limb.roles, limb.source_names, limb.target_names))
        return pairs, RetargetOptions(pairs=pairs, foot_ik=True, foot_ik_settings=self.settings)

    def test_geometry_reference_lengths_use_object_scale_once(self):
        for obj in (self.source, self.target):
            obj.matrix_world = Matrix.LocRotScale(Vector((4.0, -1.0, 0.0)), Quaternion((0.0, 0.0, 1.0), -0.7), Vector((0.01,) * 3))
        bpy.context.view_layer.update()
        pairs, options = self.geometry_options()
        geometry = _prepare_retarget_geometry(self.source, self.target, pairs, options, bpy.context.scene)
        self.assertAlmostEqual(geometry.limbs[0].target_upper_length, math.sqrt(1.04) * 0.01, delta=1e-7)

    def test_pose_channel_solver_uses_armature_space_for_transformed_object(self):
        self.target.matrix_world = Matrix.LocRotScale(Vector((4.0, -1.0, 0.0)), Quaternion((0.0, 0.0, 1.0), -0.7), Vector((0.01,) * 3))
        bpy.context.view_layer.update()
        pairs, options = self.geometry_options()
        geometry = _prepare_retarget_geometry(self.source, self.target, pairs, options, bpy.context.scene, armature_coordinates=True)
        space = geometry.target_space
        limb = geometry.limbs[0]
        goal = foot_ik.IKGoal(space.position(self.target.pose.bones["LAnkle"].head) + Vector((0.0, 0.0, 0.005)), space.rotation(self.target.pose.bones["LAnkle"].matrix))
        _solve_pose_channel_chain(self.target, space, limb, goal, None)
        actual = space.position(self.target.pose.bones["LAnkle"].head)
        self.assertLess((actual - goal.position).length, 1e-6)

    def test_detached_leg_is_rejected_before_pelvis_coordination(self):
        bpy.context.view_layer.objects.active = self.target
        self.target.select_set(True)
        bpy.ops.object.mode_set(mode="EDIT")
        self.target.data.edit_bones["LUpper"].parent = None
        bpy.ops.object.mode_set(mode="OBJECT")
        pairs, options = self.geometry_options()
        with self.assertRaises(RetargetError):
            _prepare_retarget_geometry(self.source, self.target, pairs, options, bpy.context.scene)

    def test_asymmetric_segment_lengths_keep_feet_and_bone_lengths(self):
        bpy.context.view_layer.objects.active = self.target
        self.target.select_set(True)
        bpy.ops.object.mode_set(mode="EDIT")
        for side, knee_height in (("L", 1.7), ("R", 1.0)):
            knee = self.target.data.edit_bones[side + "Knee"]
            upper = self.target.data.edit_bones[side + "Upper"]
            knee.head = (upper.head.x, -0.15, knee_height)
            upper.tail = knee.head
        bpy.ops.object.mode_set(mode="OBJECT")
        bpy.context.view_layer.update()
        pairs, options = self.geometry_options()
        self.geometry = _prepare_retarget_geometry(self.source, self.target, pairs, options, bpy.context.scene)
        self.solve()
        for limb in self.geometry.limbs:
            points = [self.target.pose.bones[name].head for name in limb.target_names]
            self.assertAlmostEqual(points[2].z, 0.0, delta=1e-4)
            self.assertAlmostEqual((points[1] - points[0]).length, limb.target_upper_length, delta=1e-5)
            self.assertAlmostEqual((points[2] - points[1]).length, limb.target_lower_length, delta=1e-5)

    def test_ground_targets_pull_shared_pelvis_without_stretch(self):
        self.solve()
        self.assertAlmostEqual(self.target.pose.bones["Body"].head.z, 2.0, delta=1e-4)
        for side in ("L", "R"):
            points = [self.target.pose.bones[side + name].head for name in ("Upper", "Knee", "Ankle")]
            self.assertAlmostEqual(points[2].z, 0.0, delta=1e-4)
            self.assertAlmostEqual((points[1] - points[0]).length, math.sqrt(1.04), delta=1e-5)
            self.assertAlmostEqual((points[2] - points[1]).length, math.sqrt(1.04), delta=1e-5)

    def test_pelvis_compensation_precedes_first_leg_solve(self):
        heights = []
        original = ik._solve_chain

        def record(*args, **kwargs):
            heights.append(self.target.pose.bones["Body"].head.z)
            return original(*args, **kwargs)

        with patch.object(ik, "_solve_chain", record):
            self.solve()
        self.assertGreater(len(heights), 0)
        self.assertAlmostEqual(heights[0], 2.0, delta=1e-4)

    def test_pinned_pelvis_keeps_input_location(self):
        self.settings.pelvis_ik_mode = "PIN_INPUT"
        self.solve()
        self.assertAlmostEqual(self.target.pose.bones["Body"].head.z, 2.3, delta=1e-5)

    def test_zero_weight_keeps_input_location(self):
        self.settings.pelvis_ik_alpha = 0.0
        self.solve()
        self.assertAlmostEqual(self.target.pose.bones["Body"].head.z, 2.3, delta=1e-5)

    def test_configuration_rejects_unknown_mode(self):
        self.settings.pelvis_ik_mode = "UNKNOWN"
        with self.assertRaises(ValueError):
            foot_ik.validate_foot_ik_settings(self.settings)

    def test_configuration_rejects_nonfinite_weight(self):
        self.settings.pelvis_ik_alpha = float("nan")
        with self.assertRaises(ValueError):
            foot_ik.validate_foot_ik_settings(self.settings)

    def test_configuration_rejects_invalid_iterations(self):
        self.settings.pelvis_ik_iterations = -1
        with self.assertRaises(ValueError):
            foot_ik.validate_foot_ik_settings(self.settings)

    def test_translated_rotated_centimeter_rigs_keep_metric_solution(self):
        self.source.matrix_world = Matrix.LocRotScale(Vector((-2.0, 3.0, 0.0)), Quaternion((0.0, 0.0, 1.0), 0.4), Vector((0.01,) * 3))
        self.target.matrix_world = Matrix.LocRotScale(Vector((4.0, -1.0, 0.0)), Quaternion((0.0, 0.0, 1.0), -0.7), Vector((0.01,) * 3))
        bpy.context.view_layer.update()
        self.geometry.source_space = build_motion_space(self.source, Matrix.Identity(3), 1.0, 0.0)
        self.geometry.target_space = build_motion_space(self.target, Matrix.Identity(3), 1.0, 0.0)
        for limb in self.geometry.limbs:
            limb.source_initial_length *= 0.01
            limb.target_initial_length *= 0.01
            limb.target_upper_length *= 0.01
            limb.target_lower_length *= 0.01
        self.solve()
        self.assertAlmostEqual(self.target.pose.bones["Body"].head.z, 2.0, delta=1e-4)
        for side in ("L", "R"):
            self.assertAlmostEqual(self.target.pose.bones[side + "Ankle"].head.z, 0.0, delta=1e-4)

    def test_free_mode_resolves_competing_leg_reaches(self):
        self.settings.pelvis_ik_mode = "FREE"
        self.settings.pelvis_ik_rotation = 0.0
        self.settings.pelvis_ik_pose_weight = 0.0
        legs = (
            foot_ik.LegReachConstraint(Vector((-0.15, 0.0, 0.20)), Vector((-0.15, 0.08, 0.22)), Vector((-0.15, 0.08, 0.22)), 0.18, 0.445, Vector((0.0, -0.4, 0.9))),
            foot_ik.LegReachConstraint(Vector((0.15, 0.0, 0.40)), Vector((0.02, 0.12, 0.10)), Vector((0.02, 0.12, 0.10)), 0.32, 0.445, Vector((0.4, -0.4, 0.8))),
        )
        shift = foot_ik.solve_pelvis_motion(legs, self.settings, Vector())[0]
        for leg in legs:
            distance = (leg.root + shift - leg.goal).length
            self.assertGreaterEqual(distance, leg.minimum - 1e-5)
            self.assertLessEqual(distance, leg.maximum + 1e-5)
        reversed_shift = foot_ik.solve_pelvis_motion(tuple(reversed(legs)), self.settings, Vector())[0]
        self.assertLess((shift - reversed_shift).length, 1e-6)

    def test_zero_iteration_prepull_matches_centroid_formula(self):
        self.settings.pelvis_ik_iterations = 0
        self.settings.pelvis_ik_alpha = 0.5
        self.settings.pelvis_ik_horizontal = 0.25
        self.settings.pelvis_ik_vertical = 0.75
        legs = (
            foot_ik.LegReachConstraint(Vector((0.0, 0.0, 2.0)), Vector(), Vector((0.4, 0.2, 0.3)), 0.0, 3.0, Vector((0.0, 0.0, 1.0))),
            foot_ik.LegReachConstraint(Vector((0.0, 0.0, 2.0)), Vector(), Vector((-0.2, 0.6, 0.1)), 0.0, 3.0, Vector((0.0, 0.0, 1.0))),
        )
        shift = foot_ik.solve_pelvis_motion(legs, self.settings, Vector())[0]
        self.assertLess((shift - Vector((0.0125, 0.05, 0.075))).length, 1e-6)

    def test_conflicting_goals_remain_finite_and_do_not_change_inputs(self):
        leg = foot_ik.LegReachConstraint(Vector(), Vector(), Vector((0.0, 0.0, 10.0)), 1.0, 2.0, Vector((0.0, 0.0, -1.0)))
        opposite = foot_ik.LegReachConstraint(Vector(), Vector(), Vector((0.0, 0.0, -10.0)), 1.0, 2.0, Vector((0.0, 0.0, 1.0)))
        shift = foot_ik.solve_pelvis_motion((leg, opposite), self.settings, Vector())[0]
        self.assertTrue(all(math.isfinite(value) for value in shift))
        self.assertEqual(tuple(leg.goal), (0.0, 0.0, 10.0))
        self.assertEqual(tuple(opposite.goal), (0.0, 0.0, -10.0))

    def test_tilted_pelvis_does_not_straighten_the_opposite_leg(self):
        body = self.target.pose.bones["Body"]
        body.rotation_mode = "QUATERNION"
        body.rotation_quaternion = Quaternion((0.0, 0.0, 1.0), 0.65)
        bpy.context.view_layer.update()
        self.solve()
        self.assertGreater(body.head.z, 1.9)
        for side in ("L", "R"):
            root = self.target.pose.bones[side + "Upper"].head
            end = self.target.pose.bones[side + "Ankle"].head
            self.assertAlmostEqual((end - root).length, 2.0, delta=1e-4)
            self.assertAlmostEqual(end.z, 0.0, delta=1e-4)
            self.assertGreater(root.z, end.z)
