import bpy
from bpy.props import IntProperty
from bpy.types import Operator
from mathutils import Matrix

from .animation import SpringBoneBakeJob, specs_from_settings
from .contact_bake import SkirtContactBakeJob
from .solver import SpringBoneError
from .targets import target_armature

_session = None
_message = ""
_VIEW_EVENTS = {
    "MOUSEMOVE",
    "INBETWEEN_MOUSEMOVE",
    "MIDDLEMOUSE",
    "WHEELUPMOUSE",
    "WHEELDOWNMOUSE",
    "WHEELINMOUSE",
    "WHEELOUTMOUSE",
    "TRACKPADPAN",
    "TRACKPADZOOM",
    "MOUSESMARTZOOM",
    "NDOF_MOTION",
}


def _view_event(event_type):
    return event_type in _VIEW_EVENTS or event_type.startswith("NDOF_")


def job_running():
    session = _session
    return session is not None and session.job is not None and not session.job.finished


def active_session():
    return _session


def realtime_running():
    return job_running() and bool(getattr(_session.job, "is_realtime", False))


def get_realtime_preview(_manager):
    return realtime_running()


def set_realtime_preview(_manager, enabled):
    try:
        if enabled:
            start_realtime(bpy.context)
        elif realtime_running():
            stop_active_session()
            set_message("实时预览已停止，原动作已恢复")
    except Exception as exc:
        stop_active_session()
        set_message(str(exc))


def _realtime_frame(scene, depsgraph=None):
    if not realtime_running():
        return
    try:
        _session.job.frame_update(scene, depsgraph)
    except Exception as exc:
        stop_active_session()
        set_message(str(exc))


def _realtime_timer():
    if not realtime_running():
        return None
    try:
        if not any(screen.is_animation_playing for screen in bpy.data.screens):
            _session.job.run_slice()
        else:
            _session.job._guard()
    except Exception as exc:
        stop_active_session()
        set_message(str(exc))
        return None
    return 1.0 / 60.0


def _remove_realtime_callbacks():
    if _realtime_frame in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.remove(_realtime_frame)
    if bpy.app.timers.is_registered(_realtime_timer):
        bpy.app.timers.unregister(_realtime_timer)


def start_realtime(context):
    global _session
    from .realtime import RealtimeSpringPreview

    target = target_armature(context)
    if target is None:
        raise SpringBoneError("请选择目标骨架")
    if _session is not None:
        if realtime_running() and _session.job.armature == target:
            return _session
        if job_running() or _session.job.armature != target:
            raise SpringBoneError("请先停止其他动态骨骼任务")
        stop_active_session()
    job = RealtimeSpringPreview(target)
    _session = _Session(job, False)
    try:
        bpy.app.handlers.frame_change_post.append(_realtime_frame)
        bpy.app.timers.register(_realtime_timer, first_interval=1.0 / 60.0)
    except Exception:
        stop_active_session()
        raise
    set_message("实时预览：逐节重力、惯性与球/胶囊碰撞")
    return _session


def last_message():
    return _message


def set_message(text):
    global _message
    _message = text


def config_token(obj):
    settings = obj.sb_settings
    scene = bpy.context.scene
    chains = []
    for chain in settings.chains:
        chains.append(
            (
                tuple(item.name for item in chain.bone_names),
                round(float(chain.stiffness), 6),
                round(float(chain.drag_force), 6),
                round(float(chain.gravity_power), 6),
                tuple(round(float(value), 6) for value in chain.gravity_dir),
                round(float(chain.hit_radius_m), 6),
                round(float(chain.weight), 6),
                bool(chain.cone_enabled),
                round(float(chain.cone_angle_deg), 6),
                chain.inertia_space,
                chain.ancestor_name,
                round(float(chain.warmup_seconds), 6),
            )
        )
    colliders = []
    for item in settings.colliders:
        colliders.append(
            (
                item.shape,
                item.bone_name,
                round(float(item.radius_m), 6),
                tuple(round(float(value), 6) for value in item.head_offset_m),
                tuple(round(float(value), 6) for value in item.tail_offset_m),
            )
        )
    target = target_armature(bpy.context)
    contact = (settings.contact_garment, settings.contact_body, float(settings.contact_margin_m), float(settings.contact_frame_step), float(settings.contact_root_offset_m))
    return (int(scene.frame_start), int(scene.frame_end), tuple(chains), tuple(colliders), target, contact)


