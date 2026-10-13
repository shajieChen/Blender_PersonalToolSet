"""Preview the 3D viewport with Unity Scene view controls.

Perspective: hold the right mouse button to fly. The mouse looks around the
eye, WASD move along the look direction, and Q/E move on world up.
Orthographic: holding the right mouse button orbits the current pivot.
Middle-mouse pans, Alt+left-mouse orbits, and Alt+right-mouse zooms.
Shift speeds those drags up. Scroll changes fly speed only while flying.
Esc restores the view from when the drag started.
"""

from __future__ import annotations

from math import exp

import bpy
from bpy.props import EnumProperty, FloatProperty
from bpy.types import AddonPreferences, Operator, Panel
from mathutils import Quaternion, Vector

bl_info = {
    "name": "WASD Fly Camera",
    "author": "Blender Plugin",
    "version": (1, 1, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > 飞行",
    "description": "用 Unity 场景视口的方式平移、环绕、缩放和飞行预览相机",
    "category": "3D View",
}

_ADDON_KEYMAPS = []
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


class WASDFlyPreferences(AddonPreferences):
    bl_idname = __name__

    speed: FloatProperty(
        name="飞行速度",
        description="按住右键飞行时相机每秒移动的距离",
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
        layout.prop(self, "speed")
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


def _register_keymap():
    keymap = bpy.context.window_manager.keyconfigs.addon.keymaps.new(
        name="3D View",
        space_type="VIEW_3D",
    )
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


def register():
    bpy.utils.register_class(WASDFlyPreferences)
    bpy.utils.register_class(WASD_OT_fly_camera)
    bpy.utils.register_class(WASD_OT_scene_nav)
    bpy.utils.register_class(WASD_OT_frame_selected)
    bpy.utils.register_class(WASD_PT_fly_camera)
    _register_keymap()


def unregister():
    for keymap, item in _ADDON_KEYMAPS:
        keymap.keymap_items.remove(item)
    _ADDON_KEYMAPS.clear()
    bpy.utils.unregister_class(WASD_PT_fly_camera)
    bpy.utils.unregister_class(WASD_OT_frame_selected)
    bpy.utils.unregister_class(WASD_OT_scene_nav)
    bpy.utils.unregister_class(WASD_OT_fly_camera)
    bpy.utils.unregister_class(WASDFlyPreferences)
