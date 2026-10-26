import bpy
from mathutils import Matrix

from .mounts import HumanoidMountError, ParentPose, is_mount, parent_at_world, validate_matrix, validate_mount, validate_parent_change, world_matrix
from .properties import SCHEMA


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
    desired = world_matrix(mount) if rule == "SNAP" else world_matrix(root)
    parent_at_world(root, mount, desired)


def detach_weapon(root):
    validate_grip(root)
    desired = world_matrix(root)
    parent_at_world(root, None, desired)
