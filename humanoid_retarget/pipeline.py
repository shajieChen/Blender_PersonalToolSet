"""Import, auto-rig, retarget and export helpers used by the addon operators."""

from __future__ import annotations

import os

import bpy

from .autorig import AutoRigError, auto_rig_meshes
from .classify import CORE_ROLES, classify_armature
from .retarget import ACTION_SEP, RetargetError, RetargetOptions, bake_retarget, collect_actions

SOURCE_EXTS = {".fbx", ".glb", ".gltf", ".bvh"}
TARGET_EXTS = {".fbx", ".glb", ".gltf", ".obj"}
EXPORT_EXTS = {".fbx", ".glb", ".gltf"}


class PipelineError(RuntimeError):
    pass



def initial_filepath(stored: str) -> str:
    """Return a stored file path when its folder still exists."""
    if not stored:
        return ""
    folder = stored if os.path.isdir(stored) else os.path.dirname(stored)
    if folder and os.path.isdir(folder):
        return stored
    return ""


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



def _hide_armature_object(armature, hidden: bool) -> None:
    """Eye-icon hide. The armature modifier still deforms the mesh."""
    try:
        armature.hide_set(hidden)
    except RuntimeError:
        pass


def set_armature_bones_visible(armature, show: bool) -> None:
    """Hide or restore one armature's bone display. Skinned meshes stay visible.

    Octahedral cones are drawn by the armature object, so hiding individual
    bone flags is not enough. hide_set removes those cones without disabling
    the armature modifier.
    """
    if armature is None or getattr(armature, "type", None) != "ARMATURE":
        return
    data = getattr(armature, "data", None)
    if data is None or not hasattr(data, "bones"):
        return
    if not show:
        if "hr_bones_hidden_by_tool" not in armature:
            hidden_before = [bone.name for bone in data.bones if bone.hide]
            armature["hr_bone_hide_before"] = "\n".join(hidden_before)
            try:
                armature["hr_object_hidden_before"] = bool(armature.hide_get())
            except RuntimeError:
                armature["hr_object_hidden_before"] = False
            armature["hr_bones_hidden_by_tool"] = True
        for bone in data.bones:
            bone.hide = True
        _hide_armature_object(armature, True)
        return
    if not armature.get("hr_bones_hidden_by_tool"):
        return
    previously = {name for name in str(armature.get("hr_bone_hide_before", "")).split("\n") if name}
    for bone in data.bones:
        bone.hide = bone.name in previously
    _hide_armature_object(armature, bool(armature.get("hr_object_hidden_before", False)))
    del armature["hr_bones_hidden_by_tool"]
    if "hr_bone_hide_before" in armature:
        del armature["hr_bone_hide_before"]
    if "hr_object_hidden_before" in armature:
        del armature["hr_object_hidden_before"]


def stand_positions(mode, source_half_x, source_half_y, target_half_x, target_half_y, gap=0.35):
    """Ground locations for the source and the retarget target.

    X is left/right in the front view: negative is the viewer's left.
    Y is depth: negative is in front of the origin.
    """
    side_source = source_half_x + gap
    side_target = target_half_x + gap
    depth_source = source_half_y + gap
    depth_target = target_half_y + gap
    separated = source_half_x + target_half_x + gap
    layouts = {
        "SIDE": ((-side_source, 0.0), (side_target, 0.0)),
        "SWAP": ((side_source, 0.0), (-side_target, 0.0)),
        "OVERLAP": ((0.0, 0.0), (0.0, 0.0)),
        "SOURCE_ORIGIN": ((0.0, 0.0), (separated, 0.0)),
        "TARGET_ORIGIN": ((-separated, 0.0), (0.0, 0.0)),
        "DEPTH": ((0.0, -depth_source), (0.0, depth_target)),
    }
    try:
        return layouts[mode]
    except KeyError as exc:
        raise PipelineError("未知的站位: " + str(mode)) from exc


def _half_extents(arm_obj):
    from mathutils import Vector

    rotation = arm_obj.matrix_world.to_3x3()
    xs = []
    ys = []

    def add(point):
        xs.append(point.x)
        ys.append(point.y)

    for bone in arm_obj.data.bones:
        add(rotation @ bone.head_local)
        add(rotation @ bone.tail_local)
    for obj in bpy.data.objects:
        if obj.parent != arm_obj or obj.type != "MESH":
            continue
        for corner in obj.bound_box:
            add(rotation @ (obj.matrix_local @ Vector(corner)))
    if not xs:
        return 0.75, 0.75
    return max(max(abs(value) for value in xs), 0.25), max(max(abs(value) for value in ys), 0.25)


