import unittest

import numpy as np

from run_spring_bone_contact_audit import independent_intersections, point_inside_votes


class SpringBoneContactAudit(unittest.TestCase):
    def test_independent_plane_intervals_measure_real_intersection(self):
        first = np.array([[-1., -1., 0.], [1., -1., 0.], [0., 1., 0.]])
        second = np.array([[0., -.5, -1.], [0., -.5, 1.], [0., .5, 1.]])
        triangles = np.array([[0, 1, 2]])
        result = independent_intersections(first, triangles, second, triangles)
        self.assertEqual(result["pairs"], 1)
        self.assertGreater(result["maximum_segment"], 0.1)
        self.assertEqual(independent_intersections(first, triangles, second + [3., 0., 0.], triangles)["pairs"], 0)

    def test_closed_volume_ray_votes_distinguish_inside_and_outside(self):
        points = np.array([[-1., -1., -1.], [1., -1., -1.], [1., 1., -1.], [-1., 1., -1.], [-1., -1., 1.], [1., -1., 1.], [1., 1., 1.], [-1., 1., 1.]])
        triangles = np.array([[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4], [1, 2, 6], [1, 6, 5], [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]])
        rows = point_inside_votes(np.array([[0., 0., 0.], [2., 0., 0.]]), points, triangles)
        self.assertEqual(rows[0]["inside_votes"], 3)
        self.assertAlmostEqual(rows[0]["nearest_surface_distance"], 1.0)
        self.assertEqual(rows[1]["inside_votes"], 0)
