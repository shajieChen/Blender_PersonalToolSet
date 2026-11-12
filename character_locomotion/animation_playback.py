import bpy

from .animation_library import action_curves


def pose_channels(bone):
    rotation = "rotation_quaternion" if bone.rotation_mode == "QUATERNION" else "rotation_axis_angle" if bone.rotation_mode == "AXIS_ANGLE" else "rotation_euler"
    return ("location", rotation, "scale")


class CharacterPlayback:
    def __init__(self, rig, scene, view_layer, clips, blend=0.15):
        self.rig = rig
        self.scene = scene
        self.view_layer = view_layer
        self.clips = clips
        self.blend = blend
        self.had_animation = rig.animation_data is not None
        self.animation = rig.animation_data_create()
        self.original_action = self.animation.action
        self.original_slot = self.animation.action_slot
        self.original_use_nla = self.animation.use_nla
        self.original_tracks = [(track, track.mute, track.is_solo) for track in self.animation.nla_tracks]
        self.pose = [(bone, {channel: tuple(getattr(bone, channel)) for channel in pose_channels(bone)}) for bone in rig.pose.bones]
        self.created_tracks = []
        self.created_actions = []
        self.prepared = {}
        self.state = None
        self.phase = 0.0
        self.elapsed_blend = 0.0
        self.closed = False
        try:
            self.animation.action = None
            self.animation.use_nla = True
            for track, mute, solo in self.original_tracks:
                track.mute = True
                track.is_solo = False
            for state, clip in clips.items():
                copied = clip.action.copy()
                self.created_actions.append(copied)
                curves, slot = action_curves(copied, clip.slot_id)
                self.animation.action = copied
                if slot:
                    self.animation.action_slot = slot
                existing = {(curve.data_path, curve.array_index) for curve in curves}
                for bone, channels in self.pose:
                    for channel, values in channels.items():
                        setattr(bone, channel, values)
                        for index in range(len(values)):
                            if (bone.path_from_id(channel), index) not in existing:
                                bone.keyframe_insert(channel, index=index, frame=clip.start)
                self.prepared[state] = (copied, self.animation.action_slot)
            self.animation.action = None
            self.source = self._new_strip(self._snapshot(self.pose), None)
            first = next(iter(clips))
            self.target = self._new_strip(*self.prepared[first])
            self._weight(self.target, 0.0)
        except Exception:
            self.close()
            raise

    def _new_strip(self, action, slot):
        track = self.animation.nla_tracks.new()
        self.created_tracks.append(track)
        track.name = "Character preview"
        strip = track.strips.new("Character preview", self.scene.frame_current - 1, action)
        if slot:
            strip.action_slot = slot
        strip.frame_start = self.scene.frame_current - 1
        strip.frame_end = self.scene.frame_current + 1
        strip.use_animated_time = True
        strip.use_animated_time_cyclic = False
        strip.strip_time = 1.0
        strip.blend_type = "REPLACE"
        strip.blend_in = 0.0
        strip.blend_out = 0.0
        strip.extrapolation = "NOTHING"
        self._weight(strip, 1.0)
        return strip

    def _weight(self, strip, value):
        strip.use_animated_influence = True
        curve = strip.fcurves.find("influence")
        if curve is None or not curve.keyframe_points:
            strip.influence = value
            strip.keyframe_insert("influence", frame=self.scene.frame_current)
            curve = strip.fcurves.find("influence")
        for point in curve.keyframe_points:
            point.co.y = value
            point.handle_left.y = value
            point.handle_right.y = value
        curve.update()
        strip.influence = value

    def _snapshot(self, pose):
        action = bpy.data.actions.new("Character transition pose")
        self.created_actions.append(action)
        self.animation.action = action
        muted = [(track, track.mute) for track in self.created_tracks]
        try:
            for track, mute in muted:
                track.mute = True
            for bone, channels in pose:
                for channel, values in channels.items():
                    setattr(bone, channel, values)
                    bone.keyframe_insert(channel, frame=1.0)
        finally:
            self.animation.action = None
            for track, mute in muted:
                track.mute = mute
        return action

    def _capture(self):
        self.rig.update_tag(refresh={"TIME", "OBJECT", "DATA"})
        self.view_layer.update()
        evaluated = self.rig.evaluated_get(bpy.context.evaluated_depsgraph_get())
        return [(bone, {channel: tuple(getattr(evaluated.pose.bones[bone.name], channel)) for channel in pose_channels(bone)}) for bone in self.rig.pose.bones]

    def _switch(self, state):
        pose = self._capture()
        old_snapshot = self.source.action
        snapshot = self._snapshot(pose)
        self.source.action = snapshot
        self.source.action_slot = snapshot.slots[0]
        self.source.strip_time = 1.0
        if old_snapshot in self.created_actions:
            self.created_actions.remove(old_snapshot)
            bpy.data.actions.remove(old_snapshot)
        action, slot = self.prepared[state]
        self.target.action = action
        if slot:
            self.target.action_slot = slot
        clip = self.clips[state]
        self.target.action_frame_start = clip.start
        self.target.action_frame_end = clip.end
        if self.state is None or self.state == "IDLE" or state == "IDLE":
            self.phase = 0.0
        self.state = state
        self.elapsed_blend = 0.0
        self._weight(self.target, 0.0)

    def update(self, state, dt, speed=0.0):
        if state != self.state:
            self._switch(state)
        clip = self.clips[state]
        rate = speed / clip.speed if state in {"WALK", "RUN"} else 1.0
        phase = self.phase + dt * clip.fps * rate / clip.period
        self.phase = phase % 1.0 if clip.loop else min(1.0, phase)
        self.target.strip_time = min(clip.end, clip.start + self.phase * clip.period)
        self.elapsed_blend += dt
        self._weight(self.target, min(1.0, self.elapsed_blend / self.blend) if self.blend else 1.0)
        self.rig.update_tag(refresh={"TIME", "OBJECT", "DATA"})

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            for track in self.created_tracks:
                try:
                    self.animation.nla_tracks.remove(track)
                except (ReferenceError, RuntimeError):
                    pass
            self.animation.action = None
            try:
                self.animation.action = self.original_action
                if self.original_action and self.original_slot:
                    self.animation.action_slot = self.original_slot
            except ReferenceError:
                pass
            self.animation.use_nla = self.original_use_nla
            for track, mute, solo in self.original_tracks:
                try:
                    track.mute = mute
                    track.is_solo = solo
                except ReferenceError:
                    pass
            for bone, channels in self.pose:
                try:
                    for channel, values in channels.items():
                        setattr(bone, channel, values)
                except ReferenceError:
                    pass
            if not self.had_animation:
                self.rig.animation_data_clear()
            self.rig.update_tag(refresh={"TIME", "OBJECT", "DATA"})
        except ReferenceError:
            pass
        finally:
            for action in self.created_actions:
                try:
                    bpy.data.actions.remove(action)
                except ReferenceError:
                    pass
            self.created_actions.clear()