def _place_group(arm_obj, other, x, y):
    arm_obj.location.x = x
    arm_obj.location.y = y
    scene_collection = bpy.context.scene.collection
    for collection in arm_obj.users_collection:
        if collection == scene_collection:
            continue
        if other is not None and other.name in collection.objects:
            continue
        for obj in collection.objects:
            if obj == arm_obj or obj.parent is not None:
                continue
            if obj.type not in {"MESH", "EMPTY", "ARMATURE"}:
                continue
            obj.location.x = x
            obj.location.y = y


def apply_stand_layout(source, target, mode):
    if source is not None and getattr(source, "type", None) != "ARMATURE":
        source = None
    if target is not None and getattr(target, "type", None) != "ARMATURE":
        target = None
    if source is None and target is None:
        return
    source_half = _half_extents(source) if source is not None else (0.75, 0.75)
    target_half = _half_extents(target) if target is not None else (0.75, 0.75)
    (source_x, source_y), (target_x, target_y) = stand_positions(
        mode,
        source_half[0],
        source_half[1],
        target_half[0],
        target_half[1],
    )
    if source is not None:
        _place_group(source, target, source_x, source_y)
    if target is not None:
        _place_group(target, source, target_x, target_y)


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
    report, baked = retarget_existing(source, armature, options)
    armature["hr_role"] = "target"
    summary = note + "\n" + report
    return armature, summary, baked, auto


def _animation_binding(obj):
    anim = obj.animation_data if obj is not None else None
    if anim is None:
        return None, None
    return anim.action, getattr(anim, "action_slot", None)


def _capture_user_state(source, target):
    active = bpy.context.view_layer.objects.active
    mode = bpy.context.object.mode if bpy.context.object is not None else "OBJECT"
    return {
        "active": active,
        "mode": mode,
        "frame": bpy.context.scene.frame_current,
        "selected": [obj for obj in bpy.context.view_layer.objects if obj.select_get()],
        "source_anim": _animation_binding(source),
        "target_anim": _animation_binding(target),
        "actions": set(bpy.data.actions),
    }


def _assign_saved_action(obj, action, slot):
    if obj is None:
        return
    if action is None:
        if obj.animation_data is not None:
            obj.animation_data_clear()
        return
    anim = obj.animation_data or obj.animation_data_create()
    anim.action = action
    if slot is not None:
        try:
            anim.action_slot = slot
        except (TypeError, RuntimeError):
            pass


def _restore_user_state(source, target, state):
    _assign_saved_action(source, *state["source_anim"])
    _assign_saved_action(target, *state["target_anim"])
    bpy.context.scene.frame_set(state["frame"])
    for obj in bpy.context.view_layer.objects:
        obj.select_set(obj in state["selected"])
    if state["active"] is not None and state["active"].name in bpy.data.objects:
        bpy.context.view_layer.objects.active = state["active"]
        if bpy.context.object is not None and bpy.context.object.mode != state["mode"]:
            try:
                bpy.ops.object.mode_set(mode=state["mode"])
            except RuntimeError:
                ensure_object_mode()


def _release_action(action):
    if action is None:
        return
    try:
        action.use_fake_user = False
    except (AttributeError, RuntimeError):
        pass
    if action.users == 0:
        bpy.data.actions.remove(action)


def _delete_owned_armature(obj):
    if obj is None or obj.name not in bpy.data.objects:
        return
    data = obj.data
    bpy.context.view_layer.objects.active = obj
    if bpy.context.object is not None and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.data.objects.remove(obj, do_unlink=True)
    if data is not None and getattr(data, "users", 0) == 0:
        bpy.data.armatures.remove(data)


