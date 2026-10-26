import math
import pathlib
import sys
import unittest

import bpy
from mathutils import Matrix, Quaternion, Vector


def _modules():
    import spring_bone
    import spring_bone.animation as animation
    import spring_bone.solver as solver

    return spring_bone, animation, solver


def _curve_rows(animation, action, slot):
    rows = []
    for bag in animation.iter_channelbags(action, slot):
        for fcurve in bag.fcurves:
            keys = tuple((round(point.co[0], 5), round(point.co[1], 6)) for point in fcurve.keyframe_points)
            rows.append((fcurve.data_path, fcurve.array_index, keys))
    return tuple(sorted(rows))


def _quaternions(animation, action, slot, bone_name):
    path = f'pose.bones["{bone_name}"].rotation_quaternion'
    curves = {}
    for bag in animation.iter_channelbags(action, slot):
        for fcurve in bag.fcurves:
            if fcurve.data_path == path:
                curves[fcurve.array_index] = fcurve
    frames = [point.co[0] for point in curves[0].keyframe_points]
    values = []
    for frame in frames:
        values.append(Quaternion(tuple(curves[index].evaluate(frame) for index in range(4))))
    return values


class SpringBoneAnimation(unittest.TestCase):
    def setUp(self):
        self.spring, self.animation, self.solver = _modules()
        self.objects = []
        self.actions = []
        self.handlers = []
        scene = bpy.context.scene
        self.fps = scene.render.fps
        self.fps_base = scene.render.fps_base
        self.frame_start = scene.frame_start
        self.frame_end = scene.frame_end
        self.frame = scene.frame_current

    def tearDown(self):
        for handler in self.handlers:
            if handler in bpy.app.handlers.frame_change_post:
                bpy.app.handlers.frame_change_post.remove(handler)
        scene = bpy.context.scene
        scene.render.fps = self.fps
        scene.render.fps_base = self.fps_base
        scene.frame_start = self.frame_start
        scene.frame_end = self.frame_end
        scene.frame_set(self.frame)
        for obj in self.objects:
            data = obj.data
            bpy.data.objects.remove(obj, do_unlink=True)
            if data is not None and data.users == 0 and isinstance(data, bpy.types.Armature):
                bpy.data.armatures.remove(data)
        for action in self.actions:
            if action.name in bpy.data.actions:
                bpy.data.actions.remove(action, do_unlink=True)

    def test_package_file_matches_requested_source(self):
        package_root = pathlib.Path(bpy.utils.user_resource("SCRIPTS")) / "addons" if "--installed" in sys.argv else pathlib.Path(__file__).resolve().parents[1]
        self.assertEqual(pathlib.Path(self.spring.__file__).resolve().parent, (package_root / "spring_bone").resolve())
        print("SPRING_BONE_FILE", self.spring.__file__)

    def test_sample_does_not_write_and_bake_keeps_source(self):
        arm = self._chain()
        self._animate(arm)
        source = arm.animation_data.action
        slot = arm.animation_data.action_slot
        before = _curve_rows(self.animation, source, slot)
        scene = bpy.context.scene
        scene.frame_set(scene.frame_end)
        source_direction = self._direction(arm, "BoneA")
        scene.frame_set(13)
        source_mid = self._direction(arm, "BoneA")
        source_location = arm.pose.bones["Parent"].location.copy()
        job = self._job(arm, warmup=0.0)
        while job.phase != "write" and not job.finished:
            job.advance()
        self.assertEqual(_curve_rows(self.animation, source, slot), before)
        job.run_budgeted()
        self.assertEqual(_curve_rows(self.animation, source, slot), before)
        self.assertFalse(source.get("sb_generated"))
        self.assertTrue(job.delivered)
        self.assertEqual(job.result_action.get("sb_generated"), 1)
        self.assertEqual(job.result_action.get("sb_frame_start"), job.frame_start)
        self.assertEqual(job.result_action.get("sb_frame_end"), job.frame_end)
        self.assertTrue(job.result_action.use_fake_user)
        self.assertNotEqual(job.result_action, source)
        result_rows = _curve_rows(self.animation, job.result_action, job.result_action.slots[0])
        self.assertTrue(any(row[0].endswith("location") for row in result_rows))
        location_before = [row for row in before if row[0].endswith("location")]
        location_after = [row for row in result_rows if row[0].endswith("location")]
        self.assertEqual(location_before, location_after)
        values = _quaternions(self.animation, job.result_action, job.result_action.slots[0], "BoneA")
        self.assertGreater(len(values), 2)
        for quat in values:
            self.assertLessEqual(abs(quat.magnitude - 1.0), 1e-5)
        for earlier, later in zip(values, values[1:]):
            self.assertGreaterEqual(earlier.dot(later), -1e-6)
        scene.frame_set(scene.frame_end)
        baked_direction = self._direction(arm, "BoneA")
        self.assertGreater(source_direction.angle(baked_direction), 0.05)
        length = (arm.matrix_world @ arm.pose.bones["BoneA"].tail - arm.matrix_world @ arm.pose.bones["BoneA"].head).length
        self.assertLessEqual(abs(length - 0.25), max(1e-6, 0.25 * 1e-5))
        arm.animation_data.action = source
        arm.animation_data.action_slot = slot
        for name in ("BoneA", "BoneB", "BoneC"):
            arm.pose.bones[name].rotation_quaternion = Quaternion()
        scene.frame_set(scene.frame_end)
        self.assertLess(self._direction(arm, "BoneA").angle(source_direction), 1e-4)
        scene.frame_set(13)
        self.assertLess(self._direction(arm, "BoneA").angle(source_mid), 1e-4)
        self.assertLess((arm.pose.bones["Parent"].location - source_location).length, 1e-5)
        self.actions.append(job.result_action)

    def test_weight_zero_keeps_local_rotation(self):
        arm = self._chain()
        self._animate(arm)
        spec = self._spec(weight=0.0, gravity=0.0, stiffness=0.0, drag=1.0)
        job = self._job(arm, chains=[spec], warmup=0.0)
        job.run_budgeted()
        scene = bpy.context.scene
        scene.frame_set(scene.frame_end)
        for name in ("BoneA", "BoneB", "BoneC"):
            quat = arm.pose.bones[name].rotation_quaternion
            self.assertLess(quat.rotation_difference(Quaternion()).angle, 1e-3)
        self.actions.append(job.result_action)

    def test_euler_stays_continuous_near_gimbal(self):
        arm = self._chain()
        for name in ("BoneA", "BoneB", "BoneC"):
            arm.pose.bones[name].rotation_mode = "XYZ"
        parent = arm.pose.bones["Parent"]
        parent.rotation_mode = "XYZ"
        parent.rotation_euler = (0.0, math.radians(80.0), 0.0)
        parent.keyframe_insert("rotation_euler", frame=1)
        parent.rotation_euler = (0.2, math.radians(100.0), 0.2)
        parent.keyframe_insert("rotation_euler", frame=25)
        scene = bpy.context.scene
        scene.render.fps = 24
        scene.frame_start = 1
        scene.frame_end = 25
        spec = self._spec(weight=1.0, gravity=3.0, stiffness=0.2, drag=0.2)
        job = self._job(arm, chains=[spec], warmup=0.0)
        job.run_budgeted()
        for name in ("BoneA", "BoneB", "BoneC"):
            self.assertEqual(arm.pose.bones[name].rotation_mode, "XYZ")
        path = 'pose.bones["BoneA"].rotation_euler'
        curves = {}
        for bag in self.animation.iter_channelbags(job.result_action, job.result_action.slots[0]):
            for fcurve in bag.fcurves:
                if fcurve.data_path == path:
                    curves[fcurve.array_index] = fcurve
        frames = [point.co[0] for point in curves[0].keyframe_points]
        previous = None
        for frame in frames:
            euler = [curves[index].evaluate(frame) for index in range(3)]
            if previous is not None:
                for component, prior in zip(euler, previous):
                    self.assertLess(abs(component - prior), math.pi)
            previous = euler
        self.actions.append(job.result_action)

    def test_same_tick_matches_across_frame_rates(self):
        tails = []
        rotations = []
        for fps, base, end in ((24, 1.0, 25), (30, 1.0, 31), (60, 1.0, 61), (30000, 1001.0, 31)):
            arm = self._chain()
            self._key_physical_ticks(arm, fps, base, end)
            job = self._job(arm, warmup=0.0, gravity=0.0, stiffness=12.0, drag=1.0)
            job.run_budgeted()
            self.assertEqual(len(job.trace_tails), 61)
            self.assertGreater((job.trace_tails[60] - job.trace_tails[0]).length, 1e-3)
            tails.append(job.trace_tails[60].copy())
            rotations.append(job.trace_rotations[60].copy())
            self.actions.append(job.result_action)
        for tail, rotation in zip(tails[1:], rotations[1:]):
            self.assertLessEqual((tail - tails[0]).length, 1e-5)
            self.assertLessEqual(rotation.rotation_difference(rotations[0]).angle, 1e-4)

    def test_sample_restores_unkeyed_basis(self):
        arm = self._chain()
        self._animate(arm)
        scene = bpy.context.scene
        scene.frame_start = 1
        scene.frame_end = 5
        seen = {}

        def after(job):
            if job.sample_index == 1 and "dirty" not in seen:
                arm.pose.bones["BoneA"].location = (1.0, 0.0, 0.0)
                seen["dirty"] = True
            elif seen.get("dirty") and "location" not in seen and job.sample_index >= 2:
                seen["location"] = arm.pose.bones["BoneA"].location.copy()

        job = self._job(arm, warmup=0.0)
        job.after_unit = after
        job.run_budgeted()
        self.assertIn("location", seen)
        self.assertLess(seen["location"].length, 1e-4)
        self.actions.append(job.result_action)

    def test_endpoint_step_does_not_replace_grid_state(self):
        arm = self._chain()
        self._animate(arm)
        scene = bpy.context.scene
        scene.render.fps = 24
        scene.frame_start = 1
        scene.frame_end = 10
        seen = {}

        def after(job):
            if job.grid_ticks and job.grid_index == len(job.grid_ticks) and not job.endpoint_done and "tail" not in seen:
                seen["tail"] = job.runtimes[0].states[-1].current_tail_m.copy()

        job = self._job(arm, warmup=0.0)
        job.after_unit = after
        job.run_budgeted()
        self.assertIn("tail", seen)
        self.assertLess((job.runtimes[0].states[-1].current_tail_m - seen["tail"]).length, 1e-8)
        self.actions.append(job.result_action)

    def test_distant_sphere_has_no_penetration_and_cone_limits_direction(self):
        arm = self._chain()
        self._animate(arm)
        parent = arm.pose.bones["Parent"]
        parent.rotation_quaternion = Quaternion()
        parent.location = (0.0, 0.0, 0.0)
        parent.keyframe_insert("rotation_quaternion", frame=1)
        parent.keyframe_insert("location", frame=1)
        parent.keyframe_insert("rotation_quaternion", frame=25)
        parent.keyframe_insert("location", frame=25)
        self._bone(arm, "Leg", (1.5, 0.0, 1.0), (1.5, 0.2, 1.0), "")
        bpy.ops.object.mode_set(mode="POSE")
        collider = self.animation.ColliderSpec(
            "SPHERE",
            "Leg",
            0.05,
            Vector((0.0, 0.0, 0.0)),
            Vector((0.0, 0.1, 0.0)),
        )
        cone = self._spec(cone=True, angle=25.0, gravity=8.0, stiffness=0.0, drag=0.1)
        job = self._job(arm, chains=[cone], colliders=[collider], warmup=0.0)
        job.run_budgeted()
        self.assertLessEqual(job.max_penetration_m, 1e-5)
        self.assertAlmostEqual(job.result_action.get("sb_penetration_m"), job.max_penetration_m)
        scene = bpy.context.scene
        scene.frame_set(scene.frame_end)
        direction = self._direction(arm, "BoneA")
        self.assertGreater(direction.angle(Vector((0.0, 1.0, 0.0))), 0.2)
        self.assertLessEqual(direction.angle(Vector((0.0, 1.0, 0.0))), math.radians(25.0) + 1e-3)
        self.actions.append(job.result_action)

    def _chain(self):
        arm_data = bpy.data.armatures.new("SpringArm")
        obj = bpy.data.objects.new("SpringArm", arm_data)
        bpy.context.scene.collection.objects.link(obj)
        self.objects.append(obj)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode="EDIT")
        self._bone(obj, "Parent", (0.0, 0.0, 1.0), (0.0, 0.0, 1.2), "")
        self._bone(obj, "BoneA", (0.0, 0.0, 1.0), (0.0, 0.25, 1.0), "Parent")
        self._bone(obj, "BoneB", (0.0, 0.25, 1.0), (0.0, 0.5, 1.0), "BoneA")
        self._bone(obj, "BoneC", (0.0, 0.5, 1.0), (0.0, 0.75, 1.0), "BoneB")
        bpy.ops.object.mode_set(mode="POSE")
        return obj

    def _bone(self, obj, name, head, tail, parent):
        if obj.mode != "EDIT":
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.mode_set(mode="EDIT")
        edit = obj.data.edit_bones.new(name)
        edit.head = head
        edit.tail = tail
        if parent:
            edit.parent = obj.data.edit_bones[parent]
        return edit

    def _animate(self, obj):
        scene = bpy.context.scene
        scene.render.fps = 24
        scene.render.fps_base = 1.0
        scene.frame_start = 1
        scene.frame_end = 25
        parent = obj.pose.bones["Parent"]
        parent.rotation_mode = "QUATERNION"
        parent.rotation_quaternion = Quaternion()
        parent.location = (0.0, 0.0, 0.0)
        parent.keyframe_insert("rotation_quaternion", frame=1)
        parent.keyframe_insert("location", frame=1)
        parent.rotation_quaternion = Quaternion(Vector((1.0, 0.0, 0.0)), math.radians(30.0))
        parent.location = (0.2, 0.0, 0.0)
        parent.keyframe_insert("rotation_quaternion", frame=25)
        parent.keyframe_insert("location", frame=25)
        action = obj.animation_data.action
        self.actions.append(action)
        for bag in self.animation.iter_channelbags(action, obj.animation_data.action_slot):
            for fcurve in bag.fcurves:
                for point in fcurve.keyframe_points:
                    point.interpolation = "LINEAR"

    def _spec(self, weight=1.0, gravity=2.0, stiffness=0.4, drag=0.25, cone=False, angle=60.0):
        return self.animation.ChainSpec(
            ("BoneA", "BoneB", "BoneC"),
            self.solver.ChainParameters(
                stiffness=stiffness,
                drag_force=drag,
                gravity_power=gravity,
                gravity_dir=Vector((0.0, 0.0, -1.0)),
                hit_radius_m=0.0,
                weight=weight,
                cone_enabled=cone,
                cone_angle_rad=math.radians(angle),
            ),
        )

    def _job(self, obj, chains=None, colliders=None, warmup=0.0, gravity=None, stiffness=None, drag=None):
        scene = bpy.context.scene
        spec = self._spec()
        if gravity is not None:
            spec.parameters.gravity_power = gravity
        if stiffness is not None:
            spec.parameters.stiffness = stiffness
        if drag is not None:
            spec.parameters.drag_force = drag
        spec.warmup_seconds = warmup
        return self.animation.SpringBoneBakeJob(
            obj,
            chains or [spec],
            colliders or [],
            scene.frame_start,
            scene.frame_end,
            True,
        )

    def _direction(self, obj, name):
        pose = obj.pose.bones[name]
        return (obj.matrix_world @ pose.tail - obj.matrix_world @ pose.head).normalized()

    def _key_physical_ticks(self, obj, fps, base, end):
        scene = bpy.context.scene
        scene.render.fps = fps
        scene.render.fps_base = base
        scene.frame_start = 1
        scene.frame_end = end
        parent = obj.pose.bones["Parent"]
        parent.rotation_mode = "QUATERNION"
        count = self.solver.included_tick_count(end - 1, fps, base)
        for index in range(count):
            frame = self.solver.frame_for_tick(1, index, fps, base)
            parent.rotation_quaternion = Quaternion(Vector((1.0, 0.0, 0.0)), (index / 60.0) * 0.35)
            parent.keyframe_insert("rotation_quaternion", frame=frame)
        action = obj.animation_data.action
        self.actions.append(action)
        for bag in self.animation.iter_channelbags(action, obj.animation_data.action_slot):
            for fcurve in bag.fcurves:
                for point in fcurve.keyframe_points:
                    point.interpolation = "LINEAR"
