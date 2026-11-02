import ast
import json
import re
from collections import namedtuple
from pathlib import Path

import bpy

from . import equipment_orientation, mounts, placement, weapons

LibraryItem = namedtuple("LibraryItem", "name relative_path tier")


def scan_library(directory):
    directory = Path(directory).resolve()
    if not directory.is_dir():
        raise ValueError("目录不存在，请重新选择")
    names = {}
    config = directory / "config.json"
    if config.is_file():
        data = json.loads(config.read_text(encoding="utf-8-sig"))
        resource = data.get("resourceDir")
        if not resource:
            raise ValueError("config.json 缺少 resourceDir")
        resource = Path(resource)
        base = (resource if resource.is_absolute() else directory / resource).resolve() / "preview"
        source = directory / "preview" / "server.py"
        if source.is_file():
            tree = ast.parse(source.read_text(encoding="utf-8-sig"))
            for node in tree.body:
                if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "ITEM_NAMES" for target in node.targets):
                    names = ast.literal_eval(node.value)
                    break
        parts_only = True
    elif (directory / "preview" / "parts").is_dir():
        base = directory / "preview"
        parts_only = True
    else:
        base = directory
        parts_only = False
    if not base.is_dir():
        raise ValueError("资源目录不存在，请检查 resourceDir")
    search = base / "parts" if parts_only else base
    rows = []
    for path in sorted(search.rglob("*.glb")):
        relative = path.relative_to(base).as_posix()
        if "cache" in path.relative_to(base).parts or not path.resolve().is_relative_to(base.resolve()):
            continue
        match = re.search(r"(?:^|/)wp_a_(\d+)(_l|_m)?\.partsbnd/", relative, re.IGNORECASE)
        if parts_only and match is None:
            continue
        tier = {"_l": "lod", "_m": "menu"}.get(match[2], "std") if match else "std"
        name = names.get(match[1], "") if match else ""
        if match and path.stem.upper() in {"WP_A_0300_1", "WP_A_0301_1"}:
            name += "（剑鞘）"
        rows.append(LibraryItem((name + " " + path.stem).strip(), relative, tier))
    return base.resolve(), rows


def import_gltf(**kwargs):
    return bpy.ops.import_scene.gltf(**kwargs)


def load_equipment(context, base, relative_path, *, attach, orientation="ORIGINAL"):
    base = Path(base).resolve()
    path = (base / relative_path).resolve()
    if not path.is_relative_to(base):
        raise ValueError("道具路径超出资源目录")
    settings = context.scene.hm_settings
    placement.check_fitting_mode()
    if settings.fitting_stage != "NONE":
        raise mounts.HumanoidMountError("请先保存或取消当前设置")
    if attach:
        mounts.editable_object(settings.armature)
        if settings.armature.type != "ARMATURE":
            raise mounts.HumanoidMountError("请先选择角色")
        preferred = settings.mount
        if preferred is not None and (preferred.parent != settings.armature or preferred.get("hm_part") != settings.part):
            preferred = None
        mounts.mount_for_part(settings.armature, settings.part, preferred)
    previous = {kind: set(getattr(bpy.data, kind)) for kind in ("objects", "meshes", "materials", "images", "armatures", "actions", "collections")}
    selected = tuple(context.selected_objects)
    active = context.view_layer.objects.active
    saved = (settings.equipment, settings.grip, settings.mount, settings.mount_name, tuple(item.object for item in settings.equipment_parts))
    try:
        result = import_gltf(filepath=str(path))
        if result != {"FINISHED"}:
            raise ValueError("道具导入未完成")
        objects = set(bpy.data.objects) - previous["objects"]
        if not any(obj.type == "MESH" for obj in objects):
            raise ValueError("道具没有可显示的网格")
        for obj in objects:
            weapons.validate_rigid(obj)
        root = bpy.data.objects.new("GripRoot_" + path.stem, None)
        context.scene.collection.objects.link(root)
        root.empty_display_type = "ARROWS"
        root.empty_display_size = 0.1
        for obj in objects:
            if obj.parent not in objects:
                mounts.parent_at_world(obj, root, mounts.world_matrix(obj))
        for obj in root.children:
            obj["hm_library_initial_matrix"] = [value for row in obj.matrix_local for value in row]
        weapons.register_grip_root(root)
        root["hm_source_file"] = str(path)
        if settings.armature is not None:
            root["hm_library_owner"] = settings.armature
        if attach:
            mount = weapons.equip_weapon(root, settings.armature, settings.part, preferred)
            settings.mount = mount
            settings.mount_name = mount.name
        equipment_orientation.apply_preset(root, orientation, settings.part)
        placement.select_equipment(settings, (root,), root)
        for obj in context.selected_objects:
            obj.select_set(False)
        for obj in root.children_recursive:
            if obj.type == "MESH":
                obj.select_set(True)
        root.select_set(True)
        context.view_layer.objects.active = root
        return root
    except Exception:
        for obj in tuple(bpy.data.objects):
            if obj not in previous["objects"]:
                bpy.data.objects.remove(obj, do_unlink=True)
        for kind in ("collections", "meshes", "armatures", "materials", "images", "actions"):
            collection = getattr(bpy.data, kind)
            for item in tuple(collection):
                if item not in previous[kind] and item.users == 0:
                    collection.remove(item)
        settings.equipment, settings.grip, settings.mount, settings.mount_name = saved[:4]
        settings.equipment_parts.clear()
        for obj in saved[4]:
            settings.equipment_parts.add().object = obj
        for obj in context.selected_objects:
            obj.select_set(False)
        for obj in selected:
            obj.select_set(True)
        context.view_layer.objects.active = active
        raise


def clear_character_equipment(settings):
    placement.check_fitting_mode()
    if settings.fitting_stage != "NONE":
        raise mounts.HumanoidMountError("请先保存或取消当前设置")
    armature = settings.armature
    mounts.editable_object(armature)
    if armature.type != "ARMATURE":
        raise mounts.HumanoidMountError("请先选择角色")
    points = mounts.mounts_for_armature(armature)
    roots = {obj for point in points for obj in point.children}
    roots.update(obj for obj in bpy.context.scene.objects if obj.parent is None and obj.get("hm_kind") == "GRIP" and obj.get("hm_source_file") and obj.get("hm_library_owner") == armature)
    objects = {obj for root in roots for obj in (root, *root.children_recursive)}
    for point in points:
        mounts.mount_owner(point)
    for obj in objects:
        weapons.validate_rigid(obj)
        if any(scene != bpy.context.scene for scene in obj.users_scene):
            raise mounts.HumanoidMountError("附件被其他场景共用，不能自动清理")
    meshes = {obj.data for obj in objects if obj.type == "MESH"}
    clears_equipment = settings.equipment in objects
    clears_grip = settings.grip in objects
    bpy.data.batch_remove(ids=objects)
    for mesh in meshes:
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)
    if clears_equipment:
        settings.equipment = None
        settings.equipment_parts.clear()
    if clears_grip:
        settings.grip = None
    return len(roots)
