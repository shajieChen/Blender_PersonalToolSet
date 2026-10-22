"""Viewport/world environment presets for the Settings panel.

Pure JSON helpers (no bpy import) so the save/load format can be unit
tested outside Blender. The addon applies a loaded preset to the scene
world, the view transform exposure and every 3D viewport's shading.
"""

from __future__ import annotations

import json
import os


class EnvironmentError(RuntimeError):
    """An environment preset could not be saved or loaded."""


SHADING_MODES = ("MATERIAL", "RENDERED", "TEXTURE")

DEFAULTS = {
    "enabled": True,
    "shading": "MATERIAL",
    "studio_intensity": 0.55,
    "world_strength": 0.4,
    "world_color": (0.05, 0.05, 0.05, 1.0),
    "exposure": -0.3,
}

_RANGES = {
    "studio_intensity": (0.0, 2.0),
    "world_strength": (0.0, 2.0),
    "exposure": (-3.0, 3.0),
}


def _clamp(value, bounds):
    low, high = bounds
    return min(max(float(value), low), high)


def normalized_environment(data) -> dict:
    """Preset dict with defaults filled in and values clamped to range."""
    source = dict(data or {})
    result = dict(DEFAULTS)
    result["enabled"] = bool(source.get("enabled", result["enabled"]))
    shading = str(source.get("shading", result["shading"])).upper()
    result["shading"] = shading if shading in SHADING_MODES else "MATERIAL"
    for key, bounds in _RANGES.items():
        try:
            result[key] = _clamp(source.get(key, result[key]), bounds)
        except (TypeError, ValueError):
            result[key] = DEFAULTS[key]
    color = source.get("world_color", result["world_color"])
    try:
        values = [float(component) for component in color]
        if len(values) == 3:
            values.append(1.0)
        if len(values) != 4:
            raise ValueError("world_color needs 3 or 4 components")
        result["world_color"] = tuple(min(max(v, 0.0), 1.0) for v in values)
    except (TypeError, ValueError):
        result["world_color"] = DEFAULTS["world_color"]
    return result


def save_environment(path: str, data) -> str:
    """Write a preset JSON file and return the path actually used."""
    if not path:
        raise EnvironmentError("环境预设路径为空")
    target = path if path.lower().endswith(".json") else path + ".json"
    folder = os.path.dirname(os.path.abspath(target))
    os.makedirs(folder, exist_ok=True)
    payload = {"version": 1, "environment": normalized_environment(data)}
    with open(target, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return target


def load_environment(path: str) -> dict:
    """Read a preset JSON file as a normalized environment dict."""
    if not path or not os.path.isfile(path):
        raise EnvironmentError(f"找不到环境预设: {path or '(未设置路径)'}")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError) as exc:
        raise EnvironmentError(f"环境预设无法读取: {exc}") from exc
    data = payload.get("environment", payload) if isinstance(payload, dict) else {}
    return normalized_environment(data)