class _Session:
    def __init__(self, job, bake):
        self.job = job
        self.bake = bake
        self.timer = None
        self.window_manager = bpy.context.window_manager
        self.message = ""
        self.last_report = 0.0

    def remove_timer(self):
        if self.timer is None:
            return
        timer = self.timer
        self.timer = None
        try:
            if self.window_manager is not None:
                self.window_manager.event_timer_remove(timer)
        except (ReferenceError, RuntimeError):
            pass

    def run_slice(self):
        self.job.run_slice()


def stop_active_session():
    global _session
    session = _session
    _session = None
    _remove_realtime_callbacks()
    if session is None:
        return
    try:
        session.remove_timer()
    finally:
        if session.job is not None and not session.job.delivered:
            session.job.cancel()
        if getattr(session.job, "is_realtime", False):
            set_message("实时预览已停止，原动作已恢复")


def release_session_keep_result():
    global _session
    if realtime_running():
        stop_active_session()
        return
    session = _session
    _session = None
    if session is not None:
        session.remove_timer()


def begin_session(context, bake, fault_point=None):
    global _session
    if _session is not None:
        raise SpringBoneError("已有动态骨骼任务")
    obj = target_armature(context)
    if obj is None:
        raise SpringBoneError("请选择场景中的目标骨架")
    chains, colliders = specs_from_settings(obj.sb_settings)
    scene = context.scene
    job = SpringBoneBakeJob(
        obj,
        chains,
        colliders,
        scene.frame_start,
        scene.frame_end,
        bake,
        identity_token=lambda: config_token(obj),
        fault_point=fault_point,
    )
    _session = _Session(job, bake)
    return _session


def start_preview(context):
    if _session is not None:
        if _session.job is not None and _session.job.armature != target_armature(context):
            raise SpringBoneError("请先停止其他角色的预览")
        if _session.job is not None and not _session.job.finished:
            raise SpringBoneError("已有动态骨骼任务")
        stop_active_session()
    return begin_session(context, False)


def start_bake(context):
    if _session is not None and _session.job is not None and _session.job.armature != target_armature(context):
        raise SpringBoneError("请先停止其他角色的预览")
    if (
        _session is not None
        and _session.job is not None
        and _session.job.preview_still_valid()
    ):
        _session.job.publish_from_preview()
        release_session_keep_result()
        return None
    if _session is not None:
        stop_active_session()
    return begin_session(context, True)


def start_contact_bake(context):
    global _session
    if job_running():
        raise SpringBoneError("请先结束当前动态骨骼任务")
    obj = target_armature(context)
    if obj is None:
        raise SpringBoneError("请选择场景中的目标骨架")
    if _session is not None:
        if _session.job.armature != obj:
            raise SpringBoneError("请先停止其他角色的预览")
        if _session.job.preview_still_valid():
            _session.job.publish_from_preview()
        release_session_keep_result()
    job = SkirtContactBakeJob(obj, context.scene.frame_start, context.scene.frame_end, identity_token=lambda: config_token(obj))
    _session = _Session(job, True)
    return _session


def consume_modal_event(event_type):
    session = _session
    if session is None or session.job is None:
        return "CANCELLED"
    if event_type in {"ESC", "RIGHTMOUSE"}:
        stop_active_session()
        return "CANCELLED"
    if event_type != "TIMER":
        if _view_event(event_type):
            return "PASS_THROUGH"
        return "RUNNING_MODAL"
    try:
        session.run_slice()
    except SpringBoneError:
        stop_active_session()
        raise
    session = _session
    if session is None or session.job is None or session.job.finished:
        if session is not None and session.bake and session.job is not None and session.job.delivered:
            release_session_keep_result()
        elif session is not None:
            session.remove_timer()
        return "FINISHED"
    return "RUNNING_MODAL"


def _report_progress(operator, session):
    import time

    now = time.perf_counter()
    if now - session.last_report < 0.25 and not session.job.finished:
        return
    session.last_report = now
    session.message = f"{session.job.phase} {session.job.progress:.0%}"
    set_message(session.message)
    operator.report({"INFO"}, session.message)
    screen = bpy.context.screen
    if screen is None:
        return
    for area in screen.areas:
        if area.type == "VIEW_3D":
            area.tag_redraw()


def _drop_display(empty, armature):
    if empty is None or getattr(empty, "type", "") != "EMPTY" or empty.parent != armature:
        return
    try:
        name = empty.name
    except ReferenceError:
        return
    if name in bpy.data.objects:
        bpy.data.objects.remove(empty, do_unlink=True)


