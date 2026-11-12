from math import hypot, isfinite
from math import atan2, pi
from time import perf_counter
import sys

import bpy
from mathutils import Matrix, Vector

from . import animation_library as library
from .animation_playback import CharacterPlayback

_active_session = None
KEYS = frozenset({"UP_ARROW", "DOWN_ARROW", "LEFT_ARROW", "RIGHT_ARROW", "LEFT_SHIFT", "RIGHT_SHIFT"})


def movement_intent(held):
    x = float("RIGHT_ARROW" in held) - float("LEFT_ARROW" in held)
    y = float("UP_ARROW" in held) - float("DOWN_ARROW" in held)
    length = hypot(x, y)
    if not length:
        return 0.0, 0.0, "IDLE"
    return x / length, y / length, "RUN" if held.intersection({"LEFT_SHIFT", "RIGHT_SHIFT"}) else "WALK"


def travel(dt, speed, unit_scale):
    if not all(isfinite(value) for value in (dt, speed, unit_scale)) or unit_scale <= 0 or speed < 0:
        raise ValueError("时间、速度或场景单位无效")
    return min(0.05, max(0.0, dt)) * speed / unit_scale


def active_session():
    return _active_session


def stop_session(*args):
    if _active_session:
        _active_session.close()


def resolve_character(obj):
    if obj is None:
        raise ValueError("请先选择角色骨架或蒙皮网格")
    if obj.type == "ARMATURE":
        return obj
    if obj.type != "MESH":
        raise ValueError("当前对象不是骨架或蒙皮网格")
    candidates = {modifier.object for modifier in obj.modifiers if modifier.type == "ARMATURE" and modifier.object is not None}
    if obj.parent and obj.parent.type == "ARMATURE":
        candidates.add(obj.parent)
    if len(candidates) != 1:
        raise ValueError("没有唯一骨架，请在角色搜索框中明确选择")
    return candidates.pop()


def readiness(rig):
    if rig is None:
        return "先选一个角色骨架或蒙皮网格"
    for role in library.ROLES:
        clip = library.find_clip(rig, getattr(rig.cl_settings, role.lower() + "_id"))
        if clip is None:
            return "还缺" + library.ROLE_LABELS[role] + "动画，请选择片段或载入动画库"
        if clip.kind != role:
            return library.ROLE_LABELS[role] + "槽的用途不匹配，请重新选择"
    return ""


def viewport_contains(area, x, y):
    def contains(region):
        return region.x <= x < region.x + region.width and region.y <= y < region.y + region.height
    window = any(region.type == "WINDOW" and contains(region) for region in area.regions)
    excluded = {"HEADER", "TOOL_HEADER"}
    if area.spaces.active.show_region_ui:
        excluded.add("UI")
    if area.spaces.active.show_region_toolbar:
        excluded.add("TOOLS")
    return window and not any(region.type in excluded and region.width > 1 and contains(region) for region in area.regions)


def validate_character(rig, context):
    if rig is None or rig.type != "ARMATURE" or context.scene.objects.get(rig.name) != rig:
        raise ValueError("请选择当前场景中的角色骨架")
    spring = sys.modules.get("spring_bone.operators")
    if spring is not None and spring.job_running() and spring.active_session().job.armature == rig:
        raise ValueError("请先停止该角色的动态骨骼实时预览或烘焙任务，再启动角色操控")
    if rig.library or rig.override_library or rig.data.library or rig.parent or rig.mode != "OBJECT":
        raise ValueError("需要本地、无父级且处于物体模式的骨架")
    if not rig.data.bones or rig.constraints or any(bone.constraints for bone in rig.pose.bones):
        raise ValueError("骨架含约束或为空，请先用重定向工具烘焙到干净目标")
    for animation in (rig.animation_data, rig.data.animation_data):
        if animation and (animation.drivers or getattr(animation, "use_tweak_mode", False)):
            raise ValueError("请先退出 NLA 编辑并烘焙竞争驱动")
    if context.screen and context.screen.is_animation_playing:
        raise ValueError("请先停止时间轴播放")
    scale = tuple(rig.scale)
    if not all(isfinite(value) for value in scale) or min(scale) <= 0 or max(scale) - min(scale) > 1e-5:
        raise ValueError("角色缩放需要为正且均匀")
    if (rig.matrix_world.to_quaternion() @ Vector((0, 0, 1))).z < 0.9999:
        raise ValueError("角色本地 Z 轴需要朝上，请先应用对象旋转")
    settings = rig.cl_settings
    if not all(isfinite(value) for value in (settings.walk_speed, settings.run_speed, settings.blend)) or not 0 < settings.walk_speed < settings.run_speed:
        raise ValueError("走速与跑速需要为正，跑速必须大于走速")
    travel(0, settings.walk_speed, context.scene.unit_settings.scale_length)


