import bpy

from character_control_fixtures import CharacterTestCase
from character_locomotion.animation_playback import CharacterPlayback


class PlaybackTests(CharacterTestCase):
    def player(self, blend=0.15):
        return CharacterPlayback(self.rig, self.scene, bpy.context.view_layer, self.clips, blend)

    def test_actual_bones_and_static_scene_time(self):
        player = self.player(0)
        try:
            for state, value in (("IDLE", 1), ("WALK", 5), ("RUN", 10)):
                player.update(state, 0, self.clips[state].speed)
                self.assertAlmostEqual(self.pose_height(), value, places=4)
                self.assertEqual(self.scene.frame_current, 1)
        finally:
            player.close()

    def test_actual_animation_time(self):
        player = self.player(0)
        try:
            clip = self.clips["WALK"]
            player.update("WALK", 10 / clip.fps, clip.speed)
            self.assertAlmostEqual(self.pose_height(), 6, places=4)
        finally:
            player.close()

    def test_transition_midpoint_and_rapid_switch(self):
        for clip in self.clips.values():
            curves, slot = __import__("character_locomotion.animation_library", fromlist=["action_curves"]).action_curves(clip.action, clip.slot_id)
            for curve in curves:
                value = curve.keyframe_points[0].co.y
                for key in curve.keyframe_points:
                    key.co.y = value
                    key.handle_left.y = value
                    key.handle_right.y = value
        player = self.player(0.2)
        baseline = len(bpy.data.actions)
        try:
            player.update("IDLE", 0.2)
            self.assertAlmostEqual(self.pose_height(), 1, places=4)
            player.update("WALK", 0, 1.5)
            self.assertAlmostEqual(self.pose_height(), 1, places=4)
            player.update("WALK", 0.1, 1.5)
            middle = self.pose_height()
            self.assertAlmostEqual(middle, 3, places=3)
            player.update("RUN", 0, 4)
            self.assertAlmostEqual(self.pose_height(), middle, places=3)
            for index in range(30):
                player.update("WALK" if index % 2 else "RUN", 0.01, 2)
                self.pose_height()
            self.assertEqual(len(self.rig.animation_data.nla_tracks), 2)
            self.assertEqual(len(bpy.data.actions), baseline)
        finally:
            player.close()

    def test_restore_twenty_cycles(self):
        animation = self.rig.animation_data
        original = animation.action
        slot = animation.action_slot
        track = animation.nla_tracks.new()
        track.is_solo = True
        count = len(bpy.data.actions)
        for index in range(20):
            player = self.player()
            player.update("RUN", 0.05, 4)
            self.pose_height()
            player.close()
            player.close()
            self.assertEqual(animation.action, original)
            self.assertEqual(animation.action_slot, slot)
            self.assertTrue(track.is_solo)
            self.assertEqual(len(animation.nla_tracks), 1)
            self.assertEqual(len(bpy.data.actions), count)

    def test_deleted_original_action_still_restores_tracks(self):
        track = self.rig.animation_data.nla_tracks.new()
        track.is_solo = True
        original = self.rig.animation_data.action
        player = self.player()
        bpy.data.actions.remove(original)
        player.close()
        self.assertTrue(track.is_solo)
        self.assertFalse(track.mute)
        self.assertEqual(len(self.rig.animation_data.nla_tracks), 1)
