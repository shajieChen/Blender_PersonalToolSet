import importlib
import math
import unittest
from unittest.mock import patch

import bpy
from mathutils import Matrix, Vector


class SpringBoneGizmos(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec("spring_bone.gizmos"), "Spring Bone viewport drawing is missing")
        return importlib.import_module("spring_bone.gizmos")

    def test_sphere_matches_collision_radius(self):
        module = self.module()
        center = Vector((2.0, 3.0, 4.0))
        vertices = module.sphere_lines(center, 0.25)
        self.assertGreater(len(vertices), 0)
        for vertex in vertices:
            self.assertAlmostEqual((vertex - center).length, 0.25, places=5)

    def test_capsule_includes_end_caps(self):
        module = self.module()
        start = Vector((1.0, 2.0, 3.0))
        end = Vector((1.0, 2.0, 5.0))
        vertices = module.capsule_lines(start, end, 0.3)
        self.assertLess(min(vertex.z for vertex in vertices), start.z - 0.29)
        self.assertGreater(max(vertex.z for vertex in vertices), end.z + 0.29)
        for vertex in vertices:
            ratio = max(0.0, min(1.0, (vertex - start).dot(end - start) / (end - start).length_squared))
            self.assertAlmostEqual((vertex - (start + (end - start) * ratio)).length, 0.3, places=5)

    def test_degenerate_capsule_is_sphere(self):
        module = self.module()
        center = Vector((1.0, -2.0, 4.0))
        vertices = module.capsule_lines(center, center, 0.5)
        for vertex in vertices:
            self.assertAlmostEqual((vertex - center).length, 0.5, places=5)

    def test_disabled_drawing_does_not_evaluate(self):
        module = self.module()
        with patch.object(module, "_drawing_target", return_value=None):
            with patch.object(module, "_build_geometry", side_effect=AssertionError("disabled drawing evaluated the rig")):
                module.draw_callback()
                module.draw_labels()

    def test_properties_panels_and_unit_conversion(self):
        module = self.module()
        import spring_bone
        spring_bone.register()
        armature = None
        data = None
        try:
            data = bpy.data.armatures.new("GizmoTestRig")
            armature = bpy.data.objects.new("GizmoTestRig", data)
            bpy.context.scene.collection.objects.link(armature)
            bpy.context.view_layer.objects.active = armature
            armature.select_set(True)
            bpy.ops.object.mode_set(mode="EDIT")
            bone = data.edit_bones.new("Skirt")
            bone.head = (0.0, 0.0, 0.0)
            bone.tail = (0.0, 1.0, 0.0)
            bpy.ops.object.mode_set(mode="OBJECT")
            armature.matrix_world = Matrix.Translation((2.0, 0.0, 0.0))
            settings = armature.sb_settings
            self.assertFalse(settings.show_gizmos)
            chain = settings.chains.add()
            chain.name = "Skirt"
            chain.bone_names.add().name = "Skirt"
            collider = settings.colliders.add()
            collider.bone_name = "Skirt"
            collider.radius_m = 0.05
            collider.head_offset_m = (0.0, 0.1, 0.0)
            geometry = module._build_geometry(armature, settings, 0.1)
            self.assertGreater(len(geometry.active_lines), 0)
            self.assertGreater(len(geometry.collider_lines), 0)
            center = Vector((2.0, 1.0, 0.0))
            for vertex in geometry.collider_lines:
                self.assertAlmostEqual((vertex - center).length, 0.5, places=5)
            settings.show_gizmos = True
            self.assertEqual(module._drawing_target(), armature)
            settings.show_gizmos = False
            self.assertIsNone(module._drawing_target())
            for suffix in ("chains", "colliders", "playback", "result"):
                panel = getattr(bpy.types, "SPRING_BONE_PT_" + suffix)
                self.assertEqual(panel.bl_parent_id, "SPRING_BONE_PT_main")
        finally:
            spring_bone.unregister()
            if armature is not None:
                bpy.data.objects.remove(armature, do_unlink=True)
            if data is not None:
                bpy.data.armatures.remove(data)

    def test_register_remove_handlers_are_idempotent(self):
        module = self.module()
        module.register_draw()
        first = module._handle
        module.register_draw()
        self.assertEqual(module._handle, first)
        module.unregister_draw()
        module.unregister_draw()
        self.assertIsNone(module._handle)
        self.assertIsNone(module._label_handle)

    def test_geometry_rejects_invalid_radius(self):
        module = self.module()
        for radius in (-1.0, math.inf, math.nan):
            self.assertEqual(module.sphere_lines(Vector(), radius), [])

    def test_depth_groups_distinguish_near_and_far(self):
        module = self.module()
        self.assertTrue(hasattr(module, "depth_groups"), "Depth cues are missing")
        near = [Vector((0.0, 0.0, -1.0)), Vector((1.0, 0.0, -1.0))]
        far = [Vector((0.0, 0.0, -3.0)), Vector((1.0, 0.0, -3.0))]
        groups = module.depth_groups(far + near, Matrix.Identity(4))
        self.assertEqual(groups[0], near)
        self.assertEqual(groups[-1], far)

    def test_depth_cues_remain_visible_through_meshes(self):
        module = self.module()
        vertices = [Vector((0.0, 0.0, -1.0)), Vector((1.0, 0.0, -1.0)), Vector((0.0, 0.0, -3.0)), Vector((1.0, 0.0, -3.0))]
        with patch.object(module.gpu.state, "depth_test_set") as depth:
            with patch.object(module, "_draw_lines") as draw:
                module._draw_depth_lines(vertices, module._bone_color, 3.0, Matrix.Identity(4))
        self.assertTrue(depth.call_args_list)
        self.assertTrue(all(call.args == ("NONE",) for call in depth.call_args_list))
        foreground = [call.args[1] for index, call in enumerate(draw.call_args_list) if index % 2 == 1 and call.args[0]]
        self.assertTrue(all(color[3] == module._bone_color[3] for color in foreground))
        self.assertGreater(sum(foreground[-1][:3]), sum(foreground[0][:3]))


