"""Screen positions of the View3D navigation gizmo. No Blender imports.

Mirrors source/blender/editors/space_view3d/view3d_gizmo_navigate.cc so a hover
test lands on the same buttons Blender draws.
"""

MINI_SIZE = 28.0
MINI_OFFSET = 2.0
GIZMO_OFFSET = 10.0


def round_half_away(value):
    if value >= 0:
        return int(value + 0.5)
    return int(value - 0.5)


def ui_scale_factor(dpi, pixel_size, ui_scale):
    return (dpi * pixel_size / 72.0) * ui_scale


def navigation_hotspots(
    width,
    height,
    *,
    ui_scale,
    gizmo_size,
    mini_axis_type,
    mini_axis_size,
    show_navigate,
    show_gizmo,
    view_perspective,
    lock_rotation,
):
    """Return hit targets in region pixels, origin at the bottom left."""
    if width <= 0 or height <= 0 or ui_scale <= 0:
        return []
    if not show_gizmo:
        return []
    show_rotate = mini_axis_type == "GIZMO"
    if not show_navigate and not show_rotate:
        return []

    icon_offset = ui_scale * (GIZMO_OFFSET + (gizmo_size / 2.0 if show_rotate else 0.0))
    icon_offset_mini = (MINI_SIZE + MINI_OFFSET) * ui_scale
    if mini_axis_type == "GIZMO":
        icon_offset_from_axis = icon_offset * 2.2
    elif mini_axis_type == "MINIMAL":
        icon_offset_from_axis = (20.0 * ui_scale * 2.0) + (mini_axis_size * ui_scale * 1.6)
    else:
        icon_offset_from_axis = icon_offset_mini * 0.75

    spots = []
    if show_rotate:
        spots.append({
            "id": "rotate",
            "operator": "view3d.rotate",
            "cx": width - icon_offset,
            "cy": height - icon_offset,
            "radius": (gizmo_size / 2.0) * ui_scale,
        })

    if show_navigate:
        center_x = round_half_away(width - icon_offset_mini * 0.75)
        cursor_y = round_half_away(height - icon_offset_from_axis)
        slot = 0
        mini_radius = (MINI_SIZE / 2.0) * ui_scale
        is_camera = view_perspective == "CAMERA"

        def add(spot_id, operator):
            nonlocal slot
            spots.append({
                "id": spot_id,
                "operator": operator,
                "cx": float(center_x),
                "cy": float(round_half_away(cursor_y - icon_offset_mini * slot)),
                "radius": mini_radius,
            })
            slot += 1

        add("zoom", "view3d.zoom")
        add("move", "view3d.move")
        if not lock_rotation:
            add("camera", "view3d.view_camera")
            if not is_camera:
                add("persp", "view3d.view_persportho")
    return spots


def hotspot_at(hotspots, x, y, pad=0.0):
    for spot in reversed(hotspots):
        reach = spot["radius"] + pad
        if abs(x - spot["cx"]) <= reach and abs(y - spot["cy"]) <= reach:
            return spot
    return None


def chip_anchor_beside(spot, gap):
    """Right edge and vertical center, sitting just left of the hovered button.

    Blender's own tooltip drops below-left of the icon and covers anything
    drawn under the column.
    """
    return {
        "right": spot["cx"] - spot["radius"] - gap,
        "center_y": spot["cy"],
    }


def place_chip(anchor_right, anchor_top, chip_w, chip_h, region_w, region_h, margin):
    x = anchor_right - chip_w
    y = anchor_top - chip_h
    max_x = max(margin, region_w - margin - chip_w)
    max_y = max(margin, region_h - margin - chip_h)
    x = min(max(x, margin), max_x)
    y = min(max(y, margin), max_y)
    return x, y
