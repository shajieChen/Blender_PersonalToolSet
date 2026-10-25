import unittest
from unittest.mock import patch
import pathlib
import tempfile
from types import SimpleNamespace

import bpy
import numpy as np
from mathutils import Matrix, Quaternion


class SpringBoneSkinCollision(unittest.TestCase):
    def test_owned_modal_operator_identifiers_are_allowed(self):
        from spring_bone.animation import foreign_modal_active
        for identifier in ("spring_bone.contact_bake", "SPRING_BONE_OT_contact_bake", "SPRING_BONE_OT_preview", "SPRING_BONE_OT_bake"):
            context = SimpleNamespace(window=SimpleNamespace(modal_operators=[SimpleNamespace(bl_idname=identifier)]))
            self.assertFalse(foreign_modal_active(context))
        context = SimpleNamespace(window=SimpleNamespace(modal_operators=[SimpleNamespace(bl_idname="TRANSFORM_OT_translate")]))
        self.assertTrue(foreign_modal_active(context))

    def test_triangle_interiors_collide_without_inside_vertices(self):
        from spring_bone.skin_collision import triangle_crossings

        first = np.array([[-1., -1., 0.], [1., -1., 0.], [0., 1., 0.]])
        second = np.array([[0., -.5, -1.], [0., -.5, 1.], [0., .5, 1.]])
        self.assertGreater(triangle_crossings(first, np.array([[0, 1, 2]]), second, np.array([[0, 1, 2]])), 0)
        self.assertEqual(triangle_crossings(first, np.array([[0, 1, 2]]), second + np.array([3., 0., 0.]), np.array([[0, 1, 2]])), 0)
        self.assertGreater(triangle_crossings(first * 1e-5, np.array([[0, 1, 2]]), second * 1e-5, np.array([[0, 1, 2]])), 0)

    def test_skin_search_corrects_bones_without_moving_rest_vertices(self):
        from spring_bone.skin_collision import SkinCollisionFrame, search_skin_pose

        points = np.array([[0., 1., 0.], [0., 2., 0.], [1., 1., 0.]])
        original = points.copy()
        identity = np.asarray(Matrix.Identity(4), dtype=np.float64)
        frame = SkinCollisionFrame(np.array([-1]), np.array([identity]), np.array([identity]), points, np.ones((3, 1)), identity, np.array([identity]), np.zeros((1, 3)), [Quaternion()], np.ones((1, 3)), points)
        obstacle = np.array([[.25, .75, -1.], [.25, 2.25, -1.], [.25, 1.5, 1.]])
        triangles = np.array([[0, 1, 2]])
        result = None
        for result in search_skin_pose(frame, triangles, obstacle, triangles, max_angle=1.2):
            pass
        self.assertEqual(result.triangle_pairs, 0)
        self.assertTrue(np.array_equal(points, original))
        self.assertLessEqual(Quaternion().rotation_difference(result.rotations[0]).angle, 1.20001)

    def test_unsolvable_mesh_returns_residual(self):
        from spring_bone.skin_collision import SkinCollisionFrame, search_skin_pose

        points = np.array([[0., 1., 0.], [0., 2., 0.], [1., 1., 0.]])
        identity = np.asarray(Matrix.Identity(4), dtype=np.float64)
        frame = SkinCollisionFrame(np.array([-1]), np.array([identity]), np.array([identity]), points, np.zeros((3, 1)), identity, np.array([identity]), np.zeros((1, 3)), [Quaternion()], np.ones((1, 3)), points)
        obstacle = np.array([[.25, .75, -1.], [.25, 2.25, -1.], [.25, 1.5, 1.]])
        result = None
        for result in search_skin_pose(frame, np.array([[0, 1, 2]]), obstacle, np.array([[0, 1, 2]]), max_angle=.5):
            pass
        self.assertGreater(result.triangle_pairs, 0)


