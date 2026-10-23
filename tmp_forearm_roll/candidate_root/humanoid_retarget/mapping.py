"""Editable bone-role table and reusable JSON presets."""

from __future__ import annotations

import json
import os
import re

from .classify import ALL_ROLES, classify_armature


class PresetError(RuntimeError):
    """A mapping preset could not be saved or loaded."""

_NAME_RE = re.compile(r"[^\w\-]+", re.UNICODE)


def build_pairs(src, tgt) -> list[tuple[str, str, str]]:
    src_roles = classify_armature(src)
    tgt_roles = classify_armature(tgt)
    pairs = []
    for role in ALL_ROLES:
        if role in src_roles and role in tgt_roles:
            pairs.append((role, src_roles[role], tgt_roles[role]))
    return pairs


def preset_dir() -> str:
    path = os.path.join(os.path.dirname(__file__), "presets")
    os.makedirs(path, exist_ok=True)
    return path


def safe_preset_name(name: str) -> str:
    cleaned = _NAME_RE.sub("_", (name or "").strip()).strip("._")
    if not cleaned or cleaned in {".", ".."}:
        raise PresetError("预设名无效")
    return cleaned[:64]


def save_preset(name: str, pairs: list[tuple[str, str, str]]) -> str:
    filename = safe_preset_name(name) + ".json"
    path = os.path.join(preset_dir(), filename)
    payload = {
        "name": safe_preset_name(name),
        "pairs": [{"role": role, "source": src, "target": tgt} for role, src, tgt in pairs],
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return path


def load_preset(name: str) -> list[tuple[str, str, str]]:
    path = os.path.join(preset_dir(), safe_preset_name(name) + ".json")
    if not os.path.isfile(path):
        raise PresetError(f"找不到预设 {name}")
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    pairs = []
    for item in payload.get("pairs", []):
        role = item.get("role")
        source = item.get("source")
        target = item.get("target")
        if role and source and target:
            pairs.append((role, source, target))
    if not pairs:
        raise PresetError(f"预设 {name} 是空的")
    return pairs


def merge_preset(auto_pairs, preset_pairs, src, tgt) -> list[tuple[str, str, str]]:
    """Keep a preset bone only when that bone exists on the current armature."""
    resolved = {role: (source, target) for role, source, target in auto_pairs}
    src_names = set(src.data.bones.keys())
    tgt_names = set(tgt.data.bones.keys())
    for role, source, target in preset_pairs:
        current = resolved.get(role, (None, None))
        source_name = source if source in src_names else current[0]
        target_name = target if target in tgt_names else current[1]
        if source_name and target_name:
            resolved[role] = (source_name, target_name)
    return [(role, resolved[role][0], resolved[role][1]) for role in ALL_ROLES if role in resolved]
