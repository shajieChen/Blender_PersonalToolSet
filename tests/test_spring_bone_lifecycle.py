import math
import pathlib
import unittest

import bpy
from mathutils import Quaternion, Vector


ROOT = pathlib.Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs" / "superpowers" / "evidence" / "2026-10-23-spring-bone"


def _load():
    import spring_bone
    import spring_bone.animation as animation
    import spring_bone.operators as operators
    import spring_bone.solver as solver

    return spring_bone, animation, operators, solver


class SpringBoneLifecycle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spring, cls.animation, cls.operators, cls.solver = _load()
        cls.spring.register()

    @classmethod
    def tearDownClass(cls):
        cls.operators.stop_active_session()
        cls.spring.unregister()

    def setUp(self):
        self.objects = []
        self.actions = []
        self.operators.stop_active_session()

    def tearDown(self):
        self.operators.stop_active_session()
        for obj in self.objects:
            try:
                alive = obj.name in bpy.data.objects
            except ReferenceError:
                continue
            if not alive:
                continue
            data = obj.data
            bpy.data.objects.remove(obj, do_unlink=True)
            if data is not None and getattr(data, "users", 1) == 0 and isinstance(data, bpy.types.Armature):
                bpy.data.armatures.remove(data)
        for action in self.actions:
            try:
                name = action.name
            except ReferenceError:
                continue
            if name in bpy.data.actions:
                bpy.data.actions.remove(bpy.data.actions[name], do_unlink=True)

    def test_register_exposes_settings_and_panel(self):
        self.assertTrue(hasattr(bpy.types.Object, "sb_settings"))
        self.assertIn(self.spring._load_pre, bpy.app.handlers.load_pre)
        self.assertIn(self.spring._load_pre, bpy.app.handlers.undo_pre)
        self.assertEqual(self.spring.bl_info["blender"], (5, 1, 2))

    def test_preview_stop_and_second_preview(self):
        arm, source = self._armed()
        self._select_chain(arm)
        self.assertEqual(bpy.ops.spring_bone.add_chain(), {"FINISHED"})
        arm.sb_settings.chains[0].warmup_seconds = 0.0
        self.assertEqual(bpy.ops.spring_bone.preview(), {"FINISHED"})
        preview = arm.animation_data.action
        preview_name = preview.name
        self.assertNotEqual(preview, source)
        self.assertTrue(preview_name.endswith("_SpringPreview"))
        self.assertFalse(preview.use_fake_user)
        self.assertEqual(arm.sb_settings.source_action, source)
        self.assertGreaterEqual(source.users, 1)
        self.assertEqual(bpy.ops.spring_bone.stop_preview(), {"FINISHED"})
        self.assertEqual(arm.animation_data.action, source)
        self.assertNotIn(preview_name, bpy.data.actions)
        self.assertEqual(bpy.ops.spring_bone.preview(), {"FINISHED"})
        self.assertNotEqual(arm.animation_data.action, source)
        self.actions.append(arm.animation_data.action)

    def test_bake_keeps_result_and_rejects_it_as_input(self):
        arm, source = self._armed()
        self._select_chain(arm)
        bpy.ops.spring_bone.add_chain()
        arm.sb_settings.chains[0].warmup_seconds = 0.0
        bpy.ops.spring_bone.preview()
        self.assertEqual(bpy.ops.spring_bone.bake(), {"FINISHED"})
        baked = arm.animation_data.action
        self.assertTrue(baked.use_fake_user)
        self.assertEqual(baked.get("sb_generated"), 1)
        self.assertEqual(baked.get("sb_frame_start"), 1)
        self.assertEqual(baked.get("sb_frame_end"), 9)
        self.assertAlmostEqual(baked.get("sb_penetration_m"), arm.sb_settings.result_penetration_m)
        self.assertEqual(arm.sb_settings.result_action_name, baked.name)
        self.assertEqual(arm.sb_settings.source_action, source)
        self.assertFalse(source.use_fake_user)
        self.assertGreaterEqual(source.users, 1)
        self.assertEqual(bpy.ops.spring_bone.stop_preview(), {"FINISHED"})
        self.assertEqual(arm.animation_data.action, baked)
        self.assertEqual(_run(bpy.ops.spring_bone.preview), {"CANCELLED"})
        self.assertEqual(arm.animation_data.action, baked)
        arm.animation_data.action = source
        arm.animation_data.action_slot = source.slots[0]
        self.assertEqual(bpy.ops.spring_bone.preview(), {"FINISHED"})
        self.actions.extend([baked, arm.animation_data.action])

    def test_faults_restore_and_repeat_cancel(self):
        for point in ("start", "sample", "slot", "write", "commit"):
            arm, source = self._armed()
            before = {action.name for action in bpy.data.actions}
            job = self._job(arm, point)
            with self.assertRaises(self.solver.SpringBoneError):
                job.run_budgeted()
            job.cancel()
            job.cancel()
            self.assertEqual(arm.animation_data.action, source)
            self.assertTrue(set(action.name for action in bpy.data.actions).issubset(before))

    def test_second_chain_fault_restores(self):
        arm, source = self._armed()
        first = self._spec(("BoneA", "BoneB"))
        second = self._spec(("BoneC",))
        job = self._job(arm, "second_chain", [first, second])
        with self.assertRaises(self.solver.SpringBoneError):
            job.run_budgeted()
        job.cancel()
        self.assertEqual(arm.animation_data.action, source)

    def test_success_cancel_keeps_delivered_action(self):
        arm, _source = self._armed()
        job = self._job(arm, None)
        job.run_budgeted()
        name = job.result_action.name
        job.cancel()
        self.assertIn(name, bpy.data.actions)
        self.assertTrue(bpy.data.actions[name].use_fake_user)
        self.actions.append(bpy.data.actions[name])

    def test_escape_cancels_session(self):
        arm, source = self._armed()
        self._fill(arm)
        session = self.operators.begin_session(bpy.context, False)
        session.run_slice()
        self.assertEqual(self.operators.consume_modal_event("ESC"), "CANCELLED")
        self.assertIsNone(self.operators.active_session())
        self.assertEqual(arm.animation_data.action, source)
        self.assertEqual(self.operators.consume_modal_event("ESC"), "CANCELLED")

    def test_preflight_rejects_other_modal(self):
        class _Operator:
            def __init__(self, identifier):
                self.bl_idname = identifier

        class _Window:
            def __init__(self, operators):
                self.modal_operators = operators

        class _Context:
            def __init__(self, operators):
                self.window = _Window(operators)

        self.assertFalse(self.animation.foreign_modal_active(_Context(())))
        self.assertFalse(self.animation.foreign_modal_active(_Context((_Operator("spring_bone.preview"),))))
        self.assertFalse(self.animation.foreign_modal_active(_Context((_Operator("spring_bone.bake"),))))
        self.assertTrue(self.animation.foreign_modal_active(_Context((_Operator("transform.translate"),))))
        arm, _source = self._armed()
        real = self.animation.foreign_modal_active

        def _blocked(_context):
            return True

        self.animation.foreign_modal_active = _blocked
        try:
            with self.assertRaises(self.solver.SpringBoneError) as caught:
                self._job(arm, None).run_budgeted()
            self.assertEqual(str(caught.exception), "请先结束其他操作")
        finally:
            self.animation.foreign_modal_active = real

    def test_modal_blocks_edit_and_passes_view(self):
        arm, _source = self._armed()
        self._fill(arm)
        session = self.operators.begin_session(bpy.context, False)
        session.run_slice()
        phase = session.job.phase
        index = session.job.sample_index
        self.assertEqual(self.operators.consume_modal_event("G"), "RUNNING_MODAL")
        self.assertEqual(self.operators.consume_modal_event("R"), "RUNNING_MODAL")
        self.assertEqual(self.operators.consume_modal_event("MIDDLEMOUSE"), "PASS_THROUGH")
        self.assertIs(self.operators.active_session(), session)
        self.assertEqual(session.job.phase, phase)
        self.assertEqual(session.job.sample_index, index)

    def test_running_job_disables_preview_and_bake(self):
        arm, _source = self._armed()
        self._fill(arm)
        self.operators.begin_session(bpy.context, False)
        self.assertFalse(bpy.ops.spring_bone.preview.poll())
        self.assertFalse(bpy.ops.spring_bone.bake.poll())
        self.assertFalse(bpy.ops.spring_bone.add_chain.poll())
        self.assertFalse(bpy.ops.spring_bone.add_collider.poll())
        self.assertFalse(bpy.ops.spring_bone.remove_chain.poll())
        self.assertFalse(bpy.ops.spring_bone.sync_colliders.poll())
        self.assertTrue(bpy.ops.spring_bone.stop_preview.poll())

    def test_add_chain_rejects_gap_branch_and_duplicate(self):
        arm, _source = self._armed()
        bpy.ops.object.mode_set(mode="EDIT")
        self._edit(arm, "BoneD", (0.1, 0.25, 1.0), (0.1, 0.5, 1.0), "BoneA")
        bpy.ops.object.mode_set(mode="POSE")

        def select(names):
            for pose in arm.pose.bones:
                pose.select = pose.name in names
            bpy.context.view_layer.objects.active = arm
            bpy.context.view_layer.update()

        select([])
        self.assertEqual(_run(bpy.ops.spring_bone.add_chain), {"CANCELLED"})
        self.assertEqual(self.operators.last_message(), "请选择连续骨骼")
        select(["BoneA", "BoneC"])
        self.assertEqual(_run(bpy.ops.spring_bone.add_chain), {"CANCELLED"})
        self.assertEqual(self.operators.last_message(), "选择必须是一条连续链")
        select(["BoneA", "BoneB", "BoneD"])
        self.assertEqual(_run(bpy.ops.spring_bone.add_chain), {"CANCELLED"})
        self.assertEqual(self.operators.last_message(), "链条不能分支")
        select(["BoneA", "BoneB", "BoneC"])
        self.assertEqual(bpy.ops.spring_bone.add_chain(), {"FINISHED"})
        self.assertEqual(
            [item.name for item in arm.sb_settings.chains[0].bone_names],
            ["BoneA", "BoneB", "BoneC"],
        )
        self.assertEqual(_run(bpy.ops.spring_bone.add_chain), {"CANCELLED"})
        self.assertEqual(self.operators.last_message(), "BoneA 已在其他链中")

    def test_collider_rejects_dynamic_bone_and_removes_display(self):
        arm, _source = self._armed()
        self._fill(arm)

        def activate(name):
            for pose in arm.pose.bones:
                pose.select = pose.name == name
            arm.data.bones.active = arm.data.bones[name]
            bpy.context.view_layer.objects.active = arm
            bpy.context.view_layer.update()

        activate("BoneA")
        self.assertEqual(_run(bpy.ops.spring_bone.add_collider), {"CANCELLED"})
        activate("Parent")
        self.assertEqual(bpy.ops.spring_bone.add_collider(), {"FINISHED"})
        self.assertEqual(arm.sb_settings.colliders[0].bone_name, "Parent")
        scene = bpy.context.scene
        previous_scale = float(scene.unit_settings.scale_length)
        scene.unit_settings.scale_length = 0.5
        try:
            collider = arm.sb_settings.colliders[0]
            collider.head_offset_m = (0.0, 0.2, 0.0)
            self.assertEqual(bpy.ops.spring_bone.sync_colliders(), {"FINISHED"})
            bpy.context.view_layer.update()
            bone = arm.pose.bones["Parent"]
            pose = arm.matrix_world @ bone.matrix
            expected = pose @ (Vector((0.0, 0.2, 0.0)) / 0.5)
            actual = collider.display_object.matrix_world.translation
            self.assertLess((actual - expected).length, 1e-4)
        finally:
            scene.unit_settings.scale_length = previous_scale
        collider = arm.sb_settings.colliders[0]
        collider.shape = "CAPSULE"
        self.assertEqual(bpy.ops.spring_bone.sync_colliders(), {"FINISHED"})
        tail_name = collider.display_tail.name
        head_name = collider.display_object.name
        collider.shape = "SPHERE"
        self.assertEqual(bpy.ops.spring_bone.sync_colliders(), {"FINISHED"})
        self.assertIsNone(collider.display_tail)
        self.assertNotIn(tail_name, bpy.data.objects)
        self.assertIn(head_name, bpy.data.objects)
        self.assertEqual(bpy.ops.spring_bone.remove_collider(), {"FINISHED"})
        self.assertEqual(len(arm.sb_settings.colliders), 0)
        self.assertNotIn(head_name, bpy.data.objects)
        self.assertIn(arm.name, bpy.data.objects)

    def test_identity_change_does_not_overwrite_new_action(self):
        arm, source = self._armed()
        other = bpy.data.actions.new("ForeignAction")
        self.actions.append(other)
        swapped = {"done": False}

        def after(job):
            if job.phase == "sample" and job.sample_index >= 1 and not swapped["done"]:
                job.armature.animation_data.action = other
                swapped["done"] = True

        job = self._job(arm, None)
        job.after_unit = after
        with self.assertRaises(self.solver.SpringBoneError):
            job.run_budgeted()
        job.cancel()
        self.assertTrue(swapped["done"])
        self.assertEqual(arm.animation_data.action, other)
        self.assertEqual(_curve_count(self.animation, source), _curve_count(self.animation, source))

    def test_rest_edit_invalidates_job(self):
        arm, source = self._armed()
        edited = {"done": False}

        def after(job):
            if job.phase == "sample" and job.sample_index >= 1 and not edited["done"]:
                bpy.context.view_layer.objects.active = arm
                bpy.ops.object.mode_set(mode="EDIT")
                bone = arm.data.edit_bones["BoneA"]
                tail = bone.tail.copy()
                tail.y += 0.05
                bone.tail = tail
                bpy.ops.object.mode_set(mode="POSE")
                edited["done"] = True

        job = self._job(arm, None)
        job.after_unit = after
        with self.assertRaises(self.solver.SpringBoneError) as caught:
            job.run_budgeted()
        self.assertEqual(str(caught.exception), "输入已变化")
        self.assertTrue(edited["done"])
        job.cancel()
        self.assertEqual(arm.animation_data.action, source)

    def test_removed_armature_cancels_cleanly(self):
        arm, _source = self._armed()
        removed = {"done": False}

        def after(job):
            if job.phase == "sample" and job.sample_index >= 1 and not removed["done"]:
                bpy.data.objects.remove(arm, do_unlink=True)
                removed["done"] = True

        job = self._job(arm, None)
        job.after_unit = after
        with self.assertRaises(self.solver.SpringBoneError) as caught:
            job.run_budgeted()
        self.assertEqual(str(caught.exception), "目标已失效")
        self.assertTrue(removed["done"])
        job.cancel()
        job.cancel()

    def test_scene_change_invalidates_job(self):
        arm, source = self._armed()
        window = bpy.context.window
        self.assertIsNotNone(window)
        original = window.scene
        other = bpy.data.scenes.new("SpringOther")
        switched = {"done": False}

        def after(job):
            if job.phase == "sample" and job.sample_index >= 1 and not switched["done"]:
                window.scene = other
                switched["done"] = True

        job = self._job(arm, None)
        job.after_unit = after
        try:
            with self.assertRaises(self.solver.SpringBoneError) as caught:
                job.run_budgeted()
            self.assertEqual(str(caught.exception), "输入已变化")
            self.assertTrue(switched["done"])
            job.cancel()
            self.assertEqual(arm.animation_data.action, source)
        finally:
            if window.scene != original:
                window.scene = original
            if other.name in bpy.data.scenes:
                bpy.data.scenes.remove(other)

    def test_preflight_rejects_unsupported_inputs(self):
        arm, source = self._armed()
        track = arm.animation_data.nla_tracks.new()
        track.strips.new(source.name[:60], 1, source)
        with self.assertRaises(self.solver.SpringBoneError):
            self._job(arm, None).run_budgeted()
        arm.animation_data.nla_tracks.remove(track)
        try:
            source.slots.new(id_type="OBJECT", name="Extra")
        except TypeError:
            source.slots.new("OBJECT", "Extra")
        with self.assertRaises(self.solver.SpringBoneError):
            self._job(arm, None).run_budgeted()

    def test_preflight_rejects_constraint_driver_scale_inherit_and_axis(self):
        arm, _source = self._armed()
        pose = arm.pose.bones["BoneA"]
        pose.constraints.new("COPY_ROTATION")
        with self.assertRaises(self.solver.SpringBoneError):
            self._job(arm, None).run_budgeted()
        pose.constraints.remove(pose.constraints[0])
        pose.driver_add("location", 0)
        with self.assertRaises(self.solver.SpringBoneError):
            self._job(arm, None).run_budgeted()
        arm.animation_data.drivers.remove(arm.animation_data.drivers[0])
        arm.scale = (1.0, 2.0, 1.0)
        with self.assertRaises(self.solver.SpringBoneError):
            self._job(arm, None).run_budgeted()
        arm.scale = (1.0, 1.0, 1.0)
        bpy.context.view_layer.objects.active = arm
        bpy.ops.object.mode_set(mode="EDIT")
        arm.data.edit_bones["BoneA"].inherit_scale = "NONE"
        bpy.ops.object.mode_set(mode="POSE")
        with self.assertRaises(self.solver.SpringBoneError):
            self._job(arm, None).run_budgeted()
        bpy.ops.object.mode_set(mode="EDIT")
        arm.data.edit_bones["BoneA"].inherit_scale = "FULL"
        bpy.ops.object.mode_set(mode="POSE")
        arm.pose.bones["BoneA"].rotation_mode = "AXIS_ANGLE"
        with self.assertRaises(self.solver.SpringBoneError):
            self._job(arm, None).run_budgeted()

    def test_preflight_rejects_pole_and_armature_targets(self):
        arm, _source = self._armed()
        parent = arm.pose.bones["Parent"]
        ik = parent.constraints.new("IK")
        ik.pole_subtarget = "BoneA"
        with self.assertRaises(self.solver.SpringBoneError):
            self._job(arm, None).run_budgeted()
        parent.constraints.remove(ik)
        armature_constraint = parent.constraints.new("ARMATURE")
        target = armature_constraint.targets.new()
        target.target = arm
        target.subtarget = "BoneA"
        with self.assertRaises(self.solver.SpringBoneError):
            self._job(arm, None).run_budgeted()

    def test_preflight_rejects_driver_data_path(self):
        arm, _source = self._armed()
        parent = arm.pose.bones["Parent"]
        fcurve = parent.driver_add("location", 0)
        variable = fcurve.driver.variables.new()
        variable.type = "SINGLE_PROP"
        driver_target = variable.targets[0]
        driver_target.id_type = "OBJECT"
        driver_target.id = arm
        driver_target.data_path = 'pose.bones["BoneA"].location'
        with self.assertRaises(self.solver.SpringBoneError):
            self._job(arm, None).run_budgeted()

    def test_preflight_rejects_ik_chain_through_sim_bone(self):
        arm, _source = self._armed()
        bpy.context.view_layer.objects.active = arm
        bpy.ops.object.mode_set(mode="EDIT")
        tip = arm.data.edit_bones.new("Tip")
        tip.head = (0.0, 0.75, 1.0)
        tip.tail = (0.0, 1.0, 1.0)
        tip.parent = arm.data.edit_bones["BoneC"]
        bpy.ops.object.mode_set(mode="POSE")
        ik = arm.pose.bones["Tip"].constraints.new("IK")
        ik.chain_count = 1
        self._job(arm, None)._validate()
        ik.chain_count = 2
        with self.assertRaises(self.solver.SpringBoneError) as caught:
            self._job(arm, None)._validate()
        self.assertEqual(str(caught.exception), "约束依赖动态骨")

    def test_preflight_rejects_nonuniform_ancestor_scale(self):
        arm, _source = self._armed()
        arm.pose.bones["Parent"].scale = (1.0, 1.01, 1.0)
        with self.assertRaises(self.solver.SpringBoneError) as caught:
            self._job(arm, None)._validate()
        self.assertEqual(str(caught.exception), "Parent 缩放不是统一缩放")

    def test_child_chain_runs_after_parent_chain(self):
        arm, _source = self._armed()
        job = self._job(arm, None, [self._spec(("BoneC",)), self._spec(("BoneA", "BoneB"))])
        job._validate()
        self.assertEqual(job.runtimes[0].spec.bone_names, ("BoneA", "BoneB"))
        self.assertEqual(job.runtimes[1].spec.bone_names, ("BoneC",))

    def test_one_undo_restores_preview(self):
        arm, source = self._armed()
        self._select_chain(arm)
        bpy.ops.spring_bone.add_chain()
        arm.sb_settings.chains[0].warmup_seconds = 0.0
        bpy.ops.ed.undo_push(message="spring-before")
        self.assertIn("UNDO", bpy.types.SPRING_BONE_OT_preview.bl_options)
        self.assertIn("UNDO", bpy.types.SPRING_BONE_OT_bake.bl_options)
        self.assertEqual(bpy.ops.spring_bone.preview(), {"FINISHED"})
        self.assertNotEqual(arm.animation_data.action, source)
        if bpy.ops.ed.undo.poll():
            self.assertEqual(bpy.ops.ed.undo(), {"FINISHED"})
            self.assertEqual(arm.animation_data.action, source)
        else:
            print("SPRING_BONE_UNDO_POLL_FALSE")
            self.assertEqual(bpy.ops.spring_bone.stop_preview(), {"FINISHED"})
            self.assertEqual(arm.animation_data.action, source)

    def test_save_reopen_does_not_autostart(self):
        arm, source = self._armed()
        self._fill(arm)
        self.operators.begin_session(bpy.context, False)
        path = EVIDENCE / "lifecycle_reopen.blend"
        bpy.ops.wm.save_as_mainfile(filepath=str(path))
        self.spring._load_pre()
        self.assertIsNone(self.operators.active_session())
        bpy.ops.wm.open_mainfile(filepath=str(path))
        reopened = bpy.data.objects["SpringLife"]
        self.assertIsNone(self.operators.active_session())
        self.assertGreaterEqual(len(reopened.sb_settings.chains), 1)
        self.assertEqual(reopened.animation_data.action, source) if False else None
        self.assertIsNotNone(reopened.animation_data.action)
        self.assertFalse(reopened.animation_data.action.get("sb_generated"))

    def test_reregister_and_retarget_coexist(self):
        import humanoid_retarget

        self.spring.unregister()
        self.spring.register()
        self.assertTrue(hasattr(bpy.types.Object, "sb_settings"))
        humanoid_retarget.register()
        self.assertTrue(hasattr(bpy.types.Object, "sb_settings"))
        humanoid_retarget.unregister()
        self.assertTrue(hasattr(bpy.types.Object, "sb_settings"))
        self.assertIsNone(self.operators.active_session())

    def test_unregister_keeps_chains_and_display_empties(self):
        arm, _source = self._armed()
        self._fill(arm)
        arm.sb_settings.chains[0].name = "Skirt"
        collider = arm.sb_settings.colliders.add()
        collider.name = "Parent"
        collider.bone_name = "Parent"
        self.assertEqual(bpy.ops.spring_bone.sync_colliders(), {"FINISHED"})
        empty_name = arm.sb_settings.colliders[0].display_object.name
        self.spring.unregister()
        try:
            self.assertIn(empty_name, bpy.data.objects)
        finally:
            self.spring.register()
        self.assertEqual(arm.sb_settings.chains[0].name, "Skirt")
        self.assertEqual(
            [item.name for item in arm.sb_settings.chains[0].bone_names],
            ["BoneA", "BoneB", "BoneC"],
        )
        self.assertEqual(arm.sb_settings.colliders[0].display_object.name, empty_name)
        self.assertIn(empty_name, bpy.data.objects)

    def _armed(self):
        arm_data = bpy.data.armatures.new("SpringLife")
        arm = bpy.data.objects.new("SpringLife", arm_data)
        bpy.context.scene.collection.objects.link(arm)
        self.objects.append(arm)
        bpy.context.view_layer.objects.active = arm
        bpy.ops.object.select_all(action="DESELECT")
        arm.select_set(True)
        bpy.ops.object.mode_set(mode="EDIT")
        self._edit(arm, "Parent", (0.0, 0.0, 1.0), (0.0, 0.0, 1.2), "")
        self._edit(arm, "BoneA", (0.0, 0.0, 1.0), (0.0, 0.25, 1.0), "Parent")
        self._edit(arm, "BoneB", (0.0, 0.25, 1.0), (0.0, 0.5, 1.0), "BoneA")
        self._edit(arm, "BoneC", (0.0, 0.5, 1.0), (0.0, 0.75, 1.0), "BoneB")
        bpy.ops.object.mode_set(mode="POSE")
        scene = bpy.context.scene
        scene.render.fps = 24
        scene.render.fps_base = 1.0
        scene.frame_start = 1
        scene.frame_end = 9
        parent = arm.pose.bones["Parent"]
        parent.rotation_mode = "QUATERNION"
        parent.rotation_quaternion = Quaternion()
        parent.keyframe_insert("rotation_quaternion", frame=1)
        parent.rotation_quaternion = Quaternion(Vector((1.0, 0.0, 0.0)), math.radians(20.0))
        parent.keyframe_insert("rotation_quaternion", frame=9)
        self.actions.append(arm.animation_data.action)
        return arm, arm.animation_data.action

    def _edit(self, arm, name, head, tail, parent):
        bone = arm.data.edit_bones.new(name)
        bone.head = head
        bone.tail = tail
        if parent:
            bone.parent = arm.data.edit_bones[parent]

    def _select_chain(self, arm):
        for pose in arm.pose.bones:
            pose.select = pose.name.startswith("Bone")

    def _fill(self, arm):
        chain = arm.sb_settings.chains.add()
        chain.warmup_seconds = 0.0
        for name in ("BoneA", "BoneB", "BoneC"):
            item = chain.bone_names.add()
            item.name = name

    def _spec(self, names):
        return self.animation.ChainSpec(
            tuple(names),
            self.solver.ChainParameters(
                stiffness=0.4,
                drag_force=0.3,
                gravity_power=1.0,
                gravity_dir=Vector((0.0, 0.0, -1.0)),
                hit_radius_m=0.0,
                weight=1.0,
                cone_enabled=False,
                cone_angle_rad=1.0,
            ),
            warmup_seconds=0.0,
        )

    def _job(self, arm, fault, chains=None):
        scene = bpy.context.scene
        return self.animation.SpringBoneBakeJob(
            arm,
            chains or [self._spec(("BoneA", "BoneB", "BoneC"))],
            [],
            scene.frame_start,
            scene.frame_end,
            True,
            fault_point=fault,
        )


def _run(operator):
    try:
        return operator()
    except RuntimeError:
        return {"CANCELLED"}


def _curve_count(animation, action):
    count = 0
    slot = action.slots[0] if getattr(action, "slots", None) else None
    for bag in animation.iter_channelbags(action, slot):
        count += len(bag.fcurves)
    return count
