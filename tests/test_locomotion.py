import unittest

from character_locomotion import locomotion
from character_control_fixtures import CharacterTestCase
import bpy


class MovementTests(unittest.TestCase):
    def test_walk_direction(self):
        self.assertEqual(locomotion.movement_intent({"UP_ARROW"}), (0.0, 1.0, "WALK"))

    def test_diagonal_normalized(self):
        x, y, state = locomotion.movement_intent({"UP_ARROW", "RIGHT_ARROW"})
        self.assertAlmostEqual(x * x + y * y, 1.0)
        self.assertEqual(state, "WALK")

    def test_double_shift_release(self):
        keys = {"UP_ARROW", "LEFT_SHIFT", "RIGHT_SHIFT"}
        self.assertEqual(locomotion.movement_intent(keys)[2], "RUN")
        keys.remove("LEFT_SHIFT")
        self.assertEqual(locomotion.movement_intent(keys)[2], "RUN")

    def test_idle_and_opposite(self):
        for keys in ({"LEFT_SHIFT"}, {"UP_ARROW", "DOWN_ARROW"}, set()):
            self.assertEqual(locomotion.movement_intent(keys), (0.0, 0.0, "IDLE"))

    def test_frame_rates_and_units(self):
        for rate in (30, 60, 120):
            self.assertAlmostEqual(sum(locomotion.travel(1 / rate, 1.5, 0.01) for _ in range(rate)), 150)

    def test_stall_clamped(self):
        self.assertAlmostEqual(locomotion.travel(10, 2, 1), 0.1)
        with self.assertRaises(ValueError):
            locomotion.travel(0.01, 2, 0)


class PageContractTests(CharacterTestCase):
    def test_live_spring_owner_is_rejected_without_mutation(self):
        from test_spring_bone_realtime import SpringBoneRealtime
        from spring_bone import operators as spring
        SpringBoneRealtime.setUpClass()
        case = SpringBoneRealtime()
        try:
            case.setUp()
            job = case._start()
            action = job.armature.animation_data.action
            with self.assertRaisesRegex(ValueError, "动态骨骼"):
                locomotion.validate_character(job.armature, bpy.context)
            self.assertTrue(spring.realtime_running())
            self.assertEqual(job.armature.animation_data.action, action)
        finally:
            case.tearDown()
            SpringBoneRealtime.tearDownClass()

    def test_readiness_and_stable_rename(self):
        self.assertEqual(locomotion.readiness(self.rig), "")
        self.clips["WALK"].name = "renamed action with a long display name"
        self.assertEqual(locomotion.readiness(self.rig), "")
        self.rig.cl_settings.walk_id = ""
        self.assertIn("行走", locomotion.readiness(self.rig))

    def test_selected_mesh_single_and_ambiguous_armature(self):
        from character_control_fixtures import make_rig
        mesh = bpy.data.objects.new("Skin", bpy.data.meshes.new("Skin"))
        bpy.context.collection.objects.link(mesh)
        modifier = mesh.modifiers.new("Skeleton", "ARMATURE")
        modifier.object = self.rig
        self.assertEqual(locomotion.resolve_character(mesh), self.rig)
        modifier = mesh.modifiers.new("SecondSkeleton", "ARMATURE")
        modifier.object = make_rig("Another")
        with self.assertRaises(ValueError):
            locomotion.resolve_character(mesh)

    def test_validation_after_external_action_change(self):
        from character_locomotion import animation_library as library
        library.validate_clip(self.clips["IDLE"], self.rig, self.scene)
        self.clips["IDLE"].slot_id = "invalid-slot"
        with self.assertRaises(ValueError):
            library.validate_clip(self.clips["IDLE"], self.rig, self.scene)

    def test_failed_load_keeps_bindings(self):
        from character_locomotion import animation_library as library
        before = self.rig.cl_settings.walk_id
        with self.assertRaises(Exception):
            library.load_library(self.rig, self.scene, "//does-not-exist.blend")
        self.assertEqual(self.rig.cl_settings.walk_id, before)