class SpringBoneTargets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import spring_bone
        cls.spring = spring_bone
        cls.spring.register()

    @classmethod
    def tearDownClass(cls):
        cls.spring.unregister()

    def setUp(self):
        from test_spring_bone_lifecycle import SpringBoneLifecycle
        self.fixture = SpringBoneLifecycle()
        self.fixture.objects = []
        self.fixture.actions = []
        self.fixture.operators = self.spring.operators

    def tearDown(self):
        if hasattr(bpy.context.scene, "sb_target_armature"):
            bpy.context.scene.sb_target_armature = None
        self.fixture.tearDown()

    def test_explicit_target_does_not_follow_active_rig(self):
        self.assertTrue(hasattr(bpy.types.Scene, "sb_target_armature"), "Scene rig selection is missing")
        from spring_bone.targets import target_armature
        first, _ = self.fixture._armed()
        second, _ = self.fixture._armed()
        bpy.context.scene.sb_target_armature = first
        self.assertEqual(bpy.context.object, second)
        self.assertEqual(target_armature(bpy.context), first)
        bpy.context.scene.sb_target_armature = second
        self.assertEqual(target_armature(bpy.context), second)

    def test_bake_only_writes_selected_character(self):
        self.assertTrue(hasattr(bpy.types.Scene, "sb_target_armature"), "Scene rig selection is missing")
        first, first_action = self.fixture._armed()
        self.fixture._fill(first)
        second, second_action = self.fixture._armed()
        self.fixture._fill(second)
        bpy.context.scene.sb_target_armature = first
        session = self.spring.operators.begin_session(bpy.context, True)
        try:
            session.job.run_budgeted()
            self.fixture.actions.append(first.animation_data.action)
            self.assertNotEqual(first.animation_data.action, first_action)
            self.assertEqual(second.animation_data.action, second_action)
        finally:
            self.spring.operators.release_session_keep_result()

    def test_other_character_cannot_publish_existing_preview(self):
        self.assertTrue(hasattr(bpy.types.Scene, "sb_target_armature"), "Scene rig selection is missing")
        first, _ = self.fixture._armed()
        self.fixture._fill(first)
        second, second_action = self.fixture._armed()
        self.fixture._fill(second)
        bpy.context.scene.sb_target_armature = first
        session = self.spring.operators.start_preview(bpy.context)
        session.job.run_budgeted()
        bpy.context.scene.sb_target_armature = second
        with self.assertRaises(self.spring.operators.SpringBoneError):
            self.spring.operators.start_bake(bpy.context)
        self.assertFalse(session.job.delivered)
        self.assertEqual(second.animation_data.action, second_action)

    def test_mesh_uses_its_armature_when_no_target_selected(self):
        self.assertTrue(hasattr(bpy.types.Scene, "sb_target_armature"), "Scene rig selection is missing")
        from spring_bone.targets import target_armature
        armature, _ = self.fixture._armed()
        bpy.ops.object.mode_set(mode="OBJECT")
        data = bpy.data.meshes.new("SpringTargetMesh")
        mesh = bpy.data.objects.new("SpringTargetMesh", data)
        self.fixture.objects.append(mesh)
        bpy.context.scene.collection.objects.link(mesh)
        mesh.modifiers.new("Armature", "ARMATURE").object = armature
        bpy.context.view_layer.objects.active = mesh
        bpy.context.scene.sb_target_armature = None
        self.assertEqual(target_armature(bpy.context), armature)

    def _weighted_cloth(self, armature, bone_name):
        bpy.ops.object.mode_set(mode="OBJECT")
        data = bpy.data.meshes.new("SpringHemTest")
        data.from_pydata([(0.0, 0.6, 1.0)], [], [])
        mesh = bpy.data.objects.new("SpringHemTest", data)
        bpy.context.scene.collection.objects.link(mesh)
        self.fixture.objects.append(mesh)
        mesh.modifiers.new("Armature", "ARMATURE").object = armature
        mesh.vertex_groups.new(name=bone_name).add([0], 1.0, "REPLACE")
        return mesh

    def test_trim_zero_weight_tip_preserves_skin_and_bones(self):
        self.assertTrue(hasattr(self.spring.operators, "trim_unweighted_tips"), "Skinning-aware chain repair is missing")
        armature, action = self.fixture._armed()
        self.fixture._fill(armature)
        mesh = self._weighted_cloth(armature, "BoneB")
        before = [(g.group, g.weight) for g in mesh.data.vertices[0].groups]
        removed = self.spring.operators.trim_unweighted_tips(armature, bpy.context.scene)
        self.assertEqual(removed, ["BoneC"])
        self.assertEqual([b.name for b in armature.sb_settings.chains[0].bone_names], ["BoneA", "BoneB"])
        self.assertIn("BoneC", armature.data.bones)
        self.assertEqual(armature.animation_data.action, action)
        self.assertEqual(before, [(g.group, g.weight) for g in mesh.data.vertices[0].groups])

    def test_weighted_tip_keeps_unweighted_parent_bones(self):
        self.assertTrue(hasattr(self.spring.operators, "trim_unweighted_tips"), "Skinning-aware chain repair is missing")
        armature, _ = self.fixture._armed()
        self.fixture._fill(armature)
        self._weighted_cloth(armature, "BoneC")
        self.assertEqual(self.spring.operators.trim_unweighted_tips(armature, bpy.context.scene), [])
        self.assertEqual(len(armature.sb_settings.chains[0].bone_names), 3)

    def test_unbound_chain_is_not_deleted(self):
        self.assertTrue(hasattr(self.spring.operators, "trim_unweighted_tips"), "Skinning-aware chain repair is missing")
        armature, _ = self.fixture._armed()
        self.fixture._fill(armature)
        self._weighted_cloth(armature, "Parent")
        with self.assertRaises(self.spring.operators.SpringBoneError):
            self.spring.operators.trim_unweighted_tips(armature, bpy.context.scene)
        self.assertEqual(len(armature.sb_settings.chains[0].bone_names), 3)
