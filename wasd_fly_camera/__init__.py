"""Preview the 3D viewport with Unity Scene view controls.

Perspective: hold the right mouse button to fly. The mouse looks around the
eye, WASD move along the look direction, and Q/E move on world up.
Orthographic: holding the right mouse button orbits the current pivot.
Middle-mouse pans, Alt+left-mouse orbits, and Alt+right-mouse zooms.
Shift speeds those drags up. Scroll changes fly speed only while flying.
Esc restores the view from when the drag started.
"""

from __future__ import annotations

from math import exp, isfinite
from time import perf_counter

import bpy
from bpy.props import EnumProperty, FloatProperty
from bpy.types import AddonPreferences, Operator, Panel
from mathutils import Quaternion, Vector

bl_info = {
    "name": "WASD Fly Camera",
    "author": "Blender Plugin",
    "version": (1, 2, 0),
    "blender": (5, 1, 2),
    "location": "View3D > Sidebar > 飞行",
    "description": "按住中键使用 WASD 移动视口，保留可选 Unity 风格导航",
    "category": "3D View",
}

_ADDON_KEYMAPS = []
_active_navigation = None
_MMB_MODE = "BLENDER_MMB"
_UNITY_MODE = "UNITY"
_MMB_INTERVAL = 1.0 / 60.0
_MAX_MMB_DT = 0.05
_MMB_KEYS = frozenset({"W", "A", "S", "D"})
_MODIFIER_KEYS = frozenset({"LEFT_SHIFT", "RIGHT_SHIFT", "LEFT_CTRL", "RIGHT_CTRL", "LEFT_ALT", "RIGHT_ALT", "OSKEY"})
_WORLD_UP = Vector((0.0, 0.0, 1.0))


def fly_axes(rotation):
    """Camera axes. Blender cameras look along local -Z and keep local +Y as up."""
    forward = (rotation @ Vector((0.0, 0.0, -1.0))).normalized()
    right = (rotation @ Vector((1.0, 0.0, 0.0))).normalized()
    up = (rotation @ Vector((0.0, 1.0, 0.0))).normalized()
    return forward, right, up


def fly_translation(rotation, held, speed, dt):
    """Unity flythrough: WASD follows the look direction, Q/E follow world up."""
    forward, right, _up = fly_axes(rotation)
    direction = Vector((0.0, 0.0, 0.0))
    if "W" in held:
        direction += forward
    if "S" in held:
        direction -= forward
    if "D" in held:
        direction += right
    if "A" in held:
        direction -= right
    if "E" in held:
        direction += _WORLD_UP
    if "Q" in held:
        direction -= _WORLD_UP
    if direction.length_squared < 1.0e-12:
        return Vector((0.0, 0.0, 0.0))
    return direction.normalized() * speed * dt


def fly_look(rotation, dx, dy, sensitivity):
    """Yaw around world up, then pitch around the camera right. Roll stays locked."""
    yaw = Quaternion(_WORLD_UP, -dx * sensitivity)
    turned = yaw @ rotation
    right = (turned @ Vector((1.0, 0.0, 0.0))).normalized()
    pitched = Quaternion(right, dy * sensitivity) @ turned
    pitched.normalize()
    forward = pitched @ Vector((0.0, 0.0, -1.0))
    if abs(forward.normalized().dot(_WORLD_UP)) > 0.995:
        return turned.normalized()
    return pitched


def view_eye(location, rotation, distance):
    """Eye of a viewport whose pivot sits ``distance`` in front of the camera."""
    return Vector(location) + rotation @ Vector((0.0, 0.0, distance))


def location_for_eye(eye, rotation, distance):
    """Pivot that keeps ``eye`` fixed for a viewport rotation and distance."""
    return Vector(eye) - rotation @ Vector((0.0, 0.0, distance))


def right_drag_mode(perspective):
    """Unity uses the right button to fly in perspective and orbit in orthographic."""
    if perspective == "ORTHO":
        return "ORBIT"
    return "FLY"


def pan_offset(rotation, dx, dy, distance, sensitivity):
    """Move the camera so the scene point under the cursor follows the drag."""
    _forward, right, up = fly_axes(rotation)
    scale = max(abs(distance), 0.01) * sensitivity
    return (-right * dx - up * dy) * scale


def zoom_distance(distance, dy, sensitivity):
    """Mouse-up zooms toward the pivot. The distance stays inside a finite range."""
    updated = distance * exp(-dy * sensitivity)
    return min(10000.0, max(0.01, updated))


