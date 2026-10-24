import math
from contextlib import contextmanager

import bpy
from bpy_extras.anim_utils import BakeOptions, bake_action_objects
from mathutils import Matrix

from .classify import classify_armature, classify_by_name
from .retarget import ACTION_SEP, _assign_action

APOSE_ARM_ANGLE = math.radians(45.0)


class AposeExportError(RuntimeError):
    pass


@contextmanager
def apose_model_reference(arm):
    reference = arm.get("hr_fbx_default_pose")
    anim = arm.animation_data_create()
    action, slot, use_nla = anim.action, anim.action_slot, anim.use_nla
    pose_position = arm.data.pose_position
    channels = _apose_source_channels(arm)
    try:
        anim.action = None
        anim.use_nla = False
        arm.data.pose_position = "POSE"
        for name, values in reference.items():
            bone = arm.pose.bones[name]
            for field, value in values.items():
                setattr(bone, field, value)
        bpy.context.view_layer.update()
        yield
    finally:
        anim.action = action
        if action is not None:
            anim.action_slot = slot
        anim.use_nla = use_nla
        arm.data.pose_position = pose_position
        _restore_apose_source_channels(channels)


def _apose_source_channels(source):
    return [(obj, obj.location.copy(), obj.rotation_euler.copy(), obj.rotation_quaternion.copy(),
             tuple(obj.rotation_axis_angle), obj.scale.copy()) for obj in [source, *source.pose.bones]]


def _restore_apose_source_channels(channels):
    for obj, location, euler, quaternion, axis_angle, scale in channels:
        obj.location = location
        obj.rotation_euler = euler
        obj.rotation_quaternion = quaternion
        obj.rotation_axis_angle = axis_angle
        obj.scale = scale


@contextmanager
def apose_animation_actions(source, target, actions):
    scene = bpy.context.scene
    frame, subframe = scene.frame_current, scene.frame_subframe
    had_animation = source.animation_data is not None
    anim = source.animation_data_create()
    if anim.use_tweak_mode:
        raise AposeExportError("请先退出动画条带编辑模式，再导出。")
    original_action, original_slot = anim.action, anim.action_slot
    original_nla = anim.use_nla
    original_pose = source.data.pose_position
    channels = _apose_source_channels(source)
    constraints = []
    created = []
    options = BakeOptions(only_selected=False, do_pose=True, do_object=False,
                          do_visual_keying=True, do_constraint_clear=False, do_parents_clear=False,
                          do_clean=False, do_location=True, do_rotation=True, do_scale=True,
                          do_bbone=False, do_custom_props=False)
    try:
        try:
            source.data.pose_position = "POSE"
            anim.use_nla = False
            for bone in target.pose.bones:
                constraint = bone.constraints.new("COPY_TRANSFORMS")
                constraints.append((bone, constraint))
                constraint.target = source
                constraint.subtarget = bone.name
                constraint.target_space = "POSE"
                constraint.owner_space = "POSE"
            for action in actions:
                _restore_apose_source_channels(channels)
                _assign_action(source, action)
                if action == original_action:
                    anim.action_slot = original_slot
                start, end = action.frame_range
                first, last = round(start), round(end)
                if abs(start - first) > 1e-6 or abs(end - last) > 1e-6:
                    raise AposeExportError("A-Pose 动画转换需要已烘焙的整数帧动作: " + action.name)
                baked = bpy.data.actions.new("APose_" + action.name)
                created.append(baked)
                baked["hr_export_clip_name"] = action.name
                result = bake_action_objects([(target, baked)], frames=range(first, last + 1), bake_options=options)
                if not result or result[0] != baked:
                    raise AposeExportError("A-Pose 动画转换失败: " + action.name)
        finally:
            for bone, constraint in reversed(constraints):
                bone.constraints.remove(constraint)
            anim.action = original_action
            if original_action is not None:
                anim.action_slot = original_slot
            anim.use_nla = original_nla
            source.data.pose_position = original_pose
            _restore_apose_source_channels(channels)
            if not had_animation:
                source.animation_data_clear()
            scene.frame_set(frame, subframe=subframe)
        target["hr_actions"] = ACTION_SEP.join(action.name for action in created)
        _assign_action(target, created[0])
        target.animation_data.use_nla = False
        yield
    finally:
        for action in reversed(created):
            bpy.data.actions.remove(action)