def retarget_through_human_metarig(source, target, options):
    from . import rigify_metarig

    state = _capture_user_state(source, target)
    owned = None
    delivered = []
    failed = True
    try:
        definition = rigify_metarig.load_human_metarig_definition()
        source_hop = rigify_metarig.calibrate_source_to_metarig(source, definition, options)
        target_hop = rigify_metarig.calibrate_target_to_metarig(target, definition, options)
        owned = rigify_metarig.create_human_metarig_armature(definition)
        owned.hide_set(True)
        if options.reference == "CURRENT":
            first_reference, second_reference = rigify_metarig.capture_hop_references(
                source,
                owned,
                target,
                source_hop.pairs,
                target_hop.pairs,
                state["frame"],
            )
        else:
            first_reference = None
            second_reference = None
        first_options = RetargetOptions(
            pairs=source_hop.pairs,
            reference=options.reference,
            reference_data=first_reference,
            root_motion="KEEP",
            foot_ik=False,
            hand_ik=False,
            standard_skeleton="DIRECT",
        )
        bake_retarget(source, owned, first_options)
        second_options = RetargetOptions(
            pairs=target_hop.pairs,
            reference=options.reference,
            reference_data=second_reference,
            root_motion=options.root_motion,
            foot_ik=options.foot_ik,
            hand_ik=options.hand_ik,
            standard_skeleton="DIRECT",
        )
        report, delivered = bake_retarget(owned, target, second_options)
        source_names = {role: source_name for role, source_name, _sample_name in source_hop.pairs}
        corrected = {role: target_name for role, _sample_name, target_name in second_options.resolved_pairs or []}
        options.resolved_pairs = [
            (role, source_names[role], corrected[role])
            for role in corrected
            if role in source_names
        ]
        failed = False
        return report, delivered
    finally:
        _delete_owned_armature(owned)
        for action in list(bpy.data.actions):
            if action not in state["actions"] and action not in delivered:
                _release_action(action)
        if failed:
            _restore_user_state(source, target, state)


def retarget_existing(source, target, options=None):
    options = options or RetargetOptions()
    try:
        if options.standard_skeleton == "RIGIFY_HUMAN_METARIG":
            report, baked = retarget_through_human_metarig(source, target, options)
        else:
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


def _reveal_for_export(obj, revealed):
    """Viewport-hidden armatures still have to be selected for export."""
    try:
        if obj.hide_get():
            obj.hide_set(False)
            revealed.append(obj)
    except RuntimeError:
        pass
    obj.hide_select = False
    obj.select_set(True)


def _select_hierarchy(arm_obj):
    ensure_object_mode()
    revealed = []
    for obj in bpy.context.view_layer.objects:
        obj.select_set(False)
    _reveal_for_export(arm_obj, revealed)
    bpy.context.view_layer.objects.active = arm_obj
    for obj in list(bpy.context.scene.objects):
        parent = obj.parent
        if parent == arm_obj or (parent is not None and parent.parent == arm_obj):
            _reveal_for_export(obj, revealed)
    return revealed


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


def export_armature(arm_obj, path, export_all_actions=True):
    if arm_obj is None or arm_obj.type != "ARMATURE":
        raise PipelineError("还没有可导出的目标骨架。")
    ext = os.path.splitext(path)[1].lower()
    if ext not in EXPORT_EXTS:
        raise PipelineError("导出格式请使用 .glb、.gltf 或 .fbx。")
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    revealed = _select_hierarchy(arm_obj)
    hidden_bones = [bone for bone in arm_obj.data.bones if bone.hide]
    for bone in hidden_bones:
        bone.hide = False
    try:
        _export_current_selection(arm_obj, path, ext, export_all_actions)
    finally:
        for bone in hidden_bones:
            bone.hide = True
        for obj in revealed:
            try:
                obj.hide_set(True)
            except RuntimeError:
                pass
    return path


def _export_current_selection(arm_obj, path, ext, export_all_actions):
    if ext == ".fbx":
        _export_fbx_with_rest_bind(path)
    else:
        export_format = "GLB" if ext == ".glb" else "GLTF_SEPARATE"
        if not export_all_actions:
            anim = arm_obj.animation_data
            if anim is None or anim.action is None:
                raise PipelineError("当前没有可导出的动画。")
        animation_mode = "ACTIONS" if export_all_actions else "ACTIVE_ACTIONS"
        try:
            _call_op(
                bpy.ops.export_scene.gltf,
                filepath=path,
                use_selection=True,
                export_format=export_format,
                export_animations=True,
                export_animation_mode=animation_mode,
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
                export_animation_mode=animation_mode,
            )
    return path
