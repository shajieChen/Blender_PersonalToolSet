"""Regression: proximal-π fold flip is banned (candy-wrapper).

Frame-11 Hand-IK bisect (body.FBX / 突刺 glb) showed identical forearm_l
quaternions on HEAD vs working tree — uncommitted fold was not the cause of
the screenshot bend. Hand IK already produces opposed fold on committed code.
"""
import math
import inspect
import unittest

from mathutils import Matrix, Quaternion, Vector

from humanoid_retarget import retarget
from humanoid_retarget.retarget import should_flip_limb_fold


def _proximal_pi_flip_binormal(proximal: Vector, binormal: Vector) -> Vector:
    return Quaternion(proximal.normalized(), math.pi) @ binormal


class LimbFoldTests(unittest.TestCase):
    def test_matching_bind_side_does_not_flip(self):
        rest = Vector((0.0, 0.0, 1.0))
        posed = Vector((0.0, 0.0, 2.0))
        self.assertFalse(should_flip_limb_fold(rest, Matrix.Identity(3), posed))

    def test_opposing_fold_detected(self):
        rest = Vector((0.0, 0.0, 1.0))
        posed = Vector((0.0, 0.0, -1.0))
        self.assertTrue(should_flip_limb_fold(rest, Matrix.Identity(3), posed))

    def test_straight_limb_skips(self):
        rest = Vector((0.0, 0.0, 1.0))
        posed = Vector((0.0, 0.0, 0.0))
        self.assertFalse(should_flip_limb_fold(rest, Matrix.Identity(3), posed))

    def test_proximal_pi_flip_inverts_binormal_and_is_banned(self):
        proximal = Vector((0.0, 1.0, 0.0))
        binormal = Vector((0.0, 0.0, 1.0))
        after = _proximal_pi_flip_binormal(proximal, binormal)
        self.assertLess(
            after.dot(binormal),
            0.0,
            msg="documents why π-about-proximal must not run in bake",
        )

    def test_bake_loop_does_not_call_fold_correction(self):
        source = inspect.getsource(retarget._bake_retarget)
        self.assertNotIn(
            "correct_limb_fold_directions(",
            source,
            msg="proximal-π fold must stay out of the bake loop",
        )


if __name__ == "__main__":
    unittest.main()