class LocomotionSession:
    def __init__(self, context, preview_id=""):
        self.manager = context.window_manager
        self.window = context.window
        self.screen = self.window.screen
        self.workspace = self.window.workspace
        self.area = context.area
        self.scene = context.scene
        self.view_layer = context.view_layer
        self.rig = self.scene.cl_character
        self.preview_id = preview_id
        self.timer = None
        self.player = None
        self.closed = False
        self.held = set()
        self.inside = False
        self.focused = True
        self.status = "正在检查，可按 Esc 取消"
        self.matrix = self.rig.matrix_world.copy() if self.rig else None
        self.frame = (self.scene.frame_current, self.scene.frame_subframe)
        self.checks = None
        self.clips = {}
        self.last_time = perf_counter()
        self.last_timer_duration = 0.0

    def begin(self, context):
        global _active_session
        if _active_session:
            raise ValueError("已有操控或预览会话，请先停止")
        if not self.area or self.area.type != "VIEW_3D":
            raise ValueError("请在 3D 视口启动")
        if len(self.window.modal_operators):
            raise ValueError("请先结束其他交互工具")
        validate_character(self.rig, context)
        if self.preview_id:
            clip = library.find_clip(self.rig, self.preview_id)
            if clip is None:
                raise ValueError("片段已失效，请重新选择")
            self.clips = {"PREVIEW": clip}
        else:
            reason = readiness(self.rig)
            if reason:
                raise ValueError(reason)
            self.clips = {role: library.find_clip(self.rig, getattr(self.rig.cl_settings, role.lower() + "_id")) for role in library.ROLES}
        self.checks = self._validate()
        rotation = self.area.spaces.active.region_3d.view_rotation
        forward = rotation @ Vector((0, 0, -1))
        forward.z = 0
        self.forward = forward.normalized() if forward.length_squared > 1e-10 else Vector((0, 1, 0))
        self.right = self.forward.cross(Vector((0, 0, 1)))
        self.timer = self.manager.event_timer_add(1 / 60, window=self.window)
        self.last_timer_duration = self.timer.time_duration
        _active_session = self
        self._header()

    def _validate(self):
        for clip in self.clips.values():
            try:
                yield from library.validate_clip_steps(clip, self.rig, self.scene)
            except Exception:
                self.rig.cl_settings.repair_clip_id = clip.clip_id
                raise
        self.rig.cl_settings.repair_clip_id = ""

    def _header(self):
        self.area.header_text_set(self.status + " | 方向键走 / Shift 跑 / Esc 停止并恢复")
        self.area.tag_redraw()

    def valid(self):
        return self.window.screen == self.screen and self.window.workspace == self.workspace and self.window.scene == self.scene and any(area == self.area for area in self.screen.areas) and self.area.type == "VIEW_3D" and self.scene.objects.get(self.rig.name) == self.rig and self.rig.mode == "OBJECT" and self.frame == (self.scene.frame_current, self.scene.frame_subframe)

    def event(self, event):
        if self.closed:
            return {"CANCELLED", "PASS_THROUGH"}
        if not self.valid() or event.type == "ESC":
            self.close()
            return {"CANCELLED"}
        if event.type == "WINDOW_DEACTIVATE":
            self.focused = False
            self.held.clear()
        if event.type == "MOUSEMOVE":
            self.focused = True
            self.inside = viewport_contains(self.area, event.mouse_x, event.mouse_y)
            if not self.inside:
                self.held.clear()
        if event.type in KEYS:
            if event.value == "PRESS" and self.inside and self.focused and self.player:
                self.held.add(event.type)
            elif event.value == "RELEASE":
                self.held.discard(event.type)
            return {"RUNNING_MODAL"}
        if event.type == "TIMER":
            duration = self.timer.time_duration
            if duration <= self.last_timer_duration:
                return {"PASS_THROUGH"}
            self.last_timer_duration = duration
            now = perf_counter()
            dt = min(0.05, max(0.0, now - self.last_time))
            self.last_time = now
            self.tick(dt)
            self._header()
            return {"RUNNING_MODAL"}
        if event.type in {"MIDDLEMOUSE", "MOUSEMOVE", "WHEELUPMOUSE", "WHEELDOWNMOUSE", "TRACKPADPAN", "TRACKPADZOOM"}:
            return {"PASS_THROUGH"}
        if not self.inside and event.type in {"LEFTMOUSE", "RIGHTMOUSE"}:
            return {"PASS_THROUGH"}
        return {"RUNNING_MODAL"}

    def tick(self, dt):
        if self.checks is not None:
            try:
                for index in range(64):
                    next(self.checks)
                return
            except StopIteration:
                self.checks = None
                self.player = CharacterPlayback(self.rig, self.scene, self.view_layer, self.clips, self.rig.cl_settings.blend)
                self.last_time = perf_counter()
        if not self.inside or not self.focused:
            self.held.clear()
            self.status = "已暂停，将鼠标移入视口后重新按键"
        elif self.preview_id:
            self.status = "原地预览"
        else:
            self.status = "操控中"
        if self.preview_id:
            if self.inside and self.focused:
                self.player.update("PREVIEW", dt)
            return
        self.advance(dt)

    def advance(self, dt):
        x, y, state = movement_intent(self.held)
        settings = self.rig.cl_settings
        speed = settings.run_speed if state == "RUN" else settings.walk_speed if state == "WALK" else 0.0
        direction = self.right * x + self.forward * y
        if direction.length_squared:
            offset = {"Y": pi / 2, "NEG_Y": -pi / 2, "X": 0, "NEG_X": pi}[settings.forward]
            position = self.rig.matrix_world.translation + direction * travel(dt, speed, self.scene.unit_settings.scale_length)
            self.rig.matrix_world = Matrix.Translation(position) @ Matrix.Rotation(atan2(direction.y, direction.x) - offset, 4, "Z") @ Matrix.Diagonal((*self.rig.scale, 1.0))
        self.player.update(state, dt, speed)
        if self.inside and self.focused:
            self.status = library.ROLE_LABELS[state]

    def close(self, message="已停止并恢复入口状态"):
        global _active_session
        if self.closed:
            return
        self.closed = True
        if _active_session is self:
            _active_session = None
        try:
            if self.timer:
                self.manager.event_timer_remove(self.timer)
                self.timer = None
        finally:
            try:
                if self.player:
                    self.player.close()
            finally:
                try:
                    if self.rig and self.matrix:
                        self.rig.matrix_world = self.matrix
                        self.rig.cl_settings.message = message
                    self.area.header_text_set(None)
                    self.area.tag_redraw()
                    self.view_layer.update()
                except ReferenceError:
                    pass
                self.held.clear()
