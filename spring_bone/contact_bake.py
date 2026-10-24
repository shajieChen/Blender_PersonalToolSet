import math
import time
import hashlib

import bpy
import numpy as np
from mathutils import Matrix, Quaternion, Vector

from .animation import _rest_token, align_quaternion_key_signs, bone_name_from_path, foreign_modal_active, iter_channelbags
from .skin_collision import SkinCollisionFrame, search_skin_pose, triangle_crossings
from .solver import SpringBoneError


def _action_token(action, slot):
    digest = hashlib.sha256()
    for bag in iter_channelbags(action, slot):
        for curve in bag.fcurves:
            points = curve.keyframe_points
            digest.update(repr((curve.data_path, curve.array_index, curve.mute, curve.extrapolation, len(points))).encode("utf-8"))
            for field in ("co", "handle_left", "handle_right"):
                values = np.empty(len(points) * 2, dtype=np.float32)
                points.foreach_get(field, values)
                digest.update(values.tobytes())
            digest.update(repr(tuple(point.interpolation for point in points)).encode("utf-8"))
    return digest.digest()


def _mesh_token(obj):
    mesh = obj.data
    digest = hashlib.sha256()
    coordinates = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", coordinates)
    indices = np.empty(len(mesh.loops), dtype=np.int32)
    mesh.loops.foreach_get("vertex_index", indices)
    sizes = np.empty(len(mesh.polygons), dtype=np.int32)
    mesh.polygons.foreach_get("loop_total", sizes)
    weights = np.array([(vertex.index, slot.group, slot.weight) for vertex in mesh.vertices for slot in vertex.groups], dtype=np.float64)
    groups = tuple((group.name, group.index) for group in obj.vertex_groups)
    digest.update(repr((mesh.name, len(mesh.vertices), groups)).encode("utf-8"))
    for values in (coordinates, indices, sizes, weights):
        digest.update(values.tobytes())
    return digest.digest()


def _mesh_arrays(obj):
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        if len(mesh.vertices) != len(obj.data.vertices):
            raise SpringBoneError("防穿修正不支持改变拓扑的修改器")
        mesh.calc_loop_triangles()
        points = np.array([evaluated.matrix_world @ vertex.co for vertex in mesh.vertices], dtype=np.float64)
        normal_matrix = evaluated.matrix_world.to_3x3().inverted().transposed()
        normals = np.array([(normal_matrix @ vertex.normal).normalized() for vertex in mesh.vertices], dtype=np.float64)
        triangles = np.array([tuple(triangle.vertices) for triangle in mesh.loop_triangles], dtype=np.int32)
        return points, normals, triangles
    finally:
        evaluated.to_mesh_clear()


def _skin_weights(obj, armature, names):
    deform = {group.index for group in obj.vertex_groups if (bone := armature.data.bones.get(group.name)) is not None and bone.use_deform}
    lookup = {group.index: names.index(group.name) for group in obj.vertex_groups if group.name in names and group.index in deform}
    weights = np.zeros((len(obj.data.vertices), len(names)), dtype=np.float64)
    for vertex in obj.data.vertices:
        total = sum(slot.weight for slot in vertex.groups if slot.group in deform)
        if total <= 1e-12:
            continue
        for slot in vertex.groups:
            if slot.group in lookup:
                weights[vertex.index, lookup[slot.group]] = slot.weight / total
    return weights


def _validate_mesh(obj, armature):
    if obj is None or obj.type != "MESH" or obj.name not in bpy.context.scene.objects:
        raise SpringBoneError("请选择场景中的裙面网格和身体网格")
    modifiers = [modifier for modifier in obj.modifiers if modifier.show_viewport]
    if len(modifiers) != 1 or modifiers[0].type != "ARMATURE" or modifiers[0].object != armature:
        raise SpringBoneError("网格必须仅通过目标骨架的 Armature 修改器变形")
    modifier = modifiers[0]
    if modifier.use_deform_preserve_volume or modifier.use_bone_envelopes or not modifier.use_vertex_groups or modifier.vertex_group:
        raise SpringBoneError("防穿修正需要无遮罩的线性顶点组蒙皮")
    if obj.data.shape_keys is not None:
        raise SpringBoneError("防穿修正暂不支持形态键网格")


