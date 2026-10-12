"""Import, auto-rig, retarget and export helpers used by the addon operators."""

from __future__ import annotations

import os

import bpy

from .autorig import AutoRigError, auto_rig_meshes
from .classify import CORE_ROLES, classify_armature
from .retarget import ACTION_SEP, RetargetError, bake_retarget, collect_actions

SOURCE_EXTS = {".fbx", ".glb", ".gltf", ".bvh"}
TARGET_EXTS = {".fbx", ".glb", ".gltf", ".obj"}
EXPORT_EXTS = {".fbx", ".glb", ".gltf"}


class PipelineError(RuntimeError):
    pass


def _call_op(operator, **wanted):
    allowed = set(operator.get_rna_type().properties.keys())
    kwargs = {key: value for key, value in wanted.items() if key in allowed}
    return operator(**kwargs)


def ensure_object_mode():
    active = bpy.context.object
    if active is not None and active.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")


def move_to_collection(objects, collection_name):
    collection = bpy.data.collections.get(collection_name)
    if collection is None:
        collection = bpy.data.collections.new(collection_name)
    if collection.name not in bpy.context.scene.collection.children:
        bpy.context.scene.collection.children.link(collection)
    for obj in objects:
        if obj is None or obj.name not in bpy.data.objects:
            continue
        for owner in list(obj.users_collection):
            owner.objects.unlink(obj)
        collection.objects.link(obj)
    return collection


def import_model(path, automatic_bone_orientation=False):
    ext = os.path.splitext(path)[1].lower()
    if ext not in SOURCE_EXTS | TARGET_EXTS:
        raise PipelineError("不支持的文件格式: " + ext)
    ensure_object_mode()
    before_objects = set(bpy.data.objects)
    before_actions = set(bpy.data.actions)
    if ext == ".fbx":
        extra = {}
        if automatic_bone_orientation:
            extra["automatic_bone_orientation"] = True
        _call_op(bpy.ops.import_scene.fbx, filepath=path, **extra)
    elif ext in {".glb", ".gltf"}:
        _call_op(bpy.ops.import_scene.gltf, filepath=path)
    elif ext == ".obj":
        _call_op(bpy.ops.wm.obj_import, filepath=path)
    elif ext == ".bvh":
        _call_op(bpy.ops.import_anim.bvh, filepath=path)
    else:
        raise PipelineError("不支持的文件格式: " + ext)
    objects = [obj for obj in bpy.data.objects if obj not in before_objects]
    actions = [action for action in bpy.data.actions if action not in before_actions]
    return objects, actions


def pick_armature(objects):
    armatures = [obj for obj in objects if obj.type == "ARMATURE"]
    if not armatures:
        return None

    def score(obj):
        animated = 1 if obj.animation_data and obj.animation_data.action else 0
        return (animated, len(obj.data.bones))

    return max(armatures, key=score)


def remember_source(arm_obj, actions):
    names = []
    for action in actions:
        if action is not None and action.name not in names:
            names.append(action.name)
    if arm_obj.animation_data and arm_obj.animation_data.action:
        current = arm_obj.animation_data.action.name
        if current not in names:
            names.insert(0, current)
    arm_obj["hr_role"] = "source"
    arm_obj["hr_actions"] = ACTION_SEP.join(names)


def _is_helper_sphere(obj) -> bool:
    """A standalone mesh that is basically a ball, not a character body."""
    if obj is None or obj.type != "MESH" or obj.data is None:
        return False
    verts = obj.data.vertices
    count = len(verts)
    if count < 12 or count > 4000:
        return False
    xs = [vertex.co.x for vertex in verts]
    ys = [vertex.co.y for vertex in verts]
    zs = [vertex.co.z for vertex in verts]
    size = (max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))
    longest = max(size)
    if longest < 1e-5:
        return False
    if min(size) / longest < 0.7:
        return False
    center = ((max(xs) + min(xs)) * 0.5, (max(ys) + min(ys)) * 0.5, (max(zs) + min(zs)) * 0.5)
    radii = []
    for vertex in verts:
        dx = vertex.co.x - center[0]
        dy = vertex.co.y - center[1]
        dz = vertex.co.z - center[2]
        radii.append((dx * dx + dy * dy + dz * dz) ** 0.5)
    mean = sum(radii) / len(radii)
    if mean < 1e-5:
        return False
    deviation = (sum((radius - mean) ** 2 for radius in radii) / len(radii)) ** 0.5
    return deviation / mean < 0.35


