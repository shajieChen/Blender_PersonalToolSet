"""Viewport skeleton gizmos for the retarget source and target.

MotionBuilder, Maya and Unreal draw a marker on each joint and a line to the
next joint. Blender's octahedral bones follow local Y, which on these game
rigs points sideways, so the overlay uses the body chain instead.
"""

from __future__ import annotations

import blf
import bpy
import gpu
from bpy_extras.view3d_utils import location_3d_to_region_2d
from gpu_extras.batch import batch_for_shader
from mathutils import Vector

from .classify import classify_armature

_HANDLE = None
_LABEL_HANDLE = None
_ROLE_CACHE = {}

_CHAIN = {
    "hips": "spine",
    "spine": "chest",
    "chest": "neck",
    "neck": "head",
    "shoulder_l": "upperarm_l",
    "upperarm_l": "forearm_l",
    "forearm_l": "hand_l",
    "shoulder_r": "upperarm_r",
    "upperarm_r": "forearm_r",
    "forearm_r": "hand_r",
    "thigh_l": "shin_l",
    "shin_l": "foot_l",
    "foot_l": "toe_l",
    "thigh_r": "shin_r",
    "shin_r": "foot_r",
    "foot_r": "toe_r",
}

_COLOR = {
    "center": (0.96, 0.78, 0.22, 1.0),
    "left": (0.30, 0.62, 1.0, 1.0),
    "right": (1.0, 0.38, 0.32, 1.0),
}

# Standard humanoid skeleton names (UE5 Mannequin style). Drawn next to each
# mapped joint together with the rig's own bone name.
_STANDARD_NAMES = {
    "hips": "pelvis",
    "spine": "spine_01",
    "chest": "spine_02",
    "neck": "neck_01",
    "head": "head",
    "shoulder_l": "clavicle_l",
    "shoulder_r": "clavicle_r",
    "upperarm_l": "upperarm_l",
    "upperarm_r": "upperarm_r",
    "forearm_l": "lowerarm_l",
    "forearm_r": "lowerarm_r",
    "hand_l": "hand_l",
    "hand_r": "hand_r",
    "thigh_l": "thigh_l",
    "thigh_r": "thigh_r",
    "shin_l": "calf_l",
    "shin_r": "calf_r",
    "foot_l": "foot_l",
    "foot_r": "foot_r",
    "toe_l": "ball_l",
    "toe_r": "ball_r",
}

_LABEL_COLOR = (0.92, 0.92, 0.92, 0.9)

_OCTA = (
    (0, 2), (0, 3), (0, 4), (0, 5),
    (1, 2), (1, 3), (1, 4), (1, 5),
    (2, 4), (4, 3), (3, 5), (5, 2),
)


def _side(role):
    if role.endswith("_l"):
        return "left"
    if role.endswith("_r"):
        return "right"
    return "center"


def _mapped_roles(arm, settings):
    if settings is None or not settings.mappings:
        return None
    source = arm == settings.source
    target = arm == settings.target
    if not source and not target:
        return None
    roles = {}
    for item in settings.mappings:
        name = item.source_bone if source else item.target_bone
        if item.role and name:
            roles[item.role] = name
    return roles or None


def _roles_for(arm, settings):
    mapped = _mapped_roles(arm, settings)
    if mapped:
        return mapped
    token = (arm.as_pointer(), len(arm.data.bones))
    cached = _ROLE_CACHE.get(token)
    if cached is None:
        cached = classify_armature(arm)
        _ROLE_CACHE[token] = cached
    return cached


def _evaluated(arm):
    try:
        depsgraph = bpy.context.evaluated_depsgraph_get()
        return arm.evaluated_get(depsgraph)
    except Exception:
        return arm


def _joint(arm, name):
    pose = arm.pose.bones.get(name) if arm and arm.pose else None
    if pose is None:
        return None
    return arm.matrix_world @ pose.head


def gizmo_links(arm, roles):
    """World-space joint links. Each item is (role, child_role, start, end)."""
    links = []
    if arm is None or not roles:
        return links
    for role, child in _CHAIN.items():
        if role not in roles or child not in roles:
            continue
        start = _joint(arm, roles[role])
        end = _joint(arm, roles[child])
        if start is None or end is None or (end - start).length < 1e-6:
            continue
        links.append((role, child, start, end))
    return links


def _radius(links):
    longest = 0.0
    for _role, _child, start, end in links:
        longest = max(longest, (end - start).length)
    return max(longest * 0.08, 1e-4)


def _octa(center, radius):
    offsets = (
        Vector((0.0, 0.0, radius)),
        Vector((0.0, 0.0, -radius)),
        Vector((radius, 0.0, 0.0)),
        Vector((-radius, 0.0, 0.0)),
        Vector((0.0, radius, 0.0)),
        Vector((0.0, -radius, 0.0)),
    )
    points = [center + offset for offset in offsets]
    return [(points[a], points[b]) for a, b in _OCTA]


