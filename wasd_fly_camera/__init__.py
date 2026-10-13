"""Fly the 3D viewport like the Unity Scene view.

Hold the right mouse button, then use the mouse to look and WASD to move.
Q and E move along world up. Shift moves faster. The scroll wheel changes speed.
Release the right mouse button to keep the view. Esc restores the view from
when the flight started. Orthographic views do not fly.
"""

from __future__ import annotations

import bpy
from bpy.props import FloatProperty
from bpy.types import AddonPreferences, Operator, Panel
from mathutils import Quaternion, Vector

bl_info = {
    "name": "WASD Fly Camera",
    "author": "Blender Plugin",
    "version": (1, 0, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > 飞行",
    "description": "按住鼠标右键，用 WASD 飞行预览相机，操作对齐 Unity 场景视图",
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


def scaled_speed(speed, faster, multiplier):
    return speed * multiplier if faster else speed


def scroll_speed(speed, up):
    factor = 1.1 if up else 1.0 / 1.1
    return min(1000.0, max(0.01, speed * factor))


def _preferences():
    addon = bpy.context.preferences.addons.get(__name__)
    return addon.preferences if addon else None


class WASDFlyPreferences(AddonPreferences):
    bl_idname = __name__

    speed: FloatProperty(
        name="飞行速度",
        description="按住右键时相机每秒移动的距离",
        default=4.0,
        min=0.01,
        max=1000.0,
    )
    shift_multiplier: FloatProperty(
        name="Shift 倍率",
        description="按住 Shift 时的速度倍率，对应 Unity 飞行加速",
        default=5.0,
        min=1.0,
        max=100.0,
    )
    mouse_sensitivity: FloatProperty(
        name="鼠标灵敏度",
        description="按住右键时鼠标移动转向的速度",
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


class WASD_OT_fly_camera(Operator):
    bl_idname = "view3d.wasd_fly_camera"
    bl_label = "WASD 飞行"
    bl_description = "按住鼠标右键飞行。W/S 前后，A/D 左右，Q/E 上下，Shift 加速，滚轮改速度"
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
        if region.view_perspective == "ORTHO":
            self.report({"WARNING"}, "正交视图不进入飞行。Unity 的飞行只用于透视场景相机")
            return {"CANCELLED"}
        if region.view_perspective == "CAMERA" and context.scene.camera is None:
            self.report({"WARNING"}, "当前是相机视图，但场景没有相机")
            return {"CANCELLED"}
        preferences = _preferences()
        self.speed = preferences.speed if preferences else 4.0
        self.shift_multiplier = preferences.shift_multiplier if preferences else 5.0
        self.sensitivity = preferences.mouse_sensitivity if preferences else 0.003
        self.held = set()
        self.faster = False
        self.mouse = (event.mouse_x, event.mouse_y)
        self.region = region
        self._save_view(context)
        self.timer = context.window_manager.event_timer_add(1.0 / 60.0, window=context.window)
        context.window.cursor_modal_set("NONE")
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
        if event.type in {"W", "A", "S", "D", "Q", "E"}:
            if event.value == "PRESS":
                self.held.add(event.type)
            elif event.value == "RELEASE":
                self.held.discard(event.type)
            return {"RUNNING_MODAL"}
        if event.type in {"LEFT_SHIFT", "RIGHT_SHIFT"}:
            self.faster = event.value == "PRESS"
            return {"RUNNING_MODAL"}
        if event.type == "WHEELUPMOUSE":
            self.speed = scroll_speed(self.speed, True)
            return {"RUNNING_MODAL"}
        if event.type == "WHEELDOWNMOUSE":
            self.speed = scroll_speed(self.speed, False)
            return {"RUNNING_MODAL"}
        if event.type == "MOUSEMOVE":
            dx = event.mouse_x - self.mouse[0]
            dy = event.mouse_y - self.mouse[1]
            self.mouse = (event.mouse_x, event.mouse_y)
            self._look(dx, dy)
            return {"RUNNING_MODAL"}
        if event.type == "TIMER":
            self._move()
            return {"RUNNING_MODAL"}
        return {"RUNNING_MODAL"}

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

    def _look(self, dx, dy):
        if dx == 0 and dy == 0:
            return
        if self.camera:
            rotation = fly_look(self.camera.matrix_world.to_quaternion(), dx, dy, self.sensitivity)
            location = self.camera.matrix_world.to_translation()
            self.camera.matrix_world = rotation.to_matrix().to_4x4()
            self.camera.matrix_world.translation = location
            return
        self.region.view_rotation = fly_look(self.region.view_rotation, dx, dy, self.sensitivity)

    def _move(self):
        if not self.held:
            return
        speed = scaled_speed(self.speed, self.faster, self.shift_multiplier)
        rotation = self.camera.matrix_world.to_quaternion() if self.camera else self.region.view_rotation
        delta = fly_translation(rotation, self.held, speed, 1.0 / 60.0)
        if self.camera:
            self.camera.location += delta
            return
        self.region.view_location += delta

    def _finish(self, context):
        context.window_manager.event_timer_remove(self.timer)
        context.window.cursor_modal_restore()
        if context.area:
            context.area.header_text_set(None)


class WASD_PT_fly_camera(Panel):
    bl_label = "WASD 飞行相机"
    bl_idname = "WASD_PT_fly_camera"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "飞行"

    def draw(self, context):
        layout = self.layout
        preferences = _preferences()
        layout.label(text="按住鼠标右键开始飞行")
        layout.label(text="W/S 前后，A/D 左右，Q/E 上下")
        layout.label(text="Shift 加速，滚轮改变速度")
        layout.label(text="松开右键保留视角，Esc 还原")
        if preferences:
            layout.prop(preferences, "speed")
            layout.prop(preferences, "shift_multiplier")
            layout.prop(preferences, "mouse_sensitivity")
        region = context.region_data
        if region and region.view_perspective == "CAMERA":
            layout.label(text="当前移动场景相机")
        elif region and region.view_perspective == "ORTHO":
            layout.label(text="正交视图不飞行")
        else:
            layout.label(text="当前移动视口预览")


def _register_keymap():
    keymap = bpy.context.window_manager.keyconfigs.addon.keymaps.new(
        name="3D View",
        space_type="VIEW_3D",
    )
    item = keymap.keymap_items.new("view3d.wasd_fly_camera", "RIGHTMOUSE", "PRESS")
    _ADDON_KEYMAPS.append((keymap, item))


def register():
    bpy.utils.register_class(WASDFlyPreferences)
    bpy.utils.register_class(WASD_OT_fly_camera)
    bpy.utils.register_class(WASD_PT_fly_camera)
    _register_keymap()


def unregister():
    for keymap, item in _ADDON_KEYMAPS:
        keymap.keymap_items.remove(item)
    _ADDON_KEYMAPS.clear()
    bpy.utils.unregister_class(WASD_PT_fly_camera)
    bpy.utils.unregister_class(WASD_OT_fly_camera)
    bpy.utils.unregister_class(WASDFlyPreferences)
