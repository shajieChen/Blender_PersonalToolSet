from dataclasses import dataclass, field
from math import cos, isfinite, pi, sin

import blf
import bpy
import gpu
from bpy_extras.view3d_utils import location_3d_to_region_2d
from gpu_extras.batch import batch_for_shader
from mathutils import Vector

from .targets import target_armature


_handle = None
_label_handle = None
_shader = None
_bone_color = (0.1, 1.0, 0.75, 1.0)
_active_color = (1.0, 0.85, 0.12, 1.0)
_collider_color = (1.0, 0.22, 0.65, 0.95)
_outline_color = (0.015, 0.025, 0.04, 0.9)
_circle_segments = 24


@dataclass
class SpringBoneDrawing:
    bone_lines: list = field(default_factory=list)
    active_lines: list = field(default_factory=list)
    collider_lines: list = field(default_factory=list)


def _ring(center, axis_x, axis_y, radius, segments):
    vertices = []
    for index in range(segments):
        for angle in (2.0 * pi * index / segments, 2.0 * pi * (index + 1) / segments):
            vertices.append(center + radius * (axis_x * cos(angle) + axis_y * sin(angle)))
    return vertices


def sphere_lines(center, radius, segments=_circle_segments):
    if not isfinite(radius) or radius <= 0.0:
        return []
    axes = (Vector((1.0, 0.0, 0.0)), Vector((0.0, 1.0, 0.0)), Vector((0.0, 0.0, 1.0)))
    vertices = []
    for first, second in ((0, 1), (1, 2), (2, 0)):
        vertices.extend(_ring(center, axes[first], axes[second], radius, segments))
    return vertices


def capsule_lines(start, end, radius):
    if not isfinite(radius) or radius <= 0.0:
        return []
    delta = end - start
    if delta.length <= 1e-8:
        return sphere_lines(start, radius)
    axis = delta.normalized()
    seed = Vector((1.0, 0.0, 0.0)) if abs(axis.x) < 0.9 else Vector((0.0, 1.0, 0.0))
    axis_x = axis.cross(seed).normalized()
    axis_y = axis.cross(axis_x).normalized()
    vertices = _ring(start, axis_x, axis_y, radius, _circle_segments)
    vertices.extend(_ring(end, axis_x, axis_y, radius, _circle_segments))
    for radial in (axis_x, axis_y, -axis_x, -axis_y):
        vertices.extend((start + radial * radius, end + radial * radius))
        for center, sign in ((start, -1.0), (end, 1.0)):
            for index in range(6):
                for angle in (pi * index / 12.0, pi * (index + 1) / 12.0):
                    vertices.append(center + radius * (radial * cos(angle) + axis * sign * sin(angle)))
    return vertices


def _bone_lines(head, tail):
    delta = tail - head
    length = delta.length
    if length <= 1e-8:
        return []
    axis = delta / length
    seed = Vector((1.0, 0.0, 0.0)) if abs(axis.x) < 0.9 else Vector((0.0, 1.0, 0.0))
    axis_x = axis.cross(seed).normalized() * length * 0.075
    axis_z = axis.cross(axis_x).normalized() * length * 0.075
    center = head + delta * 0.25
    corners = (center + axis_x, center + axis_z, center - axis_x, center - axis_z)
    vertices = [head, tail]
    for index, corner in enumerate(corners):
        vertices.extend((head, corner, tail, corner, corner, corners[(index + 1) % 4]))
    vertices.extend(sphere_lines(head, length * 0.04, 8))
    vertices.extend(sphere_lines(tail, length * 0.04, 8))
    return vertices


def _build_geometry(armature, settings, scale_length):
    drawing = SpringBoneDrawing()
    if not isfinite(scale_length) or scale_length <= 0.0:
        return drawing
    world = armature.matrix_world
    for index, chain in enumerate(settings.chains):
        lines = drawing.active_lines if index == settings.active_chain else drawing.bone_lines
        for item in chain.bone_names:
            pose = armature.pose.bones.get(item.name)
            if pose is None:
                continue
            head = world @ pose.head
            tail = world @ pose.tail
            lines.extend(_bone_lines(head, tail))
    for collider in settings.colliders:
        pose = armature.pose.bones.get(collider.bone_name)
        if pose is None:
            continue
        matrix = world @ pose.matrix
        start = matrix @ (Vector(collider.head_offset_m) / scale_length)
        radius = float(collider.radius_m) / scale_length
        if collider.shape == "CAPSULE":
            end = matrix @ (Vector(collider.tail_offset_m) / scale_length)
            drawing.collider_lines.extend(capsule_lines(start, end, radius))
        else:
            drawing.collider_lines.extend(sphere_lines(start, radius))
    return drawing