def orbit_eye(eye, rotation, dx, dy, sensitivity, distance):
    """Orbit a camera eye around the pivot one view-distance ahead."""
    forward, _right, _up = fly_axes(rotation)
    pivot = Vector(eye) + forward * distance
    turned = fly_look(rotation, dx, dy, sensitivity)
    new_forward, _right, _up = fly_axes(turned)
    return pivot - new_forward * distance, turned


def scaled_speed(speed, faster, multiplier):
    return speed * multiplier if faster else speed


def scroll_speed(speed, up):
    factor = 1.1 if up else 1.0 / 1.1
    return min(1000.0, max(0.01, speed * factor))


def _preferences():
    addon = bpy.context.preferences.addons.get(__name__)
    return addon.preferences if addon else None


def _nav_preferences():
    preferences = _preferences()
    if preferences is None:
        return 4.0, 5.0, 0.003
    return preferences.speed, preferences.shift_multiplier, preferences.mouse_sensitivity


def _navigation_mode():
    preferences = _preferences()
    return getattr(preferences, "navigation_mode", _MMB_MODE)


def _stop_navigation():
    if _active_navigation is not None:
        _active_navigation._finish()


def _navigation_mode_changed(preferences, context):
    _stop_navigation()
    _register_keymap(preferences.navigation_mode)


def _mmb_view_available(context):
    area, region, view = context.area, context.region, context.region_data
    if area is None or area.type != "VIEW_3D" or region is None or region.type != "WINDOW" or view is None:
        return False
    space = context.space_data
    return view.view_perspective in {"PERSP", "ORTHO"} and not view.lock_rotation and not getattr(space, "lock_object", None) and not getattr(space, "lock_cursor", False) and context.preferences.inputs.view_rotate_method == "TURNTABLE"


def _foreign_navigation_modal(context):
    for operator in context.window.modal_operators:
        name = getattr(operator, "bl_idname", "")
        if operator == _active_navigation or name in {"view3d.mmb_wasd_move", "VIEW3D_OT_mmb_wasd_move", "screen.animation_play", "SCREEN_OT_animation_play"}:
            continue
        return True
    return False


class WASDFlyPreferences(AddonPreferences):
    bl_idname = __name__

    navigation_mode: EnumProperty(
        name="导航模式",
        items=((_MMB_MODE, "Blender 中键 WASD", "按住中键移动视口，松开恢复正常快捷键"), (_UNITY_MODE, "Unity 兼容模式", "保留原中键平移、右键飞行等操作")),
        default=_MMB_MODE,
        update=_navigation_mode_changed,
    )
    speed: FloatProperty(
        name="飞行速度",
        description="中键视口或兼容模式每秒移动的 Blender 单位",
        default=4.0,
        min=0.01,
        max=1000.0,
    )
    shift_multiplier: FloatProperty(
        name="Shift 倍率",
        description="按住 Shift 时加快飞行、平移、环绕和缩放",
        default=5.0,
        min=1.0,
        max=100.0,
    )
    mouse_sensitivity: FloatProperty(
        name="鼠标灵敏度",
        description="鼠标转向、环绕、平移和缩放的速度",
        default=0.003,
        min=0.0001,
        max=0.05,
        precision=4,
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "navigation_mode")
        layout.prop(self, "speed")
        if self.navigation_mode == _UNITY_MODE:
            layout.prop(self, "shift_multiplier")
        layout.prop(self, "mouse_sensitivity")


class _ViewDrag:
    def _begin_drag(self, context, event):
        _speed, self.shift_multiplier, self.sensitivity = _nav_preferences()
        self.faster = bool(event.shift)
        self.mouse = (event.mouse_x, event.mouse_y)
        self.region = context.region_data
        self._save_view(context)

    def _save_view(self, context):
        region = self.region
        self.saved_perspective = region.view_perspective
        self.saved_location = region.view_location.copy()
        self.saved_rotation = region.view_rotation.copy()
        self.saved_distance = region.view_distance
        camera = context.scene.camera if region.view_perspective == "CAMERA" else None
        self.camera = camera
        self.saved_camera = camera.matrix_world.copy() if camera else None

    def _restore_view(self):
        region = self.region
        region.view_location = self.saved_location
        region.view_rotation = self.saved_rotation
        region.view_distance = self.saved_distance
        if self.camera and self.saved_camera:
            self.camera.matrix_world = self.saved_camera

    def _track_mouse(self, event):
        dx = event.mouse_x - self.mouse[0]
        dy = event.mouse_y - self.mouse[1]
        self.mouse = (event.mouse_x, event.mouse_y)
        return dx, dy

    def _viewport_rotation(self):
        if self.camera:
            return self.camera.matrix_world.to_quaternion()
        return self.region.view_rotation

    def _viewport_distance(self):
        return max(abs(self.region.view_distance), 0.01)