def _buckets(arm, roles):
    buckets = {side: [] for side in _COLOR}
    links = gizmo_links(arm, roles)
    radius = _radius(links)
    seen = set()
    for role, _child, start, end in links:
        buckets[_side(role)].extend((start, end))
        if role not in seen:
            seen.add(role)
            for segment in _octa(start, radius):
                buckets[_side(role)].extend(segment)
        if _child not in seen:
            seen.add(_child)
            for segment in _octa(end, radius):
                buckets[_side(_child)].extend(segment)
    return buckets


def _shader():
    try:
        return gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR"), True
    except Exception:
        return gpu.shader.from_builtin("UNIFORM_COLOR"), False


def _draw_arm(arm, settings):
    roles = _roles_for(arm, settings)
    if not roles:
        return
    evaluated = _evaluated(arm)
    buckets = _buckets(evaluated, roles)
    shader, polyline = _shader()
    region = bpy.context.region
    for side, coords in buckets.items():
        if len(coords) < 2:
            continue
        batch = batch_for_shader(shader, "LINES", {"pos": coords})
        shader.bind()
        shader.uniform_float("color", _COLOR[side])
        if polyline and region is not None:
            shader.uniform_float("lineWidth", 2.5)
            shader.uniform_float("viewportSize", (float(region.width), float(region.height)))
        batch.draw(shader)


def draw_callback():
    context = bpy.context
    scene = getattr(context, "scene", None)
    settings = getattr(scene, "hr_settings", None) if scene is not None else None
    if settings is None or not settings.draw_bone_gizmos:
        return
    if context.region_data is None:
        return
    try:
        gpu.state.blend_set("ALPHA")
        gpu.state.depth_test_set("NONE")
        for arm in (settings.source, settings.target):
            if arm is not None and getattr(arm, "type", None) == "ARMATURE":
                _draw_arm(arm, settings)
    except Exception as exc:
        print("[HumanoidRetarget] gizmo:", exc)
    finally:
        gpu.state.blend_set("NONE")
        gpu.state.depth_test_set("NONE")


def _draw_labels(arm, settings, region, rv3d):
    """Screen-space labels: standard skeleton name plus the rig's bone name."""
    roles = _roles_for(arm, settings)
    if not roles:
        return
    evaluated = _evaluated(arm)
    font_id = 0
    placed = []
    for role, bone_name in roles.items():
        joint = _joint(evaluated, bone_name)
        if joint is None:
            continue
        screen = location_3d_to_region_2d(region, rv3d, joint)
        if screen is None:
            continue
        if any((screen - other).length < 10.0 for other in placed):
            continue
        placed.append(screen)
        standard = _STANDARD_NAMES.get(role, role)
        x = screen.x + 5.0
        y = screen.y + 5.0
        blf.size(font_id, 11.0)
        blf.color(font_id, *_COLOR[_side(role)])
        blf.position(font_id, x, y, 0)
        blf.draw(font_id, standard)
        if bone_name.lower() == standard:
            continue
        _width, height = blf.dimensions(font_id, standard)
        blf.size(font_id, 9.0)
        blf.color(font_id, *_LABEL_COLOR)
        blf.position(font_id, x, y - height - 1.0, 0)
        blf.draw(font_id, bone_name)


def draw_label_callback():
    context = bpy.context
    scene = getattr(context, "scene", None)
    settings = getattr(scene, "hr_settings", None) if scene is not None else None
    if settings is None or not settings.show_gizmo_labels:
        return
    region = getattr(context, "region", None)
    rv3d = getattr(context, "region_data", None)
    if region is None or rv3d is None:
        return
    try:
        for arm in (settings.source, settings.target):
            if arm is not None and getattr(arm, "type", None) == "ARMATURE":
                _draw_labels(arm, settings, region, rv3d)
    except Exception as exc:
        print("[HumanoidRetarget] labels:", exc)


def register_draw():
    global _HANDLE, _LABEL_HANDLE
    if _HANDLE is None:
        _HANDLE = bpy.types.SpaceView3D.draw_handler_add(draw_callback, (), "WINDOW", "POST_VIEW")
    if _LABEL_HANDLE is None:
        _LABEL_HANDLE = bpy.types.SpaceView3D.draw_handler_add(draw_label_callback, (), "WINDOW", "POST_PIXEL")


def unregister_draw():
    global _HANDLE, _LABEL_HANDLE
    if _HANDLE is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_HANDLE, "WINDOW")
        _HANDLE = None
    if _LABEL_HANDLE is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_LABEL_HANDLE, "WINDOW")
        _LABEL_HANDLE = None
    _ROLE_CACHE.clear()