def _selected_chain(bones):
    selected = list(bones)
    if not selected:
        raise SpringBoneError("请选择连续骨骼")
    roots = [bone for bone in selected if bone.parent not in selected]
    if len(roots) != 1:
        raise SpringBoneError("选择必须是一条连续链")
    ordered = [roots[0]]
    while True:
        children = [bone for bone in selected if bone.parent == ordered[-1]]
        if not children:
            break
        if len(children) != 1:
            raise SpringBoneError("链条不能分支")
        ordered.append(children[0])
    if len(ordered) != len(selected):
        raise SpringBoneError("选择必须是一条连续链")
    return ordered


def _weighted_chain_bones(armature, scene):
    weighted = set()
    found_mesh = False
    for obj in scene.objects:
        if obj.type != "MESH":
            continue
        modifiers = [item for item in obj.modifiers if item.type == "ARMATURE" and item.object == armature and item.show_viewport]
        if not modifiers:
            continue
        if any(item.use_bone_envelopes for item in modifiers):
            raise SpringBoneError("使用骨骼封套，不能按顶点权重修正末端")
        if not any(item.use_vertex_groups for item in modifiers):
            continue
        found_mesh = True
        groups = {group.index: group.name for group in obj.vertex_groups if group.name in armature.data.bones and armature.data.bones[group.name].use_deform}
        for vertex in obj.data.vertices:
            for slot in vertex.groups:
                if slot.weight > 1e-6 and slot.group in groups:
                    weighted.add(groups[slot.group])
    if not found_mesh:
        raise SpringBoneError("未找到目标骨架驱动的蒙皮网格")
    return weighted


def trim_unweighted_tips(armature, scene):
    if active_session() is not None:
        raise SpringBoneError("请先停止预览")
    chains = armature.sb_settings.chains
    weighted = _weighted_chain_bones(armature, scene)
    if not any(item.name in weighted for chain in chains for item in chain.bone_names):
        raise SpringBoneError("选定链未找到蒙皮权重，未修改")
    plans = []
    for chain in chains:
        if not any(item.name in weighted for item in chain.bone_names):
            continue
        end = len(chain.bone_names)
        trailing = set()
        while end > 1:
            name = chain.bone_names[end - 1].name
            bone = armature.data.bones.get(name)
            if bone is None:
                raise SpringBoneError(f"找不到骨骼 {name}")
            if name in weighted or any(child.name not in trailing for child in bone.children):
                break
            trailing.add(name)
            end -= 1
        plans.append((chain, end))
    removed = []
    for chain, end in plans:
        while len(chain.bone_names) > end:
            removed.append(chain.bone_names[-1].name)
            chain.bone_names.remove(len(chain.bone_names) - 1)
    return removed


class SPRING_BONE_OT_trim_tips(Operator):
    bl_idname = "spring_bone.trim_unweighted_tips"
    bl_label = "修正无权重末端"
    bl_description = "按绑定网格检查全部链，仅移除不驱动蒙皮的末端配置，保留骨骼与原权重"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return active_session() is None and target_armature(context) is not None

    def execute(self, context):
        try:
            removed = trim_unweighted_tips(target_armature(context), context.scene)
        except SpringBoneError as exc:
            set_message(str(exc))
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        message = f"已移除 {len(removed)} 个无权重末端配置，原骨骼与蒙皮未改动"
        set_message(message)
        self.report({"INFO"}, message)
        return {"FINISHED"}


def _sync_empty(armature, collider, scale, pointer_name, offset, display_type):
    empty = getattr(collider, pointer_name)
    if empty is not None and empty.name not in bpy.data.objects:
        empty = None
    if empty is None:
        empty = bpy.data.objects.new(f"SB_{armature.name}_{collider.name}", None)
        armature.users_collection[0].objects.link(empty) if armature.users_collection else bpy.context.scene.collection.objects.link(empty)
        setattr(collider, pointer_name, empty)
    empty.parent = armature
    empty.parent_type = "BONE"
    empty.parent_bone = collider.bone_name
    bone = armature.pose.bones.get(collider.bone_name)
    length = bone.bone.length if bone is not None else 0.0
    local = [(float(value) / scale) if scale else float(value) for value in offset]
    local[1] -= length
    empty.rotation_euler = (0.0, 0.0, 0.0)
    empty.scale = (1.0, 1.0, 1.0)
    empty.location = tuple(local)
    empty.matrix_parent_inverse = Matrix.Identity(4)
    empty.empty_display_type = display_type
    empty.empty_display_size = max(collider.radius_m / scale, 0.001) if scale else collider.radius_m
    empty.show_in_front = True
    return empty