def _sphere_objects(armature):
    found = []
    seen = set()

    def add(obj):
        if obj is None or obj == armature or obj.name in seen:
            return
        seen.add(obj.name)
        found.append(obj)

    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        parented = obj.parent == armature or getattr(obj, "parent_type", "") == "BONE" and obj.parent == armature
        skinned = any(
            mod.type == "ARMATURE" and getattr(mod, "object", None) == armature
            for mod in obj.modifiers
        )
        if parented or skinned:
            add(obj)
    if armature.pose:
        for pose_bone in armature.pose.bones:
            add(pose_bone.custom_shape)
    return found


def set_bone_sphere_display(armature, show: bool) -> None:
    """Hide imported bone-shape spheres. The real character mesh stays visible."""
    if armature is None or getattr(armature, "type", None) != "ARMATURE":
        return
    data = armature.data
    if not show:
        if "hr_display_type" not in armature:
            armature["hr_display_type"] = data.display_type
        if "hr_custom_shapes" not in armature:
            armature["hr_custom_shapes"] = bool(data.show_bone_custom_shapes)
        data.show_bone_custom_shapes = False
        if data.display_type == "ENVELOPE":
            data.display_type = "OCTAHEDRAL"
        hidden = []
        for obj in _sphere_objects(armature):
            if not _is_helper_sphere(obj):
                continue
            if not obj.hide_viewport:
                hidden.append(obj.name)
            obj.hide_viewport = True
            try:
                obj.hide_set(True)
            except RuntimeError:
                pass
        armature["hr_hidden_sphere_objects"] = "\n".join(hidden)
        return

    saved_display = armature.get("hr_display_type")
    if saved_display in {"OCTAHEDRAL", "STICK", "BBONE", "ENVELOPE", "WIRE"}:
        data.display_type = saved_display
    if "hr_custom_shapes" in armature:
        data.show_bone_custom_shapes = bool(armature["hr_custom_shapes"])
    for name in str(armature.get("hr_hidden_sphere_objects", "")).split("\n"):
        obj = bpy.data.objects.get(name) if name else None
        if obj is None:
            continue
        obj.hide_viewport = False
        try:
            obj.hide_set(False)
        except RuntimeError:
            pass


def load_source(path, automatic_bone_orientation=False):
    objects, actions = import_model(path, automatic_bone_orientation=automatic_bone_orientation)
    armature = pick_armature(objects)
    if armature is None:
        raise PipelineError("这个文件里没有骨架。动画来源需要带骨骼和动画。")
    remember_source(armature, actions)
    move_to_collection(objects, "HR_Source")
    clip_count = len(collect_actions(armature))
    summary = f"已导入动画来源: {armature.name}，{len(armature.data.bones)} 根骨骼，{clip_count} 个动作"
    return armature, summary


def _usable_armature(arm_obj, meshes):
    if arm_obj is None:
        return False
    roles = classify_armature(arm_obj)
    core = sum(1 for role in CORE_ROLES if role in roles)
    if core >= 4:
        return True
    return not meshes


def load_target_and_retarget(path, source, options=None):
    if source is None or source.type != "ARMATURE":
        raise PipelineError("请先导入含动画的来源模型。")
    objects, _actions = import_model(path)
    meshes = [obj for obj in objects if obj.type == "MESH"]
    armature = pick_armature(objects)
    auto = False
    if _usable_armature(armature, meshes):
        note = "目标自带骨架，已直接映射"
    else:
        if not meshes:
            raise PipelineError("目标文件里没有网格，也没有可识别的人形骨架。")
        try:
            armature, weight_mode, _landmarks = auto_rig_meshes(meshes)
        except AutoRigError as exc:
            raise PipelineError(str(exc)) from exc
        objects = list(objects) + [armature]
        auto = True
        note = f"目标没有可用骨架，已按 T/A Pose 自动绑定（{weight_mode}）"
    move_to_collection(objects, "HR_Target")
    try:
        report, baked = bake_retarget(source, armature, options)
    except RetargetError as exc:
        raise PipelineError(str(exc)) from exc
    armature["hr_role"] = "target"
    summary = note + "\n" + report
    return armature, summary, baked, auto


