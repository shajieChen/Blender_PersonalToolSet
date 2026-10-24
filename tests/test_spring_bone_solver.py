import math
import unittest

from mathutils import Matrix, Quaternion, Vector


def _load_solver():
    import spring_bone.solver as solver
    return solver


class SpringBoneSolverContract(unittest.TestCase):
    def test_capsule_endcap_push_uses_spherical_normal(self):
        solver = _load_solver()
        collider = solver.CapsuleCollider(Vector((0.0, 0.0, 0.0)), Vector((0.0, 0.0, 2.0)), 0.2)
        for point in (Vector((0.0, 0.0, 2.1)), Vector((0.04, 0.0, -0.1))):
            pushed, signed = solver.push_collider(point, collider, 0.01, Vector((0.0, 1.0, 0.0)), Vector((1.0, 0.0, 0.0)))
            self.assertLess(signed, 0.0)
            self.assertGreaterEqual(solver.signed_collider_distance(pushed, collider, 0.01), -1e-7)

    def test_solver_module_exposes_step_chain(self):
        solver = _load_solver()
        self.assertTrue(hasattr(solver, "step_chain"))
        self.assertTrue(hasattr(solver, "ChainParameters"))
        self.assertFalse(solver.__file__.replace("\\", "/").find("/humanoid_retarget/") >= 0)

    def test_hand_calculated_tail(self):
        solver = _load_solver()
        parameters = solver.ChainParameters(
            stiffness=0.0,
            drag_force=0.5,
            gravity_power=1.0,
            gravity_dir=Vector((0.0, 0.0, -1.0)),
            hit_radius_m=0.0,
            weight=1.0,
            cone_enabled=False,
            cone_angle_rad=math.radians(60.0),
        )
        state = solver.SegmentState(
            length_m=1.0,
            previous_tail_m=Vector((0.0, 1.0, 0.0)),
            current_tail_m=Vector((0.0, 1.0, 0.0)),
            last_direction=Vector((0.0, 1.0, 0.0)),
            last_radial=Vector((0.0, 0.0, 0.0)),
        )
        sample = solver.SegmentSample(base_pose=Matrix.Identity(4))
        solver.step_chain(
            [state],
            [sample],
            parent_base=Matrix.Identity(4),
            parent_solved=Matrix.Identity(4),
            armature_world=Matrix.Identity(4),
            scale_length=1.0,
            parameters=parameters,
            colliders=(),
        )
        expected = Vector((0.0, 1.0, -1.0 / 60.0)).normalized()
        self.assertLess((state.current_tail_m - expected).length, 1e-7)
        length_error = abs(state.current_tail_m.length - 1.0)
        self.assertLessEqual(length_error, max(1e-6, 1e-5))

    def test_drag_keeps_inertia_displacement(self):
        solver = _load_solver()
        parameters = solver.ChainParameters(
            stiffness=0.0,
            drag_force=0.0,
            gravity_power=0.0,
            gravity_dir=Vector((0.0, 0.0, -1.0)),
            hit_radius_m=0.0,
            weight=1.0,
            cone_enabled=False,
            cone_angle_rad=math.pi,
        )
        state = solver.SegmentState(
            length_m=1.0,
            previous_tail_m=Vector((0.0, 1.0, 0.0)),
            current_tail_m=Vector((0.2, 0.9797958971, 0.0)),
            last_direction=Vector((0.2, 0.9797958971, 0.0)).normalized(),
            last_radial=Vector((0.0, 0.0, 0.0)),
        )
        sample = solver.SegmentSample(base_pose=Matrix.Identity(4))
        before = state.current_tail_m - state.previous_tail_m
        solver.step_chain(
            [state],
            [sample],
            parent_base=Matrix.Identity(4),
            parent_solved=Matrix.Identity(4),
            armature_world=Matrix.Identity(4),
            scale_length=1.0,
            parameters=parameters,
            colliders=(),
        )
        moved = state.current_tail_m - Vector((0.2, 0.9797958971, 0.0))
        self.assertGreater(moved.dot(before), 0.0)

    def test_follow_translation_cancels_shared_delta_only(self):
        solver = _load_solver()
        parameters = solver.ChainParameters(
            stiffness=0.0,
            drag_force=0.25,
            gravity_power=2.0,
            gravity_dir=Vector((0.0, 0.0, -1.0)),
            hit_radius_m=0.0,
            weight=1.0,
            cone_enabled=False,
            cone_angle_rad=math.pi,
        )
        delta = Vector((3.0, -1.0, 0.5))

        def run(extra):
            state = solver.SegmentState(
                length_m=1.0,
                previous_tail_m=Vector((0.0, 1.0, 0.0)),
                current_tail_m=Vector((0.1, 0.9949874371, 0.0)),
                last_direction=Vector((0.1, 0.9949874371, 0.0)).normalized(),
                last_radial=Vector((0.0, 0.0, 0.0)),
            )
            parent_solved = Matrix.Identity(4) if extra is None else Matrix.Translation(extra)
            solver.step_chain(
                [state],
                [solver.SegmentSample(base_pose=Matrix.Identity(4))],
                parent_base=Matrix.Identity(4),
                parent_solved=parent_solved,
                armature_world=Matrix.Identity(4),
                scale_length=1.0,
                parameters=parameters,
                colliders=(),
                translation_delta_m=extra,
            )
            return state.current_tail_m.copy()

        stayed = run(None)
        followed = run(delta)
        self.assertLess((followed - (stayed + delta)).length, 1e-6)

    def test_sphere_push_then_length(self):
        solver = _load_solver()
        parameters = solver.ChainParameters(
            stiffness=0.0,
            drag_force=1.0,
            gravity_power=0.0,
            gravity_dir=Vector((0.0, 0.0, -1.0)),
            hit_radius_m=0.0,
            weight=1.0,
            cone_enabled=False,
            cone_angle_rad=math.pi,
        )
        state = solver.SegmentState(
            length_m=1.0,
            previous_tail_m=Vector((0.0, 1.0, 0.0)),
            current_tail_m=Vector((0.0, 1.0, 0.0)),
            last_direction=Vector((0.0, 1.0, 0.0)),
            last_radial=Vector((1.0, 0.0, 0.0)),
        )
        collider = solver.SphereCollider(center_m=Vector((0.0, 1.0, 0.0)), radius_m=0.25)
        solver.step_chain(
            [state],
            [solver.SegmentSample(base_pose=Matrix.Identity(4))],
            parent_base=Matrix.Identity(4),
            parent_solved=Matrix.Identity(4),
            armature_world=Matrix.Identity(4),
            scale_length=1.0,
            parameters=parameters,
            colliders=(collider,),
        )
        self.assertLess(abs(state.current_tail_m.length - 1.0), 1e-6)
        self.assertGreater(state.current_tail_m.x, 0.0)
        cleared, signed = solver.push_collider(
            Vector((0.0, 1.0, 0.0)),
            collider,
            0.0,
            Vector((0.0, 1.0, 0.0)),
            Vector((1.0, 0.0, 0.0)),
        )
        self.assertLessEqual(signed, -0.2)
        self.assertGreaterEqual(
            (cleared - collider.center_m).length - collider.radius_m,
            -1e-5,
        )

    def test_sphere_center_uses_last_radial(self):
        solver = _load_solver()
        direction = solver.collision_direction(
            Vector((0.0, 0.0, 0.0)),
            Vector((0.0, 1.0, 0.0)),
            Vector((1.0, 0.0, 0.0)),
            axis=None,
        )
        self.assertLess((direction - Vector((1.0, 0.0, 0.0))).length, 1e-7)

    def test_capsule_mid_end_and_degenerate(self):
        solver = _load_solver()
        capsule = solver.CapsuleCollider(
            start_m=Vector((0.0, 0.0, 0.0)),
            end_m=Vector((0.0, 0.0, 2.0)),
            radius_m=0.2,
        )
        mid = solver.signed_collider_distance(Vector((0.3, 0.0, 1.0)), capsule, 0.0)
        self.assertAlmostEqual(mid, 0.1, places=6)
        end = solver.signed_collider_distance(Vector((0.0, 0.0, 2.3)), capsule, 0.0)
        self.assertAlmostEqual(end, 0.1, places=6)
        degenerate = solver.CapsuleCollider(
            start_m=Vector((1.0, 2.0, 3.0)),
            end_m=Vector((1.0, 2.0, 3.0)),
            radius_m=0.5,
        )
        outside = solver.signed_collider_distance(Vector((1.0, 2.0, 4.0)), degenerate, 0.1)
        self.assertAlmostEqual(outside, 0.4, places=6)

    def test_tangent_sphere_does_not_push(self):
        solver = _load_solver()
        sphere = solver.SphereCollider(center_m=Vector((0.0, 0.0, 0.0)), radius_m=1.0)
        self.assertAlmostEqual(
            solver.signed_collider_distance(Vector((1.0, 0.0, 0.0)), sphere, 0.0),
            0.0,
            places=7,
        )
        pushed, depth = solver.push_collider(
            Vector((1.0, 0.0, 0.0)),
            sphere,
            0.0,
            Vector((0.0, 1.0, 0.0)),
            Vector((0.0, 0.0, 0.0)),
        )
        self.assertLess(pushed.x - 1.0, 1e-8)
        self.assertLessEqual(depth, 0.0)

    def test_cone_boundary_and_clamp(self):
        solver = _load_solver()
        limit = math.radians(60.0)
        on_edge = Vector((math.sin(limit), math.cos(limit), 0.0))
        kept = solver.cone_clamp_direction(on_edge, Vector((0.0, 1.0, 0.0)), limit)
        self.assertLess((kept - on_edge.normalized()).length, 1e-6)
        wide = Vector((1.0, 0.0, 0.0))
        clamped = solver.cone_clamp_direction(wide, Vector((0.0, 1.0, 0.0)), limit)
        self.assertAlmostEqual(clamped.normalized().dot(Vector((0.0, 1.0, 0.0))), math.cos(limit), places=6)
        self.assertGreater(clamped.x, 0.0)

    def test_antiparallel_swing_is_deterministic(self):
        solver = _load_solver()
        result = solver.swing_with_twist(Quaternion((1.0, 0.0, 0.0, 0.0)), Vector((0.0, -1.0, 0.0)))
        pointed = result @ Vector((0.0, 1.0, 0.0))
        self.assertLess((pointed - Vector((0.0, -1.0, 0.0))).length, 1e-6)
        again = solver.swing_with_twist(Quaternion((1.0, 0.0, 0.0, 0.0)), Vector((0.0, -1.0, 0.0)))
        self.assertLess(result.rotation_difference(again).angle, 1e-7)
        self.assertLess(abs(result.magnitude - 1.0), 1e-5)

    def test_zero_direction_falls_back(self):
        solver = _load_solver()
        chosen = solver.direction_or_fallback(
            Vector((0.0, 0.0, 0.0)),
            Vector((0.0, 0.0, 0.0)),
            Vector((0.0, 0.0, 1.0)),
        )
        self.assertLess((chosen - Vector((0.0, 0.0, 1.0))).length, 1e-7)

    def test_weight_zero_bypasses_and_weight_one_matches(self):
        solver = _load_solver()
        base = dict(
            stiffness=0.0,
            drag_force=0.5,
            gravity_power=1.0,
            gravity_dir=Vector((0.0, 0.0, -1.0)),
            hit_radius_m=0.0,
            cone_enabled=False,
            cone_angle_rad=math.pi,
        )

        def once(weight):
            parameters = solver.ChainParameters(weight=weight, **base)
            state = solver.SegmentState(
                length_m=1.0,
                previous_tail_m=Vector((0.0, 1.0, 0.0)),
                current_tail_m=Vector((0.0, 1.0, 0.0)),
                last_direction=Vector((0.0, 1.0, 0.0)),
                last_radial=Vector((0.0, 0.0, 0.0)),
            )
            rotations = solver.step_chain(
                [state],
                [solver.SegmentSample(base_pose=Matrix.Identity(4))],
                parent_base=Matrix.Identity(4),
                parent_solved=Matrix.Identity(4),
                armature_world=Matrix.Identity(4),
                scale_length=1.0,
                parameters=parameters,
                colliders=(),
            )
            return state.current_tail_m.copy(), rotations[0].copy()

        tail_off, rot_off = once(0.0)
        tail_on, rot_on = once(1.0)
        self.assertLess((tail_off - Vector((0.0, 1.0, 0.0))).length, 1e-6)
        self.assertLess(rot_off.rotation_difference(Quaternion()).angle, 1e-6)
        self.assertGreater((tail_on - Vector((0.0, 1.0, 0.0))).length, 1e-4)

    def test_child_uses_solved_parent(self):
        solver = _load_solver()
        parameters = solver.ChainParameters(
            stiffness=0.0,
            drag_force=1.0,
            gravity_power=0.0,
            gravity_dir=Vector((0.0, 0.0, -1.0)),
            hit_radius_m=0.0,
            weight=1.0,
            cone_enabled=False,
            cone_angle_rad=math.pi,
        )
        swing = Quaternion(Vector((0.0, 0.0, 1.0)), math.radians(20.0))
        parent_tail = swing @ Vector((0.0, 1.0, 0.0))
        child_tail = swing @ Vector((0.0, 2.0, 0.0))
        parent_base = Matrix.Identity(4)
        child_base = Matrix.Translation(Vector((0.0, 1.0, 0.0)))
        parent_solved = swing.to_matrix().to_4x4()
        parent_dir = parent_tail.normalized()
        states = [
            solver.SegmentState(1.0, parent_tail, parent_tail.copy(), parent_dir, Vector((0.0, 0.0, 0.0))),
            solver.SegmentState(1.0, child_tail, child_tail.copy(), parent_dir, Vector((0.0, 0.0, 0.0))),
        ]
        solver.step_chain(
            states,
            [solver.SegmentSample(parent_base), solver.SegmentSample(child_base)],
            parent_base=Matrix.Identity(4),
            parent_solved=parent_solved,
            armature_world=Matrix.Identity(4),
            scale_length=1.0,
            parameters=parameters,
            colliders=(),
        )
        expected_head = parent_tail
        child_root = states[1].current_tail_m - states[1].last_direction * states[1].length_m
        self.assertLess((child_root - expected_head).length, 1e-5)

    def test_tick_grid_is_independent_of_display_fps(self):
        solver = _load_solver()
        spans = []
        for fps, fps_base, frame_span in (
            (24, 1.0, 24),
            (30, 1.0, 30),
            (60, 1.0, 60),
            (30000, 1001.0, 30000),
        ):
            ticks = solver.included_tick_count(frame_span, fps, fps_base)
            spans.append(ticks)
        self.assertEqual(spans, [61, 61, 61, 60 * 1001 + 1])

    def test_quaternion_norm_after_swing(self):
        solver = _load_solver()
        result = solver.swing_with_twist(
            Quaternion(Vector((1.0, 2.0, 3.0)), 0.4),
            Vector((0.2, 0.9, -0.1)),
        )
        self.assertLess(abs(result.magnitude - 1.0), 1e-5)

    def test_parameter_and_mirror_errors_are_explicit(self):
        solver = _load_solver()
        parameters = solver.ChainParameters(
            stiffness=1.0,
            drag_force=1.5,
            gravity_power=0.0,
            gravity_dir=Vector((0.0, 0.0, -1.0)),
            hit_radius_m=0.0,
            weight=1.0,
            cone_enabled=False,
            cone_angle_rad=1.0,
        )
        with self.assertRaises(solver.SpringBoneError) as caught:
            solver.validate_parameters(parameters)
        self.assertEqual(str(caught.exception), "拖曳超出范围")
        parameters.drag_force = 0.5
        parameters.gravity_power = 1.0
        parameters.gravity_dir = Vector((0.0, 0.0, 0.0))
        with self.assertRaises(solver.SpringBoneError) as caught:
            solver.validate_parameters(parameters)
        self.assertEqual(str(caught.exception), "重力方向无效")
        mirror = Matrix(((-1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0), (0.0, 0.0, 0.0, 1.0)))
        self.assertFalse(solver.matrix_has_supported_scale(mirror))
        with self.assertRaises(solver.SpringBoneError) as caught:
            solver.included_tick_count(-1, 24, 1.0)
        self.assertEqual(str(caught.exception), "帧跨度无效")


if __name__ == "__main__":
    unittest.main()
