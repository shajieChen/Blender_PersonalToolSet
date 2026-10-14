import unittest

from mathutils import Vector

from humanoid_retarget.soft_repulsion import (
    SoftRepulsionSettings,
    closest_point_on_segment,
    integrate_verlet,
    sphere_force,
)


class SoftRepulsionTests(unittest.TestCase):
    def test_cubic_midpoint(self):
        settings = SoftRepulsionSettings()
        force = sphere_force(
            Vector((0.25, 0.0, 0.0)),
            Vector((0.0, 0.0, 0.0)),
            0.10,
            settings,
        )
        self.assertAlmostEqual(force.x, 0.08, places=6)

    def test_inside_keeps_raw_direction(self):
        force = sphere_force(
            Vector((0.05, 0.0, 0.0)),
            Vector((0.0, 0.0, 0.0)),
            0.10,
            SoftRepulsionSettings(),
        )
        self.assertAlmostEqual(force.x, 3.2, places=5)

    def test_center_has_zero_force(self):
        force = sphere_force(
            Vector((0.0, 0.0, 0.0)),
            Vector((0.0, 0.0, 0.0)),
            0.10,
            SoftRepulsionSettings(),
        )
        self.assertEqual(tuple(force), (0.0, 0.0, 0.0))

    def test_equal_range_uses_strict_boundary(self):
        settings = SoftRepulsionSettings(
            minimum_distance_m=0.10,
            maximum_distance_m=0.10,
        )
        force = sphere_force(
            Vector((0.10, 0.0, 0.0)),
            Vector((0.0, 0.0, 0.0)),
            0.0,
            settings,
        )
        self.assertEqual(tuple(force), (0.0, 0.0, 0.0))

    def test_inverted_far_field(self):
        settings = SoftRepulsionSettings(inverted=True)
        force = sphere_force(
            Vector((1.0, 0.0, 0.0)),
            Vector((0.0, 0.0, 0.0)),
            0.0,
            settings,
        )
        self.assertAlmostEqual(force.x, -0.64, places=6)

    def test_degenerate_segment(self):
        start = Vector((1.0, 2.0, 3.0))
        result = closest_point_on_segment(
            Vector((8.0, 9.0, 10.0)), start, start
        )
        self.assertEqual(tuple(result), tuple(start))

    def test_verlet_formula(self):
        position, velocity = integrate_verlet(
            Vector((0.0, 0.0, 0.0)),
            Vector((0.0, 0.0, 0.0)),
            Vector((0.08, 0.0, 0.0)),
            1.0,
            0.01,
            1.0,
            0.1,
        )
        self.assertAlmostEqual(velocity.x, 0.00792, places=7)
        self.assertAlmostEqual(position.x, 0.000792, places=8)


if __name__ == "__main__":
    unittest.main()
