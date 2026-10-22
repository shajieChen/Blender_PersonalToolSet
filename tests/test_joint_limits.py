import math
import unittest

from mathutils import Quaternion, Vector

from humanoid_retarget.joint_limits import (
    AxisAngleLimit,
    BoneAngleLimits,
    JointBody,
    JointRotationConstraint,
    LimitType,
    bone_limits_are_free,
    decompose_rotation_angles,
    detect_hinge_axis_index,
    fixed_bone_limits,
    hinge_bone_limits,
    joint_limits_are_ineffective,
    provisional_arm_joint_limits,
    run_rotation_limit_pass,
    update_joint_limits,
)


def make_joint(limits, degrees=0.0, axis=(0.0, 0.0, 1.0)):
    identity = Quaternion((1.0, 0.0, 0.0, 0.0))
    parent = JointBody(
        identity.copy(),
        identity.copy(),
        BoneAngleLimits(rotation_stiffness=1.0),
        inverse_mass=0.0,
    )
    child = JointBody(
        Quaternion(axis, math.radians(degrees)),
        identity.copy(),
        limits,
    )
    return JointRotationConstraint(parent, child, identity.copy())


class JointLimitTests(unittest.TestCase):
    def test_free_does_not_repair_range(self):
        limits = BoneAngleLimits(
            x=AxisAngleLimit(LimitType.FREE, 10.0, -10.0)
        )
        joint = make_joint(limits, 50.0)
        before = tuple(joint.child.rotation)
        update_joint_limits(joint, True, 30.0)
        self.assertEqual(tuple(joint.child.rotation), before)
        self.assertEqual(limits.x.maximum, -10.0)

    def test_reversed_range_becomes_min_plus_one(self):
        limits = BoneAngleLimits(
            x=AxisAngleLimit(LimitType.LIMITED, 10.0, -10.0)
        )
        update_joint_limits(make_joint(limits), True, 30.0)
        self.assertEqual(limits.x.maximum, 11.0)

    def test_two_degrees_is_limited(self):
        limits = BoneAngleLimits(
            x=AxisAngleLimit(LimitType.LOCKED),
            y=AxisAngleLimit(LimitType.LOCKED),
            z=AxisAngleLimit(LimitType.LIMITED, 0.0, 2.0),
        )
        joint = make_joint(limits, 20.0)
        run_rotation_limit_pass((joint,), True, 30.0)
        angle = decompose_rotation_angles(joint)[0][2]
        self.assertAlmostEqual(angle, 2.0, places=3)

    def test_less_than_two_degrees_is_fixed(self):
        limits = BoneAngleLimits(
            x=AxisAngleLimit(LimitType.LOCKED),
            y=AxisAngleLimit(LimitType.LOCKED),
            z=AxisAngleLimit(LimitType.LIMITED, 10.0, 11.0),
        )
        joint = make_joint(limits, 20.0)
        run_rotation_limit_pass((joint,), True, 30.0)
        self.assertAlmostEqual(abs(joint.child.rotation.w), 1.0, places=5)

    def test_hinge_final_limit(self):
        limits = BoneAngleLimits(
            x=AxisAngleLimit(LimitType.LOCKED),
            y=AxisAngleLimit(LimitType.LOCKED),
            z=AxisAngleLimit(LimitType.LIMITED, -30.0, 30.0),
        )
        joint = make_joint(limits, 60.0)
        run_rotation_limit_pass((joint,), True, 0.0)
        angle = decompose_rotation_angles(joint)[0][2]
        self.assertAlmostEqual(angle, 30.0, places=3)

    def test_y_angle_has_source_negative_sign(self):
        joint = make_joint(
            BoneAngleLimits(), 30.0, (0.0, 1.0, 0.0)
        )
        angle = decompose_rotation_angles(joint)[0][1]
        self.assertAlmostEqual(angle, -30.0, places=3)

    def test_single_locked_axis_has_no_extra_branch(self):
        limits = BoneAngleLimits(
            x=AxisAngleLimit(LimitType.LOCKED)
        )
        joint = make_joint(limits, 30.0, (1.0, 0.0, 0.0))
        before = tuple(joint.child.rotation)
        update_joint_limits(joint, True, 30.0)
        self.assertEqual(tuple(joint.child.rotation), before)

    def test_free_only_configs_are_ineffective(self):
        self.assertTrue(joint_limits_are_ineffective(()))
        self.assertTrue(joint_limits_are_ineffective((
            BoneAngleLimits(role="forearm_l"),
        )))
        self.assertFalse(bone_limits_are_free(fixed_bone_limits("shoulder_l")))
        self.assertFalse(joint_limits_are_ineffective(
            provisional_arm_joint_limits()
        ))

    def test_hinge_axis_follows_cross_product(self):
        proximal = Vector((0.0, 1.0, 0.0))
        distal = Vector((0.0, 1.0, 0.1))
        local = (
            Vector((1.0, 0.0, 0.0)),
            Vector((0.0, 1.0, 0.0)),
            Vector((0.0, 0.0, 1.0)),
        )
        self.assertEqual(detect_hinge_axis_index(proximal, distal, local), 0)
        limits = hinge_bone_limits("forearm_l", 0)
        self.assertEqual(limits.x.kind, LimitType.FREE)
        self.assertEqual(limits.y.kind, LimitType.LOCKED)
        self.assertEqual(limits.z.kind, LimitType.LOCKED)


if __name__ == "__main__":
    unittest.main()
