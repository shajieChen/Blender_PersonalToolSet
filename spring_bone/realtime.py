import math
import time

import bpy
from mathutils import Matrix

from .animation import SampleTick, _ChainRuntime, _rest_token, _warmup_ticks, align_quaternion_key_signs, colliders_for_tick, initialize_runtime, order_runtimes, solve_runtime, specs_from_settings
from .contact_bake import _action_token
from .solver import FIXED_DT, FOLLOW_TRANSLATION, SpringBoneError, matrix_has_supported_scale, validate_parameters
from .targets import target_armature


MAX_UPDATE_STEPS = 16
SOURCE_CHECK_SECONDS = .5


def _matrix_between(first, second, amount):
    first_location, first_rotation, first_scale = first.decompose()
    second_location, second_rotation, second_scale = second.decompose()
    return Matrix.LocRotScale(first_location.lerp(second_location, amount), first_rotation.slerp(second_rotation, amount), first_scale.lerp(second_scale, amount))


def _tick_between(first, second, amount):
    return SampleTick(first.frame + (second.frame - first.frame) * amount, _matrix_between(first.armature_world, second.armature_world, amount), {name: _matrix_between(first.poses[name], second.poses[name], amount) for name in second.poses}, {name: first.lengths[name] + (length - first.lengths[name]) * amount for name, length in second.lengths.items()})


