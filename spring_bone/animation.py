import time
from dataclasses import dataclass

import bpy
from mathutils import Euler, Matrix, Quaternion, Vector

from .solver import (
    FIXED_HZ,
    FOLLOW_TRANSLATION,
    WORLD,
    CapsuleCollider,
    ChainParameters,
    SegmentSample,
    SegmentState,
    SphereCollider,
    SpringBoneError,
    direction_or_fallback,
    frame_for_tick,
    included_tick_count,
    matrix_has_supported_scale,
    reference_pose,
    signed_collider_distance,
    step_chain,
    validate_parameters,
)

_AXIS_Y = Vector((0.0, 1.0, 0.0))
_ROTATION_SUFFIXES = ("rotation_quaternion", "rotation_euler", "rotation_axis_angle")


@dataclass
class ChainSpec:
    bone_names: tuple
    parameters: ChainParameters
    inertia_space: str = WORLD
    ancestor_name: str = ""
    warmup_seconds: float = 0.5


@dataclass
class ColliderSpec:
    shape: str
    bone_name: str
    radius_m: float
    head_offset_m: Vector
    tail_offset_m: Vector


@dataclass
class SolvedBone:
    name: str
    object_matrix: Matrix
    parent_matrix: Matrix


@dataclass
class SampleTick:
    frame: float
    armature_world: Matrix
    poses: dict
    lengths: dict


def specs_from_settings(settings):
    chains = []
    for chain in settings.chains:
        parameters = ChainParameters(
            stiffness=float(chain.stiffness),
            drag_force=float(chain.drag_force),
            gravity_power=float(chain.gravity_power),
            gravity_dir=Vector(chain.gravity_dir).copy(),
            hit_radius_m=float(chain.hit_radius_m),
            weight=float(chain.weight),
            cone_enabled=bool(chain.cone_enabled),
            cone_angle_rad=float(chain.cone_angle_deg) * 3.141592653589793 / 180.0,
            )
        chains.append(
            ChainSpec(
                bone_names=tuple(item.name for item in chain.bone_names),
                parameters=parameters,
                inertia_space=chain.inertia_space,
                ancestor_name=chain.ancestor_name,
                warmup_seconds=float(chain.warmup_seconds),
            )
        )
    colliders = []
    for item in settings.colliders:
        colliders.append(
            ColliderSpec(
                shape=item.shape,
                bone_name=item.bone_name,
                radius_m=float(item.radius_m),
                head_offset_m=Vector(item.head_offset_m).copy(),
                tail_offset_m=Vector(item.tail_offset_m).copy(),
            )
        )
    return chains, colliders


def iter_channelbags(action, slot):
    layers = getattr(action, "layers", None)
    if not layers or slot is None:
        return
    for layer in layers:
        for strip in layer.strips:
            if not hasattr(strip, "channelbag"):
                continue
            bag = strip.channelbag(slot)
            if bag is not None:
                yield bag


def bone_name_from_path(data_path):
    marker = 'pose.bones["'
    if not data_path.startswith(marker):
        return None, ""
    end = data_path.find('"]', len(marker))
    if end < 0:
        return None, ""
    return data_path[len(marker) : end], data_path[end + 2 :]


def _is_descendant(bone, ancestor):
    cursor = bone.parent
    while cursor is not None:
        if cursor == ancestor:
            return True
        cursor = cursor.parent
    return False


def _rotation_paths(names):
    paths = set()
    for name in names:
        for suffix in _ROTATION_SUFFIXES:
            paths.add(f'pose.bones["{name}"].{suffix}')
    return paths


def _split_frame(frame):
    whole = int(frame)
    if frame < 0.0 and whole != frame:
        whole -= 1
    return whole, float(frame) - whole


def _rest_token(armature):
    tokens = []
    for bone in armature.data.bones:
        parent = bone.parent.name if bone.parent is not None else ""
        matrix = bone.matrix_local
        flat = tuple(round(float(matrix[row][col]), 6) for row in range(4) for col in range(4))
        tokens.append((bone.name, flat, round(float(bone.length), 6), parent))
    return tuple(tokens)


def foreign_modal_active(context):
    window = getattr(context, "window", None)
    if window is None:
        return False
    for operator in getattr(window, "modal_operators", ()):
        if getattr(operator, "bl_idname", "") in {"spring_bone.preview", "spring_bone.bake"}:
            continue
        return True
    return False


def _warmup_ticks(seconds):
    if seconds < 0.0 or seconds > 5.0 or seconds != seconds:
        raise SpringBoneError("预热时间超出范围")
    return int(round(seconds * FIXED_HZ))


class _ChainRuntime:
    def __init__(self, spec, warmup_left):
        self.spec = spec
        self.warmup_left = warmup_left
        self.states = None
        self.prev_ancestor = None


