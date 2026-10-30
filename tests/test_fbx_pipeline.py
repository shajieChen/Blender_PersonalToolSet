import os
import pathlib
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import bpy

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import humanoid_retarget
from humanoid_retarget import pipeline
from io_scene_fbx import parse_fbx


def build_rig(name="ExportRig", hips_name="hips"):
    data = bpy.data.armatures.new(name)
    arm = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    arm.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    root = data.edit_bones.new("root")
    root.head = (0, 0, 0)
    root.tail = (0, 0, 1)
    hips = data.edit_bones.new(hips_name)
    hips.head = root.tail
    hips.tail = (0, 0, 1.2)
    hips.parent = root
    hips.use_connect = False
    tip = data.edit_bones.new("tip")
    tip.head = hips.tail
    tip.tail = (0, 0, 1.4)
    tip.parent = hips
    tip.use_connect = True
    bpy.ops.object.mode_set(mode="OBJECT")
    mesh = bpy.data.meshes.new("Body")
    mesh.from_pydata([(0, 0, 1), (0.1, 0, 1), (0, 0.1, 1), (0, 0, 1.1)], [],
                     [(0, 1, 2), (0, 1, 3), (0, 2, 3), (1, 2, 3)])
    obj = bpy.data.objects.new("Body", mesh)
    bpy.context.collection.objects.link(obj)
    obj.parent = arm
    obj.vertex_groups.new(name=hips_name).add(list(range(4)), 1.0, "REPLACE")
    obj.modifiers.new("Skin", "ARMATURE").object = arm
    return arm


def animate(arm, name, end=5, distance=0.2, hips_name="hips"):
    arm.animation_data_create().action = None
    bone = arm.pose.bones[hips_name]
    bone.location = (0, 0, 0)
    bone.keyframe_insert("location", frame=1)
    bone.location = (distance, 0, distance / 2)
    bone.keyframe_insert("location", frame=end)
    action = arm.animation_data.action
    action.name = name
    action.use_fake_user = True
    return action


def take_names(path):
    root, _version = parse_fbx.parse(path)
    objects = next(element for element in root.elems if element.id == b"Objects")
    return [element.props[1].decode("utf-8").split("\x00")[0]
            for element in objects.elems if element.id == b"AnimationStack"]


class FbxPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        humanoid_retarget.register()

    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.folder = tempfile.TemporaryDirectory(prefix="codex-fbx-test-")
        self.addCleanup(self.folder.cleanup)

    def path(self, name):
        return os.path.join(self.folder.name, name + ".fbx")

    def batch(self):
        arm = build_rig()
        old = animate(arm, "ObsoleteClip", distance=1.0)
        first = animate(arm, "BatchFirst", end=3)
        current = animate(arm, "BatchCurrent", end=5)
        arm["hr_actions"] = "\n".join([first.name, current.name])
        track = arm.animation_data.nla_tracks.new()
        track.strips.new(old.name, 1, old)
        arm.animation_data.use_nla = False
        return arm, first, current, track

    def test_missing_import_file_is_rejected_before_scene_changes(self):
        arm = build_rig()
        bpy.ops.object.mode_set(mode="EDIT")
        objects = set(bpy.data.objects)
        actions = set(bpy.data.actions)
        path = self.path("蓝色小肥鱼")
        with patch.object(pipeline, "_call_op") as importer:
            with self.assertRaises(pipeline.PipelineError) as caught:
                pipeline.import_model(path)
        importer.assert_not_called()
        self.assertIn(path, str(caught.exception))
        self.assertIn("重新选择", str(caught.exception))
        self.assertEqual(arm.mode, "EDIT")
        self.assertEqual(set(bpy.data.objects), objects)
        self.assertEqual(set(bpy.data.actions), actions)
        bpy.ops.object.mode_set(mode="OBJECT")

    def test_import_rejects_directories_for_all_model_formats(self):
        for ext in sorted(pipeline.SOURCE_EXTS | pipeline.TARGET_EXTS):
            with self.subTest(ext=ext):
                path = os.path.join(self.folder.name, "folder" + ext)
                os.mkdir(path)
                with patch.object(pipeline, "_call_op") as importer:
                    with self.assertRaises(pipeline.PipelineError):
                        pipeline.import_model(path)
                importer.assert_not_called()

    def test_import_operator_errors_are_reported_with_the_path(self):
        path = self.path("unreadable")
        pathlib.Path(path).write_bytes(b"invalid fbx")
        for error in (RuntimeError("import failed"), OSError("access denied")):
            with self.subTest(error=type(error).__name__):
                with patch.object(pipeline, "_call_op", side_effect=error):
                    with self.assertRaises(pipeline.PipelineError) as caught:
                        pipeline.import_model(path)
                self.assertIn(path, str(caught.exception))
                self.assertIs(caught.exception.__cause__, error)

    def test_cancelled_import_does_not_return_success(self):
        path = self.path("cancelled")
        pathlib.Path(path).write_bytes(b"invalid fbx")
        with patch.object(pipeline, "_call_op", return_value={"CANCELLED"}):
            with self.assertRaises(pipeline.PipelineError):
                pipeline.import_model(path)

    def test_missing_file_is_handled_by_both_import_buttons(self):
        arm, _first, _current, _track = self.batch()
        settings = bpy.context.scene.hr_settings
        settings.source = arm
        settings.target = arm
        settings.last_source_path = "saved_source.fbx"
        settings.last_target_path = "saved_target.fbx"
        actions = set(bpy.data.actions)
        objects = set(bpy.data.objects)
        for operator_type in (humanoid_retarget.HR_OT_import_source, humanoid_retarget.HR_OT_import_target):
            with self.subTest(operator=operator_type.__name__):
                reports = []
                operator = SimpleNamespace(filepath=self.path("蓝色小肥鱼"), automatic_bone_orientation=False,
                                           report=lambda level, message: reports.append((level, message)))
                result = operator_type.execute(operator, bpy.context)
                self.assertEqual(result, {"CANCELLED"})
                self.assertEqual(reports[-1][0], {"ERROR"})
                self.assertIn(operator.filepath, settings.status)
                self.assertEqual(settings.last_source_path, "saved_source.fbx")
                self.assertEqual(settings.last_target_path, "saved_target.fbx")
                self.assertIs(settings.source, arm)
                self.assertIs(settings.target, arm)
                self.assertEqual(set(bpy.data.objects), objects)
                self.assertEqual(set(bpy.data.actions), actions)

    def test_unicode_filename_roundtrip(self):
        arm = build_rig()
        animate(arm, "UnicodeClip")
        path = self.path("蓝色小肥鱼")
        pipeline.export_armature(arm, path, export_all_actions=False)
        objects, actions = pipeline.import_model(path)
        self.assertTrue(any(obj.type == "ARMATURE" for obj in objects))
        self.assertTrue(actions)

    def test_recalled_paths_keep_the_last_folder(self):
        missing = self.path("removed")
        self.assertEqual(pipeline.initial_filepath(missing), missing)
        self.assertEqual(pipeline.initial_filepath(self.folder.name), self.folder.name)
        self.assertEqual(pipeline.initial_filepath(os.path.join(self.folder.name, "missing", "file.fbx")), "")

    def test_batch_export_excludes_old_actions_and_starts_with_current(self):
        arm, first, current, _track = self.batch()
        path = self.path("batch")
        pipeline.export_armature(arm, path)
        names = take_names(path)
        self.assertEqual(len(names), 2, names)
        self.assertTrue(names[0].endswith(current.name), names)
        self.assertTrue(any(name.endswith(first.name) for name in names), names)
        self.assertIsNotNone(bpy.data.actions.get("ObsoleteClip"))

    def test_current_export_honors_false(self):
        arm, _first, current, _track = self.batch()
        path = self.path("current")
        pipeline.export_armature(arm, path, export_all_actions=False)
        names = take_names(path)
        self.assertEqual(len(names), 1, names)
        self.assertTrue(names[0].endswith(current.name), names)

    def test_stashed_batch_names_are_preserved(self):
        arm, first, current, _track = self.batch()
        strips = []
        for action in [first, current]:
            track = arm.animation_data.nla_tracks.new()
            strip = track.strips.new(action.name, 1, action)
            strips.append((strip, strip.name))
        path = self.path("stashed")
        pipeline.export_armature(arm, path)
        self.assertEqual(take_names(path), [current.name, first.name])
        for strip, name in strips:
            self.assertEqual(strip.name, name)

    def test_untracked_rig_exports_owned_actions_only(self):
        arm, first, current, track = self.batch()
        del arm["hr_actions"]
        old = track.strips[0].action
        track.strips[0].action = first
        path = self.path("owned")
        pipeline.export_armature(arm, path)
        names = take_names(path)
        self.assertEqual(len(names), 2, names)
        self.assertFalse(any(name.endswith(old.name) for name in names), names)
        self.assertTrue(any(name.endswith(current.name) for name in names), names)

    def test_active_derivative_is_included_without_obsolete_actions(self):
        arm, _first, _current, _track = self.batch()
        derivative = animate(arm, "CurrentSpring")
        path = self.path("derivative")
        pipeline.export_armature(arm, path)
        names = take_names(path)
        self.assertEqual(len(names), 3, names)
        self.assertTrue(names[0].endswith(derivative.name), names)
        self.assertFalse(any(name.endswith("ObsoleteClip") for name in names), names)

    def test_static_rig_exports_without_creating_animation_data(self):
        arm = build_rig()
        path = self.path("static")
        pipeline.export_armature(arm, path)
        self.assertEqual(take_names(path), [])
        self.assertIsNone(arm.animation_data)

    def test_stored_actions_work_without_existing_animation_data(self):
        arm = build_rig()
        action = animate(arm, "StoredClip")
        arm["hr_actions"] = action.name
        arm.animation_data_clear()
        path = self.path("stored")
        pipeline.export_armature(arm, path)
        self.assertEqual(len(take_names(path)), 1)
        self.assertIsNone(arm.animation_data)

    def test_missing_batch_action_fails_without_exporting_another_take(self):
        arm, _first, current, track = self.batch()
        arm["hr_actions"] = "MissingClip"
        with self.assertRaises(pipeline.PipelineError):
            pipeline.export_armature(arm, self.path("missing"))
        self.assertIs(arm.animation_data.action, current)
        self.assertEqual(list(arm.animation_data.nla_tracks), [track])

    def test_export_restores_state_after_success(self):
        arm, _first, current, track = self.batch()
        track.is_solo = True
        bpy.context.scene.frame_set(3, subframe=0.25)
        basis = arm.pose.bones["hips"].matrix_basis.copy()
        actions = set(bpy.data.actions)
        pipeline.export_armature(arm, self.path("success"))
        self.assertIs(arm.animation_data.action, current)
        self.assertFalse(arm.animation_data.use_nla)
        self.assertEqual(list(arm.animation_data.nla_tracks), [track])
        self.assertTrue(track.is_solo)
        self.assertEqual(set(bpy.data.actions), actions)
        self.assertEqual(arm.pose.bones["hips"].matrix_basis, basis)
        self.assertAlmostEqual(bpy.context.scene.frame_subframe, 0.25)

    def test_export_cleans_up_partial_track_creation(self):
        arm, _first, current, track = self.batch()
        assign = pipeline._assign_action
        calls = []

        def fail_second_assignment(obj, action):
            calls.append(action)
            if len(calls) == 2:
                raise RuntimeError("partial preparation")
            assign(obj, action)

        with patch.object(pipeline, "_assign_action", side_effect=fail_second_assignment):
            with self.assertRaisesRegex(RuntimeError, "partial preparation"):
                pipeline.export_armature(arm, self.path("partial"))
        self.assertIs(arm.animation_data.action, current)
        self.assertEqual(list(arm.animation_data.nla_tracks), [track])

    def test_export_failure_restores_bind_pose_and_strip_names(self):
        import io_scene_fbx.export_fbx_bin as export_bin
        arm, _first, current, track = self.batch()
        strip = track.strips[0]
        strip.name = "__hr_export_saved_0"
        original_writer = export_bin.fbx_data_object_elements
        bpy.context.scene.frame_set(3)
        with patch.object(export_bin, "fbx_data_object_elements", side_effect=RuntimeError("node failure")):
            with self.assertRaises(RuntimeError):
                pipeline.export_armature(arm, self.path("node_failure"))
        self.assertEqual(arm.data.pose_position, "POSE")
        self.assertIs(arm.animation_data.action, current)
        self.assertEqual(list(arm.animation_data.nla_tracks), [track])
        self.assertEqual(strip.name, "__hr_export_saved_0")
        self.assertFalse(strip.mute)
        self.assertEqual(bpy.context.scene.frame_current, 3)
        self.assertIs(export_bin.fbx_data_object_elements, original_writer)

    def test_saved_strip_names_do_not_conflict_during_restore(self):
        arm, first, _current, track = self.batch()
        track.strips[0].name = "__hr_saved_strip.001"
        other = arm.animation_data.nla_tracks.new()
        other.strips.new("OrdinaryStrip", 1, first)
        names = [strip.name for track in arm.animation_data.nla_tracks for strip in track.strips]
        pipeline.export_armature(arm, self.path("saved_names"))
        restored = [strip.name for track in arm.animation_data.nla_tracks for strip in track.strips]
        self.assertEqual(restored, names)

    def test_fractional_action_range_is_preserved(self):
        arm = build_rig()
        bone = arm.pose.bones["hips"]
        bone.location = (0, 0, 0)
        bone.keyframe_insert("location", frame=-1.5)
        bone.location = (0.2, 0, 0)
        bone.keyframe_insert("location", frame=3.5)
        path = self.path("fractional")
        pipeline.export_armature(arm, path, export_all_actions=False)
        root, _version = parse_fbx.parse(path)
        objects = next(element for element in root.elems if element.id == b"Objects")
        stack = next(element for element in objects.elems if element.id == b"AnimationStack")
        props = next(element for element in stack.elems if element.id == b"Properties70")
        values = {element.props[0]: element.props[-1] for element in props.elems}
        from io_scene_fbx.fbx_utils import FBX_KTIME
        duration = (values[b"LocalStop"] - values.get(b"LocalStart", 0)) / FBX_KTIME
        fps = bpy.context.scene.render.fps / bpy.context.scene.render.fps_base
        self.assertAlmostEqual(duration * fps, 5.0, places=5)

    def test_export_restores_animation_state_after_failure(self):
        arm, _first, current, track = self.batch()
        track.mute = False
        track.is_solo = True
        bpy.context.scene.frame_set(3, subframe=0.25)
        original_slot = arm.animation_data.action_slot
        original_basis = arm.pose.bones["hips"].matrix_basis.copy()
        with patch.object(pipeline, "_call_op", side_effect=RuntimeError("export failed")):
            with self.assertRaisesRegex(RuntimeError, "export failed"):
                pipeline.export_armature(arm, self.path("failure"))
        self.assertEqual(len(arm.animation_data.nla_tracks), 1)
        self.assertIs(arm.animation_data.action, current)
        self.assertEqual(arm.animation_data.action_slot, original_slot)
        self.assertFalse(arm.animation_data.use_nla)
        self.assertFalse(track.mute)
        self.assertTrue(track.is_solo)
        self.assertEqual(bpy.context.scene.frame_current, 3)
        self.assertAlmostEqual(bpy.context.scene.frame_subframe, 0.25)
        self.assertEqual(arm.pose.bones["hips"].matrix_basis, original_basis)

    def test_import_preserves_animated_translation(self):
        self.check_translation_roundtrip("hips")

    def test_import_handles_escaped_bone_names(self):
        self.check_translation_roundtrip('hip"joint')

    def test_small_baked_motion_is_not_simplified_away(self):
        arm = build_rig()
        bone = arm.pose.bones["hips"]
        expected = {}
        for frame, value in [(1, 0.1), (2, 0.10002), (3, 0.1)]:
            bone.location = (value, 0, 0)
            bone.keyframe_insert("location", frame=frame)
            bpy.context.scene.frame_set(frame)
            expected[frame] = bone.matrix.translation.copy()
        path = self.path("small_motion")
        pipeline.export_armature(arm, path, export_all_actions=False)
        objects, _actions = pipeline.import_model(path)
        imported = next(obj for obj in objects if obj.type == "ARMATURE")
        for frame, position in expected.items():
            bpy.context.scene.frame_set(frame)
            actual = imported.pose.bones["hips"].matrix.translation
            self.assertLess((actual - position).length, 1e-6)

    def check_translation_roundtrip(self, hips_name):
        arm = build_rig(hips_name=hips_name)
        animate(arm, "MovingHips", hips_name=hips_name)
        scene = bpy.context.scene
        scene.frame_start = 1
        scene.frame_end = 5
        expected = {}
        for frame in range(1, 6):
            scene.frame_set(frame)
            expected[frame] = arm.pose.bones[hips_name].matrix.translation.copy()
        scene.frame_set(1)
        path = self.path("translation")
        bpy.ops.export_scene.fbx(filepath=path, use_selection=True,
                                 object_types={"ARMATURE", "MESH"}, add_leaf_bones=False,
                                 bake_anim_use_all_actions=False, bake_anim_use_nla_strips=False)
        objects, _actions = pipeline.import_model(path)
        imported = next(obj for obj in objects if obj.type == "ARMATURE")
        self.assertFalse(imported.data.bones[hips_name].use_connect)
        self.assertTrue(imported.data.bones["tip"].use_connect)
        for frame, position in expected.items():
            scene.frame_set(frame + 1)
            actual = imported.pose.bones[hips_name].matrix.translation
            self.assertLess((actual - position).length, 1e-5)

    def test_export_file_operator_preserves_current_only_choice(self):
        arm, _first, _current, _track = self.batch()
        settings = bpy.context.scene.hr_settings
        settings.target = arm
        settings.export_format = "FBX"
        with patch.object(humanoid_retarget, "export_apose_animations") as export:
            result = bpy.ops.hr.export_result_file(filepath=self.path("operator"),
                                                   export_all_actions=False, fbx_pose="ANIMATED")
        self.assertEqual(result, {"FINISHED"})
        self.assertFalse(export.call_args.kwargs["export_all_actions"])


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(FbxPipelineTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print(f"FBX_PIPELINE_SELECTED {result.testsRun}")
    sys.exit(0 if result.wasSuccessful() and result.testsRun > 0 else 1)
