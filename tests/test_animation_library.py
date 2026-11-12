from pathlib import Path
import tempfile

import bpy

from character_control_fixtures import CharacterTestCase, make_rig
from character_locomotion import animation_library as library


class LibraryTests(CharacterTestCase):
    def test_self_contained_roundtrip_and_deduplication(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "motions.blend")
            library.save_library(self.rig, self.scene, path)
            other = make_rig("Receiver")
            library.load_library(other, self.scene, path)
            self.assertEqual(len(other.cl_clips), 3)
            count = (len(bpy.data.objects), len(bpy.data.armatures), len(bpy.data.actions))
            library.load_library(other, self.scene, path)
            self.assertEqual((len(bpy.data.objects), len(bpy.data.armatures), len(bpy.data.actions)), count)
            for clip in other.cl_clips:
                library.validate_clip(clip, other, self.scene)

    def test_same_id_conflict_rolls_back(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "motions.blend")
            library.save_library(self.rig, self.scene, path)
            before = self.rig.cl_settings.walk_id
            self.clips["WALK"].speed = 99
            count = len(bpy.data.actions)
            with self.assertRaises(ValueError):
                library.load_library(self.rig, self.scene, path)
            self.assertEqual(len(self.rig.cl_clips), 3)
            self.assertEqual(self.rig.cl_settings.walk_id, before)
            self.assertEqual(len(bpy.data.actions), count)

    def test_bone_length_mismatch_browse_but_no_play(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "motions.blend")
            library.save_library(self.rig, self.scene, path)
            other = make_rig("OtherSkeleton")
            bpy.ops.object.mode_set(mode="EDIT")
            other.data.edit_bones["Limb"].tail.z = 3
            bpy.ops.object.mode_set(mode="OBJECT")
            library.load_library(other, self.scene, path)
            self.assertEqual(len(other.cl_clips), 3)
            self.assertEqual(other.cl_settings.walk_id, "UNSET")
            with self.assertRaises(ValueError):
                library.validate_clip(other.cl_clips[0], other, self.scene)

    def test_root_excursion_rejected_even_if_endpoints_equal(self):
        self.rig.animation_data.action = self.clips["WALK"].action
        root = self.rig.pose.bones["Root"]
        for frame, x in ((1, 0), (11, 5), (21, 0)):
            root.location.x = x
            root.keyframe_insert("location", frame=frame)
        with self.assertRaises(ValueError):
            library.validate_clip(self.clips["WALK"], self.rig, self.scene)

    def test_cleared_binding_not_automatically_replaced(self):
        self.rig.cl_settings.walk_id = ""
        library.autofill(self.rig)
        self.assertEqual(self.rig.cl_settings.walk_id, "")

    def test_unconfirmed_timing_and_ambiguous_slots_rejected(self):
        clip = self.clips["WALK"]
        clip.confirmed = False
        with self.assertRaises(ValueError):
            library.validate_clip(clip, self.rig, self.scene)
        clip.action.slots.new("OBJECT", "Another")
        with self.assertRaises(ValueError):
            library.add_clip(self.rig, self.scene, clip.action, "WALK")

    def test_root_vertical_motion_uses_rest_bone_axes(self):
        self.rig.animation_data.action = self.clips["WALK"].action
        root = self.rig.pose.bones["Root"]
        for frame, value in ((1, 0), (11, 0.5), (21, 0)):
            root.location.y = value
            root.keyframe_insert("location", frame=frame)
        library.validate_clip(self.clips["WALK"], self.rig, self.scene)

    def test_root_local_z_horizontal_motion_rejected(self):
        self.rig.animation_data.action = self.clips["WALK"].action
        root = self.rig.pose.bones["Root"]
        for frame, value in ((1, 0), (11, 0.5), (21, 0)):
            root.location.z = value
            root.keyframe_insert("location", frame=frame)
        with self.assertRaises(ValueError):
            library.validate_clip(self.clips["WALK"], self.rig, self.scene)