def _remove_apose_copy(obj):
    data = obj.data
    kind = obj.type
    bpy.data.objects.remove(obj, do_unlink=True)
    if data is not None and data.users == 0:
        if kind == "MESH":
            bpy.data.meshes.remove(data)
        elif kind == "ARMATURE":
            bpy.data.armatures.remove(data)


def _apose_arm_directions(arm, roles):
    required = ("hips", "head", "upperarm_l", "forearm_l", "hand_l",
                "upperarm_r", "forearm_r", "hand_r")
    missing = [role for role in required if role not in roles]
    if missing:
        raise AposeExportError("A-Pose 缺少人体骨骼映射: " + ", ".join(missing))
    bones = arm.data.bones
    lateral = bones[roles["upperarm_l"]].head_local - bones[roles["upperarm_r"]].head_local
    up = bones[roles["head"]].head_local - bones[roles["hips"]].head_local
    if lateral.length < 1e-8 or up.length < 1e-8:
        raise AposeExportError("无法确定 A-Pose 的人体方向。")
    lateral.normalize()
    up -= lateral * up.dot(lateral)
    if up.length < 1e-8:
        raise AposeExportError("人体躯干和双臂方向重合，无法生成 A-Pose。")
    up.normalize()
    return {"l": lateral * math.cos(APOSE_ARM_ANGLE) - up * math.sin(APOSE_ARM_ANGLE),
            "r": -lateral * math.cos(APOSE_ARM_ANGLE) - up * math.sin(APOSE_ARM_ANGLE)}


def _pose_apose_arms(arm, roles, directions):
    arm.animation_data_clear()
    arm.data.pose_position = "POSE"
    for constraint in list(arm.constraints):
        arm.constraints.remove(constraint)
    for bone in arm.pose.bones:
        for constraint in list(bone.constraints):
            bone.constraints.remove(constraint)
        bone.matrix_basis = Matrix.Identity(4)
    bpy.context.view_layer.update()
    for side, direction in directions.items():
        for role in ("upperarm", "forearm", "hand"):
            bone = arm.pose.bones[roles[f"{role}_{side}"]]
            current = bone.tail - bone.head
            if current.length < 1e-8:
                raise AposeExportError("A-Pose 骨骼长度为零: " + bone.name)
            rotation = current.rotation_difference(direction).to_matrix().to_4x4()
            pivot = Matrix.Translation(bone.head)
            bone.matrix = pivot @ rotation @ pivot.inverted_safe() @ bone.matrix
            bpy.context.view_layer.update()


def _apose_mesh_coordinates(obj):
    skin_copy = obj.copy()
    try:
        skin_copy.data = obj.data.copy()
        bpy.context.scene.collection.objects.link(skin_copy)
        skin_copy_keys = skin_copy.data.shape_keys
        skin_copy_key_name = skin_copy_keys.name if skin_copy_keys else None
        if skin_copy_keys is not None and skin_copy_keys == obj.data.shape_keys:
            raise AposeExportError("A-Pose 形态键副本未隔离: " + obj.name)
        skin_copy.shape_key_clear()
        if skin_copy_key_name:
            detached_keys = bpy.data.shape_keys.get(skin_copy_key_name)
            if detached_keys is not None:
                bpy.data.batch_remove(ids=[detached_keys])
        for modifier in skin_copy.modifiers:
            if modifier.type != "ARMATURE":
                modifier.show_viewport = False
                modifier.show_render = False
        keys = obj.data.shape_keys
        sources = list(keys.key_blocks) if keys else [obj.data]
        results = []
        for source in sources:
            points = source.data if keys else source.vertices
            coordinates = [0.0] * (len(points) * 3)
            points.foreach_get("co", coordinates)
            skin_copy.data.vertices.foreach_set("co", coordinates)
            skin_copy.data.update()
            bpy.context.view_layer.update()
            depsgraph = bpy.context.evaluated_depsgraph_get()
            evaluated = skin_copy.evaluated_get(depsgraph)
            mesh = evaluated.to_mesh()
            try:
                if len(mesh.vertices) != len(points):
                    raise AposeExportError("A-Pose 蒙皮评估改变了顶点数量: " + obj.name)
                mesh.vertices.foreach_get("co", coordinates)
                results.append(coordinates)
            finally:
                evaluated.to_mesh_clear()
        return results
    finally:
        _remove_apose_copy(skin_copy)


