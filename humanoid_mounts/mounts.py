import math

import bpy
from mathutils import Matrix

from .properties import PARTS, SCHEMA

MATRIX_TOLERANCE = 1e-5


class HumanoidMountError(RuntimeError):
    pass


def world_matrix(obj):
    bpy.context.view_layer.update()
    return obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).matrix_world.copy()


def matrix_distance(first, second):
    return max(abs(first[row][column] - second[row][column]) for row in range(4) for column in range(4))


def editable_object(obj):
    try:
        exists = obj is not None and bpy.data.objects.get(obj.name) == obj
    except ReferenceError:
        exists = False
    if not exists:
        raise HumanoidMountError("对象已失效")
    if obj.library is not None or obj.override_library is not None or not obj.is_editable:
        raise HumanoidMountError("请使用本地可编辑对象")
    if obj.name not in bpy.context.scene.objects:
        raise HumanoidMountError("对象不属于当前场景")


def validate_parent_change(obj):
    editable_object(obj)
    animation = obj.animation_data
    has_animation = animation is not None and (animation.action is not None or len(animation.drivers) > 0 or len(animation.nla_tracks) > 0)
    if has_animation or len(obj.constraints) or obj.rigid_body is not None:
        raise HumanoidMountError("对象含动画、驱动、约束或刚体，首批不迁移")
    validate_matrix(world_matrix(obj))
    validate_matrix(obj.matrix_basis)


def validate_matrix(matrix):
    if any(not math.isfinite(value) for row in matrix for value in row):
        raise HumanoidMountError("变换包含非有限值")
    determinant = matrix.to_3x3().determinant()
    if determinant <= 1e-12:
        raise HumanoidMountError("不支持奇异或反射变换")
    location, rotation, scale = matrix.decompose()
    reconstructed = Matrix.LocRotScale(location, rotation, scale)
    if matrix_distance(matrix, reconstructed) > MATRIX_TOLERANCE:
        raise HumanoidMountError("变换包含无法保持的剪切")


class ParentPose:
    def __init__(self, obj):
        self.obj = obj
        self.parent = obj.parent
        self.parent_type = obj.parent_type
        self.bone_name = obj.parent_bone
        self.inverse = obj.matrix_parent_inverse.copy()
        self.location = obj.location.copy()
        self.rotation_mode = obj.rotation_mode
        self.euler = obj.rotation_euler.copy()
        self.quaternion = obj.rotation_quaternion.copy()
        self.axis_angle = tuple(obj.rotation_axis_angle)
        self.scale = obj.scale.copy()
        self.delta_location = obj.delta_location.copy()
        self.delta_euler = obj.delta_rotation_euler.copy()
        self.delta_quaternion = obj.delta_rotation_quaternion.copy()
        self.delta_scale = obj.delta_scale.copy()

    def restore(self):
        obj = self.obj
        obj.parent = self.parent
        obj.parent_type = self.parent_type
        obj.parent_bone = self.bone_name
        obj.matrix_parent_inverse = self.inverse
        obj.rotation_mode = self.rotation_mode
        obj.location = self.location
        obj.rotation_euler = self.euler
        obj.rotation_quaternion = self.quaternion
        obj.rotation_axis_angle = self.axis_angle
        obj.scale = self.scale
        obj.delta_location = self.delta_location
        obj.delta_rotation_euler = self.delta_euler
        obj.delta_rotation_quaternion = self.delta_quaternion
        obj.delta_scale = self.delta_scale
        bpy.context.view_layer.update()


def validate_parent(obj, parent):
    ancestor = parent
    visited = set()
    while ancestor is not None:
        if ancestor == obj or ancestor in visited:
            raise HumanoidMountError("绑定会形成父级循环")
        visited.add(ancestor)
        ancestor = ancestor.parent


def parent_at_world(obj, parent, desired):
    validate_parent_change(obj)
    validate_matrix(desired)
    if parent is not None:
        editable_object(parent)
        validate_parent(obj, parent)
        parent_world = world_matrix(parent)
        validate_matrix(parent_world)
    basis = obj.matrix_basis.copy()
    validate_matrix(basis)
    saved = ParentPose(obj)
    try:
        obj.parent = parent
        obj.parent_type = "OBJECT"
        obj.parent_bone = ""
        obj.matrix_parent_inverse = Matrix.Identity(4)
        world_matrix(obj)
        obj.matrix_world = desired
        if matrix_distance(world_matrix(obj), desired) > MATRIX_TOLERANCE:
            raise HumanoidMountError("无法精确保留对象变换")
    except Exception:
        saved.restore()
        raise


def is_mount(obj):
    return obj is not None and obj.type == "EMPTY" and obj.get("hm_kind") == "MOUNT"


