import unittest

import bpy


class SpringBoneRealtime(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import spring_bone
        cls.spring = spring_bone
        spring_bone.register()

    @classmethod
    def tearDownClass(cls):
        cls.spring.unregister()

    def setUp(self):
        self.objects_before = set(bpy.data.objects)
        self.actions_before = set(bpy.data.actions)
        self.armatures_before = set(bpy.data.armatures)
        self.arm = bpy.data.objects.new("RealtimeRig", bpy.data.armatures.new("RealtimeRig"))
        bpy.context.collection.objects.link(self.arm)
        bpy.context.view_layer.objects.active = self.arm
        self.arm.select_set(True)
        bpy.ops.object.mode_set(mode="EDIT")
        parent = None
        for index in range(3):
            bone = self.arm.data.edit_bones.new("Hem" + str(index))
            bone.head = (0., index * .2, 1.)
            bone.tail = (0., (index + 1) * .2, 1.)
            bone.parent = parent
            parent = bone
        bpy.ops.object.mode_set(mode="OBJECT")
        chain = self.arm.sb_settings.chains.add()
        chain.gravity_power = 2.
        chain.stiffness = .4
        chain.drag_force = .4
        chain.warmup_seconds = 0.
        for pose in self.arm.pose.bones:
            pose.rotation_mode = "QUATERNION"
            pose.keyframe_insert("rotation_quaternion", frame=1)
            pose.keyframe_insert("rotation_quaternion", frame=25)
            chain.bone_names.add().name = pose.name
        self.source = self.arm.animation_data.action
        bpy.context.scene.sb_target_armature = self.arm
        bpy.context.scene.render.fps = 24
        bpy.context.scene.render.fps_base = 1.
        bpy.context.scene.frame_start, bpy.context.scene.frame_end = 1, 25
        bpy.context.scene.frame_set(1)
        self.arm.animation_data.use_nla = False

    def tearDown(self):
        from spring_bone.operators import stop_active_session
        stop_active_session()
        for obj in set(bpy.data.objects) - self.objects_before:
            bpy.data.objects.remove(obj, do_unlink=True)
        for action in set(bpy.data.actions) - self.actions_before:
            bpy.data.actions.remove(action, do_unlink=True)
        for armature in set(bpy.data.armatures) - self.armatures_before:
            if armature.users == 0:
                bpy.data.armatures.remove(armature)

    def _start(self):
        from spring_bone.operators import start_realtime
        return start_realtime(bpy.context).job

    def test_realtime_overlay_tracks_simulated_pose_and_colliders(self):
        from spring_bone import gizmos
        bpy.ops.object.mode_set(mode="EDIT")
        bone = self.arm.data.edit_bones.new("Leg")
        bone.head, bone.tail = (2., 0., 1.), (2., .5, 1.)
        bpy.ops.object.mode_set(mode="OBJECT")
        collider = self.arm.sb_settings.colliders.add()
        collider.bone_name = "Leg"
        collider.shape = "CAPSULE"
        self.arm.sb_settings.show_gizmos = True
        job = self._start()
        for frame in (2, 8):
            bpy.context.scene.frame_set(frame)
            bpy.context.view_layer.update()
            drawing = gizmos._evaluated_drawing(self.arm)
            self.assertIsNotNone(drawing)
            self.assertGreater(len(drawing.collider_lines), 0)
            evaluated = self.arm.evaluated_get(bpy.context.evaluated_depsgraph_get())
            pose = evaluated.pose.bones["Hem0"]
            self.assertLess((drawing.active_lines[0] - evaluated.matrix_world @ pose.head).length, 1e-6)
            self.assertLess((drawing.active_lines[1] - evaluated.matrix_world @ pose.tail).length, 1e-6)
        before = drawing.active_lines[1].copy()
        self.arm.sb_settings.chains[0].gravity_dir = (0., 0., 1.)
        for _ in range(30):
            job.update_paused(1. / 60.)
        bpy.context.view_layer.update()
        self.assertGreater((gizmos._evaluated_drawing(self.arm).active_lines[1] - before).length, .01)
        self.arm.sb_settings.show_gizmos = False
        self.assertIsNone(gizmos._drawing_target())

    def test_realtime_overlay_draws_chain_labels(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from mathutils import Vector
        from spring_bone import gizmos
        self._start()
        context = SimpleNamespace(region=object(), region_data=object(), evaluated_depsgraph_get=bpy.context.evaluated_depsgraph_get)
        with patch.object(gizmos, "_drawing_target", return_value=self.arm), patch.object(gizmos, "bpy", SimpleNamespace(context=context)), patch.object(gizmos, "location_3d_to_region_2d", return_value=Vector((10., 20.))), patch.object(gizmos.blf, "size"), patch.object(gizmos.blf, "position"), patch.object(gizmos.blf, "color"), patch.object(gizmos.blf, "draw") as draw:
            gizmos.draw_labels()
        self.assertEqual(draw.call_count, 2)
        self.assertEqual(draw.call_args.args[1], self.arm.sb_settings.chains[0].name)

    def test_frame_events_apply_gravity_to_every_segment(self):
        self._start()
        for frame in range(2, 20):
            bpy.context.scene.frame_set(frame)
        bpy.context.view_layer.update()
        for pose in self.arm.pose.bones:
            self.assertLess((pose.tail - pose.head).normalized().z, -.2, pose.name)

    def test_stopping_restores_action_and_releases_runtime_resources(self):
        from spring_bone.operators import stop_active_session
        job = self._start()
        source_object, action = job.sampler, job.input_action
        object_name, action_name = source_object.name, action.name
        bpy.context.scene.frame_set(12)
        stop_active_session()
        self.assertIs(self.arm.animation_data.action, self.source)
        self.assertEqual(bpy.context.scene.frame_current, 12)
        self.assertNotIn(object_name, bpy.data.objects)
        self.assertNotIn(action_name, bpy.data.actions)
        self.assertTrue(job.finished)

    def test_repeated_frame_does_not_feed_simulated_pose_back_as_input(self):
        self._start()
        bpy.context.scene.frame_set(2)
        first = [pose.matrix.copy() for pose in self.arm.pose.bones]
        for _ in range(4):
            bpy.context.scene.frame_set(2)
        for pose, matrix in zip(self.arm.pose.bones, first):
            self.assertLess(max(abs(pose.matrix[r][c] - matrix[r][c]) for r in range(4) for c in range(4)), 1e-5)

    def test_paused_parameter_changes_take_effect_without_new_action(self):
        job = self._start()
        owned = job.input_action
        self.arm.sb_settings.chains[0].gravity_dir = (0., 0., 1.)
        for _ in range(30):
            job.update_paused(1. / 60.)
        bpy.context.view_layer.update()
        self.assertGreater((self.arm.pose.bones["Hem2"].tail - self.arm.pose.bones["Hem2"].head).normalized().z, .2)
        self.assertIs(job.input_action, owned)

    def test_disabled_nla_with_existing_tracks_is_allowed(self):
        self.arm.animation_data.nla_tracks.new().strips.new("Stored", 1, self.source)
        self.arm.animation_data.use_nla = False
        self._start()

    def test_external_action_switch_is_not_overwritten(self):
        from spring_bone.operators import active_session
        self._start()
        other = self.source.copy()
        self.arm.animation_data.action = other
        self.arm.animation_data.action_slot = other.slots[0]
        bpy.context.scene.frame_set(2)
        self.assertIs(self.arm.animation_data.action, other)
        self.assertIsNone(active_session())

    def test_checkbox_starts_and_stops_realtime(self):
        from spring_bone.operators import active_session
        bpy.context.window_manager.sb_realtime_preview = True
        self.assertIsNotNone(active_session())
        self.assertTrue(bpy.context.window_manager.sb_realtime_preview)
        bpy.context.window_manager.sb_realtime_preview = False
        self.assertIsNone(active_session())
        self.assertFalse(bpy.context.window_manager.sb_realtime_preview)

    def test_source_curves_are_unchanged(self):
        from spring_bone.contact_bake import _action_token
        before = _action_token(self.source, self.source.slots[0])
        job = self._start()
        for _ in range(8):
            job.update_paused(1. / 60.)
        self.assertEqual(before, _action_token(self.source, self.source.slots[0]))

    def test_weight_zero_keeps_base_rotation(self):
        self.arm.sb_settings.chains[0].weight = 0.
        self._start()
        for frame in range(2, 10):
            bpy.context.scene.frame_set(frame)
        bpy.context.view_layer.update()
        for pose in self.arm.pose.bones:
            self.assertLess(abs((pose.tail - pose.head).normalized().z), 1e-6)

    def test_backward_jump_resets_to_same_initial_state(self):
        self._start()
        bpy.context.scene.frame_set(1)
        initial = [pose.matrix.copy() for pose in self.arm.pose.bones]
        for frame in range(2, 12):
            bpy.context.scene.frame_set(frame)
        bpy.context.scene.frame_set(1)
        for pose, matrix in zip(self.arm.pose.bones, initial):
            self.assertLess(max(abs(pose.matrix[r][c] - matrix[r][c]) for r in range(4) for c in range(4)), 1e-5)

    def test_generated_entry_uses_base_and_restores_generated_action(self):
        from spring_bone.operators import stop_active_session
        generated = self.source.copy()
        generated["sb_generated"] = 1
        generated["sb_contact_input"] = self.source.name
        self.arm.animation_data.action = generated
        self.arm.animation_data.action_slot = generated.slots[0]
        job = self._start()
        self.assertIs(job.source_action, self.source)
        stop_active_session()
        self.assertIs(self.arm.animation_data.action, generated)

    def test_stop_removes_frame_callback_and_paused_timer(self):
        from spring_bone.operators import _realtime_frame, _realtime_timer, stop_active_session
        self._start()
        self.assertIn(_realtime_frame, bpy.app.handlers.frame_change_post)
        self.assertTrue(bpy.app.timers.is_registered(_realtime_timer))
        stop_active_session()
        self.assertNotIn(_realtime_frame, bpy.app.handlers.frame_change_post)
        self.assertFalse(bpy.app.timers.is_registered(_realtime_timer))

    def test_load_undo_save_render_hooks_stop_active_realtime(self):
        from spring_bone.operators import active_session
        for handlers in (bpy.app.handlers.load_pre, bpy.app.handlers.undo_pre, bpy.app.handlers.save_pre, bpy.app.handlers.render_pre):
            self._start()
            self.assertIn(self.spring._load_pre, handlers)
            self.spring._load_pre()
            self.assertIsNone(active_session())
            self.assertIs(self.arm.animation_data.action, self.source)

    def test_deleted_target_releases_owned_objects(self):
        from spring_bone.operators import active_session
        job = self._start()
        sampler_name = job.sampler.name
        bpy.data.objects.remove(self.arm, do_unlink=True)
        bpy.context.scene.frame_set(2)
        self.assertIsNone(active_session())
        self.assertNotIn(sampler_name, bpy.data.objects)

    def test_active_nla_is_rejected(self):
        from spring_bone.operators import active_session, start_realtime
        from spring_bone.solver import SpringBoneError
        self.arm.animation_data.nla_tracks.new().strips.new("Stored", 1, self.source)
        self.arm.animation_data.use_nla = True
        with self.assertRaises(SpringBoneError):
            start_realtime(bpy.context)
        self.assertIsNone(active_session())

    def test_rotation_mode_change_is_preserved(self):
        from spring_bone.operators import active_session
        self._start()
        self.arm.pose.bones["Hem0"].rotation_mode = "XYZ"
        bpy.context.scene.frame_set(2)
        self.assertIsNone(active_session())
        self.assertEqual(self.arm.pose.bones["Hem0"].rotation_mode, "XYZ")

    def test_second_character_cannot_start_parallel_session(self):
        from spring_bone.operators import active_session, start_realtime
        from spring_bone.solver import SpringBoneError
        job = self._start()
        other = self.arm.copy()
        bpy.context.collection.objects.link(other)
        bpy.context.scene.sb_target_armature = other
        with self.assertRaises(SpringBoneError):
            start_realtime(bpy.context)
        self.assertIs(active_session().job, job)
        bpy.context.scene.frame_set(2)
        self.assertIsNone(active_session())

    def test_nonuniform_pose_scale_fails_without_resource_leaks(self):
        from spring_bone.operators import active_session
        from spring_bone.solver import SpringBoneError
        self.arm.pose.bones["Hem0"].scale = (1., 1.2, 1.)
        before = set(bpy.data.objects)
        with self.assertRaises(SpringBoneError):
            self._start()
        self.assertIsNone(active_session())
        self.assertEqual(set(bpy.data.objects), before)
        self.assertIs(self.arm.animation_data.action, self.source)

    def test_disabled_nla_tracks_also_allow_existing_offline_bake(self):
        from spring_bone.operators import start_bake, release_session_keep_result
        self.arm.animation_data.nla_tracks.new().strips.new("Stored", 1, self.source)
        self.arm.animation_data.use_nla = False
        session = start_bake(bpy.context)
        session.job.run_budgeted()
        self.assertTrue(session.job.delivered)
        release_session_keep_result()

    def test_unregister_stops_realtime_before_removing_properties(self):
        from spring_bone.operators import active_session, _realtime_frame, _realtime_timer
        job = self._start()
        sampler_name = job.sampler.name
        try:
            self.spring.unregister()
            self.assertIsNone(active_session())
            self.assertNotIn(sampler_name, bpy.data.objects)
            self.assertNotIn(_realtime_frame, bpy.app.handlers.frame_change_post)
            self.assertFalse(bpy.app.timers.is_registered(_realtime_timer))
            self.assertFalse(hasattr(bpy.types.WindowManager, "sb_realtime_preview"))
            self.assertIs(self.arm.animation_data.action, self.source)
        finally:
            self.spring.register()

    def test_fixed_step_moving_anchor_matches_24_and_60_fps(self):
        from spring_bone.animation import iter_channelbags
        from spring_bone.operators import stop_active_session
        tails = []
        root = self.arm.pose.bones["Hem0"]
        path = root.path_from_id("location")
        for fps in (24, 60):
            bpy.context.scene.render.fps = fps
            for bag in iter_channelbags(self.source, self.source.slots[0]):
                for curve in list(bag.fcurves):
                    if curve.data_path == path:
                        bag.fcurves.remove(curve)
            root.location = (0., 0., 0.)
            root.keyframe_insert("location", frame=1)
            root.location = (.2, 0., 0.)
            root.keyframe_insert("location", frame=fps + 1)
            for bag in iter_channelbags(self.source, self.source.slots[0]):
                for curve in bag.fcurves:
                    for point in curve.keyframe_points:
                        point.interpolation = "LINEAR"
            bpy.context.scene.frame_set(1)
            job = self._start()
            for frame in range(2, fps + 2):
                bpy.context.scene.frame_set(frame)
            tails.append([state.current_tail_m.copy() for state in job.runtimes[0].states])
            stop_active_session()
        self.assertLess(max((first - second).length for first, second in zip(*tails)), 1e-5)

    def test_sphere_and_capsule_colliders_affect_realtime_motion(self):
        from spring_bone.animation import colliders_for_tick
        from spring_bone.operators import stop_active_session
        from spring_bone.solver import signed_collider_distance
        bpy.ops.object.mode_set(mode="EDIT")
        bone = self.arm.data.edit_bones.new("Leg")
        bone.head, bone.tail = (.1, .2, 1.), (.1, .2, 1.1)
        bpy.ops.object.mode_set(mode="OBJECT")
        self.arm.sb_settings.chains[0].gravity_power = 0.
        collider = self.arm.sb_settings.colliders.add()
        collider.bone_name = "Leg"
        collider.radius_m = .13
        collider.tail_offset_m = (0., .15, 0.)
        for shape in ("SPHERE", "CAPSULE"):
            collider.shape = shape
            job = self._start()
            for _ in range(60):
                job.update_paused(1. / 60.)
            state = job.runtimes[0].states[0]
            self.assertLess(state.current_tail_m.x, -.03, shape)
            body = colliders_for_tick(job.colliders, job.last_tick, job.scale_length)[0]
            self.assertGreater(signed_collider_distance(state.current_tail_m, body, .01), -.002, shape)
            stop_active_session()

    def test_non_simulated_hand_pose_matches_base_while_skirt_moves(self):
        from mathutils import Quaternion
        bpy.ops.object.mode_set(mode="EDIT")
        bone = self.arm.data.edit_bones.new("Hand")
        bone.head, bone.tail = (1., 0., 1.), (1., .1, 1.)
        bpy.ops.object.mode_set(mode="OBJECT")
        hand = self.arm.pose.bones["Hand"]
        hand.rotation_mode = "QUATERNION"
        hand.rotation_quaternion = Quaternion()
        hand.keyframe_insert("rotation_quaternion", frame=1)
        hand.rotation_quaternion = Quaternion((1., 0., 0.), .5)
        hand.keyframe_insert("rotation_quaternion", frame=25)
        bpy.context.scene.frame_set(1)
        job = self._start()
        for frame in range(2, 14):
            bpy.context.scene.frame_set(frame)
            bpy.context.view_layer.update()
            expected = job.sampler.evaluated_get(bpy.context.evaluated_depsgraph_get()).pose.bones["Hand"].matrix
            self.assertLess(max(abs(hand.matrix[r][c] - expected[r][c]) for r in range(4) for c in range(4)), 1e-6)
        self.assertLess((self.arm.pose.bones["Hem0"].tail - self.arm.pose.bones["Hem0"].head).normalized().z, -.2)

    def test_unconfigured_hand_quaternion_animation_is_not_repaired(self):
        from mathutils import Quaternion
        from spring_bone.animation import iter_channelbags
        bpy.ops.object.mode_set(mode="EDIT")
        bone = self.arm.data.edit_bones.new("Hand")
        bone.head, bone.tail = (1., 0., 1.), (1., .1, 1.)
        bpy.ops.object.mode_set(mode="OBJECT")
        hand = self.arm.pose.bones["Hand"]
        hand.rotation_mode = "QUATERNION"
        for frame in (1, 25):
            hand.keyframe_insert("rotation_quaternion", frame=frame)
        rotation = Quaternion((1., 0., 0.), 1.2)
        path = hand.path_from_id("rotation_quaternion")
        for bag in iter_channelbags(self.source, self.source.slots[0]):
            for curve in bag.fcurves:
                if curve.data_path == path:
                    for index, point in enumerate(curve.keyframe_points):
                        point.co.y = rotation[curve.array_index] * (1. if index == 0 else -1.)
                        point.interpolation = "LINEAR"
                    curve.update()
        bpy.context.scene.frame_set(13)
        bpy.context.view_layer.update()
        expected = hand.matrix.copy()
        self._start()
        bpy.context.view_layer.update()
        self.assertLess(max(abs(hand.matrix[r][c] - expected[r][c]) for r in range(4) for c in range(4)), 1e-6)