def _bake_apose_mesh(obj):
    coordinates = _apose_mesh_coordinates(obj)
    obj.data.vertices.foreach_set("co", coordinates[0])
    keys = obj.data.shape_keys
    if keys:
        keys.animation_data_clear()
        for key, values in zip(keys.key_blocks, coordinates):
            key.data.foreach_set("co", values)
            key.value = 0.0
    obj.data.update()


@contextmanager
def apose_export_objects(source, bind_apose=True):
    roles = classify_armature(source)
    roles.update(classify_by_name(source))
    directions = _apose_arm_directions(source, roles)
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"
              and any(modifier.type == "ARMATURE" and modifier.object == source for modifier in obj.modifiers)]
    if not meshes:
        raise AposeExportError("目标骨架没有可导出的蒙皮网格。")
    active = bpy.context.view_layer.objects.active
    mode = active.mode if active else "OBJECT"
    selected = list(bpy.context.selected_objects)
    channels = _apose_source_channels(source)
    created = []
    try:
        if active is not None and mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        arm = source.copy()
        created.append(arm)
        arm.data = source.data.copy()
        arm.name = source.name + "_APose"
        arm.parent = None
        arm.matrix_world = source.matrix_world.copy()
        arm.location = (0.0, 0.0, 0.0)
        arm.hide_viewport = False
        arm.hide_render = False
        arm.hide_select = False
        if "hr_actions" in arm:
            del arm["hr_actions"]
        bpy.context.scene.collection.objects.link(arm)
        original_channels = _apose_source_channels(arm)
        _pose_apose_arms(arm, roles, directions)
        if not bind_apose:
            arm["hr_fbx_default_pose"] = {
                bone.name: {field: list(getattr(bone, field)) for field in
                            ("location", "rotation_euler", "rotation_quaternion", "rotation_axis_angle", "scale")}
                for bone in arm.pose.bones}
            _restore_apose_source_channels(original_channels)
        for source_mesh in meshes:
            obj = source_mesh.copy()
            created.append(obj)
            obj.data = source_mesh.data.copy()
            obj.name = source_mesh.name + "_APose"
            obj.animation_data_clear()
            obj.parent = arm
            obj.parent_type = "OBJECT"
            obj.matrix_world = source_mesh.matrix_world.copy()
            obj.matrix_world.translation -= source.matrix_world.translation
            obj.hide_viewport = False
            obj.hide_render = False
            obj.hide_select = False
            for modifier in obj.modifiers:
                if modifier.type == "ARMATURE" and modifier.object == source:
                    modifier.object = arm
                    modifier.show_viewport = True
                    modifier.show_render = True
                elif modifier.type == "ARMATURE":
                    raise AposeExportError("A-Pose 暂不支持多个骨架共同蒙皮: " + source_mesh.name)
            bpy.context.scene.collection.objects.link(obj)
            if bind_apose:
                _bake_apose_mesh(obj)
        if bind_apose:
            for obj in bpy.context.selected_objects:
                obj.select_set(False)
            arm.select_set(True)
            bpy.context.view_layer.objects.active = arm
            bpy.ops.object.mode_set(mode="POSE")
            bpy.ops.pose.armature_apply(selected=False)
            bpy.ops.object.mode_set(mode="OBJECT")
            bpy.context.view_layer.update()
            for side, direction in directions.items():
                for role in ("upperarm", "forearm", "hand"):
                    bone = arm.data.bones[roles[f"{role}_{side}"]]
                    actual = (bone.tail_local - bone.head_local).normalized()
                    if actual.dot(direction) < 1.0 - 1e-5:
                        raise AposeExportError("A-Pose 静止姿态未通过校验: " + bone.name)
        yield arm
    finally:
        current = bpy.context.view_layer.objects.active
        if current is not None and current.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        for obj in reversed(created):
            _remove_apose_copy(obj)
        for obj in bpy.context.selected_objects:
            obj.select_set(False)
        for obj in selected:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = active
        if active is not None and mode != "OBJECT":
            bpy.ops.object.mode_set(mode=mode)
        _restore_apose_source_channels(channels)
