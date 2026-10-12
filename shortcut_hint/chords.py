"""Turn a keymap event into colored keycap descriptors. No Blender imports."""

SKIP_PREFIXES = ("NDOF", "TIMER", "PEN", "ERASER")
SKIP_TYPES = {
    "",
    "NONE",
    "MOUSEMOVE",
    "INBETWEEN_MOUSEMOVE",
    "TRACKPADPAN",
    "TRACKPADZOOM",
    "MOUSEROTATE",
    "ACTIONZONE_AREA",
    "ACTIONZONE_REGION",
    "ACTIONZONE_FULLSCREEN",
}

MOUSE_TYPES = {
    "LEFTMOUSE",
    "MIDDLEMOUSE",
    "RIGHTMOUSE",
    "WHEELUPMOUSE",
    "WHEELDOWNMOUSE",
    "WHEELINMOUSE",
    "WHEELOUTMOUSE",
}

LABELS_ZH = {
    "LEFTMOUSE": "左键",
    "MIDDLEMOUSE": "中键",
    "RIGHTMOUSE": "右键",
    "WHEELUPMOUSE": "滚轮上",
    "WHEELDOWNMOUSE": "滚轮下",
    "WHEELINMOUSE": "滚轮上",
    "WHEELOUTMOUSE": "滚轮下",
    "SPACE": "空格",
    "RET": "回车",
    "NUMPAD_ENTER": "小键盘回车",
    "ESC": "Esc",
    "TAB": "Tab",
    "BACK_SPACE": "退格",
    "DEL": "删除",
    "LEFT_ARROW": "左",
    "RIGHT_ARROW": "右",
    "UP_ARROW": "上",
    "DOWN_ARROW": "下",
}

LABELS_EN = {
    "LEFTMOUSE": "LMB",
    "MIDDLEMOUSE": "MMB",
    "RIGHTMOUSE": "RMB",
    "WHEELUPMOUSE": "Wheel Up",
    "WHEELDOWNMOUSE": "Wheel Down",
    "WHEELINMOUSE": "Wheel Up",
    "WHEELOUTMOUSE": "Wheel Down",
    "SPACE": "Space",
    "RET": "Enter",
    "NUMPAD_ENTER": "Num Enter",
    "ESC": "Esc",
    "TAB": "Tab",
    "BACK_SPACE": "Backspace",
    "DEL": "Del",
    "LEFT_ARROW": "Left",
    "RIGHT_ARROW": "Right",
    "UP_ARROW": "Up",
    "DOWN_ARROW": "Down",
}

# Used when the live keymap has not been built yet (background Blender).
FACTORY = {
    "view3d.move": {"type": "MIDDLEMOUSE", "shift": True, "ctrl": False, "alt": False, "oskey": False},
    "view3d.rotate": {"type": "MIDDLEMOUSE", "shift": False, "ctrl": False, "alt": False, "oskey": False},
    "view3d.zoom": {"type": "MIDDLEMOUSE", "shift": False, "ctrl": True, "alt": False, "oskey": False},
    "view3d.view_camera": {"type": "NUMPAD_0", "shift": False, "ctrl": False, "alt": False, "oskey": False},
    "view3d.view_persportho": {"type": "NUMPAD_5", "shift": False, "ctrl": False, "alt": False, "oskey": False},
}


def score_event(event_type):
    if not event_type or event_type in SKIP_TYPES or event_type.startswith(SKIP_PREFIXES):
        return -1
    if event_type in {"LEFTMOUSE", "MIDDLEMOUSE", "RIGHTMOUSE"}:
        return 100
    if event_type.startswith("WHEEL"):
        return 40
    return 80


def pick_event(items):
    """Prefer a mouse button chord over a wheel, trackpad, or timer."""
    best = None
    best_score = -1
    for item in items:
        if not item.get("active", True):
            continue
        score = score_event(item.get("type"))
        if score > best_score:
            best = item
            best_score = score
    return best


def _is_zh(language):
    return str(language or "").lower().startswith("zh")


def _event_chip(event_type, language):
    zh = _is_zh(language)
    table = LABELS_ZH if zh else LABELS_EN
    if event_type.startswith("NUMPAD_"):
        rest = event_type[len("NUMPAD_"):]
        text = ("小键盘" if zh else "Num") + rest
        return {"text": text, "kind": "key"}
    if event_type in table:
        kind = "mouse" if event_type in MOUSE_TYPES else "key"
        return {"text": table[event_type], "kind": kind}
    text = event_type.replace("_", " ").title()
    return {"text": text, "kind": "key"}


def format_chord(item, language):
    if item is None:
        return []
    chips = []
    for flag, label in (("ctrl", "Ctrl"), ("shift", "Shift"), ("alt", "Alt"), ("oskey", "Win")):
        if item.get(flag):
            chips.append({"text": label, "kind": "mod"})
    chips.append(_event_chip(item.get("type") or "", language))
    return chips


def binding_for(idname, live_items, language):
    chosen = pick_event(live_items)
    if chosen is None:
        chosen = FACTORY.get(idname)
    return format_chord(chosen, language)