class RealtimeSpringPreview:
    is_realtime = True
    progress = 0.0
    phase = "实时预览"
    delivered = False

    def __init__(self, armature):
        self.armature = armature
        self.scene = bpy.context.scene
        self.finished = False
        self.sampler = None
        self.input_action = None
        self.captured = False
        self.busy = False
        self.accumulator = 0.0
        self.tick_count = 0
        self.diagnostics_enabled = False
        self.last_solved = []
        self.last_tick = None
        self.last_wall_time = time.perf_counter()
        self.next_source_check = self.last_wall_time + SOURCE_CHECK_SECONDS
        try:
            self._prepare()
            self.frame_update(self.scene)
        except Exception:
            self.cancel()
            raise

    def _source_action(self, action):
        visited = set()
        while action.get("sb_generated"):
            if action in visited:
                raise SpringBoneError("无法确定基础动作，请先选择原始动作")
            visited.add(action)
            source = bpy.data.actions.get(action.get("sb_contact_input", "")) or self.armature.sb_settings.source_action
            if source is None or source == action:
                raise SpringBoneError("请先选择原始基础动作，再开启实时预览")
            action = source
        return action

    def _prepare(self):
        armature = self.armature
        anim = armature.animation_data
        if armature.type != "ARMATURE" or armature.mode == "EDIT" or armature.library or armature.data.library or anim is None or anim.action is None:
            raise SpringBoneError("实时预览需要可编辑的骨架和基础动作")
        if anim.use_nla and any(track.strips and not track.mute for track in anim.nla_tracks):
            raise SpringBoneError("请关闭NLA后开启实时预览")
        if anim.drivers or armature.constraints or any(pose.constraints for pose in armature.pose.bones):
            raise SpringBoneError("实时预览需要先烘焙骨架约束和驱动")
        if anim.action_blend_type != "REPLACE" or abs(anim.action_influence - 1.0) > 1e-6 or self.scene.is_nla_tweakmode or armature.data.pose_position != "POSE":
            raise SpringBoneError("实时预览需要完整替换的姿态动作")
        self.source_action = self._source_action(anim.action)
        if len(self.source_action.slots) != 1 or len(self.source_action.layers) != 1 or len(self.source_action.layers[0].strips) != 1:
            raise SpringBoneError("实时预览需要单槽单层动作")
        self.chains, self.colliders = specs_from_settings(armature.sb_settings)
        self._validate_specs()
        self.topology = self._topology()
        self.names = tuple(name for spec in self.chains for name in spec.bone_names)
        self.entry_action, self.entry_slot = anim.action, anim.action_slot
        self.entry_poses = [(pose.name, pose.rotation_mode, pose.matrix_basis.copy()) for pose in armature.pose.bones]
        self.entry_modes = {name: armature.pose.bones[name].rotation_mode for name in self.names}
        self.scale_length = float(self.scene.unit_settings.scale_length)
        if not math.isfinite(self.scale_length) or self.scale_length <= 0.0:
            raise SpringBoneError("场景单位比例无效")
        self.clock = (self.scene.render.fps, self.scene.render.fps_base, self.scale_length)
        self.evaluation = (anim.use_nla, anim.action_blend_type, anim.action_influence)
        self.rest_value = _rest_token(armature)
        self.source_value = _action_token(self.source_action, self.source_action.slots[0])
        self.captured = True
        self.input_action = self.source_action.copy()
        self.input_action.name = self.source_action.name + "_RealtimeInput"
        self.input_action.use_fake_user = False
        align_quaternion_key_signs(self.input_action, self.input_action.slots[0], self.names)
        self.input_value = _action_token(self.input_action, self.input_action.slots[0])
        self.sampler = armature.copy()
        self.sampler.name = armature.name + "_RealtimeSource"
        self.sampler.animation_data_clear()
        self.sampler.animation_data_create().action = self.input_action
        self.sampler.animation_data.action_slot = self.input_action.slots[0]
        self.sampler.animation_data.use_nla = False
        self.scene.collection.objects.link(self.sampler)
        self.sampler.hide_render = True
        self.sampler.hide_select = True
        self.sampler.hide_set(True)
        if self.source_action != self.entry_action:
            for name in self.names:
                self.sampler.pose.bones[name].matrix_basis = Matrix.Identity(4)
        anim.action = self.input_action
        anim.action_slot = self.input_action.slots[0]
        bpy.context.view_layer.update()
        self.runtimes = order_runtimes([_ChainRuntime(spec, 0) for spec in self.chains], armature)

    def _topology(self):
        return tuple((spec.bone_names, spec.inertia_space, spec.ancestor_name) for spec in self.chains), tuple((spec.shape, spec.bone_name) for spec in self.colliders)

    def _validate_specs(self):
        names = [name for spec in self.chains for name in spec.bone_names]
        if not self.chains or not names or len(names) != len(set(names)):
            raise SpringBoneError("请配置不重复的连续动态骨骼链")
        for spec in self.chains:
            validate_parameters(spec.parameters)
            if any(not math.isfinite(value) for value in spec.parameters.gravity_dir) or not math.isfinite(spec.parameters.gravity_dir.length):
                raise SpringBoneError("重力方向不是有限数")
            _warmup_ticks(spec.warmup_seconds)
            bones = [self.armature.data.bones.get(name) for name in spec.bone_names]
            if not bones or any(bone is None or bone.length <= 1e-8 for bone in bones):
                raise SpringBoneError("动态链包含无效骨骼")
            if any(child.parent != parent for parent, child in zip(bones, bones[1:])):
                raise SpringBoneError("动态链必须父子连续")
            for bone in bones:
                pose = self.armature.pose.bones[bone.name]
                if bone.inherit_scale != "FULL" or not bone.use_inherit_rotation or bone.bbone_segments != 1 or pose.rotation_mode == "AXIS_ANGLE" or any(pose.lock_rotation) or pose.lock_rotation_w:
                    raise SpringBoneError(f"{bone.name} 的继承、旋转或锁定不支持实时预览")
            if spec.inertia_space == FOLLOW_TRANSLATION and spec.ancestor_name not in {bone.name for bone in bones[0].parent_recursive}:
                raise SpringBoneError("跟随平移需要有效的非模拟祖先")
        for collider in self.colliders:
            bone = self.armature.data.bones.get(collider.bone_name)
            if bone is None or bone.name in names or any(parent.name in names for parent in bone.parent_recursive):
                raise SpringBoneError("碰撞骨不能依赖动态链")
            if collider.shape not in {"SPHERE", "CAPSULE"} or not math.isfinite(collider.radius_m) or collider.radius_m < 0.0:
                raise SpringBoneError("碰撞体参数无效")
            if any(not math.isfinite(value) for value in (*collider.head_offset_m, *collider.tail_offset_m)):
                raise SpringBoneError("碰撞体偏移不是有限数")

    def _guard(self):
        armature = self.armature
        try:
            alive = bpy.data.objects.get(armature.name) == armature and self.scene.objects.get(armature.name) == armature
        except ReferenceError:
            alive = False
        if not alive or bpy.context.scene != self.scene or target_armature(bpy.context) != armature:
            raise SpringBoneError("实时预览目标已变化")
        anim = armature.animation_data
        if anim is None or anim.action != self.input_action or anim.action_slot != self.input_action.slots[0]:
            raise SpringBoneError("活动动作已切换，已停止实时预览")
        if armature.mode == "EDIT" or (anim.use_nla, anim.action_blend_type, anim.action_influence) != self.evaluation:
            raise SpringBoneError("骨架或动画求值状态已变化")
        if anim.drivers or armature.constraints or any(pose.constraints for pose in armature.pose.bones):
            raise SpringBoneError("约束或驱动已变化，请停止实时预览")
        if any(armature.pose.bones.get(name) is None or armature.pose.bones[name].rotation_mode != mode for name, mode in self.entry_modes.items()):
            raise SpringBoneError("动态骨或旋转模式已变化")
        if (self.scene.render.fps, self.scene.render.fps_base, self.scene.unit_settings.scale_length) != self.clock:
            raise SpringBoneError("帧率或场景单位已变化，请重新开启实时预览")
        self.chains, self.colliders = specs_from_settings(armature.sb_settings)
        self._validate_specs()
        if self._topology() != self.topology:
            raise SpringBoneError("链或碰撞绑定已变化，请重新开启实时预览")
        by_names = {spec.bone_names: spec for spec in self.chains}
        for runtime in self.runtimes:
            runtime.spec = by_names[runtime.spec.bone_names]
        now = time.perf_counter()
        if now >= self.next_source_check:
            if _rest_token(armature) != self.rest_value or _action_token(self.source_action, self.source_action.slots[0]) != self.source_value or _action_token(self.input_action, self.input_action.slots[0]) != self.input_value:
                raise SpringBoneError("基础动作或静态骨架已编辑，请重新开启实时预览")
            self.next_source_check = now + SOURCE_CHECK_SECONDS

    def _sample(self, depsgraph=None):
        if not matrix_has_supported_scale(self.armature.matrix_world):
            raise SpringBoneError("骨架对象需要统一正缩放")
        evaluated = self.sampler.evaluated_get(depsgraph or bpy.context.evaluated_depsgraph_get())
        needed = set(self.names)
        for spec in self.chains:
            root = self.armature.data.bones[spec.bone_names[0]]
            if root.parent:
                needed.add(root.parent.name)
            if spec.ancestor_name:
                needed.add(spec.ancestor_name)
        needed.update(spec.bone_name for spec in self.colliders)
        poses, lengths = {}, {}
        self.base_bases = {}
        world = self.armature.matrix_world.copy()
        for name in needed:
            pose = evaluated.pose.bones[name]
            if any(not math.isfinite(value) for row in pose.matrix for value in row):
                raise SpringBoneError(f"{name} 的基础姿势不是有限数")
            poses[name] = pose.matrix.copy()
            linear = pose.matrix.to_3x3()
            columns = [linear.col[index].copy() for index in range(3)]
            lengths_scale = [column.length for column in columns]
            if min(lengths_scale) <= 1e-8 or max(lengths_scale) - min(lengths_scale) > max(lengths_scale) * 1e-4 or linear.determinant() <= 0.0 or any(abs(columns[first].normalized().dot(columns[second].normalized())) > 1e-4 for first, second in ((0, 1), (0, 2), (1, 2))):
                raise SpringBoneError(f"{name} 包含不支持的非统一缩放或剪切")
            if name in self.names:
                scale = pose.scale
                if min(scale) <= 0.0 or max(scale) - min(scale) > max(scale) * 1e-4:
                    raise SpringBoneError(f"{name} 的缩放不支持实时预览")
                lengths[name] = ((world @ pose.tail) - (world @ pose.head)).length * self.scale_length
                if not math.isfinite(lengths[name]) or lengths[name] <= 1e-8:
                    raise SpringBoneError(f"{name} 的骨长无效")
                self.base_bases[name] = pose.matrix_basis.copy()
        return SampleTick(self.scene.frame_current + self.scene.frame_subframe, world, poses, lengths)

    def _solve(self, tick, runtimes=None):
        solved_poses, solved = {}, []
        colliders = colliders_for_tick(self.colliders, tick, self.scale_length)
        for runtime in self.runtimes if runtimes is None else runtimes:
            for state, name in zip(runtime.states, runtime.spec.bone_names):
                state.length_m = tick.lengths[name]
            values, rotations = solve_runtime(runtime, self.armature, tick, self.scale_length, solved_poses, colliders)
            solved.extend(values)
        self.last_solved = solved
        if self.diagnostics_enabled:
            self.tick_count += 1

    def _reset(self, tick):
        self.accumulator = 0.0
        for runtime in self.runtimes:
            initialize_runtime(runtime, self.armature, tick, self.scale_length, tick.lengths)
        warmups = {id(runtime): _warmup_ticks(runtime.spec.warmup_seconds) for runtime in self.runtimes}
        for index in range(max(warmups.values(), default=0)):
            self._solve(tick, [runtime for runtime in self.runtimes if index < warmups[id(runtime)]])
        self._solve(tick)

    def _advance(self, tick, seconds):
        previous_remainder = self.accumulator
        self.accumulator += seconds
        steps = min(MAX_UPDATE_STEPS, int((self.accumulator + 1e-10) / FIXED_DT))
        for index in range(steps):
            amount = min(1.0, max(0.0, ((index + 1.) * FIXED_DT - previous_remainder) / max(seconds, 1e-12)))
            interpolated = _tick_between(self.last_tick, tick, amount)
            self._solve(interpolated)
        self.accumulator -= steps * FIXED_DT

    def _apply(self):
        for item in self.last_solved:
            pose = self.armature.pose.bones[item.name]
            bone = pose.bone
            parent_rest = bone.parent.matrix_local if bone.parent else Matrix.Identity(4)
            basis = bone.convert_local_to_pose(item.object_matrix, bone.matrix_local, parent_matrix=item.parent_matrix, parent_matrix_local=parent_rest, invert=True)
            rotation = basis.to_quaternion().normalized()
            pose.matrix_basis = self.base_bases[item.name]
            if pose.rotation_mode == "QUATERNION":
                pose.rotation_quaternion = rotation
            else:
                pose.rotation_euler = rotation.to_euler(pose.rotation_mode, pose.rotation_euler)
        self.armature.update_tag(refresh={"OBJECT"})

    def frame_update(self, scene, depsgraph=None):
        if self.finished or self.busy or scene != self.scene:
            return
        self.busy = True
        try:
            self._guard()
            tick = self._sample(depsgraph)
            delta = 0.0 if self.last_tick is None else (tick.frame - self.last_tick.frame) * self.clock[1] / self.clock[0]
            if self.last_tick is None or delta < 0.0 or delta > MAX_UPDATE_STEPS * FIXED_DT:
                self._reset(tick)
            elif delta > 0.0:
                self._advance(tick, delta)
            self.last_tick = tick
            self._apply()
            self.last_wall_time = time.perf_counter()
        finally:
            self.busy = False

    def update_paused(self, seconds):
        if self.finished or self.busy:
            return
        self.busy = True
        try:
            self._guard()
            bpy.context.view_layer.update()
            tick = self._sample()
            if self.last_tick is None or tick.frame != self.last_tick.frame:
                self._reset(tick)
            else:
                self._advance(tick, min(max(seconds, 0.0), MAX_UPDATE_STEPS * FIXED_DT))
            self.last_tick = tick
            self._apply()
        finally:
            self.busy = False

    def run_slice(self):
        now = time.perf_counter()
        self.update_paused(now - self.last_wall_time)
        self.last_wall_time = now

    def preview_still_valid(self):
        return False

    def cancel(self):
        if self.finished:
            return
        self.finished = True
        try:
            if self.captured:
                anim = self.armature.animation_data
                if anim is not None and anim.action == self.input_action:
                    if self.armature.mode != "EDIT":
                        for name, mode, basis in self.entry_poses:
                            pose = self.armature.pose.bones.get(name)
                            if pose is not None and pose.rotation_mode == mode:
                                pose.matrix_basis = basis
                    anim.action, anim.action_slot = self.entry_action, self.entry_slot
                    self.scene.frame_set(self.scene.frame_current, subframe=self.scene.frame_subframe)
        except ReferenceError:
            pass
        finally:
            if self.sampler is not None:
                try:
                    bpy.data.objects.remove(self.sampler, do_unlink=True)
                except ReferenceError:
                    pass
                self.sampler = None
            if self.input_action is not None:
                try:
                    bpy.data.actions.remove(self.input_action, do_unlink=True)
                except ReferenceError:
                    pass
                self.input_action = None
