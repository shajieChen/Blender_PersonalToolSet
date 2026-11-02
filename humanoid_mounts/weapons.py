import bpy
from mathutils import Matrix

from .mounts import HumanoidMountError, ParentPose, is_mount, parent_at_world, validate_matrix, validate_mount, validate_parent_change, world_matrix
from .properties import SCHEMA
from . import bone_roles, mounts


def validate_rigid(obj):
    validate_parent_change(obj)
    if obj.type not in {"EMPTY", "MESH"} or is_mount(obj):
        raise HumanoidMountError("请选择刚性武器部件或握持根")
    if obj.type == "MESH" and any(modifier.type == "ARMATURE" for modifier in obj.modifiers):
        raise HumanoidMountError("首批不处理带骨架蒙皮的武器")


def validate_grip(obj):
    validate_rigid(obj)
    if obj.type != "EMPTY" or obj.get("hm_kind") != "GRIP" or obj.get("hm_schema") != SCHEMA:
        raise HumanoidMountError("请选择已创建或登记的武器握持根")
    if obj.parent is not None:
        if not is_mount(obj.parent):
            raise HumanoidMountError("握持根具有外部父级，请先明确处理")
    for child in obj.children_recursive:
        validate_rigid(child)


def register_grip_root(root):
    validate_rigid(root)
    if root.type != "EMPTY" or root.parent is not None:
        raise HumanoidMountError("请选择没有外部父级的握持 Empty")
    if root.get("hm_kind") not in {None, "GRIP"} or root.get("hm_schema") not in {None, SCHEMA}:
        raise HumanoidMountError("对象标记不兼容，不能覆盖登记")
    for child in root.children_recursive:
        validate_rigid(child)
    root["hm_kind"] = "GRIP"
    root["hm_schema"] = SCHEMA


def prepare_grip_root(parts, anchor):
    parts = tuple(parts)
    if not parts or len(set(parts)) != len(parts):
        raise HumanoidMountError("请选择不重复的刚性武器部件")
    validate_matrix(anchor)
    for part in parts:
        validate_rigid(part)
        if part.parent is not None or part.children:
            raise HumanoidMountError("部件已有父子层级，首批不自动迁移")
    poses = [(ParentPose(part), world_matrix(part)) for part in parts]
    root = bpy.data.objects.new("GripRoot_" + parts[0].name, None)
    try:
        bpy.context.scene.collection.objects.link(root)
        root["hm_kind"] = "GRIP"
        root["hm_schema"] = SCHEMA
        root.matrix_world = anchor
        root.empty_display_type = "ARROWS"
        root.empty_display_size = 0.1
        root.show_in_front = True
        root.show_name = False
        world_matrix(root)
        for pose, desired in poses:
            parent_at_world(pose.obj, root, desired)
        return root
    except Exception:
        for pose, desired in poses:
            pose.restore()
        bpy.data.objects.remove(root, do_unlink=True)
        raise


def bind_weapon(root, mount, rule):
    validate_grip(root)
    validate_mount(mount)
    if rule not in {"SNAP", "KEEP_WORLD"}:
        raise HumanoidMountError("绑定规则无效")
    if root.parent is not None and root.parent != mount:
        raise HumanoidMountError("武器已绑定到其他挂点，请先解除")
    mounts.validate_parent(root, mount)
    if rule == "SNAP":
        _snap_grip_to_mount(root, mount)
    else:
        parent_at_world(root, mount, world_matrix(root))


def _snap_grip_to_mount(root, mount):
    saved = ParentPose(root)
    try:
        root.parent = mount
        root.parent_type = "OBJECT"
        root.parent_bone = ""
        root.matrix_parent_inverse = Matrix.Identity(4)
        root.delta_location = (0, 0, 0)
        root.delta_rotation_euler = (0, 0, 0)
        root.delta_rotation_quaternion = (1, 0, 0, 0)
        root.delta_scale = (1, 1, 1)
        root.matrix_basis = Matrix.Identity(4)
        if mounts.matrix_distance(world_matrix(root), world_matrix(mount)) > mounts.MATRIX_TOLERANCE:
            raise HumanoidMountError("道具未贴合目标挂点，已恢复")
    except Exception:
        saved.restore()
        raise


def detach_weapon(root):
    validate_grip(root)
    desired = world_matrix(root)
    parent_at_world(root, None, desired)


def find_grip_root(obj):
    candidates = []
    visited = set()
    while obj is not None:
        if obj in visited:
            raise HumanoidMountError("武器父级存在循环")
        visited.add(obj)
        if obj.get("hm_kind") == "GRIP":
            candidates.append(obj)
        obj = obj.parent
    if len(candidates) > 1:
        raise HumanoidMountError("装备存在多层拿法记录，请在高级设置中处理")
    return candidates[0] if candidates else None


def grip_from_object(obj):
    root = find_grip_root(obj)
    if root is None:
        raise HumanoidMountError("请选择已校准武器；首次使用请在自定义中创建握持根")
    validate_grip(root)
    return root


def equip_weapon(root, armature, part, preferred_mount=None):
    validate_grip(root)
    mounts.editable_object(armature)
    if armature.type != "ARMATURE" or part not in bone_roles.PART_ROLES:
        raise HumanoidMountError("请选择人形角色和有效部位")
    mount = mounts.mount_for_part(armature, part, preferred_mount)
    if root.parent is not None and root.parent != mount:
        raise HumanoidMountError("武器已绑定到其他挂点，请先解除")
    if mount is not None:
        validate_mount(mount)
    saved = ParentPose(root)
    created = False
    try:
        if mount is None:
            bone_name = bone_roles.resolve_bone(armature, part)
            mount = mounts.create_mount(armature, bone_name, part)
            created = True
        bind_weapon(root, mount, "SNAP")
        return mount
    except Exception:
        saved.restore()
        if created:
            bpy.data.objects.remove(mount, do_unlink=True)
        raise


def remember_grip(root, mount):
    validate_grip(root)
    validate_mount(mount)
    if root.parent is not None and root.parent != mount:
        raise HumanoidMountError("装备已在其他位置，请先取下")
    children = tuple(root.children)
    saved = [ParentPose(obj) for obj in (root,) + children]
    desired = [world_matrix(obj) for obj in children]
    try:
        bind_weapon(root, mount, "SNAP")
        for child, world in zip(children, desired):
            parent_at_world(child, root, world)
    except Exception:
        for pose in saved:
            pose.restore()
        raise
