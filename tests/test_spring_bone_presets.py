import importlib
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

import bpy
from mathutils import Matrix


class SpringBonePresets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import spring_bone
        cls.spring = spring_bone
        spring_bone.register()

    @classmethod
    def tearDownClass(cls):
        cls.spring.unregister()

    def setUp(self):
        self.module = importlib.import_module("spring_bone.presets")
        from test_spring_bone_realtime import SpringBoneRealtime
        self.fixture = SpringBoneRealtime()
        self.fixture.setUp()
        self.arm = self.fixture.arm
        self.arm.sb_settings.chains.clear()
        self.names = [bone.name for bone in self.arm.data.bones]
        for index, bone in enumerate(self.arm.data.bones):
            bone.name = "Skirt.L" + ("." + str(index).zfill(3) if index else "")
        self.names = [bone.name for bone in self.arm.data.bones]

    def tearDown(self):
        self.fixture.tearDown()

    def preset(self, identifier):
        return self.module.load_preset(identifier)

    def test_builtin_catalog_contains_requested_profiles(self):
        self.assertTrue({"skirt_balanced", "skirt_soft", "hair", "tail"} <= {p["id"] for p in self.module.catalog("chain")})
        self.assertTrue({"humanoid_lower", "humanoid_upper", "humanoid_full"} <= {p["id"] for p in self.module.catalog("collider")})

    def test_detection_builds_contiguous_chain_without_writing(self):
        plan = self.module.build_chain_plan(self.arm, self.preset("skirt_balanced"), bpy.context.scene)
        self.assertEqual(plan["entries"][0]["bone_names"], self.names)
        self.assertEqual(len(self.arm.sb_settings.chains), 0)
        self.module.apply_plan(self.arm, plan)
        self.assertEqual([b.name for b in self.arm.sb_settings.chains[0].bone_names], self.names)

    def test_existing_chains_are_preserved_and_not_duplicated(self):
        preset = self.preset("skirt_balanced")
        self.module.apply_plan(self.arm, self.module.build_chain_plan(self.arm, preset, bpy.context.scene))
        self.arm.sb_settings.chains[0].stiffness = 9.
        plan = self.module.build_chain_plan(self.arm, preset, bpy.context.scene)
        self.assertEqual(plan["entries"], [])
        self.assertEqual(self.arm.sb_settings.chains[0].stiffness, 9.)

    def test_unrelated_hand_bones_are_not_detected(self):
        for bone in self.arm.data.bones:
            bone.name = "hand" + bone.name.replace("Skirt", "")
        plan = self.module.build_chain_plan(self.arm, self.preset("skirt_balanced"), bpy.context.scene)
        self.assertEqual(plan["entries"], [])

    def test_branch_children_are_split_without_shared_bones(self):
        bpy.ops.object.mode_set(mode="EDIT")
        parent = self.arm.data.edit_bones[self.names[0]]
        bone = self.arm.data.edit_bones.new("Skirt.R")
        bone.head, bone.tail, bone.parent = (0., .2, 1.), (.2, .4, 1.), parent
        bpy.ops.object.mode_set(mode="OBJECT")
        plan = self.module.build_chain_plan(self.arm, self.preset("skirt_balanced"), bpy.context.scene)
        names = [name for row in plan["entries"] for name in row["bone_names"]]
        self.assertEqual(len(names), len(set(names)))
        self.assertNotIn(self.names[0], names)
        self.assertEqual(len(plan["entries"]), 2)

    def test_collider_radius_scales_but_local_offsets_do_not_double_scale(self):
        preset = self.preset("humanoid_lower")
        roles = {"thigh_l": self.names[0]}
        first = self.module.build_collider_plan(self.arm, preset, bpy.context.scene, roles)
        self.arm.matrix_world = Matrix.Scale(2., 4)
        second = self.module.build_collider_plan(self.arm, preset, bpy.context.scene, roles)
        a, b = first["entries"][0], second["entries"][0]
        self.assertAlmostEqual(b["radius_m"], 2. * a["radius_m"])
        self.assertEqual(a["tail_offset_m"], b["tail_offset_m"])
        self.assertTrue(first["notices"])

    def test_collider_excludes_simulated_bones_and_descendants(self):
        self.module.apply_plan(self.arm, self.module.build_chain_plan(self.arm, self.preset("skirt_balanced"), bpy.context.scene))
        plan = self.module.build_collider_plan(self.arm, self.preset("humanoid_lower"), bpy.context.scene, {"thigh_l": self.names[1]})
        self.assertEqual(plan["entries"], [])

    def test_stale_plan_does_not_write_any_entries(self):
        plan = self.module.build_chain_plan(self.arm, self.preset("skirt_balanced"), bpy.context.scene)
        self.arm.data.bones[self.names[-1]].name = "Changed"
        with self.assertRaises(self.module.SpringBoneError):
            self.module.apply_plan(self.arm, plan)
        self.assertEqual(len(self.arm.sb_settings.chains), 0)

    def test_invalid_plan_is_atomic(self):
        plan = self.module.build_chain_plan(self.arm, self.preset("skirt_balanced"), bpy.context.scene)
        plan["entries"].append({"kind": "collider", "bone_name": "Missing", "shape": "SPHERE", "radius_m": .1, "head_offset_m": [0.,0.,0.], "tail_offset_m": [0.,0.,0.], "name": "Invalid"})
        with self.assertRaises(self.module.SpringBoneError):
            self.module.apply_plan(self.arm, plan)
        self.assertEqual(len(self.arm.sb_settings.chains), 0)
        self.assertEqual(len(self.arm.sb_settings.colliders), 0)

    def test_realtime_session_blocks_preset_application(self):
        preset = self.preset("skirt_balanced")
        self.module.apply_plan(self.arm, self.module.build_chain_plan(self.arm, preset, bpy.context.scene))
        self.fixture._start()
        with self.assertRaises(self.module.SpringBoneError):
            self.module.apply_plan(self.arm, self.module.build_chain_plan(self.arm, preset, bpy.context.scene))

    def test_character_preset_roundtrip_and_no_overwrite(self):
        self.module.apply_plan(self.arm, self.module.build_chain_plan(self.arm, self.preset("skirt_soft"), bpy.context.scene))
        with tempfile.TemporaryDirectory() as folder:
            path = self.module.save_character_preset(self.arm, bpy.context.scene, "MySkirt", pathlib.Path(folder))
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.arm.sb_settings.chains.clear()
            self.module.apply_plan(self.arm, self.module.build_character_plan(self.arm, saved, bpy.context.scene))
            self.assertEqual([b.name for b in self.arm.sb_settings.chains[0].bone_names], self.names)
            with self.assertRaises(self.module.SpringBoneError):
                self.module.save_character_preset(self.arm, bpy.context.scene, "MySkirt", pathlib.Path(folder))

    def test_preset_name_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(self.module.SpringBoneError):
                self.module.save_character_preset(self.arm, bpy.context.scene, "../escape", pathlib.Path(folder))

    def test_save_rejects_nonfinite_parameters(self):
        preset = self.preset("skirt_balanced")
        preset["parameters"]["stiffness"] = float("nan")
        with self.assertRaises(self.module.SpringBoneError):
            self.module.build_chain_plan(self.arm, preset, bpy.context.scene)

    def test_parameter_preset_only_changes_active_chain(self):
        self.module.apply_plan(self.arm, self.module.build_chain_plan(self.arm, self.preset("skirt_balanced"), bpy.context.scene))
        before = list(self.arm.sb_settings.chains[0].bone_names.keys())
        plan = self.module.build_parameter_plan(self.arm, self.preset("skirt_soft"), bpy.context.scene)
        self.module.apply_plan(self.arm, plan)
        self.assertEqual(list(self.arm.sb_settings.chains[0].bone_names.keys()), before)
        self.assertEqual(self.arm.sb_settings.chains[0].stiffness, self.preset("skirt_soft")["parameters"]["stiffness"])

    def test_operator_uses_explicit_target_in_object_mode(self):
        self.arm.sb_settings.chain_preset = "skirt_balanced"
        self.assertEqual(bpy.ops.spring_bone.apply_preset(operation="CHAINS"), {"FINISHED"})
        self.assertEqual(len(self.arm.sb_settings.chains), 1)
        self.assertTrue(hasattr(bpy.types, "SPRING_BONE_PT_presets"))

    def test_write_failure_rolls_back_added_collections(self):
        bpy.ops.object.mode_set(mode="EDIT")
        bone = self.arm.data.edit_bones.new("Leg")
        bone.head, bone.tail = (2., 0., 1.), (2., .5, 1.)
        bpy.ops.object.mode_set(mode="OBJECT")
        plan = self.module.build_chain_plan(self.arm, self.preset("skirt_balanced"), bpy.context.scene)
        plan["entries"].append({"kind":"collider", "name":"Leg", "bone_name":"Leg", "shape":"SPHERE", "radius_m":.1, "head_offset_m":[0.,0.,0.], "tail_offset_m":[0.,0.,0.]})
        original = self.module._write_fields
        def write(item, values):
            if "bone_name" in values:
                raise RuntimeError("injected write failure")
            original(item, values)
        before = self.arm.sb_settings.show_gizmos
        with patch.object(self.module, "_write_fields", side_effect=write):
            with self.assertRaises(RuntimeError):
                self.module.apply_plan(self.arm, plan)
        self.assertEqual(len(self.arm.sb_settings.chains), 0)
        self.assertEqual(len(self.arm.sb_settings.colliders), 0)
        self.assertEqual(self.arm.sb_settings.show_gizmos, before)

    def test_saved_colliders_keep_names_and_scale_on_load(self):
        plan = self.module.build_collider_plan(self.arm, self.preset("humanoid_lower"), bpy.context.scene, {"thigh_l":self.names[0]})
        self.module.apply_plan(self.arm, plan)
        collider = self.arm.sb_settings.colliders[0]
        collider.name = "MyLegCollision"
        radius = collider.radius_m
        with tempfile.TemporaryDirectory() as folder:
            path = self.module.save_character_preset(self.arm, bpy.context.scene, "MyCollision", pathlib.Path(folder))
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.arm.sb_settings.colliders.clear()
            self.arm.matrix_world = Matrix.Scale(2., 4)
            plan = self.module.build_character_plan(self.arm, saved, bpy.context.scene)
            self.module.apply_plan(self.arm, plan)
        self.assertEqual(self.arm.sb_settings.colliders[0].name, "MyLegCollision")
        self.assertAlmostEqual(self.arm.sb_settings.colliders[0].radius_m, 2. * radius)

    def test_different_character_cannot_apply_an_existing_plan(self):
        plan = self.module.build_chain_plan(self.arm, self.preset("skirt_balanced"), bpy.context.scene)
        other = self.arm.copy()
        bpy.context.scene.collection.objects.link(other)
        with self.assertRaises(self.module.SpringBoneError):
            self.module.apply_plan(other, plan)
        self.assertEqual(len(other.sb_settings.chains), 0)

    def test_pelvis_radius_uses_thigh_separation(self):
        roles = {"hips":self.names[0], "thigh_l":self.names[1], "thigh_r":self.names[2]}
        plan = self.module.build_collider_plan(self.arm, self.preset("humanoid_lower"), bpy.context.scene, roles)
        row = next(item for item in plan["entries"] if item["bone_name"] == self.names[0])
        span = (self.arm.data.bones[self.names[2]].head_local - self.arm.data.bones[self.names[1]].head_local).length
        self.assertAlmostEqual(row["radius_m"], span * .55)

    def test_new_rig_has_usable_preset_defaults(self):
        self.assertEqual(self.arm.sb_settings.chain_preset, "skirt_balanced")
        self.assertEqual(self.arm.sb_settings.collider_preset, "humanoid_lower")
        self.assertEqual(self.arm.sb_settings.character_preset, "NONE")

    def test_humanoid_matching_uses_known_names_without_geometry_override(self):
        expected = {}
        for old, name in zip(self.names, ("hips", "upper_leg.L", "lower_leg.L")):
            self.arm.data.bones[old].name = name
            expected[name] = name
        with patch("humanoid_retarget.classify.classify_armature", side_effect=AssertionError("untrusted geometry matching")):
            roles = self.module.humanoid_roles(self.arm)
        self.assertEqual(roles["hips"], "hips")
        self.assertEqual(roles["thigh_l"], "upper_leg.L")
        self.assertEqual(roles["shin_l"], "lower_leg.L")

    def test_control_bones_are_not_detected_as_skirt_chains(self):
        for bone in self.arm.data.bones:
            bone.name = "Ctrl_" + bone.name
        plan = self.module.build_chain_plan(self.arm, self.preset("skirt_balanced"), bpy.context.scene)
        self.assertEqual(plan["entries"], [])

    def test_capsule_uses_next_joint_when_bone_is_a_short_marker(self):
        bpy.ops.object.mode_set(mode="EDIT")
        bone = self.arm.data.edit_bones[self.names[0]]
        bone.tail = bone.head + (bone.tail - bone.head).normalized() * .005
        bpy.ops.object.mode_set(mode="OBJECT")
        roles = {"thigh_l":self.names[0], "shin_l":self.names[1]}
        plan = self.module.build_collider_plan(self.arm, self.preset("humanoid_lower"), bpy.context.scene, roles)
        row = next(item for item in plan["entries"] if item["bone_name"] == self.names[0])
        span = (self.arm.data.bones[self.names[1]].head_local - self.arm.data.bones[self.names[0]].head_local).length
        self.assertAlmostEqual(row["radius_m"], span * .2)
        self.assertAlmostEqual(row["tail_offset_m"][1], span * .9)

    def test_hair_and_tail_presets_match_existing_roots(self):
        for identifier, prefix in (("hair", "LiuHai.L"), ("tail", "WeiBa")):
            for index, bone in enumerate(self.arm.data.bones):
                bone.name = prefix + "." + str(index)
            plan = self.module.build_chain_plan(self.arm, self.preset(identifier), bpy.context.scene)
            self.assertEqual(len(plan["entries"]), 1)
            self.assertEqual(len(plan["entries"][0]["bone_names"]), 3)
