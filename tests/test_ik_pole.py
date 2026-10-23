"""TDD: two-bone IK pole must follow the bind fold side."""
import unittest

from mathutils import Vector

from humanoid_retarget.ik import align_pole_to_bind_side, bind_oriented_pole


class IkPoleTests(unittest.TestCase):
    def test_matching_side_unchanged(self):
        root = Vector((0.0, 0.0, 0.0))
        target = Vector((0.0, 2.0, 0.0))
        ref = Vector((1.0, 1.0, 0.0))
        pole = Vector((0.5, 1.0, 0.0))
        out = align_pole_to_bind_side(root, pole, ref, target)
        self.assertGreater(out.x, 0.0)
        self.assertAlmostEqual(out.x, pole.x, places=5)

    def test_opposite_side_flips_to_bind(self):
        root = Vector((0.0, 0.0, 0.0))
        target = Vector((0.0, 2.0, 0.0))
        ref = Vector((1.0, 1.0, 0.0))
        pole = Vector((-0.8, 1.0, 0.0))
        out = align_pole_to_bind_side(root, pole, ref, target)
        self.assertGreater(out.x, 0.0)
        direction = (target - root).normalized()
        pole_perp = (pole - root) - direction * (pole - root).dot(direction)
        out_perp = (out - root) - direction * (out - root).dot(direction)
        self.assertAlmostEqual(out_perp.length, pole_perp.length, places=5)

    def test_degenerate_mid_uses_reference(self):
        root = Vector((0.0, 0.0, 0.0))
        target = Vector((0.0, 2.0, 0.0))
        ref = Vector((1.0, 1.0, 0.0))
        pole = Vector((0.0, 1.0, 0.0))
        out = align_pole_to_bind_side(root, pole, ref, target)
        self.assertGreater(out.x, 0.0)

    def test_bind_oriented_pole_preserves_side_when_aim_swings(self):
        rest_root = Vector((0.0, 0.0, 0.0))
        rest_mid = Vector((1.0, 1.0, 0.0))
        rest_end = Vector((0.0, 2.0, 0.0))
        root = Vector((0.0, 0.0, 0.0))
        target = Vector((2.0, 0.0, 0.0))
        out = bind_oriented_pole(root, target, rest_root, rest_mid, rest_end)
        direction = (target - root).normalized()
        perp = (out - root) - direction * (out - root).dot(direction)
        self.assertGreater(perp.length, 0.1)
        rest_dir = (rest_end - rest_root).normalized()
        rest_perp = (rest_mid - rest_root) - rest_dir * (rest_mid - rest_root).dot(rest_dir)
        swing = rest_dir.rotation_difference(direction)
        expected = swing @ rest_perp
        self.assertGreater(perp.dot(expected), 0.0)

    def test_straight_bind_uses_preferred_side_behind(self):
        # T-pose style: arm along +X, character forward +Y, elbow behind = -Y.
        rest_root = Vector((0.0, 0.0, 0.0))
        rest_mid = Vector((1.0, 0.0, 0.0))
        rest_end = Vector((2.0, 0.0, 0.0))
        root = Vector((0.0, 0.0, 0.0))
        target = Vector((1.5, 0.0, 0.0))
        out = bind_oriented_pole(
            root, target, rest_root, rest_mid, rest_end,
            preferred_side=Vector((0.0, -1.0, 0.0)),
        )
        direction = (target - root).normalized()
        perp = (out - root) - direction * (out - root).dot(direction)
        self.assertLess(perp.y, 0.0)