class WASD_OT_mmb_move(_ViewDrag, Operator):
    bl_idname = "view3d.mmb_wasd_move"
    bl_label = "中键 WASD 视口移动"
    bl_description = "按住中键时 WASD 平移视口，中键拖动旋转，松开停止"
    bl_options = {"BLOCKING", "GRAB_CURSOR"}

    @classmethod
    def poll(cls, context):
        return _active_navigation is None and _navigation_mode() == _MMB_MODE and _mmb_view_available(context)

    def invoke(self, context, event):
        global _active_navigation
        if event.type != "MIDDLEMOUSE" or event.value != "PRESS" or event.shift or event.ctrl or event.alt or event.oskey or not WASD_OT_mmb_move.poll(context) or _foreign_navigation_modal(context):
            return {"PASS_THROUGH"}
        self.finished = False
        self.timer = None
        self.held = set()
        self.modifier_keys = set()
        self.manager, self.window, self.area = context.window_manager, context.window, context.area
        self.screen, self.view_region = context.window.screen, context.region
        try:
            self._begin_drag(context, event)
            self.speed = _nav_preferences()[0]
            if not isfinite(self.speed) or not isfinite(self.sensitivity):
                raise ValueError("导航速度或鼠标灵敏度无效")
            self.last_time = perf_counter()
            self.timer = self.manager.event_timer_add(_MMB_INTERVAL, window=self.window)
            self.last_timer_duration = self.timer.time_duration
            _active_navigation = self
            self.area.header_text_set("中键：WASD 移动，拖动旋转，松开停止，Esc/右键还原")
            self.manager.modal_handler_add(self)
            return {"RUNNING_MODAL"}
        except Exception as exc:
            self._finish()
            self.report({"WARNING"}, str(exc))
            return {"CANCELLED"}

    def _context_valid(self, context):
        try:
            return context.window == self.window and self.window.screen == self.screen and context.area == self.area and context.region == self.view_region and context.region_data == self.region and any(area == self.area for area in self.screen.areas) and _mmb_view_available(context) and not _foreign_navigation_modal(context)
        except ReferenceError:
            return False

    def modal(self, context, event):
        if self.finished:
            return {"CANCELLED", "PASS_THROUGH"}
        try:
            return self._modal_event(context, event)
        except Exception as exc:
            self._finish()
            self.report({"WARNING"}, str(exc))
            return {"CANCELLED"}

    def _modal_event(self, context, event):
        if event.type == "WINDOW_DEACTIVATE" or not self._context_valid(context):
            self._finish()
            return {"CANCELLED"}
        if event.type == "ESC" or (event.type == "RIGHTMOUSE" and event.value == "PRESS"):
            self._restore_view()
            self.area.tag_redraw()
            self._finish()
            return {"CANCELLED"}
        if event.type == "MIDDLEMOUSE" and event.value == "RELEASE":
            self._finish()
            return {"FINISHED"}
        if event.type in _MMB_KEYS:
            if event.value == "PRESS":
                self.held.add(event.type)
            elif event.value == "RELEASE":
                self.held.discard(event.type)
            return {"RUNNING_MODAL"}
        if event.type in _MODIFIER_KEYS:
            if event.value == "PRESS":
                self.modifier_keys.add(event.type)
            elif event.value == "RELEASE":
                self.modifier_keys.discard(event.type)
            return {"RUNNING_MODAL"}
        paused = bool(self.modifier_keys or event.shift or event.ctrl or event.alt or event.oskey)
        if event.type == "MOUSEMOVE":
            dx, dy = self._track_mouse(event)
            if not paused and (dx or dy):
                self.region.view_rotation = fly_look(self.region.view_rotation, dx, dy, self.sensitivity)
                self.area.tag_redraw()
            return {"RUNNING_MODAL"}
        if event.type == "TIMER":
            duration = self.timer.time_duration
            if duration <= self.last_timer_duration:
                return {"PASS_THROUGH"}
            self.last_timer_duration = duration
            now = perf_counter()
            dt = min(_MAX_MMB_DT, max(0.0, now - self.last_time))
            self.last_time = now
            if self.held and not paused:
                delta = fly_translation(self.region.view_rotation, self.held, self.speed, dt)
                if delta.length_squared > 0.0:
                    self.region.view_location += delta
                    self.area.tag_redraw()
            return {"RUNNING_MODAL"}
        if event.type in {"WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
            return {"PASS_THROUGH"}
        return {"RUNNING_MODAL"}

    def _finish(self):
        global _active_navigation
        if getattr(self, "finished", True):
            return
        self.finished = True
        if _active_navigation is self:
            _active_navigation = None
        self.held.clear()
        self.modifier_keys.clear()
        timer, self.timer = self.timer, None
        if timer is not None:
            try:
                self.manager.event_timer_remove(timer)
            except (ReferenceError, RuntimeError):
                pass
        try:
            if any(area == self.area for area in self.screen.areas):
                self.area.header_text_set(None)
        except ReferenceError:
            pass

    def cancel(self, context):
        self._finish()


class WASD_OT_fly_camera(_ViewDrag, Operator):
    bl_idname = "view3d.wasd_fly_camera"
    bl_label = "WASD 飞行"
    bl_description = "透视时按住右键飞行。正交时按住右键绕枢轴环绕"
    bl_options = {"UNDO", "BLOCKING"}

    @classmethod
    def poll(cls, context):
        return (
            context.area is not None
            and context.area.type == "VIEW_3D"
            and context.region is not None
            and context.region.type == "WINDOW"
            and context.region_data is not None
        )

    def invoke(self, context, event):
        region = context.region_data
        if region.view_perspective == "CAMERA" and context.scene.camera is None:
            self.report({"WARNING"}, "当前是相机视图，但场景没有相机")
            return {"CANCELLED"}
        self._begin_drag(context, event)
        self.speed = _nav_preferences()[0]
        self.held = set()
        self.orbit_pivot = right_drag_mode(region.view_perspective) == "ORBIT"
        self.timer = context.window_manager.event_timer_add(1.0 / 60.0, window=context.window)
        context.window.cursor_modal_set("NONE")
        if self.orbit_pivot:
            context.area.header_text_set("正交：按住右键绕枢轴环绕，松开保留，Esc 还原")
        else:
            context.area.header_text_set("飞行：WASD 移动，QE 上下，鼠标转向，Shift 加速，滚轮改速度，松开右键保留，Esc 还原")
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type == "ESC":
            self._restore_view()
            self._finish(context)
            return {"CANCELLED"}
        if event.type == "RIGHTMOUSE" and event.value == "RELEASE":
            self._finish(context)
            return {"FINISHED"}
        if self.orbit_pivot and event.type in {"WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
            return {"PASS_THROUGH"}
        if event.type in {"W", "A", "S", "D", "Q", "E"} and not self.orbit_pivot:
            if event.value == "PRESS":
                self.held.add(event.type)
            elif event.value == "RELEASE":
                self.held.discard(event.type)
            return {"RUNNING_MODAL"}
        if event.type in {"LEFT_SHIFT", "RIGHT_SHIFT"}:
            self.faster = event.value == "PRESS"
            return {"RUNNING_MODAL"}
        if event.type == "WHEELUPMOUSE" and not self.orbit_pivot:
            self.speed = scroll_speed(self.speed, True)
            return {"RUNNING_MODAL"}
        if event.type == "WHEELDOWNMOUSE" and not self.orbit_pivot:
            self.speed = scroll_speed(self.speed, False)
            return {"RUNNING_MODAL"}
        if event.type == "MOUSEMOVE":
            dx, dy = self._track_mouse(event)
            self._look(dx, dy)
            return {"RUNNING_MODAL"}
        if event.type == "TIMER":
            self._move()
            return {"RUNNING_MODAL"}
        return {"RUNNING_MODAL"}

    def _look(self, dx, dy):
        if dx == 0 and dy == 0:
            return
        if self.orbit_pivot:
            self.region.view_rotation = fly_look(self.region.view_rotation, dx, dy, self.sensitivity)
            return
        if self.camera:
            rotation = fly_look(self.camera.matrix_world.to_quaternion(), dx, dy, self.sensitivity)
            location = self.camera.matrix_world.to_translation()
            self.camera.matrix_world = rotation.to_matrix().to_4x4()
            self.camera.matrix_world.translation = location
            return
        eye = view_eye(self.region.view_location, self.region.view_rotation, self.region.view_distance)
        rotation = fly_look(self.region.view_rotation, dx, dy, self.sensitivity)
        self.region.view_rotation = rotation
        self.region.view_location = location_for_eye(eye, rotation, self.region.view_distance)

    def _move(self):
        if self.orbit_pivot or not self.held:
            return
        speed = scaled_speed(self.speed, self.faster, self.shift_multiplier)
        rotation = self._viewport_rotation()
        delta = fly_translation(rotation, self.held, speed, 1.0 / 60.0)
        if self.camera:
            self.camera.location += delta
            return
        eye = view_eye(self.region.view_location, self.region.view_rotation, self.region.view_distance) + delta
        self.region.view_location = location_for_eye(eye, rotation, self.region.view_distance)

    def _finish(self, context):
        context.window_manager.event_timer_remove(self.timer)
        context.window.cursor_modal_restore()
        if context.area:
            context.area.header_text_set(None)


class WASD_OT_scene_nav(_ViewDrag, Operator):
    bl_idname = "view3d.unity_scene_nav"
    bl_label = "视口导航"
    bl_description = "按 Unity 场景视口平移、环绕或缩放预览"
    bl_options = {"UNDO", "BLOCKING"}

    action: EnumProperty(
        items=(
            ("PAN", "平移", "中键拖动平移"),
            ("ORBIT", "环绕", "Alt 加左键绕枢轴环绕"),
            ("ZOOM", "缩放", "Alt 加右键拖动缩放"),
        ),
        default="PAN",
        options={"HIDDEN", "SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context):
        return WASD_OT_fly_camera.poll(context)

    def invoke(self, context, event):
        if context.region_data.view_perspective == "CAMERA" and context.scene.camera is None:
            self.report({"WARNING"}, "当前是相机视图，但场景没有相机")
            return {"CANCELLED"}
        self._begin_drag(context, event)
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type == "ESC":
            self._restore_view()
            return {"CANCELLED"}
        if event.type in {"LEFT_SHIFT", "RIGHT_SHIFT"}:
            self.faster = event.value == "PRESS"
            return {"RUNNING_MODAL"}
        if event.type == "MOUSEMOVE":
            dx, dy = self._track_mouse(event)
            if self.faster:
                dx *= self.shift_multiplier
                dy *= self.shift_multiplier
            self._apply(dx, dy)
            return {"RUNNING_MODAL"}
        release = {"PAN": "MIDDLEMOUSE", "ORBIT": "LEFTMOUSE", "ZOOM": "RIGHTMOUSE"}[self.action]
        if event.type == release and event.value == "RELEASE":
            return {"FINISHED"}
        return {"RUNNING_MODAL"}

    def _apply(self, dx, dy):
        if dx == 0 and dy == 0:
            return
        rotation = self._viewport_rotation()
        distance = self._viewport_distance()
        if self.action == "PAN":
            offset = pan_offset(rotation, dx, dy, distance, self.sensitivity)
            if self.camera:
                self.camera.location += offset
            else:
                self.region.view_location += offset
            return
        if self.action == "ORBIT":
            if self.camera:
                eye, turned = orbit_eye(
                    self.camera.matrix_world.to_translation(),
                    rotation,
                    dx,
                    dy,
                    self.sensitivity,
                    distance,
                )
                self.camera.matrix_world = turned.to_matrix().to_4x4()
                self.camera.matrix_world.translation = eye
            else:
                self.region.view_rotation = fly_look(rotation, dx, dy, self.sensitivity)
            return
        if self.camera:
            eye, _right, _up = fly_axes(rotation)
            step = dy * distance * self.sensitivity
            self.camera.location += eye * step
            return
        self.region.view_distance = zoom_distance(self.region.view_distance, dy, self.sensitivity)


class WASD_OT_frame_selected(Operator):
    bl_idname = "view3d.unity_frame_selected"
    bl_label = "框选居中"
    bl_description = "把预览对准选中的物体，对应 Unity 场景视口的 F"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return (
            context.area is not None
            and context.area.type == "VIEW_3D"
            and context.mode == "OBJECT"
        )

    def execute(self, context):
        return bpy.ops.view3d.view_selected()


class WASD_PT_fly_camera(Panel):
    bl_label = "场景预览"
    bl_idname = "WASD_PT_fly_camera"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "飞行"

    def draw(self, context):
        layout = self.layout
        preferences = _preferences()
        if preferences:
            layout.prop(preferences, "navigation_mode")
        if _navigation_mode() == _MMB_MODE:
            layout.label(text="按住中键：W/S 前后，A/D 左右")
            layout.label(text="拖动中键旋转；松开中键停止")
            layout.label(text="Esc/右键还原本次视口操作")
            layout.label(text="普通 Turntable 视口；不移动场景相机")
            if preferences:
                layout.prop(preferences, "speed")
                layout.prop(preferences, "mouse_sensitivity")
            return
        layout.label(text="中键平移，Alt+左键环绕，Alt+右键缩放")
        layout.label(text="透视：按住右键飞行，滚轮改速度")
        layout.label(text="正交：按住右键绕枢轴环绕")
        layout.label(text="W/S 前后，A/D 左右，Q/E 上下，Shift 加速")
        layout.label(text="物体模式按 F 框住选中，Esc 还原本次操作")
        preferences = _preferences()
        if preferences:
            layout.prop(preferences, "speed")
            layout.prop(preferences, "shift_multiplier")
            layout.prop(preferences, "mouse_sensitivity")
        region = context.region_data
        if region and region.view_perspective == "CAMERA":
            layout.label(text="当前移动场景相机")
        elif region and region.view_perspective == "ORTHO":
            layout.label(text="正交视图按住右键环绕")
        else:
            layout.label(text="当前移动视口预览")


def _clear_keymaps():
    for keymap, item in _ADDON_KEYMAPS:
        try:
            keymap.keymap_items.remove(item)
        except (ReferenceError, RuntimeError):
            pass
    _ADDON_KEYMAPS.clear()


def _register_keymap(mode=None):
    _clear_keymaps()
    config = bpy.context.window_manager.keyconfigs.addon
    if config is None:
        return
    keymap = config.keymaps.new(
        name="3D View",
        space_type="VIEW_3D",
    )
    if (mode or _navigation_mode()) == _MMB_MODE:
        item = keymap.keymap_items.new("view3d.mmb_wasd_move", "MIDDLEMOUSE", "PRESS")
        _ADDON_KEYMAPS.append((keymap, item))
        return
    fly_item = keymap.keymap_items.new("view3d.wasd_fly_camera", "RIGHTMOUSE", "PRESS")
    pan_item = keymap.keymap_items.new("view3d.unity_scene_nav", "MIDDLEMOUSE", "PRESS")
    pan_item.properties.action = "PAN"
    orbit_item = keymap.keymap_items.new("view3d.unity_scene_nav", "LEFTMOUSE", "PRESS")
    orbit_item.alt = True
    orbit_item.properties.action = "ORBIT"
    zoom_item = keymap.keymap_items.new("view3d.unity_scene_nav", "RIGHTMOUSE", "PRESS")
    zoom_item.alt = True
    zoom_item.properties.action = "ZOOM"
    frame_item = keymap.keymap_items.new("view3d.unity_frame_selected", "F", "PRESS")
    for item in (fly_item, pan_item, orbit_item, zoom_item, frame_item):
        _ADDON_KEYMAPS.append((keymap, item))


@bpy.app.handlers.persistent
def _load_pre(*args):
    _stop_navigation()


def register():
    bpy.utils.register_class(WASDFlyPreferences)
    bpy.utils.register_class(WASD_OT_mmb_move)
    bpy.utils.register_class(WASD_OT_fly_camera)
    bpy.utils.register_class(WASD_OT_scene_nav)
    bpy.utils.register_class(WASD_OT_frame_selected)
    bpy.utils.register_class(WASD_PT_fly_camera)
    _register_keymap()
    if _load_pre not in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.append(_load_pre)


def unregister():
    _stop_navigation()
    if _load_pre in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.remove(_load_pre)
    _clear_keymaps()
    bpy.utils.unregister_class(WASD_PT_fly_camera)
    bpy.utils.unregister_class(WASD_OT_frame_selected)
    bpy.utils.unregister_class(WASD_OT_scene_nav)
    bpy.utils.unregister_class(WASD_OT_fly_camera)
    bpy.utils.unregister_class(WASD_OT_mmb_move)
    bpy.utils.unregister_class(WASDFlyPreferences)
