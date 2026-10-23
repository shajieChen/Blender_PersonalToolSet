import pathlib
import sys
import types
import unittest
from unittest.mock import patch

import bpy
from mathutils import Vector

root = pathlib.Path(__file__).resolve().parents[1]
arguments = sys.argv[sys.argv.index("--") + 1:]
package = types.ModuleType("humanoid_retarget")
package.__path__ = [arguments[0]]
sys.modules["humanoid_retarget"] = package
sys.path.insert(0, str(root / "tests"))

from humanoid_retarget import ik
from test_pelvis_ik import PelvisIkTests


class ContactGoalTests(unittest.TestCase):
    def check_contact_goal(self, role):
        fixture = PelvisIkTests()
        fixture.setUp()
        fixture.settings.pelvis_ik_mode = "PIN_INPUT"
        for limb in fixture.geometry.limbs:
            limb.contact_local = (Vector(),)
        latest = {}
        solves = []
        original_pole = ik.transfer_source_fold_pole
        original_solve = ik._solve_chain

        def record_pole(src, source_space, tgt, target_space, limb, goal):
            latest[limb.roles[2]] = goal.copy()
            return original_pole(src, source_space, tgt, target_space, limb, goal)

        def check_solve(tgt, space, limb, goal, pole_hint=None):
            if limb.roles[2] == role:
                solves.append(goal.position.copy())
                self.assertLess((latest[role] - goal.position).length, 1e-6)
            return original_solve(tgt, space, limb, goal, pole_hint=pole_hint)

        plan = {(bpy.context.scene.frame_current, role): Vector((0.0, 0.0, 0.05))}
        with patch.object(ik, "_CONTACT_STACK_ENABLED", True), patch.object(ik, "_CORRECTION_PLAN", plan), patch.object(ik, "transfer_source_fold_pole", record_pole), patch.object(ik, "_solve_chain", check_solve):
            fixture.solve()
        self.assertGreaterEqual(len(solves), 2)
        self.assertGreater((solves[0] - solves[-1]).length, 0.01)

    def test_left_contact_recomputes_pole_after_goal_changes(self):
        self.check_contact_goal("foot_l")

    def test_right_contact_recomputes_pole_after_goal_changes(self):
        self.check_contact_goal("foot_r")


result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ContactGoalTests))
print("CONTACT_GOAL_SELECTED", result.testsRun)
sys.exit(0 if result.wasSuccessful() and result.testsRun > 0 else 1)