def mount_owner(obj):
    editable_object(obj)
    if not is_mount(obj) or obj.get("hm_schema") != SCHEMA:
        raise HumanoidMountError("请选择本插件的有效挂点")
    armature = obj.parent
    if armature is None or armature.type != "ARMATURE" or obj.parent_type != "BONE":
        raise HumanoidMountError("挂点已失去人形骨架归属")
    editable_object(armature)
    if obj.get("hm_part") not in {part[0] for part in PARTS}:
        raise HumanoidMountError("挂点部位无效")
    return armature


def validate_mount(obj):
    armature = mount_owner(obj)
    if obj.parent_bone not in armature.pose.bones:
        raise HumanoidMountError("挂点对应骨骼已不存在")
    validate_parent_change(obj)
    return armature


def mounts_for_armature(armature, part=None):
    if armature is None or armature.type != "ARMATURE":
        return []
    return sorted((obj for obj in armature.children if is_mount(obj) and (part is None or obj.get("hm_part") == part)), key=lambda obj: obj.name.casefold())


def create_mount(armature, bone_name, part):
    editable_object(armature)
    if armature.type != "ARMATURE" or bone_name not in armature.pose.bones:
        raise HumanoidMountError("请指定人形角色的实际骨骼")
    if part not in {item[0] for item in PARTS}:
        raise HumanoidMountError("不支持该人形部位")
    desired = world_matrix(armature) @ armature.evaluated_get(bpy.context.evaluated_depsgraph_get()).pose.bones[bone_name].matrix
    validate_matrix(desired)
    mount = bpy.data.objects.new("Mount_" + part, None)
    try:
        bpy.context.scene.collection.objects.link(mount)
        mount["hm_kind"] = "MOUNT"
        mount["hm_schema"] = SCHEMA
        mount["hm_part"] = part
        mount.parent = armature
        mount.parent_type = "BONE"
        mount.parent_bone = bone_name
        mount.matrix_parent_inverse = Matrix.Identity(4)
        mount.matrix_basis = Matrix.Identity(4)
        mount.empty_display_type = "ARROWS"
        mount.empty_display_size = 0.12
        mount.show_name = True
        mount.show_in_front = True
        parent_world = world_matrix(mount)
        mount.matrix_basis = parent_world.inverted() @ desired
        if matrix_distance(world_matrix(mount), desired) > MATRIX_TOLERANCE:
            raise HumanoidMountError("无法精确创建骨骼挂点")
        return mount
    except Exception:
        bpy.data.objects.remove(mount, do_unlink=True)
        raise


def rename_mount(mount, name):
    mount_owner(mount)
    cleaned = name.strip()
    if not cleaned:
        raise HumanoidMountError("挂点名称不能为空")
    mount.name = cleaned
    return mount.name


def copy_mount(mount):
    validate_mount(mount)
    desired = world_matrix(mount)
    copy = mount.copy()
    try:
        bpy.context.scene.collection.objects.link(copy)
        if matrix_distance(world_matrix(copy), desired) > MATRIX_TOLERANCE:
            raise HumanoidMountError("复制挂点变换不一致")
        return copy
    except Exception:
        bpy.data.objects.remove(copy, do_unlink=True)
        raise


def reanchor_mount(mount, bone_name):
    armature = mount_owner(mount)
    validate_parent_change(mount)
    if bone_name not in armature.pose.bones:
        raise HumanoidMountError("目标骨骼不存在")
    desired = world_matrix(mount)
    saved = ParentPose(mount)
    try:
        mount.parent_bone = bone_name
        mount.matrix_parent_inverse = Matrix.Identity(4)
        mount.matrix_basis = Matrix.Identity(4)
        parent_world = world_matrix(mount)
        validate_matrix(parent_world)
        mount.matrix_basis = parent_world.inverted() @ desired
        if matrix_distance(world_matrix(mount), desired) > MATRIX_TOLERANCE:
            raise HumanoidMountError("换骨骼后无法精确保留姿势")
    except Exception:
        saved.restore()
        raise


def reset_mount(mount):
    armature = validate_mount(mount)
    desired = world_matrix(armature) @ armature.evaluated_get(bpy.context.evaluated_depsgraph_get()).pose.bones[mount.parent_bone].matrix
    validate_matrix(desired)
    saved = ParentPose(mount)
    try:
        mount.matrix_world = desired
        if matrix_distance(world_matrix(mount), desired) > MATRIX_TOLERANCE:
            raise HumanoidMountError("无法恢复骨骼原点")
    except Exception:
        saved.restore()
        raise


def delete_mount(mount):
    mount_owner(mount)
    validate_parent_change(mount)
    children = tuple(mount.children)
    for child in children:
        validate_parent_change(child)
    saved = [(ParentPose(child), world_matrix(child)) for child in children]
    try:
        for pose, desired in saved:
            parent_at_world(pose.obj, None, desired)
        bpy.data.objects.remove(mount, do_unlink=True)
    except Exception:
        for pose, desired in saved:
            pose.restore()
        raise