class SpringBoneContactBake(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import spring_bone
        cls.spring = spring_bone
        spring_bone.register()

    @classmethod
    def tearDownClass(cls):
        cls.spring.unregister()

    def setUp(self):
        self.objects = []
        self.actions_before = set(bpy.data.actions)
        self.entry_frame = bpy.context.scene.frame_current
        self.entry_range = bpy.context.scene.frame_start, bpy.context.scene.frame_end
        self.arm = bpy.data.objects.new("ContactRig", bpy.data.armatures.new("ContactRig"))
        bpy.context.collection.objects.link(self.arm)
        self.objects.append(self.arm)
        bpy.context.view_layer.objects.active = self.arm
        self.arm.select_set(True)
        bpy.ops.object.mode_set(mode="EDIT")
        for name in ("Skirt", "Leg"):
            bone = self.arm.data.edit_bones.new(name)
            bone.head, bone.tail = (0., 0., 0.), (0., 1., 0.)
        bpy.ops.object.mode_set(mode="OBJECT")
        self.arm.pose.bones["Skirt"].rotation_mode = "QUATERNION"
        self.arm.pose.bones["Skirt"].keyframe_insert("rotation_quaternion", frame=1)
        self.arm.pose.bones["Skirt"].rotation_quaternion = Quaternion((0., 0., 1.), .1)
        self.arm.pose.bones["Skirt"].keyframe_insert("rotation_quaternion", frame=2)
        self.arm.pose.bones["Leg"].keyframe_insert("location", frame=1)
        self.arm.pose.bones["Leg"].keyframe_insert("location", frame=2)
        self.source = self.arm.animation_data.action
        self.garment = self._mesh("ContactSkirt", [(0., 1., 0.), (0., 2., 0.), (1., 1., 0.)], "Skirt")
        self.body = self._mesh("ContactBody", [(.25, .75, -1.), (.25, 2.25, -1.), (.25, 1.5, 1.)], "Leg")
        self.arm.sb_settings.chains.add().bone_names.add().name = "Skirt"
        self.arm.sb_settings.colliders.add().bone_name = "Leg"
        self.arm.sb_settings.contact_garment = self.garment
        self.arm.sb_settings.contact_body = self.body
        self.arm.sb_settings.contact_margin_m = 0.
        bpy.context.scene.sb_target_armature = self.arm
        bpy.context.scene.frame_set(1)

    def tearDown(self):
        from spring_bone.operators import stop_active_session
        stop_active_session()
        for obj in self.objects:
            try:
                data = obj.data
            except ReferenceError:
                continue
            bpy.data.objects.remove(obj, do_unlink=True)
            if data.users == 0:
                (bpy.data.armatures if isinstance(data, bpy.types.Armature) else bpy.data.meshes).remove(data)
        for action in set(bpy.data.actions) - self.actions_before:
            bpy.data.actions.remove(action, do_unlink=True)
        bpy.context.scene.frame_set(self.entry_frame)
        bpy.context.scene.frame_start, bpy.context.scene.frame_end = self.entry_range

    def _mesh(self, name, vertices, bone):
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata(vertices, [], [(0, 1, 2)])
        obj = bpy.data.objects.new(name, mesh)
        bpy.context.collection.objects.link(obj)
        self.objects.append(obj)
        obj.parent = self.arm
        obj.vertex_groups.new(name=bone).add([0, 1, 2], 1., "REPLACE")
        obj.modifiers.new("Skin", "ARMATURE").object = self.arm
        return obj

    def _rows(self, action):
        from spring_bone.animation import iter_channelbags
        return tuple((curve.data_path, curve.array_index, tuple(tuple(point.co) for point in curve.keyframe_points)) for bag in iter_channelbags(action, action.slots[0]) for curve in bag.fcurves)

    def test_body_boundary_triangle_with_one_weighted_vertex_is_checked(self):
        from spring_bone.contact_bake import SkirtContactBakeJob
        self.body.vertex_groups[0].remove([1, 2])
        job = SkirtContactBakeJob(self.arm, 1, 1)
        try:
            job.advance()
            job.advance()
            self.assertEqual(len(job.body_triangles), 1)
        finally:
            job.cancel()

    def test_garment_triangle_with_one_low_weight_vertex_is_checked(self):
        from spring_bone.contact_bake import SkirtContactBakeJob
        self.garment.vertex_groups[0].remove([1, 2])
        self.garment.vertex_groups[0].add([0], .01, "REPLACE")
        self.garment.vertex_groups.new(name="Leg").add([0], .99, "REPLACE")
        job = SkirtContactBakeJob(self.arm, 1, 1)
        try:
            job.advance()
            job.advance()
            self.assertEqual(len(job.triangles), 1)
        finally:
            job.cancel()

    def test_all_related_skinned_garment_objects_are_checked(self):
        from spring_bone.contact_bake import SkirtContactBakeJob
        second = self._mesh("ContactHem", [(3., 1., 0.), (3., 2., 0.), (4., 1., 0.)], "Skirt")
        job = SkirtContactBakeJob(self.arm, 1, 1)
        try:
            job.advance()
            job.advance()
            self.assertIn(second, job.garments)
            self.assertEqual(len(job.sample.rest_points), 6)
            self.assertEqual(len(job.triangles), 2)
        finally:
            job.cancel()

    def test_fixed_faces_of_selected_garment_are_not_silently_dropped(self):
        from spring_bone.contact_bake import SkirtContactBakeJob
        mesh = self.garment.data
        mesh.clear_geometry()
        mesh.from_pydata([(0., 1., 0.), (0., 2., 0.), (1., 1., 0.), (3., 1., 0.), (3., 2., 0.), (4., 1., 0.)], [], [(0, 1, 2), (3, 4, 5)])
        self.garment.vertex_groups.new(name="Skirt").add([0, 1, 2], 1., "REPLACE")
        job = SkirtContactBakeJob(self.arm, 1, 1)
        try:
            job.advance()
            job.advance()
            self.assertEqual(len(job.triangles), 2)
        finally:
            job.cancel()

    def test_output_interpolation_is_verified_before_publish(self):
        from spring_bone.contact_bake import SkirtContactBakeJob
        from spring_bone.solver import SpringBoneError
        job = SkirtContactBakeJob(self.arm, 1, 2)
        while job.phase != "write":
            job.advance()
        with patch("spring_bone.contact_bake.triangle_crossings", return_value=1):
            with self.assertRaises(SpringBoneError):
                job.run_budgeted()
        self.assertTrue(job.cancelled)
        self.assertIs(self.arm.animation_data.action, self.source)
        self.assertFalse(any(action.name.endswith("_ContactInput") for action in bpy.data.actions))

    def test_approved_seam_weights_can_be_restored_exactly(self):
        from run_spring_bone_seam_weights import repair_seam_weights, restore_seam_weights
        from spring_bone.contact_bake import _mesh_token, _skin_weights
        self.garment.vertex_groups[0].add([0], .01, "REPLACE")
        self.garment.vertex_groups.new(name="Leg").add([0], .99, "REPLACE")
        before = _mesh_token(self.garment)
        with tempfile.TemporaryDirectory(prefix="spring-seam-") as folder:
            backup = repair_seam_weights(self.arm, self.garment, [0], pathlib.Path(folder) / "weights.json")
            self.assertEqual([row["index"] for row in backup["vertices"]], [0])
            self.assertAlmostEqual(float(_skin_weights(self.garment, self.arm, ["Skirt"])[0, 0]), .65, places=6)
            restore_seam_weights(self.garment, backup)
        self.assertEqual(_mesh_token(self.garment), before)

    def test_result_panel_does_not_report_previous_action_as_current(self):
        from spring_bone.panels import SPRING_BONE_PT_result
        self.arm.sb_settings.result_action_name = "Previous_SkirtContact"
        labels = []
        panel = SimpleNamespace(layout=SimpleNamespace(label=lambda **values: labels.append(values["text"])))
        SPRING_BONE_PT_result.draw(panel, bpy.context)
        self.assertIn("当前动作没有动态骨骼结果", labels)
        self.assertTrue(any("未启用" in text for text in labels))
        self.assertFalse(any("0 对" in text for text in labels))

    def test_contact_bake_preserves_source_rest_weights_and_body_channels(self):
        from spring_bone.contact_bake import SkirtContactBakeJob
        before = self._rows(self.source)
        vertices = [tuple(vertex.co) for vertex in self.garment.data.vertices]
        job = SkirtContactBakeJob(self.arm, 1, 2)
        job.run_budgeted()
        self.assertTrue(job.delivered)
        self.assertEqual(self._rows(self.source), before)
        self.assertEqual([tuple(vertex.co) for vertex in self.garment.data.vertices], vertices)
        self.assertTrue(all(vertex.groups[0].weight == 1. for vertex in self.garment.data.vertices))
        self.assertEqual(job.result_action.get("sb_contact_triangle_pairs"), 0)
        self.assertIs(self.arm.animation_data.action, job.result_action)
        self.assertEqual(len(job.frame_results), 3)
        self.assertEqual(tuple(row for row in before if 'bones["Leg"]' in row[0]), tuple(row for row in self._rows(job.result_action) if 'bones["Leg"]' in row[0]))

    def test_cancel_during_write_removes_owned_action(self):
        from spring_bone.contact_bake import SkirtContactBakeJob
        job = SkirtContactBakeJob(self.arm, 1, 1)
        while job.phase != "write":
            job.advance()
        name = job.result_action.name
        job.cancel()
        self.assertTrue(job.cancelled)
        self.assertIs(self.arm.animation_data.action, self.source)
        self.assertNotIn(name, bpy.data.actions)
        self.assertEqual(bpy.context.scene.frame_current, 1)

    def test_failed_native_validation_keeps_original_action(self):
        from spring_bone.contact_bake import SkirtContactBakeJob
        from spring_bone.solver import SpringBoneError
        job = SkirtContactBakeJob(self.arm, 1, 1)
        with patch("spring_bone.contact_bake.triangle_crossings", return_value=1):
            with self.assertRaises(SpringBoneError):
                job.run_budgeted()
        self.assertTrue(job.cancelled)
        self.assertIs(self.arm.animation_data.action, self.source)
        self.assertIsNone(job.result_action)

    def test_other_character_mesh_is_rejected(self):
        from spring_bone.contact_bake import SkirtContactBakeJob
        from spring_bone.solver import SpringBoneError
        self.garment.modifiers[0].object = None
        with self.assertRaises(SpringBoneError):
            SkirtContactBakeJob(self.arm, 1, 1).run_budgeted()
        self.assertIs(self.arm.animation_data.action, self.source)

    def test_source_curve_edit_cancels_without_overwriting_edit(self):
        from spring_bone.contact_bake import SkirtContactBakeJob
        from spring_bone.animation import iter_channelbags
        from spring_bone.solver import SpringBoneError
        job = SkirtContactBakeJob(self.arm, 1, 1)
        job.advance()
        curve = next(iter_channelbags(self.source, self.source.slots[0])).fcurves[0]
        curve.keyframe_points[0].co.y += .05
        changed = tuple(curve.keyframe_points[0].co)
        with self.assertRaises(SpringBoneError):
            job.advance()
        self.assertEqual(tuple(curve.keyframe_points[0].co), changed)
        self.assertIs(self.arm.animation_data.action, self.source)

    def test_mesh_weight_edit_cancels_without_overwriting_edit(self):
        from spring_bone.contact_bake import SkirtContactBakeJob
        from spring_bone.solver import SpringBoneError
        job = SkirtContactBakeJob(self.arm, 1, 1)
        job.advance()
        self.garment.vertex_groups[0].add([0], .5, "REPLACE")
        with self.assertRaises(SpringBoneError):
            job.advance()
        self.assertAlmostEqual(self.garment.vertex_groups[0].weight(0), .5)
        self.assertIs(self.arm.animation_data.action, self.source)

    def test_foreign_modal_is_rejected(self):
        from spring_bone.contact_bake import SkirtContactBakeJob
        from spring_bone.solver import SpringBoneError
        with patch("spring_bone.contact_bake.foreign_modal_active", return_value=True):
            with self.assertRaises(SpringBoneError):
                SkirtContactBakeJob(self.arm, 1, 1).run_budgeted()
        self.assertIs(self.arm.animation_data.action, self.source)

    def test_nla_change_cancels_and_preserves_new_state(self):
        from spring_bone.contact_bake import SkirtContactBakeJob
        from spring_bone.solver import SpringBoneError
        self.arm.animation_data.use_nla = False
        job = SkirtContactBakeJob(self.arm, 1, 1)
        job.advance()
        self.arm.animation_data.use_nla = True
        with self.assertRaises(SpringBoneError):
            job.advance()
        self.assertTrue(self.arm.animation_data.use_nla)
        self.assertIs(self.arm.animation_data.action, self.source)

    def test_external_action_switch_is_preserved(self):
        from spring_bone.contact_bake import SkirtContactBakeJob
        from spring_bone.solver import SpringBoneError
        job = SkirtContactBakeJob(self.arm, 1, 1)
        job.advance()
        changed = self.source.copy()
        self.arm.animation_data.action = changed
        with self.assertRaises(SpringBoneError):
            job.advance()
        self.assertIs(self.arm.animation_data.action, changed)
        self.assertTrue(job.cancelled)

    def test_deleted_target_can_be_cancelled(self):
        from spring_bone.contact_bake import SkirtContactBakeJob
        from spring_bone.solver import SpringBoneError
        job = SkirtContactBakeJob(self.arm, 1, 1)
        job.advance()
        bpy.data.objects.remove(self.arm, do_unlink=True)
        with self.assertRaises(SpringBoneError):
            job.advance()
        self.assertTrue(job.cancelled)

    def test_rotation_mode_change_is_preserved(self):
        from spring_bone.contact_bake import SkirtContactBakeJob
        from spring_bone.solver import SpringBoneError
        job = SkirtContactBakeJob(self.arm, 1, 1)
        job.advance()
        self.arm.pose.bones["Skirt"].rotation_mode = "XYZ"
        with self.assertRaises(SpringBoneError):
            job.advance()
        self.assertEqual(self.arm.pose.bones["Skirt"].rotation_mode, "XYZ")
        self.assertIs(self.arm.animation_data.action, self.source)

    def test_contact_operator_releases_session(self):
        from spring_bone.operators import active_session
        bpy.context.scene.frame_start = bpy.context.scene.frame_end = 1
        self.assertEqual(bpy.ops.spring_bone.contact_bake(), {"FINISHED"})
        self.assertIsNone(active_session())
        self.assertEqual(self.arm.animation_data.action.get("sb_skin_contact"), 1)

    def test_antipodal_body_keys_are_repaired_in_result_only(self):
        import math
        from spring_bone.contact_bake import SkirtContactBakeJob
        leg = self.arm.pose.bones["Leg"]
        leg.rotation_mode = "QUATERNION"
        for frame, angle, sign in ((1, 170., 1.), (2, 190., 1.)):
            leg.rotation_quaternion = Quaternion((0., 0., 1.), math.radians(angle)) * sign
            leg.keyframe_insert("rotation_quaternion", frame=frame)
        from spring_bone.animation import iter_channelbags
        path = leg.path_from_id("rotation_quaternion")
        for bag in iter_channelbags(self.source, self.source.slots[0]):
            for curve in bag.fcurves:
                if curve.data_path == path:
                    for point in curve.keyframe_points:
                        frame = int(point.co.x)
                        value = Quaternion((0., 0., 1.), math.radians(170. if frame == 1 else 190.))
                        point.co.y = value[curve.array_index]
                        point.interpolation = "LINEAR"
                    curve.update()
        bpy.context.scene.frame_set(1, subframe=.5)
        self.assertLess(leg.rotation_quaternion.magnitude, .2, str(tuple(row for row in self._rows(self.source) if row[0] == path)))
        before = self._rows(self.source)
        job = SkirtContactBakeJob(self.arm, 1, 2)
        job.run_budgeted()
        self.assertEqual(before, self._rows(self.source))
        bpy.context.scene.frame_set(1, subframe=.5)
        self.assertGreater(leg.rotation_quaternion.magnitude, .99)
        self.assertGreater(abs(leg.rotation_quaternion.normalized().dot(Quaternion((0., 0., 1.), math.pi))), .999)
        self.assertGreater(job.result_action.get("sb_quaternion_sign_repairs", 0), 0)

    def test_fbx_roundtrip_keeps_corrected_bone_animation(self):
        from spring_bone.contact_bake import SkirtContactBakeJob, _mesh_arrays
        for vertex in self.body.data.vertices:
            vertex.co.x = .98
        self.arm.pose.bones["Skirt"].rotation_quaternion = Quaternion((0., 0., 1.), .3)
        self.arm.pose.bones["Skirt"].keyframe_insert("rotation_quaternion", frame=1.5)
        job = SkirtContactBakeJob(self.arm, 1, 2)
        job.run_budgeted()
        samples = {}
        for frame in (1., 1.5, 2.):
            bpy.context.scene.frame_set(int(frame), subframe=frame - int(frame))
            samples[frame] = _mesh_arrays(self.garment)[0]
        bpy.context.scene.frame_start, bpy.context.scene.frame_end = 1, 2
        for obj in bpy.context.selected_objects:
            obj.select_set(False)
        for obj in self.objects:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = self.arm
        with tempfile.TemporaryDirectory(prefix="spring-contact-") as folder:
            path = str(pathlib.Path(folder) / "corrected.fbx")
            from humanoid_retarget import pipeline
            pipeline.export_armature(self.arm, path, export_all_actions=False)
            before = set(bpy.data.objects)
            bpy.ops.import_scene.fbx(filepath=path, use_anim=True)
            imported = list(set(bpy.data.objects) - before)
            self.objects.extend(imported)
            arm = next(obj for obj in imported if obj.type == "ARMATURE")
            cloth = next(obj for obj in imported if obj.type == "MESH" and obj.name.startswith("ContactSkirt"))
            self.assertIsNotNone(arm.animation_data.action)
            for frame, expected in samples.items():
                bpy.context.scene.frame_set(int(frame), subframe=frame - int(frame))
                actual = _mesh_arrays(cloth)[0]
                self.assertLess(float(np.linalg.norm(actual - expected, axis=1).max()), 2e-5)