class SkirtContactBakeJob:
    def __init__(self, armature, frame_start, frame_end, identity_token=None):
        self.armature = armature
        self.scene = bpy.context.scene
        self.frame_start, self.frame_end = int(frame_start), int(frame_end)
        self.identity_token = identity_token
        self.phase = "prepare"
        self.finished = False
        self.delivered = False
        self.cancelled = False
        self.result_action = None
        self.working_action = None
        self.captured = False
        self.restore_entry = True
        self.solutions = []
        self.frame_results = []
        self.frame_index = 0
        self.write_index = 0
        self.search = None
        self.previous_corrections = None
        self.previous_world_offsets = None
        self.previous_rotations = {}

    @property
    def progress(self):
        total = len(getattr(self, "frames", ())) or 1
        return 1.0 if self.finished else min(.99, (self.frame_index + self.write_index) / (2.0 * total))

    def run_slice(self):
        started = time.perf_counter()
        while not self.finished:
            self.advance()
            if time.perf_counter() - started >= .016:
                return

    def run_budgeted(self):
        while not self.finished:
            self.run_slice()

    def advance(self):
        if self.finished:
            return
        try:
            if self.phase == "prepare":
                self._prepare()
            else:
                self._guard()
                if self.phase == "contact":
                    self._contact_unit()
                elif self.phase == "write":
                    self._write_unit()
                elif self.phase == "publish":
                    self._publish()
        except Exception:
            self.cancel()
            raise

    def _prepare(self):
        armature = self.armature
        if armature is None or armature.type != "ARMATURE" or armature.mode == "EDIT" or armature.library is not None or armature.data.library is not None:
            raise SpringBoneError("防穿修正需要场景中的可编辑骨架")
        if foreign_modal_active(bpy.context):
            raise SpringBoneError("请先结束其他操作")
        anim = armature.animation_data
        action = anim.action if anim is not None else None
        if action is None or action.library is not None or len(action.slots) != 1 or len(action.layers) != 1 or len(action.layers[0].strips) != 1:
            raise SpringBoneError("防穿修正需要单槽单层骨骼动作")
        if anim.use_nla and any(track.strips and not track.mute for track in anim.nla_tracks):
            raise SpringBoneError("请关闭 NLA 后再修正骨骼动作")
        if anim.action_blend_type != "REPLACE" or abs(anim.action_influence - 1.0) > 1e-6 or self.scene.is_nla_tweakmode:
            raise SpringBoneError("防穿修正需要完整替换的活动动作")
        if anim.drivers or armature.data.pose_position != "POSE" or getattr(bpy.context.screen, "is_animation_playing", False):
            raise SpringBoneError("请停止播放，使用无驱动的姿态骨架")
        settings = armature.sb_settings
        self.garment, self.body = settings.contact_garment, settings.contact_body
        if self.garment == self.body:
            raise SpringBoneError("裙面网格和身体网格必须不同")
        for obj in (self.garment, self.body):
            _validate_mesh(obj, armature)
        configured = [item.name for chain in settings.chains for item in chain.bone_names]
        if not configured or len(set(configured)) != len(configured) or any(name not in armature.pose.bones for name in configured):
            raise SpringBoneError("动态链为空、重复或包含无效骨骼")
        self.names = sorted(configured, key=lambda name: len(armature.data.bones[name].parent_recursive))
        for name in self.names:
            bone, pose = armature.data.bones[name], armature.pose.bones[name]
            if bone.inherit_scale != "FULL" or not bone.use_inherit_rotation or not bone.use_local_location or bone.bbone_segments != 1 or pose.constraints:
                raise SpringBoneError(f"{name} 的继承或变形不支持防穿修正")
            if pose.rotation_mode == "AXIS_ANGLE" or any(pose.lock_rotation) or pose.lock_rotation_w:
                raise SpringBoneError(f"{name} 的旋转模式或锁定不支持防穿修正")
            if any(child.name not in configured for child in bone.children_recursive):
                raise SpringBoneError(f"{name} 存在未配置的子骨骼")
        for bag in iter_channelbags(action, anim.action_slot):
            for curve in bag.fcurves:
                name, suffix = bone_name_from_path(curve.data_path)
                if name in configured and (suffix == ".rotation_mode" or curve.modifiers):
                    raise SpringBoneError("动态骨的模式动画或曲线修改器不支持防穿修正")
        collider_names = {item.bone_name for item in settings.colliders if item.bone_name in armature.data.bones}
        if not collider_names:
            raise SpringBoneError("请先为身体部位添加碰撞体")
        region_names = sorted({bone.name for name in collider_names for bone in (armature.data.bones[name], *armature.data.bones[name].children_recursive)})
        if set(region_names) & set(self.names):
            raise SpringBoneError("碰撞部位不能包含动态链")
        self.weights = _skin_weights(self.garment, armature, self.names)
        if self.weights.sum() <= 1e-8:
            raise SpringBoneError("裙面网格没有动态链权重")
        if _skin_weights(self.body, armature, self.names).sum() > 1e-8:
            raise SpringBoneError("身体网格不能受本次动态链驱动")
        self.body_region = _skin_weights(self.body, armature, region_names).sum(axis=1) > .05
        units = float(self.scene.unit_settings.scale_length)
        if not math.isfinite(units) or units <= 0.0:
            raise SpringBoneError("场景单位比例无效")
        self.margin = float(settings.contact_margin_m) / units
        self.clock_value = (self.scene.render.fps, self.scene.render.fps_base, units)
        self.max_root_offset = float(settings.contact_root_offset_m) / units
        step = float(settings.contact_frame_step)
        if self.frame_end < self.frame_start or not math.isfinite(step) or step <= 0.0 or not math.isfinite(self.margin):
            raise SpringBoneError("防穿修正的范围或采样无效")
        count = int(math.ceil((self.frame_end - self.frame_start) / step))
        self.frames = [min(float(self.frame_end), self.frame_start + index * step) for index in range(count + 1)]
        self.entry_action, self.entry_slot = action, anim.action_slot or action.slots[0]
        self.evaluation_value = (anim.use_nla, anim.action_blend_type, float(anim.action_influence), armature.data.pose_position)
        if anim.action_slot != self.entry_slot:
            raise SpringBoneError("请为活动动作选择有效的动作槽")
        self.entry_frame = self.scene.frame_current, self.scene.frame_subframe
        self.entry_poses = [(pose.name, pose.rotation_mode, pose.matrix_basis.copy()) for pose in armature.pose.bones]
        self.entry_modes = {pose.name: pose.rotation_mode for pose in armature.pose.bones}
        self.root_names = {name for name in self.names if armature.pose.bones[name].parent is None or armature.pose.bones[name].parent.name not in self.names}
        if any(armature.data.bones[name].use_connect for name in self.root_names) and self.max_root_offset > 0.0:
            raise SpringBoneError("相连的链首不能独立移动，请将根部修正上限设为零")
        self.action_value = _action_token(action, self.entry_slot)
        self.geometry_values = (_mesh_token(self.garment), _mesh_token(self.body))
        self.rest_value = _rest_token(armature)
        self.sample_frame_value = None
        self.identity_value = self.identity_token() if self.identity_token else None
        self.captured = True
        self.working_action = action.copy()
        self.working_action.name = action.name + "_ContactInput"
        self.working_action.use_fake_user = False
        self.continuity_repairs = align_quaternion_key_signs(self.working_action, self.working_action.slots[0])
        anim.action = self.working_action
        anim.action_slot = self.working_action.slots[0]
        self.phase = "contact"

    def _guard(self):
        try:
            alive = bpy.data.objects.get(self.armature.name) == self.armature and bpy.data.scenes.get(self.scene.name) == self.scene
        except ReferenceError:
            alive = False
        if not alive or bpy.context.scene != self.scene:
            self.restore_entry = False
            raise SpringBoneError("防穿修正目标已失效")
        anim = self.armature.animation_data
        if anim is None or anim.action != self.working_action or anim.action_slot != self.working_action.slots[0]:
            self.restore_entry = False
            raise SpringBoneError("活动动作已变化，已取消防穿修正")
        if (anim.use_nla, anim.action_blend_type, float(anim.action_influence), self.armature.data.pose_position) != self.evaluation_value or self.armature.mode == "EDIT":
            self.restore_entry = False
            raise SpringBoneError("动画求值状态已变化，已取消防穿修正")
        if any(self.armature.pose.bones.get(name) is None or self.armature.pose.bones[name].rotation_mode != self.entry_modes[name] for name in self.names):
            self.restore_entry = False
            raise SpringBoneError("骨骼或旋转模式已变化")
        current_frame = self.scene.frame_current + self.scene.frame_subframe
        if self.sample_frame_value is not None and abs(current_frame - self.sample_frame_value) > 1e-6:
            self.restore_entry = False
            raise SpringBoneError("时间轴已变化，已取消防穿修正")
        if self.identity_token and self.identity_token() != self.identity_value:
            raise SpringBoneError("防穿修正配置已变化")
        if (self.scene.render.fps, self.scene.render.fps_base, self.scene.unit_settings.scale_length) != self.clock_value:
            self.restore_entry = False
            raise SpringBoneError("帧率或场景单位已变化")
        if self.phase != "contact" and _action_token(self.entry_action, self.entry_slot) != self.action_value:
            self.restore_entry = False
            raise SpringBoneError("源动作已编辑，已取消防穿修正")
        if self.phase != "contact" and ((_mesh_token(self.garment), _mesh_token(self.body)) != self.geometry_values or _rest_token(self.armature) != self.rest_value):
            self.restore_entry = False
            raise SpringBoneError("蒙皮或静态骨架已编辑，已取消防穿修正")

    def _sample_frame(self):
        if _action_token(self.entry_action, self.entry_slot) != self.action_value:
            self.restore_entry = False
            raise SpringBoneError("源动作已编辑，已取消防穿修正")
        if (_mesh_token(self.garment), _mesh_token(self.body)) != self.geometry_values or _rest_token(self.armature) != self.rest_value:
            self.restore_entry = False
            raise SpringBoneError("蒙皮或静态骨架已编辑，已取消防穿修正")
        for obj in (self.garment, self.body):
            _validate_mesh(obj, self.armature)
        frame = self.frames[self.frame_index]
        whole = math.floor(frame)
        self.scene.frame_set(whole, subframe=frame - whole)
        self.sample_frame_value = frame
        bpy.context.view_layer.update()
        points, _normals, triangles = _mesh_arrays(self.garment)
        body_points, body_normals, body_triangles = _mesh_arrays(self.body)
        self.triangles = triangles[(self.weights.sum(axis=1)[triangles] > .05).sum(axis=1) >= 2]
        self.body_triangles = body_triangles[self.body_region[body_triangles].sum(axis=1) >= 2]
        if len(self.triangles) == 0 or len(self.body_triangles) == 0:
            raise SpringBoneError("裙面或碰撞部位没有可检查的三角形")
        self.body_points = body_points + body_normals * self.margin
        self.sample_body_points = body_points
        armature = self.armature
        bones = [armature.pose.bones[name] for name in self.names]
        relative, inverse, parents, fixed, locations, rotations, scales = [], [], [], [], [], [], []
        for pose in bones:
            parent = pose.parent
            parents.append(self.names.index(parent.name) if parent and parent.name in self.names else -1)
            relative.append(np.asarray(parent.bone.matrix_local.inverted() @ pose.bone.matrix_local if parent else pose.bone.matrix_local))
            inverse.append(np.asarray(pose.bone.matrix_local.inverted()))
            fixed.append(np.asarray(parent.matrix if parent else Matrix.Identity(4)))
            location, rotation, scale = pose.matrix_basis.decompose()
            locations.append(location)
            rotations.append(rotation)
            scales.append(scale)
        mesh_to_arm = armature.matrix_world.inverted() @ self.garment.matrix_world
        rest = np.array([mesh_to_arm @ vertex.co for vertex in self.garment.data.vertices], dtype=np.float64)
        self.sample = SkinCollisionFrame(np.array(parents), np.array(relative), np.array(inverse), rest, self.weights, np.asarray(armature.matrix_world), np.array(fixed), np.array(locations), rotations, np.array(scales), points)
        predicted = self.sample.poses(rotations)
        if max(float(np.abs(predicted[index] - np.asarray(pose.matrix)).max()) for index, pose in enumerate(bones)) > 1e-5:
            raise SpringBoneError("骨架包含当前防穿修正不支持的变换")
        self.search = search_skin_pose(self.sample, self.triangles, self.body_points, self.body_triangles, self.previous_corrections, self.previous_world_offsets, max_offset=self.max_root_offset)
        self.candidate = None
        self.initial_pairs = None

    def _contact_unit(self):
        if self.frame_index >= len(self.frames):
            self._create_result()
            self.phase = "write"
            return
        if self.search is None:
            self._sample_frame()
            return
        try:
            self.candidate = next(self.search)
            if self.initial_pairs is None:
                self.initial_pairs = self.candidate.triangle_pairs
            return
        except StopIteration:
            pass
        rotations, locations, residual = self.candidate.rotations, self.candidate.locations, self.candidate.triangle_pairs
        frame = self.frames[self.frame_index]
        self.frame_results.append({"frame": frame, "initial_triangle_pairs": self.initial_pairs, "triangle_pairs": residual})
        if residual:
            raise SpringBoneError(f"第 {frame:g} 帧仍有 {residual} 对裙面穿插，未生成结果；请调整碰撞部位、权重或动作")
        poses = [self.armature.pose.bones[name] for name in self.names]
        bases = [pose.matrix_basis.copy() for pose in poses]
        try:
            for index, pose in enumerate(poses):
                pose.matrix_basis = Matrix.LocRotScale(Vector(locations[index]), rotations[index], Vector(self.sample.scales[index]))
            bpy.context.view_layer.update()
            actual, _normals, _triangles = _mesh_arrays(self.garment)
            actual_body, _normals, _triangles = _mesh_arrays(self.body)
            if float(np.linalg.norm(actual_body - self.sample_body_points, axis=1).max()) * self.scene.unit_settings.scale_length > 1e-6:
                raise SpringBoneError("身体依赖动态链，请先隔离并烘焙身体动作")
            error = float(np.linalg.norm(actual - self.sample.points(rotations, locations), axis=1).max())
            actual_pairs = triangle_crossings(actual, self.triangles, self.sample_body_points, self.body_triangles)
            if error * self.scene.unit_settings.scale_length > 1e-5 or actual_pairs:
                raise SpringBoneError(f"第 {frame:g} 帧实际蒙皮复核失败：误差 {error * self.scene.unit_settings.scale_length:.8f} 米，穿插 {actual_pairs} 对，未生成结果")
            self.frame_results[-1]["skin_prediction_error_m"] = error * self.scene.unit_settings.scale_length
            self.frame_results[-1]["maximum_rotation_delta_deg"] = max(math.degrees(base.rotation_difference(value).angle) for base, value in zip(self.sample.rotations, rotations))
            root_offsets = np.zeros_like(locations)
            for index in np.flatnonzero(self.sample.parents < 0):
                axes = (self.sample.armature_world @ self.sample.fixed_parents[index] @ self.sample.relative_rest[index])[:3, :3]
                root_offsets[index] = axes @ (locations[index] - self.sample.locations[index])
            self.frame_results[-1]["maximum_root_offset_m"] = float(np.linalg.norm(root_offsets, axis=1).max()) * self.scene.unit_settings.scale_length
        finally:
            for pose, basis in zip(poses, bases):
                pose.matrix_basis = basis
            bpy.context.view_layer.update()
        self.solutions.append((frame, [value.copy() for value in rotations], locations.copy()))
        self.previous_corrections = [(base.inverted() @ value).normalized() for base, value in zip(self.sample.rotations, rotations)]
        self.previous_world_offsets = root_offsets
        self.frame_index += 1
        self.search = None

    def _create_result(self):
        self.result_action = self.working_action.copy()
        self.result_action.name = self.entry_action.name + "_SkirtContact"
        self.result_action.use_fake_user = False
        bag = next(iter_channelbags(self.result_action, self.result_action.slots[0]), None)
        if bag is None:
            raise SpringBoneError("无法创建防穿修正动作槽")
        self.curves = {}
        self.location_curves = {}
        for name in self.names:
            pose = self.armature.pose.bones[name]
            for suffix in ("rotation_quaternion", "rotation_euler", "rotation_axis_angle"):
                path = pose.path_from_id(suffix)
                for curve in list(bag.fcurves):
                    if curve.data_path == path:
                        bag.fcurves.remove(curve)
            mode = self.entry_modes[name]
            path = pose.path_from_id("rotation_quaternion" if mode == "QUATERNION" else "rotation_euler")
            self.curves[name] = [bag.fcurves.new(path, index=index) for index in range(4 if mode == "QUATERNION" else 3)]
            if name in self.root_names:
                path = pose.path_from_id("location")
                for curve in list(bag.fcurves):
                    if curve.data_path == path:
                        bag.fcurves.remove(curve)
                self.location_curves[name] = [bag.fcurves.new(path, index=index) for index in range(3)]

    def _write_unit(self):
        if self.write_index >= len(self.solutions):
            for curves in (*self.curves.values(), *self.location_curves.values()):
                for curve in curves:
                    curve.update()
            self.phase = "publish"
            return
        frame, rotations, locations = self.solutions[self.write_index]
        for index, (name, rotation) in enumerate(zip(self.names, rotations)):
            mode = self.entry_modes[name]
            previous = self.previous_rotations.get(name)
            if mode == "QUATERNION":
                values = rotation.copy()
                if previous is not None and previous.dot(values) < 0.0:
                    values.negate()
            else:
                values = rotation.to_euler(mode, previous) if previous is not None else rotation.to_euler(mode)
            self.previous_rotations[name] = values.copy()
            for curve, value in zip(self.curves[name], values):
                point = curve.keyframe_points.insert(frame, float(value), options={"FAST"})
                point.interpolation = "LINEAR"
            for curve, value in zip(self.location_curves.get(name, ()), locations[index]):
                point = curve.keyframe_points.insert(frame, float(value), options={"FAST"})
                point.interpolation = "LINEAR"
        self.write_index += 1

    def _publish(self):
        action = self.result_action
        action["sb_generated"] = 1
        action["sb_skin_contact"] = 1
        action["sb_contact_triangle_pairs"] = 0
        action["sb_contact_frame_step"] = float(self.armature.sb_settings.contact_frame_step)
        action["fbx_sample_step"] = float(self.armature.sb_settings.contact_frame_step)
        action["sb_quaternion_sign_repairs"] = int(self.entry_action.get("sb_quaternion_sign_repairs", 0)) + sum(self.continuity_repairs.values())
        repaired_paths = set(str(self.entry_action.get("sb_quaternion_repaired_paths", "")).splitlines()) | set(self.continuity_repairs)
        action["sb_quaternion_repaired_paths"] = "\n".join(sorted(repaired_paths))
        action["sb_frame_start"], action["sb_frame_end"] = self.frame_start, self.frame_end
        action["sb_contact_input"] = self.entry_action.name
        action.use_fake_user = True
        self._restore_entry()
        self.armature.animation_data.action = action
        self.armature.animation_data.action_slot = action.slots[0]
        self.scene.frame_set(self.entry_frame[0], subframe=self.entry_frame[1])
        bpy.data.actions.remove(self.working_action)
        self.working_action = None
        self.armature.sb_settings.result_action_name = action.name
        self.armature.sb_settings.result_start, self.armature.sb_settings.result_end = self.frame_start, self.frame_end
        self.delivered = True
        self.finished = True
        self.phase = "done"

    def _restore_entry(self):
        if not self.captured or not self.restore_entry:
            return
        anim = self.armature.animation_data
        anim.action, anim.action_slot = self.entry_action, self.entry_slot
        self.scene.frame_set(self.entry_frame[0], subframe=self.entry_frame[1])
        for name, mode, basis in self.entry_poses:
            pose = self.armature.pose.bones.get(name)
            if pose is not None:
                pose.rotation_mode = mode
                pose.matrix_basis = basis
        bpy.context.view_layer.update()

    def cancel(self):
        if self.finished:
            return
        try:
            try:
                self._restore_entry()
            except ReferenceError:
                self.restore_entry = False
            if self.result_action is not None and not self.delivered:
                try:
                    bpy.data.actions.remove(self.result_action, do_unlink=True)
                except ReferenceError:
                    pass
                self.result_action = None
            if self.working_action is not None:
                try:
                    anim = self.armature.animation_data
                    if anim is not None and anim.action == self.working_action:
                        anim.action = self.entry_action
                        anim.action_slot = self.entry_slot
                except ReferenceError:
                    pass
                try:
                    bpy.data.actions.remove(self.working_action, do_unlink=True)
                except ReferenceError:
                    pass
                self.working_action = None
        finally:
            self.finished = True
            self.cancelled = True
            self.search = None

    def preview_still_valid(self):
        return False
