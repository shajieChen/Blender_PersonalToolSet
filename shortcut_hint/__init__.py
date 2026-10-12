bl_info = {
    "name": "Shortcut Hint",
    "author": "Blender Plugin",
    "version": (1, 0, 1),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > 快捷键",
    "description": "鼠标停在视图导航按钮上时，在按钮左侧用彩色按键显示快捷键",
    "category": "3D View",
}

import time

import bpy
from bpy.props import BoolProperty

from .chords import binding_for
from .hotspots import chip_anchor_beside, hotspot_at, navigation_hotspots, place_chip, ui_scale_factor

_handle = None
_trackers = set()
_state = {"cancel": False, "hint": None, "region": None, "key": None}
_cache = {"stamp": 0.0, "items": {}}
_draw_failed = False

KIND_COLOR = {
    "mod": (0.91, 0.63, 0.12, 1.0),
    "mouse": (0.22, 0.48, 1.0, 1.0),
    "key": (0.94, 0.94, 0.94, 1.0),
}
TEXT_ON = {
    "mod": (0.12, 0.08, 0.02, 1.0),
    "mouse": (1.0, 1.0, 1.0, 1.0),
    "key": (0.1, 0.1, 0.1, 1.0),
}
PLATE = (0.07, 0.07, 0.08, 0.88)
LABEL_COLOR = (0.96, 0.96, 0.96, 1.0)


def _language(context):
    lang = bpy.app.translations.locale or ""
    view_lang = getattr(context.preferences.view, "language", "") or ""
    if view_lang and (not lang or lang == "en_US") and view_lang not in {"en_US", "DEFAULT"}:
        return view_lang
    return lang or view_lang or "en_US"


def _translate(text):
    if not text:
        return ""
    if any(ord(char) > 127 for char in text):
        return text
    return bpy.app.translations.pgettext_iface(text)


def _operator_label(idname):
    group, _, name = idname.partition(".")
    cls = getattr(bpy.types, group.upper() + "_OT_" + name, None)
    if cls is None:
        return idname
    return _translate(cls.bl_description or cls.bl_label or idname)


def _event_dict(kmi):
    return {
        "type": kmi.type,
        "shift": bool(kmi.shift),
        "ctrl": bool(kmi.ctrl),
        "alt": bool(kmi.alt),
        "oskey": bool(getattr(kmi, "oskey", False)),
        "active": bool(kmi.active),
    }


def _live_items(context, idname):
    now = time.monotonic()
    if now - _cache["stamp"] > 2.0:
        _cache["items"].clear()
        _cache["stamp"] = now
    cached = _cache["items"].get(idname)
    if cached is not None:
        return cached
    found = []
    keyconfig = context.window_manager.keyconfigs.user
    for keymap in keyconfig.keymaps:
        for item in keymap.keymap_items:
            if item.idname == idname:
                found.append(_event_dict(item))
    _cache["items"][idname] = found
    return found


def _overlay_enabled():
    addon = bpy.context.preferences.addons.get(__package__)
    if addon is None:
        return True
    return bool(addon.preferences.show_overlay)


def _view_hotspots(context, region):
    prefs = context.preferences
    space = None
    for area in context.screen.areas:
        if area.type != "VIEW_3D":
            continue
        for candidate in area.regions:
            if candidate.as_pointer() == region.as_pointer():
                space = area.spaces.active
                break
    if space is None or getattr(space, "type", None) != "VIEW_3D":
        return []
    view = region.data
    perspective = "PERSP"
    lock_rotation = False
    if view is not None:
        perspective = getattr(view, "view_perspective", "PERSP") or "PERSP"
        lock_rotation = bool(getattr(view, "lock_rotation", False))
    show_gizmo = bool(getattr(space, "show_gizmo", True) and getattr(space, "show_gizmo_navigate", True))
    return navigation_hotspots(
        region.width,
        region.height,
        ui_scale=ui_scale_factor(prefs.system.dpi, prefs.system.pixel_size, prefs.system.ui_scale),
        gizmo_size=prefs.view.gizmo_size_navigate_v3d,
        mini_axis_type=prefs.view.mini_axis_type,
        mini_axis_size=prefs.view.mini_axis_size,
        show_navigate=bool(prefs.view.show_navigate_ui),
        show_gizmo=show_gizmo,
        view_perspective=perspective,
        lock_rotation=lock_rotation,
    )