def retarget_existing(source, target, options=None):
    try:
        report, baked = bake_retarget(source, target, options)
    except RetargetError as exc:
        raise PipelineError(str(exc)) from exc
    target["hr_role"] = "target"
    return report, baked


def retarget_selected_meshes(source, meshes, options=None):
    if not meshes:
        raise PipelineError("请先选中要绑定的人体网格。")
    try:
        armature, weight_mode, _landmarks = auto_rig_meshes(meshes)
    except AutoRigError as exc:
        raise PipelineError(str(exc)) from exc
    move_to_collection([armature, *meshes], "HR_Target")
    report, baked = retarget_existing(source, armature, options)
    summary = f"已按 T/A Pose 自动绑定（{weight_mode}）\n" + report
    return armature, summary, baked


def _select_hierarchy(arm_obj):
    ensure_object_mode()
    for obj in bpy.context.view_layer.objects:
        obj.select_set(False)
    arm_obj.select_set(True)
    bpy.context.view_layer.objects.active = arm_obj
    for obj in bpy.context.scene.objects:
        parent = obj.parent
        if parent == arm_obj or (parent is not None and parent.parent == arm_obj):
            obj.select_set(True)


def _export_fbx_with_rest_bind(path):
    """Blender writes the current pose into the FBX bone node.

    Animation curves are sampled earlier in the exporter. Switching to the
    rest pose only while bone nodes are written keeps the clip and the bind
    pose apart.
    """
    import io_scene_fbx.export_fbx_bin as export_bin

    original = export_bin.fbx_data_object_elements
    touched = []

    def wrapped(root, ob_obj, scene_data):
        arm_obj = None
        if getattr(ob_obj, "is_bone", False):
            arm_obj = getattr(ob_obj, "_ref", None)
        elif getattr(ob_obj, "type", None) == "ARMATURE":
            arm_obj = ob_obj.bdata
        if arm_obj is not None and getattr(arm_obj, "type", None) == "ARMATURE":
            if arm_obj.data.pose_position != "REST":
                touched.append((arm_obj, arm_obj.data.pose_position))
                arm_obj.data.pose_position = "REST"
                bpy.context.view_layer.update()
        return original(root, ob_obj, scene_data)

    export_bin.fbx_data_object_elements = wrapped
    try:
        _call_op(
            bpy.ops.export_scene.fbx,
            filepath=path,
            use_selection=True,
            bake_anim=True,
            bake_anim_use_all_actions=True,
            bake_anim_use_nla_strips=False,
            add_leaf_bones=False,
            object_types={"ARMATURE", "MESH"},
        )
    finally:
        export_bin.fbx_data_object_elements = original
        for arm_obj, pose_position in touched:
            arm_obj.data.pose_position = pose_position


def export_armature(arm_obj, path):
    if arm_obj is None or arm_obj.type != "ARMATURE":
        raise PipelineError("还没有可导出的目标骨架。")
    ext = os.path.splitext(path)[1].lower()
    if ext not in EXPORT_EXTS:
        raise PipelineError("导出格式请使用 .glb、.gltf 或 .fbx。")
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    _select_hierarchy(arm_obj)
    if ext == ".fbx":
        _export_fbx_with_rest_bind(path)
    else:
        export_format = "GLB" if ext == ".glb" else "GLTF_SEPARATE"
        try:
            _call_op(
                bpy.ops.export_scene.gltf,
                filepath=path,
                use_selection=True,
                export_format=export_format,
                export_animations=True,
                export_animation_mode="ACTIONS",
                export_nla_strips=False,
                export_anim_single_armature=False,
                export_rest_position_armature=True,
            )
        except Exception as exc:
            print("[HumanoidRetarget] glTF export retry:", exc)
            _call_op(
                bpy.ops.export_scene.gltf,
                filepath=path,
                use_selection=True,
                export_format=export_format,
                export_animations=True,
            )
    return path