class SpringBoneBakeJob:
    def __init__(
        self,
        armature,
        chains,
        colliders,
        frame_start,
        frame_end,
        bake,
        identity_token=None,
        fault_point=None,
        after_unit=None,
    ):
        self.armature = armature
        self.chains = list(chains)
        self.colliders = list(colliders)
        self.frame_start = int(frame_start)
        self.frame_end = int(frame_end)
        self.bake = bool(bake)
        self.identity_token = identity_token
        self.identity_value = None
        self.rest_token = None
        self.entry_window = None
        self.fault_point = fault_point
        self.after_unit = after_unit
        self.scene = bpy.context.scene
        self.phase = "prepare"
        self.finished = False
        self.cancelled = False
        self.delivered = False
        self.restore_entry = True
        self.captured = False
        self._closed = False
        self.created_actions = []
        self.result_action = None
        self.sample_index = 0
        self.grid_index = 0
        self.write_index = 0
        self.endpoint_done = False
        self.grid_ticks = []
        self.endpoint_tick = None
        self.sample_plan = []
        self.solved_frames = []
        self.runtimes = []
        self.sim_names = ()
        self.frozen_lengths = {}
        self.entry_modes = {}
        self.previous_locals = {}
        self._rotation_curves = {}
        self.trace_tails = []
        self.trace_rotations = []
        self.grid_tails = []
        self.max_penetration_m = 0.0
        self.stage_seconds = {"prepare": 0.0, "sample": 0.0, "simulate": 0.0, "write": 0.0, "publish": 0.0}
        self.unit_seconds = []
        self.slice_seconds = []
        self.longest_unit = 0.0
        self._done_units = 0
        self._total_units = 1
        self._write_ready = False
        self._linear_done = False

    @property
    def progress(self):
        if self.finished:
            return 1.0
        return min(1.0, self._done_units / float(self._total_units or 1))

    def advance(self):
        if self.finished:
            return
        stage = self.phase
        started = time.perf_counter()
        try:
            self._dispatch()
        finally:
            elapsed = time.perf_counter() - started
            self.unit_seconds.append(elapsed)
            self.stage_seconds[stage] = self.stage_seconds.get(stage, 0.0) + elapsed
            if elapsed > self.longest_unit:
                self.longest_unit = elapsed
        self._done_units += 1
        if self.after_unit is not None:
            self.after_unit(self)

    def run_budgeted(self):
        while not self.finished:
            self.run_slice()

    def run_slice(self):
        started = time.perf_counter()
        while not self.finished:
            self.advance()
            if time.perf_counter() - started >= 0.016:
                break
        self.slice_seconds.append(time.perf_counter() - started)

    def cancel(self):
        if self._closed:
            return
        self._closed = True
        self.finished = True
        if self.delivered:
            return
        self.cancelled = True
        if self.captured and self.restore_entry:
            self._restore_entry()
        self._delete_owned()

    def preview_still_valid(self):
        return (
            self.finished
            and not self.delivered
            and not self.cancelled
            and self.result_action is not None
            and self._ids_alive()
            and not self._input_changed()
        )

    def publish_from_preview(self):
        if self.result_action is None or self.delivered or self.cancelled:
            raise SpringBoneError("没有可提交的预览")
        if self._input_changed():
            raise SpringBoneError("预览已失效")
        self._raise_if("commit")
        name = self.result_action.name
        if name.endswith("_SpringPreview"):
            self.result_action.name = name[: -len("Preview")]
        self.result_action.use_fake_user = True
        if self.result_action in self.created_actions:
            self.created_actions.remove(self.result_action)
        self.delivered = True
        self._remember_result()

    def _dispatch(self):
        if self.phase != "prepare":
            self._guard()
        if self.phase == "prepare":
            self._prepare()
        elif self.phase == "sample":
            self._sample_unit()
        elif self.phase == "simulate":
            self._simulate_unit()
        elif self.phase == "write":
            self._write_unit()
        elif self.phase == "publish":
            self._publish_unit()

    def _prepare(self):
        self._validate()
        self._capture_entry()
        self._raise_if("start")
        self._build_frames()
        warmup = max((item.warmup_left for item in self.runtimes), default=0)
        sim_units = warmup + len(self.grid_ticks) + (1 if self.endpoint_tick is not None else 0)
        write_units = 1 + sim_units - warmup
        self._total_units = 1 + len(self.sample_plan) + sim_units + write_units + 1
        self.phase = "sample"

    def _validate(self):
        armature = self.armature
        if armature is None or armature.type != "ARMATURE":
            raise SpringBoneError("请选择骨架")
        if getattr(armature, "library", None) is not None or getattr(armature.data, "library", None) is not None:
            raise SpringBoneError("链接数据不可编辑")
        if armature.mode == "EDIT":
            raise SpringBoneError("请先退出编辑模式")
        scene = self.scene
        screen = getattr(bpy.context, "screen", None)
        if screen is not None and getattr(screen, "is_animation_playing", False):
            raise SpringBoneError("请先停止播放")
        if getattr(scene, "is_nla_tweakmode", False):
            raise SpringBoneError("请先退出NLA调整")
        if foreign_modal_active(bpy.context):
            raise SpringBoneError("请先结束其他操作")
        scale = float(scene.unit_settings.scale_length)
        if scale <= 0.0 or scale != scale:
            raise SpringBoneError("场景单位比例无效")
        self.scale_length = scale
        self.fps = int(scene.render.fps)
        self.fps_base = float(scene.render.fps_base)
        if self.fps <= 0 or self.fps_base <= 0.0:
            raise SpringBoneError("帧率无效")
        if self.frame_end < self.frame_start:
            raise SpringBoneError("帧范围无效")
        if not self.chains:
            raise SpringBoneError("请先添加骨骼链")
        if not matrix_has_supported_scale(armature.matrix_world):
            raise SpringBoneError("只支持统一正缩放")
        anim = armature.animation_data
        action = anim.action if anim else None
        if action is None:
            raise SpringBoneError("骨架没有动作")
        if action.get("sb_generated"):
            raise SpringBoneError("请改用基础动作")
        if getattr(action, "library", None) is not None:
            raise SpringBoneError("链接数据不可编辑")
        if any(track.strips for track in anim.nla_tracks):
            raise SpringBoneError("请关闭NLA")
        if hasattr(anim, "action_influence") and abs(float(anim.action_influence) - 1.0) > 1e-6:
            raise SpringBoneError("动作影响必须为1")
        if hasattr(anim, "action_blend_type") and anim.action_blend_type != "REPLACE":
            raise SpringBoneError("动作混合必须为替换")
        slots = getattr(action, "slots", None)
        if slots is None or len(slots) != 1:
            raise SpringBoneError("只支持单个动作槽")
        layers = getattr(action, "layers", None)
        if layers is None or len(layers) != 1 or len(layers[0].strips) != 1:
            raise SpringBoneError("只支持单层动作")
        if layers[0].strips[0].type != "KEYFRAME":
            raise SpringBoneError("只支持关键帧片段")
        slot = getattr(anim, "action_slot", None) or slots[0]
        for other in bpy.data.objects:
            if other == armature or other.animation_data is None:
                continue
            other_anim = other.animation_data
            if other_anim.action == action and getattr(other_anim, "action_slot", None) == slot:
                raise SpringBoneError("动作槽正被其他对象使用")
        self.entry_action = action
        self.entry_slot = slot
        settings = getattr(armature, "sb_settings", None)
        if settings is not None:
            try:
                settings.source_action = action
            except AttributeError:
                pass
        sim_names = []
        seen = set()
        arm = armature.data
        for spec in self.chains:
            validate_parameters(spec.parameters)
            if spec.inertia_space not in (WORLD, FOLLOW_TRANSLATION):
                raise SpringBoneError("惯性空间无效")
            if not spec.bone_names:
                raise SpringBoneError("链条为空")
            bones = []
            for name in spec.bone_names:
                if '"' in name or "\\" in name:
                    raise SpringBoneError("骨骼名不能包含引号")
                bone = arm.bones.get(name)
                if bone is None:
                    raise SpringBoneError(f"找不到骨骼 {name}")
                if name in seen:
                    raise SpringBoneError(f"{name} 已在其他链中")
                seen.add(name)
                sim_names.append(name)
                bones.append(bone)
                if bone.length <= 1e-8:
                    raise SpringBoneError(f"{name} 长度为零")
                if bone.inherit_scale != "FULL" or not bone.use_inherit_rotation or bone.bbone_segments > 1:
                    raise SpringBoneError(f"{name} 继承或变形不支持")
                pose = armature.pose.bones.get(name)
                if pose is None:
                    raise SpringBoneError(f"找不到姿势骨 {name}")
                if pose.rotation_mode == "AXIS_ANGLE":
                    raise SpringBoneError(f"{name} 不支持轴角旋转")
                if any(pose.lock_rotation) or getattr(pose, "lock_rotation_w", False):
                    raise SpringBoneError(f"{name} 旋转已锁定")
                if len(pose.constraints) > 0:
                    raise SpringBoneError(f"{name} 带有约束")
            for parent, child in zip(bones, bones[1:]):
                if child.parent != parent:
                    raise SpringBoneError("链条必须父子连续")
            for bone in bones:
                self._reject_nonuniform_scale(armature, bone)
            if spec.inertia_space == FOLLOW_TRANSLATION:
                ancestor = arm.bones.get(spec.ancestor_name)
                if ancestor is None or not _is_descendant(bones[0], ancestor):
                    raise SpringBoneError("跟随平移需要链首的非模拟祖先")
        self.sim_names = tuple(sim_names)
        for spec in self.colliders:
            bone = arm.bones.get(spec.bone_name)
            if bone is None:
                raise SpringBoneError(f"找不到碰撞骨 {spec.bone_name}")
            if spec.shape not in ("SPHERE", "CAPSULE"):
                raise SpringBoneError("碰撞形状不支持")
            if spec.radius_m < 0.0 or spec.radius_m != spec.radius_m:
                raise SpringBoneError("碰撞半径无效")
            if spec.bone_name in seen:
                raise SpringBoneError("碰撞骨不能是动态骨")
            for name in sim_names:
                if _is_descendant(bone, arm.bones[name]):
                    raise SpringBoneError("碰撞绑定与动态链冲突")
        self._reject_curves(action, slot)
        self._reject_drivers(armature)
        self._reject_indirect_constraints(armature)
        self.rest_token = _rest_token(armature)
        self.entry_window = getattr(bpy.context, "window", None)
        for spec in self.chains:
            self.runtimes.append(_ChainRuntime(spec, _warmup_ticks(spec.warmup_seconds)))
        self._order_runtimes()
        if self.identity_token is not None:
            self.identity_value = self.identity_token()

    def _order_runtimes(self):
        owner = {}
        for index, runtime in enumerate(self.runtimes):
            for name in runtime.spec.bone_names:
                owner[name] = index
        children = [[] for _ in self.runtimes]
        indegree = [0] * len(self.runtimes)
        arm = self.armature.data
        for index, runtime in enumerate(self.runtimes):
            parent = arm.bones[runtime.spec.bone_names[0]].parent
            while parent is not None and parent.name not in owner:
                parent = parent.parent
            if parent is None:
                continue
            dependency = owner[parent.name]
            if dependency == index:
                continue
            children[dependency].append(index)
            indegree[index] += 1
        ordered = []
        ready = [index for index, degree in enumerate(indegree) if degree == 0]
        while ready:
            index = ready.pop(0)
            ordered.append(self.runtimes[index])
            for child in children[index]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    ready.append(child)
        if len(ordered) != len(self.runtimes):
            raise SpringBoneError("链条父子顺序无效")
        self.runtimes = ordered

    def _reject_nonuniform_scale(self, armature, root):
        cursor = root
        while cursor is not None:
            pose = armature.pose.bones.get(cursor.name)
            if pose is not None:
                scale = pose.scale
                if min(scale.x, scale.y, scale.z) <= 0.0 or abs(scale.x - scale.y) > 1e-5 or abs(scale.x - scale.z) > 1e-5:
                    raise SpringBoneError(f"{cursor.name} 缩放不是统一缩放")
            cursor = cursor.parent

    def _reject_curves(self, action, slot):
        sim = set(self.sim_names)
        for fcurve in self._fcurves(action, slot):
            if fcurve.data_path == "scale":
                raise SpringBoneError("骨架缩放动画不支持")
            bone_name, suffix = bone_name_from_path(fcurve.data_path)
            if bone_name not in sim:
                continue
            if suffix in {".location", ".scale", ".rotation_mode"} or suffix.startswith(".scale"):
                raise SpringBoneError(f"{bone_name} 含有不支持的动画通道")

    def _reject_drivers(self, armature):
        anim = armature.animation_data
        if anim is None:
            return
        sim = set(self.sim_names)
        for driver in anim.drivers:
            bone_name, _suffix = bone_name_from_path(driver.data_path)
            if bone_name in sim:
                raise SpringBoneError(f"{bone_name} 带有驱动")
            for variable in driver.driver.variables:
                for target in variable.targets:
                    if getattr(target, "bone_target", "") in sim:
                        raise SpringBoneError("驱动依赖动态骨")
                    referenced, _suffix = bone_name_from_path(getattr(target, "data_path", "") or "")
                    if referenced in sim:
                        raise SpringBoneError("驱动依赖动态骨")

    def _reject_indirect_constraints(self, armature):
        sim = set(self.sim_names)
        for pose in armature.pose.bones:
            if pose.name in sim:
                continue
            for constraint in pose.constraints:
                if self._constraint_targets_sim(pose, constraint, sim):
                    raise SpringBoneError("约束依赖动态骨")

    def _constraint_targets_sim(self, pose, constraint, sim):
        for attr in ("subtarget", "pole_subtarget"):
            if getattr(constraint, attr, "") in sim:
                return True
        if self._ik_chain_hits_sim(pose, constraint, sim):
            return True
        targets = getattr(constraint, "targets", None)
        if targets is None:
            return False
        return any(getattr(target, "subtarget", "") in sim for target in targets)

    def _ik_chain_hits_sim(self, pose, constraint, sim):
        if getattr(constraint, "type", "") not in {"IK", "SPLINE_IK"}:
            return False
        count = int(getattr(constraint, "chain_count", 0) or 0)
        bone = pose.bone
        seen = 0
        while bone is not None:
            if bone.name in sim:
                return True
            seen += 1
            if count > 0 and seen >= count:
                return False
            bone = bone.parent
        return False

    def _fcurves(self, action, slot):
        for bag in iter_channelbags(action, slot):
            for fcurve in bag.fcurves:
                yield fcurve

    def _capture_entry(self):
        armature = self.armature
        scene = self.scene
        anim = armature.animation_data
        self.had_anim = anim is not None
        self.entry_use_nla = bool(anim.use_nla) if anim else False
        self.entry_frame = int(scene.frame_current)
        self.entry_subframe = float(getattr(scene, "frame_subframe", 0.0))
        self.entry_range = (int(scene.frame_start), int(scene.frame_end))
        self.entry_mode = armature.mode
        self.entry_active = bpy.context.view_layer.objects.active
        self.entry_selected = {obj.name for obj in bpy.context.view_layer.objects if obj.select_get()}
        self.entry_poses = tuple(
            (pose.name, pose.rotation_mode, pose.matrix_basis.copy()) for pose in armature.pose.bones
        )
        self.entry_modes = {pose.name: pose.rotation_mode for pose in armature.pose.bones}
        self.captured = True

    def _build_frames(self):
        span = self.frame_end - self.frame_start
        count = included_tick_count(span, self.fps, self.fps_base)
        self.grid_frames = [
            frame_for_tick(self.frame_start, index, self.fps, self.fps_base) for index in range(count)
        ]
        self.sample_plan = list(self.grid_frames)
        base = int(round(self.fps_base))
        if (FIXED_HZ * span * base) % int(self.fps) != 0:
            self.endpoint_frame = float(self.frame_end)
            self.sample_plan.append(self.endpoint_frame)
        else:
            self.endpoint_frame = None

    def _sample_unit(self):
        if self.sample_index == 1:
            self._raise_if("sample")
        if self.sample_index >= len(self.sample_plan):
            self._initialize_states()
            self.phase = "simulate"
            return
        frame = self.sample_plan[self.sample_index]
        tick = self._read_tick(frame)
        if self.sample_index == 0:
            self.frozen_lengths = dict(tick.lengths)
        else:
            for name, length in tick.lengths.items():
                frozen = self.frozen_lengths[name]
                if abs(length - frozen) > max(1e-6, abs(frozen) * 1e-5):
                    raise SpringBoneError(f"{name} 骨长发生变化")
        if self.endpoint_frame is not None and self.sample_index == len(self.sample_plan) - 1:
            self.endpoint_tick = tick
        else:
            self.grid_ticks.append(tick)
        self.sample_index += 1

    def _restore_bases(self):
        for name, mode, basis in self.entry_poses:
            pose = self.armature.pose.bones.get(name)
            if pose is None:
                continue
            if pose.rotation_mode != mode:
                pose.rotation_mode = mode
            pose.matrix_basis = basis.copy()

    def _read_tick(self, frame):
        whole, sub = _split_frame(frame)
        self._restore_bases()
        self.scene.frame_set(whole, subframe=sub)
        bpy.context.view_layer.update()
        armature = self.armature
        poses = {}
        lengths = {}
        needed = set(self.sim_names)
        for spec in self.chains:
            root = armature.data.bones.get(spec.bone_names[0])
            if root is not None and root.parent is not None:
                needed.add(root.parent.name)
            if spec.ancestor_name:
                needed.add(spec.ancestor_name)
        for spec in self.colliders:
            needed.add(spec.bone_name)
        for name in needed:
            pose = armature.pose.bones[name]
            poses[name] = pose.matrix.copy()
            if name in self.sim_names:
                head = armature.matrix_world @ pose.head
                tail = armature.matrix_world @ pose.tail
                lengths[name] = (tail - head).length * self.scale_length
        return SampleTick(frame, armature.matrix_world.copy(), poses, lengths)

    def _initialize_states(self):
        if not self.grid_ticks:
            raise SpringBoneError("没有采样帧")
        first = self.grid_ticks[0]
        for runtime in self.runtimes:
            spec = runtime.spec
            root = self.armature.data.bones[spec.bone_names[0]]
            parent_name = root.parent.name if root.parent else ""
            parent_pose = first.poses[parent_name] if parent_name else Matrix.Identity(4)
            solved_parent = parent_pose.copy()
            states = []
            samples = []
            for index, name in enumerate(spec.bone_names):
                samples.append(SegmentSample(base_pose=first.poses[name]))
                reference = reference_pose(index, samples, parent_pose, parent_pose, solved_parent)
                world = first.armature_world @ reference
                head = world.to_translation() * self.scale_length
                direction = direction_or_fallback(world.to_quaternion() @ _AXIS_Y, _AXIS_Y, _AXIS_Y)
                tail = head + direction * self.frozen_lengths[name]
                states.append(
                    SegmentState(
                        self.frozen_lengths[name],
                        tail.copy(),
                        tail.copy(),
                        direction.copy(),
                        Vector((0.0, 0.0, 0.0)),
                    )
                )
                solved_parent = first.poses[name].copy()
            runtime.states = states
            if spec.inertia_space == FOLLOW_TRANSLATION:
                runtime.prev_ancestor = self._ancestor_head(first, spec.ancestor_name)

    def _simulate_unit(self):
        if any(runtime.warmup_left > 0 for runtime in self.runtimes):
            self._raise_second_chain()
            self.solved_this_tick = {}
            tick = self.grid_ticks[0]
            colliders = self._world_colliders(tick)
            for runtime in self.runtimes:
                if runtime.warmup_left <= 0:
                    continue
                self._step_chain(runtime, tick, False, colliders)
                runtime.warmup_left -= 1
            return
        if self.grid_index < len(self.grid_ticks):
            if self.grid_index == 0:
                self._raise_second_chain()
            tick = self.grid_ticks[self.grid_index]
            self.solved_frames.append(self._step_runtimes(self.runtimes, tick, True))
            self.grid_index += 1
            self.grid_tails.append(tuple(state.current_tail_m.copy() for state in self.runtimes[0].states))
            return
        if self.endpoint_tick is not None and not self.endpoint_done:
            clones = [self._clone_runtime(runtime) for runtime in self.runtimes]
            self.solved_frames.append(self._step_runtimes(clones, self.endpoint_tick, True))
            self.endpoint_done = True
            return
        self.phase = "write"

    def _raise_second_chain(self):
        if self.fault_point == "second_chain" and len(self.runtimes) > 1:
            self.fault_point = None
            raise SpringBoneError("second_chain")

    def _clone_runtime(self, runtime):
        clone = _ChainRuntime(runtime.spec, 0)
        clone.prev_ancestor = None if runtime.prev_ancestor is None else runtime.prev_ancestor.copy()
        clone.states = [
            SegmentState(
                state.length_m,
                state.previous_tail_m.copy(),
                state.current_tail_m.copy(),
                state.last_direction.copy(),
                state.last_radial.copy(),
            )
            for state in runtime.states
        ]
        return clone

    def _step_runtimes(self, runtimes, tick, record):
        self.solved_this_tick = {}
        solved = []
        colliders = self._world_colliders(tick)
        for runtime in runtimes:
            solved.extend(self._step_chain(runtime, tick, record, colliders))
        return solved

    def _step_chain(self, runtime, tick, record, colliders):
        spec = runtime.spec
        root = self.armature.data.bones[spec.bone_names[0]]
        parent_name = root.parent.name if root.parent else ""
        parent_base = tick.poses[parent_name] if parent_name else Matrix.Identity(4)
        parent_pose = self.solved_this_tick.get(parent_name, parent_base)
        samples = [SegmentSample(base_pose=tick.poses[name]) for name in spec.bone_names]
        delta = None
        if spec.inertia_space == FOLLOW_TRANSLATION:
            head = self._ancestor_head(tick, spec.ancestor_name)
            if runtime.prev_ancestor is None:
                delta = Vector((0.0, 0.0, 0.0))
            else:
                delta = head - runtime.prev_ancestor
            runtime.prev_ancestor = head.copy()
        solved_bones = []
        rotations = step_chain(
            runtime.states,
            samples,
            parent_base=parent_base,
            parent_solved=parent_pose,
            armature_world=tick.armature_world,
            scale_length=self.scale_length,
            parameters=spec.parameters,
            colliders=colliders,
            translation_delta_m=delta,
            solved_bones=solved_bones,
        )
        solved = []
        for index, (object_matrix, parent_matrix) in enumerate(solved_bones):
            solved.append(
                SolvedBone(
                    name=spec.bone_names[index],
                    object_matrix=object_matrix,
                    parent_matrix=parent_matrix,
                )
            )
            self.solved_this_tick[spec.bone_names[index]] = object_matrix
            if record:
                distance = self._penetration(runtime.states[index].current_tail_m, colliders, spec.parameters.hit_radius_m)
                if distance > self.max_penetration_m:
                    self.max_penetration_m = distance
        if record and runtime is self.runtimes[0]:
            self.trace_tails.append(runtime.states[-1].current_tail_m.copy())
            self.trace_rotations.append(rotations[-1].copy())
        return solved

    def _penetration(self, point, colliders, hit_radius):
        deepest = 0.0
        for collider in colliders:
            signed = signed_collider_distance(point, collider, hit_radius)
            if -signed > deepest:
                deepest = -signed
        return deepest

    def _ancestor_head(self, tick, name):
        world = tick.armature_world @ tick.poses[name]
        return world.to_translation() * self.scale_length

    def _world_colliders(self, tick):
        colliders = []
        for spec in self.colliders:
            pose = tick.armature_world @ tick.poses[spec.bone_name]
            start = self._local_meters(pose, spec.head_offset_m)
            if spec.shape == "SPHERE":
                colliders.append(SphereCollider(start, spec.radius_m))
            else:
                end = self._local_meters(pose, spec.tail_offset_m)
                colliders.append(CapsuleCollider(start, end, spec.radius_m))
        return tuple(colliders)

    def _local_meters(self, pose, offset_m):
        blender = Vector(offset_m) / self.scale_length
        return (pose @ blender) * self.scale_length

    def _write_unit(self):
        if not self._write_ready:
            self._create_result()
            self._write_ready = True
            return
        if self.write_index == 1:
            self._raise_if("write")
        if self.write_index >= len(self.solved_frames):
            if not self._linear_done:
                self._set_linear()
                self._linear_done = True
                return
            self.phase = "publish"
            return
        self._write_frame(self.solved_frames[self.write_index], self._output_frame(self.write_index))
        self.write_index += 1

    def _output_frame(self, index):
        if index < len(self.grid_frames):
            return self.grid_frames[index]
        return float(self.frame_end)

    def _create_result(self):
        action = self.entry_action.copy()
        action.use_fake_user = False
        suffix = "_Spring" if self.bake else "_SpringPreview"
        action.name = f"{self.entry_action.name}{suffix}"[:63]
        self.created_actions.append(action)
        self.result_action = action
        self._raise_if("slot")
        if len(getattr(action, "slots", ())) != 1:
            raise SpringBoneError("结果槽失败")
        self._remove_rotation_curves(action, action.slots[0])

    def _assign(self, action):
        anim = self.armature.animation_data or self.armature.animation_data_create()
        anim.action = action

    def _remove_rotation_curves(self, action, slot):
        paths = _rotation_paths(self.sim_names)
        for bag in iter_channelbags(action, slot):
            for fcurve in list(bag.fcurves):
                if fcurve.data_path in paths:
                    bag.fcurves.remove(fcurve)

    def _write_frame(self, solved, frame):
        armature = self.armature
        for item in solved:
            pose = armature.pose.bones[item.name]
            bone = armature.data.bones[item.name]
            parent = bone.parent
            parent_local = parent.matrix_local.copy() if parent is not None else Matrix.Identity(4)
            local = bone.convert_local_to_pose(
                item.object_matrix,
                bone.matrix_local,
                parent_matrix=item.parent_matrix,
                parent_matrix_local=parent_local,
                invert=True,
            )
            _location, rotation, _scale = local.decompose()
            mode = self.entry_modes[item.name]
            if mode == "QUATERNION":
                previous = self.previous_locals.get(item.name)
                if previous is not None and rotation.dot(previous) < 0.0:
                    rotation = -rotation
                self._insert_rotation(item.name, mode, frame, (rotation.w, rotation.x, rotation.y, rotation.z))
                self.previous_locals[item.name] = rotation.copy()
            else:
                hint = self.previous_locals.get(item.name)
                if hint is None:
                    hint = pose.rotation_euler.copy()
                euler = rotation.to_euler(mode, hint)
                self._insert_rotation(item.name, mode, frame, (euler.x, euler.y, euler.z))
                self.previous_locals[item.name] = Euler(euler)

    def _insert_rotation(self, name, mode, frame, values):
        curves = self._rotation_curves.get(name)
        if curves is None:
            path = f'pose.bones["{name}"].rotation_quaternion' if mode == "QUATERNION" else f'pose.bones["{name}"].rotation_euler'
            bag = next(iter_channelbags(self.result_action, self.result_action.slots[0]), None)
            if bag is None:
                raise SpringBoneError("结果槽失败")
            curves = []
            for index in range(len(values)):
                curve = bag.fcurves.find(path, index=index)
                if curve is None:
                    curve = bag.fcurves.new(path, index=index)
                curves.append(curve)
            self._rotation_curves[name] = curves
        for curve, value in zip(curves, values):
            curve.keyframe_points.insert(frame, float(value), options={"FAST"})

    def _set_linear(self):
        slot = self.result_action.slots[0]
        paths = _rotation_paths(self.sim_names)
        for bag in iter_channelbags(self.result_action, slot):
            for fcurve in bag.fcurves:
                if fcurve.data_path not in paths:
                    continue
                for point in fcurve.keyframe_points:
                    point.interpolation = "LINEAR"
                fcurve.update()

    def _publish_unit(self):
        if self.bake:
            self._raise_if("commit")
        self.result_action["sb_generated"] = 1
        self.result_action["sb_frame_start"] = self.frame_start
        self.result_action["sb_frame_end"] = self.frame_end
        self.result_action["sb_penetration_m"] = float(self.max_penetration_m)
        self._assign(self.result_action)
        slot = self.result_action.slots[0]
        anim = self.armature.animation_data
        if hasattr(anim, "action_slot"):
            anim.action_slot = slot
        self.scene.frame_start = self.frame_start
        self.scene.frame_end = self.frame_end
        self.scene.frame_set(self.frame_start)
        if self.bake:
            self.result_action.use_fake_user = True
            if self.result_action in self.created_actions:
                self.created_actions.remove(self.result_action)
            self.delivered = True
        self._remember_result()
        self.phase = "done"
        self.finished = True

    def _remember_result(self):
        settings = getattr(self.armature, "sb_settings", None)
        if settings is None:
            return
        try:
            settings.result_action_name = self.result_action.name
            settings.result_start = self.frame_start
            settings.result_end = self.frame_end
            settings.result_penetration_m = float(self.max_penetration_m)
        except AttributeError:
            return

    def _ids_alive(self):
        try:
            armature_name = self.armature.name
            scene_name = self.scene.name
            data = self.armature.data
        except ReferenceError:
            return False
        return armature_name in bpy.data.objects and scene_name in bpy.data.scenes and data is not None

    def _guard(self):
        if not self._ids_alive():
            self.restore_entry = False
            raise SpringBoneError("目标已失效")
        if self._input_changed():
            self.restore_entry = False
            raise SpringBoneError("输入已变化")

    def _input_changed(self):
        context_scene = getattr(bpy.context, "scene", None)
        if context_scene is not None and context_scene != self.scene:
            return True
        window = getattr(bpy.context, "window", None)
        if self.entry_window is not None and window is not None and window != self.entry_window:
            return True
        scene = self.scene
        if int(scene.render.fps) != self.fps or abs(float(scene.render.fps_base) - self.fps_base) > 1e-6:
            return True
        if abs(float(scene.unit_settings.scale_length) - self.scale_length) > 1e-8:
            return True
        if self.rest_token is not None and _rest_token(self.armature) != self.rest_token:
            return True
        anim = self.armature.animation_data
        current = anim.action if anim else None
        allowed = {self.entry_action, *self.created_actions}
        if current not in allowed:
            return True
        if current == self.entry_action:
            slot = getattr(anim, "action_slot", None)
            entry_id = getattr(self.entry_slot, "identifier", None)
            current_id = getattr(slot, "identifier", None)
            if entry_id != current_id:
                return True
        if self.identity_token is not None and self.identity_token() != self.identity_value:
            return True
        return False

    def _raise_if(self, point):
        if self.fault_point == point:
            self.fault_point = None
            raise SpringBoneError(point)

    def _restore_entry(self):
        armature = self.armature
        scene = self.scene
        if not self.had_anim:
            if armature.animation_data is not None:
                armature.animation_data_clear()
        else:
            anim = armature.animation_data or armature.animation_data_create()
            anim.action = self.entry_action
            if self.entry_slot is not None and hasattr(anim, "action_slot"):
                anim.action_slot = self.entry_slot
            anim.use_nla = self.entry_use_nla
        scene.frame_start = self.entry_range[0]
        scene.frame_end = self.entry_range[1]
        scene.frame_set(self.entry_frame, subframe=self.entry_subframe)
        if self.entry_active is not None:
            bpy.context.view_layer.objects.active = self.entry_active
        for obj in bpy.context.view_layer.objects:
            obj.select_set(obj.name in self.entry_selected)
        if armature.mode != self.entry_mode and self.entry_mode != "EDIT":
            bpy.ops.object.mode_set(mode=self.entry_mode)
        for name, mode, basis in self.entry_poses:
            pose = armature.pose.bones.get(name)
            if pose is None:
                continue
            pose.rotation_mode = mode
            pose.matrix_basis = basis.copy()
        bpy.context.view_layer.update()

    def _delete_owned(self):
        current = None
        anim = None
        if self._ids_alive():
            anim = self.armature.animation_data
            if anim is not None:
                current = anim.action
        for action in list(self.created_actions):
            try:
                if current == action and not self.restore_entry and anim is not None:
                    anim.action = None
                bpy.data.actions.remove(action, do_unlink=True)
            except ReferenceError:
                continue
        self.created_actions.clear()
        self.result_action = None