class SPRING_BONE_OT_add_chain(Operator):
    bl_idname = "spring_bone.add_chain"
    bl_label = "添加链"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        if job_running():
            return False
        obj = target_armature(context)
        return obj is not None and obj == context.object and obj.mode == "POSE"

    def execute(self, context):
        try:
            selected = [pose.bone for pose in context.selected_pose_bones]
            ordered = _selected_chain(selected)
            settings = target_armature(context).sb_settings
            used = {item.name for chain in settings.chains for item in chain.bone_names}
            for bone in ordered:
                if bone.name in used:
                    raise SpringBoneError(f"{bone.name} 已在其他链中")
            chain = settings.chains.add()
            chain.name = ordered[0].name
            for bone in ordered:
                item = chain.bone_names.add()
                item.name = bone.name
            settings.active_chain = len(settings.chains) - 1
        except SpringBoneError as exc:
            set_message(str(exc))
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        set_message("已添加链")
        return {"FINISHED"}


class SPRING_BONE_OT_remove_chain(Operator):
    bl_idname = "spring_bone.remove_chain"
    bl_label = "移除链"
    bl_options = {"REGISTER", "UNDO"}
    index: IntProperty(name="序号", default=0)

    @classmethod
    def poll(cls, context):
        if job_running():
            return False
        obj = target_armature(context)
        return obj is not None and obj.type == "ARMATURE"

    def execute(self, context):
        settings = target_armature(context).sb_settings
        if 0 <= self.index < len(settings.chains):
            settings.chains.remove(self.index)
            settings.active_chain = min(settings.active_chain, max(len(settings.chains) - 1, 0))
        return {"FINISHED"}


class SPRING_BONE_OT_add_collider(Operator):
    bl_idname = "spring_bone.add_collider"
    bl_label = "添加代理体"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        if job_running():
            return False
        obj = target_armature(context)
        return obj is not None and obj == context.object and obj.mode == "POSE"

    def execute(self, context):
        pose = context.active_pose_bone
        if pose is None:
            self.report({"ERROR"}, "请选择非模拟骨")
            return {"CANCELLED"}
        settings = target_armature(context).sb_settings
        used = {item.name for chain in settings.chains for item in chain.bone_names}
        if pose.name in used:
            self.report({"ERROR"}, "碰撞骨不能是动态骨")
            return {"CANCELLED"}
        collider = settings.colliders.add()
        collider.name = pose.name
        collider.bone_name = pose.name
        collider.shape = "SPHERE"
        settings.active_collider = len(settings.colliders) - 1
        set_message("已添加代理体")
        return {"FINISHED"}


class SPRING_BONE_OT_remove_collider(Operator):
    bl_idname = "spring_bone.remove_collider"
    bl_label = "移除代理体"
    bl_options = {"REGISTER", "UNDO"}
    index: IntProperty(name="序号", default=0)

    @classmethod
    def poll(cls, context):
        if job_running():
            return False
        obj = target_armature(context)
        return obj is not None and obj.type == "ARMATURE"

    def execute(self, context):
        settings = target_armature(context).sb_settings
        if 0 <= self.index < len(settings.colliders):
            collider = settings.colliders[self.index]
            displays = []
            for empty in (collider.display_object, collider.display_tail):
                if empty is not None:
                    displays.append(empty)
            settings.colliders.remove(self.index)
            for empty in displays:
                _drop_display(empty, target_armature(context))
            settings.active_collider = min(settings.active_collider, max(len(settings.colliders) - 1, 0))
        return {"FINISHED"}


class SPRING_BONE_OT_sync_colliders(Operator):
    bl_idname = "spring_bone.sync_colliders"
    bl_label = "更新代理体显示"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        if job_running():
            return False
        obj = target_armature(context)
        return obj is not None and obj.type == "ARMATURE"

    def execute(self, context):
        armature = target_armature(context)
        scale = float(context.scene.unit_settings.scale_length) or 1.0
        for collider in armature.sb_settings.colliders:
            if not collider.bone_name:
                continue
            _sync_empty(armature, collider, scale, "display_object", collider.head_offset_m, "SPHERE")
            if collider.shape == "CAPSULE":
                _sync_empty(armature, collider, scale, "display_tail", collider.tail_offset_m, "PLAIN_AXES")
            else:
                tail = collider.display_tail
                collider.display_tail = None
                _drop_display(tail, armature)
        set_message("代理体显示已更新")
        return {"FINISHED"}