def _drawing_target():
    obj = target_armature(bpy.context)
    if obj is None or obj.type != "ARMATURE" or obj.mode == "EDIT":
        return None
    settings = getattr(obj, "sb_settings", None)
    if settings is None or not settings.show_gizmos:
        return None
    space = bpy.context.space_data
    if space is not None and space.type == "VIEW_3D" and not space.overlay.show_overlays:
        return None
    return obj


def _evaluated_drawing(obj):
    from .operators import job_running

    if job_running():
        return None
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    return _build_geometry(evaluated, obj.sb_settings, float(bpy.context.scene.unit_settings.scale_length))


def _draw_lines(vertices, color, width):
    global _shader
    if not vertices:
        return
    if _shader is None:
        _shader = gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
    batch = batch_for_shader(_shader, "LINES", {"pos": vertices})
    _shader.bind()
    _shader.uniform_float("viewportSize", gpu.state.viewport_get()[2:])
    _shader.uniform_float("lineWidth", width)
    _shader.uniform_float("color", color)
    batch.draw(_shader)


def depth_groups(vertices, view_matrix):
    groups = [[], [], []]
    if not vertices:
        return groups
    distances = [-(view_matrix @ ((vertices[index] + vertices[index + 1]) * 0.5)).z for index in range(0, len(vertices), 2)]
    nearest = min(distances)
    span = max(distances) - nearest
    for index, distance in enumerate(distances):
        bucket = min(2, int((distance - nearest) * 3.0 / span)) if span > 1e-8 else 0
        groups[bucket].extend(vertices[index * 2:index * 2 + 2])
    return groups


def _draw_depth_lines(vertices, color, width, view_matrix):
    groups = depth_groups(vertices, view_matrix)
    gpu.state.depth_test_set("NONE")
    for index in (2, 1, 0):
        lines = groups[index]
        gray_weight = (0.0, 0.3, 0.6)[index]
        gray = (0.2, 0.2, 0.2)
        visible = tuple(value * (1.0 - gray_weight) + gray[channel] * gray_weight for channel, value in enumerate(color[:3])) + (color[3],)
        _draw_lines(lines, _outline_color, width + 3.0)
        _draw_lines(lines, visible, width)


def draw_callback():
    obj = _drawing_target()
    if obj is None:
        return
    drawing = _evaluated_drawing(obj)
    if drawing is None:
        return
    blend = gpu.state.blend_get()
    depth = gpu.state.depth_test_get()
    mask = gpu.state.depth_mask_get()
    try:
        gpu.state.blend_set("ALPHA")
        gpu.state.depth_mask_set(False)
        view_matrix = bpy.context.region_data.view_matrix
        for vertices, color, width in (
            (drawing.bone_lines, _bone_color, 3.0),
            (drawing.active_lines, _active_color, 4.0),
            (drawing.collider_lines, _collider_color, 2.5),
        ):
            _draw_depth_lines(vertices, color, width, view_matrix)
    finally:
        gpu.state.blend_set(blend)
        gpu.state.depth_test_set(depth)
        gpu.state.depth_mask_set(mask)


def draw_labels():
    obj = _drawing_target()
    if obj is None:
        return
    from .operators import job_running

    settings = obj.sb_settings
    if job_running() or not settings.chains:
        return
    region = bpy.context.region
    region_data = bpy.context.region_data
    if region is None or region_data is None:
        return
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    blf.size(0, 12)
    for index, chain in enumerate(settings.chains):
        if not chain.bone_names:
            continue
        pose = evaluated.pose.bones.get(chain.bone_names[0].name)
        if pose is None:
            continue
        position = evaluated.matrix_world @ pose.head
        screen = location_3d_to_region_2d(region, region_data, position)
        if screen is None:
            continue
        blf.position(0, screen.x + 5.0, screen.y + 5.0, 0.0)
        blf.color(0, 0.02, 0.02, 0.02, 1.0)
        blf.draw(0, chain.name)
        blf.position(0, screen.x + 4.0, screen.y + 6.0, 0.0)
        color = _active_color if index == settings.active_chain else _bone_color
        blf.color(0, *color)
        blf.draw(0, chain.name)


def register_draw():
    global _handle, _label_handle
    if _handle is None:
        _handle = bpy.types.SpaceView3D.draw_handler_add(draw_callback, (), "WINDOW", "POST_VIEW")
    if _label_handle is None:
        _label_handle = bpy.types.SpaceView3D.draw_handler_add(draw_labels, (), "WINDOW", "POST_PIXEL")


def unregister_draw():
    global _handle, _label_handle, _shader
    if _handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_handle, "WINDOW")
        _handle = None
    if _label_handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_label_handle, "WINDOW")
        _label_handle = None
    _shader = None