def _find_region(window, x, y):
    for area in window.screen.areas:
        if area.type != "VIEW_3D":
            continue
        if not (area.x <= x < area.x + area.width and area.y <= y < area.y + area.height):
            continue
        for region in area.regions:
            if region.type != "WINDOW":
                continue
            if region.x <= x < region.x + region.width and region.y <= y < region.y + region.height:
                return region
    return None


def _set_hint(region, hint, key):
    if _state["key"] == key:
        return
    previous = _state["region"]
    _state["hint"] = hint
    _state["region"] = region
    _state["key"] = key
    if previous is not None:
        previous.tag_redraw()
    if region is not None and region != previous:
        region.tag_redraw()


def _update_hover(context, event):
    if not _overlay_enabled():
        _set_hint(None, None, None)
        return
    window = context.window
    if window is None:
        return
    region = _find_region(window, event.mouse_x, event.mouse_y)
    if region is None:
        _set_hint(None, None, None)
        return
    local_x = event.mouse_x - region.x
    local_y = event.mouse_y - region.y
    spots = _view_hotspots(context, region)
    scale = ui_scale_factor(
        context.preferences.system.dpi,
        context.preferences.system.pixel_size,
        context.preferences.system.ui_scale,
    )
    spot = hotspot_at(spots, local_x, local_y, pad=6.0 * scale)
    if spot is None:
        _set_hint(None, None, None)
        return
    language = _language(context)
    chips = binding_for(spot["operator"], _live_items(context, spot["operator"]), language)
    if not chips:
        _set_hint(None, None, None)
        return
    anchor = chip_anchor_beside(spot, gap=10.0 * scale)
    hint = {
        "region": region.as_pointer(),
        "label": _operator_label(spot["operator"]),
        "chips": chips,
        "anchor": anchor,
        "ui_scale": scale,
    }
    _set_hint(region, hint, (region.as_pointer(), spot["id"], tuple(chip["text"] for chip in chips)))


def _rect(shader, x, y, w, h, color):
    from gpu_extras.batch import batch_for_shader

    shader.bind()
    shader.uniform_float("color", color)
    verts = (
        (x, y), (x + w, y), (x + w, y + h),
        (x, y), (x + w, y + h), (x, y + h),
    )
    batch_for_shader(shader, "TRIS", {"pos": verts}).draw(shader)


def _draw():
    global _draw_failed
    hint = _state["hint"]
    if hint is None:
        return
    region = bpy.context.region
    if region is None or region.as_pointer() != hint["region"]:
        return
    if _draw_failed:
        return
    try:
        import blf
        import gpu

        scale = hint["ui_scale"]
        font = 0
        blf.size(font, max(11, int(round(11 * scale))))
        blf.color(font, *LABEL_COLOR)
        pad = 6.0 * scale
        gap = 5.0 * scale
        label = hint["label"]
        label_w, label_h = blf.dimensions(font, label)
        chip_h = max(label_h + 4.0 * scale, 16.0 * scale)
        pieces = []
        width = pad + label_w + gap
        for index, chip in enumerate(hint["chips"]):
            if index:
                plus_w, _plus_h = blf.dimensions(font, "+")
                width += gap + plus_w + gap
                pieces.append(("plus", plus_w))
            text_w, _text_h = blf.dimensions(font, chip["text"])
            chip_w = text_w + 8.0 * scale
            pieces.append(("chip", chip_w, chip))
            width += chip_w
        width += pad
        height = chip_h + pad * 2
        anchor = hint["anchor"]
        x, y = place_chip(
            anchor["right"],
            anchor["center_y"] + height * 0.5,
            width,
            height,
            region.width,
            region.height,
            8.0 * scale,
        )
        gpu.state.blend_set("ALPHA")
        shader = gpu.shader.from_builtin("UNIFORM_COLOR")
        shader.bind()
        _rect(shader, x, y, width, height, PLATE)
        cursor = x + pad
        text_y = y + (height - label_h) * 0.5
        blf.position(font, cursor, text_y, 0)
        blf.draw(font, label)
        cursor += label_w + gap
        for piece in pieces:
            if piece[0] == "plus":
                cursor += gap
                blf.color(font, 0.8, 0.8, 0.8, 1.0)
                blf.position(font, cursor, text_y, 0)
                blf.draw(font, "+")
                cursor += piece[1] + gap
                continue
            chip_w, chip = piece[1], piece[2]
            color = KIND_COLOR[chip["kind"]]
            _rect(shader, cursor, y + pad * 0.7, chip_w, chip_h, color)
            blf.color(font, *TEXT_ON[chip["kind"]])
            text_w, _text_h = blf.dimensions(font, chip["text"])
            blf.position(font, cursor + (chip_w - text_w) * 0.5, text_y, 0)
            blf.draw(font, chip["text"])
            cursor += chip_w
    except Exception:
        _draw_failed = True


class ShortcutHintPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    show_overlay: BoolProperty(
        name="显示悬停快捷键",
        description="鼠标停在视图右上角的导航按钮上时，在按钮左侧显示彩色快捷键",
        default=True,
    )

    def draw(self, context):
        self.layout.prop(self, "show_overlay")


class SHORTCUT_PT_hint(bpy.types.Panel):
    bl_label = "快捷键标注"
    bl_idname = "SHORTCUT_PT_hint"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "快捷键"

    def draw(self, context):
        layout = self.layout
        prefs = context.preferences.addons[__package__].preferences
        layout.prop(prefs, "show_overlay")
        col = layout.column(align=True)
        col.label(text="停在右上角导航按钮上")
        col.label(text="彩色快捷键显示在按钮左侧")


class SHORTCUT_OT_track(bpy.types.Operator):
    bl_idname = "shortcut_hint.track"
    bl_label = "Shortcut Hint Tracker"
    bl_options = {"INTERNAL"}

    def invoke(self, context, event):
        window = context.window
        if window is None or _state["cancel"]:
            return {"CANCELLED"}
        key = window.as_pointer()
        if key in _trackers:
            return {"CANCELLED"}
        _trackers.add(key)
        self._window = key
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if _state["cancel"] or self._window not in _trackers:
            _trackers.discard(self._window)
            return {"CANCELLED"}
        if event.type in {"MOUSEMOVE", "INBETWEEN_MOUSEMOVE"}:
            try:
                _update_hover(context, event)
            except Exception:
                _set_hint(None, None, None)
        return {"PASS_THROUGH"}


def _ensure_trackers():
    if _state["cancel"] or bpy.app.background:
        return None
    wm = bpy.context.window_manager
    if wm is None:
        return 0.8
    for window in wm.windows:
        if window.as_pointer() in _trackers:
            continue
        try:
            with bpy.context.temp_override(window=window, screen=window.screen):
                bpy.ops.shortcut_hint.track("INVOKE_DEFAULT")
        except Exception:
            continue
    return 0.8


@bpy.app.handlers.persistent
def _on_load(_dummy):
    _trackers.clear()
    _cache["items"].clear()
    _cache["stamp"] = 0.0
    _state["hint"] = None
    _state["region"] = None
    _state["key"] = None


_classes = (ShortcutHintPreferences, SHORTCUT_PT_hint, SHORTCUT_OT_track)


def register():
    _state["cancel"] = False
    for cls in _classes:
        bpy.utils.register_class(cls)
    global _handle
    _handle = bpy.types.SpaceView3D.draw_handler_add(_draw, (), "WINDOW", "POST_PIXEL")
    if _on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load)
    if not bpy.app.background and not bpy.app.timers.is_registered(_ensure_trackers):
        bpy.app.timers.register(_ensure_trackers, first_interval=0.4, persistent=True)


def unregister():
    _state["cancel"] = True
    _trackers.clear()
    _state["hint"] = None
    _state["region"] = None
    _state["key"] = None
    global _handle
    if _handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_handle, "WINDOW")
        _handle = None
    if bpy.app.timers.is_registered(_ensure_trackers):
        bpy.app.timers.unregister(_ensure_trackers)
    if _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