class SPRING_BONE_OT_preview(Operator):
    bl_idname = "spring_bone.preview"
    bl_label = "生成预览"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = target_armature(context)
        if obj is None or obj.type != "ARMATURE" or obj.mode == "EDIT":
            return False
        return not job_running()

    def execute(self, context):
        try:
            session = start_preview(context)
            session.job.run_budgeted()
        except SpringBoneError as exc:
            stop_active_session()
            set_message(str(exc))
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        set_message("预览已生成")
        return {"FINISHED"}

    def invoke(self, context, event):
        if context.window is None:
            return self.execute(context)
        try:
            session = start_preview(context)
        except SpringBoneError as exc:
            set_message(str(exc))
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        session.timer = context.window_manager.event_timer_add(0.016, window=context.window)
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type in {"ESC", "RIGHTMOUSE"}:
            stop_active_session()
            set_message("预览已取消")
            return {"CANCELLED"}
        if event.type != "TIMER":
            if _view_event(event.type):
                return {"PASS_THROUGH"}
            return {"RUNNING_MODAL"}
        session = active_session()
        if session is None or session.job is None:
            return {"CANCELLED"}
        try:
            outcome = consume_modal_event(event.type)
        except SpringBoneError as exc:
            set_message(str(exc))
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        session = active_session()
        if session is not None:
            _report_progress(self, session)
        if outcome == "FINISHED":
            set_message("预览已生成")
            return {"FINISHED"}
        if outcome == "CANCELLED":
            set_message("预览已取消")
            return {"CANCELLED"}
        return {"RUNNING_MODAL"}


class SPRING_BONE_OT_stop(Operator):
    bl_idname = "spring_bone.stop_preview"
    bl_label = "停止预览"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return active_session() is not None or target_armature(context) is not None

    def execute(self, context):
        session = active_session()
        if session is not None and session.job is not None and session.job.delivered:
            release_session_keep_result()
            set_message("结果已保留")
            return {"FINISHED"}
        stop_active_session()
        set_message("已恢复基础动作")
        return {"FINISHED"}


class SPRING_BONE_OT_bake(Operator):
    bl_idname = "spring_bone.bake"
    bl_label = "烘焙新动作"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = target_armature(context)
        if obj is None or obj.type != "ARMATURE" or obj.mode == "EDIT":
            return False
        return not job_running()

    def execute(self, context):
        try:
            session = start_bake(context)
            if session is not None:
                session.job.run_budgeted()
                if session.job.delivered:
                    release_session_keep_result()
        except SpringBoneError as exc:
            stop_active_session()
            set_message(str(exc))
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        set_message("烘焙已完成")
        return {"FINISHED"}

    def invoke(self, context, event):
        if context.window is None:
            return self.execute(context)
        try:
            session = start_bake(context)
        except SpringBoneError as exc:
            set_message(str(exc))
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        if session is None:
            set_message("烘焙已完成")
            return {"FINISHED"}
        session.timer = context.window_manager.event_timer_add(0.016, window=context.window)
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type in {"ESC", "RIGHTMOUSE"}:
            stop_active_session()
            set_message("烘焙已取消")
            return {"CANCELLED"}
        if event.type != "TIMER":
            if _view_event(event.type):
                return {"PASS_THROUGH"}
            return {"RUNNING_MODAL"}
        try:
            outcome = consume_modal_event(event.type)
        except SpringBoneError as exc:
            set_message(str(exc))
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        session = active_session()
        if session is not None:
            _report_progress(self, session)
        if outcome == "FINISHED":
            set_message("烘焙已完成")
            return {"FINISHED"}
        if outcome == "CANCELLED":
            return {"CANCELLED"}
        return {"RUNNING_MODAL"}


class SPRING_BONE_OT_contact_bake(Operator):
    bl_idname = "spring_bone.contact_bake"
    bl_label = "修正裙面穿模（新骨骼动作）"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = target_armature(context)
        return obj is not None and obj.mode != "EDIT" and not job_running()

    def execute(self, context):
        try:
            session = start_contact_bake(context)
            session.job.run_budgeted()
            release_session_keep_result()
        except Exception as exc:
            stop_active_session()
            set_message(str(exc))
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        set_message("裙面已修正并保存为骨骼动作，可随 FBX 导出")
        return {"FINISHED"}

    def invoke(self, context, event):
        if context.window is None:
            return self.execute(context)
        try:
            session = start_contact_bake(context)
        except Exception as exc:
            set_message(str(exc))
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        session.timer = context.window_manager.event_timer_add(.016, window=context.window)
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        session = active_session()
        if session is None:
            return {"CANCELLED"}
        if event.type == "TIMER" and event.timer != session.timer:
            return {"PASS_THROUGH"}
        try:
            outcome = consume_modal_event(event.type)
        except Exception as exc:
            stop_active_session()
            set_message(str(exc))
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        if outcome == "FINISHED":
            set_message("裙面已修正并保存为骨骼动作，可随 FBX 导出")
        elif outcome == "CANCELLED":
            set_message("裙面修正已取消")
        else:
            _report_progress(self, session)
        return {outcome}
