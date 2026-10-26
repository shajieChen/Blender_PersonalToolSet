import copy
import hashlib
import json
import math
import re
from functools import lru_cache
from pathlib import Path
from statistics import median
from zlib import crc32

import bpy
from mathutils import Vector

from .animation import _rest_token
from .solver import ChainParameters, SpringBoneError, matrix_has_supported_scale, validate_parameters


PRESET_DIRECTORY = Path(__file__).with_name("preset_data")
PARAMETER_FIELDS = ("stiffness", "drag_force", "gravity_power", "gravity_dir", "hit_radius_m", "weight", "cone_enabled", "cone_angle_deg", "inertia_space", "ancestor_name", "warmup_seconds")
COLLIDER_FIELDS = ("name", "bone_name", "shape", "radius_m", "head_offset_m", "tail_offset_m")


@lru_cache(maxsize=1)
def _catalog_data():
    rows, errors = [], []
    paths = [PRESET_DIRECTORY / "builtin.json", *sorted((PRESET_DIRECTORY / "user").glob("*.json"))]
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            candidates = payload["presets"] if path.name == "builtin.json" else [payload]
            if payload.get("schema_version") != 1:
                raise ValueError("不支持的预设版本")
            for row in candidates:
                if row.get("schema_version") != 1 or row.get("kind") not in {"chain", "collider", "character"} or not re.fullmatch(r"[\w-]{1,64}", row.get("id", "")) or not isinstance(row.get("label"), str):
                    raise ValueError("预设字段无效")
                if any(existing["id"] == row["id"] for existing in rows):
                    raise ValueError("预设标识重复")
                rows.append(row)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append(path.name + ": " + str(exc))
    return rows, errors


def catalog(kind):
    return [copy.deepcopy(row) for row in _catalog_data()[0] if row["kind"] == kind]


@lru_cache(maxsize=3)
def preset_items(kind):
    codes = {"skirt_balanced": 0, "skirt_soft": 1, "hair": 2, "tail": 3, "humanoid_lower": 0, "humanoid_upper": 1, "humanoid_full": 2}
    items = tuple((row["id"], row["label"], "", codes.get(row["id"], max(1024, crc32(row["id"].encode("utf-8")) & 0x7fffffff))) for row in _catalog_data()[0] if row["kind"] == kind)
    empty = (("NONE", "选择已保存的角色配置", "", 0),)
    return empty + items if kind == "character" else items or empty


def refresh_catalog():
    _catalog_data.cache_clear()
    preset_items.cache_clear()


def load_preset(identifier):
    for row in _catalog_data()[0]:
        if row["id"] == identifier:
            return copy.deepcopy(row)
    raise SpringBoneError("找不到预设，请刷新预设列表")


def _finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise SpringBoneError("预设包含无效数值")
    return float(value)


def _vector(value):
    if not isinstance(value, (tuple, list)) or len(value) != 3:
        raise SpringBoneError("预设向量需要三个分量")
    return [_finite(component) for component in value]


def _parameters(values):
    if set(values) != set(PARAMETER_FIELDS):
        raise SpringBoneError("预设参数字段不完整")
    result = dict(values)
    result["gravity_dir"] = _vector(values["gravity_dir"])
    for name in set(PARAMETER_FIELDS) - {"gravity_dir", "cone_enabled", "inertia_space", "ancestor_name"}:
        result[name] = _finite(values[name])
    if not isinstance(values["cone_enabled"], bool) or values["inertia_space"] not in {"WORLD", "FOLLOW_TRANSLATION"} or not isinstance(values["ancestor_name"], str) or not 0. <= result["warmup_seconds"] <= 5. or not 0. <= result["cone_angle_deg"] <= 180.:
        raise SpringBoneError("预设参数超出范围")
    validate_parameters(ChainParameters(result["stiffness"], result["drag_force"], result["gravity_power"], Vector(result["gravity_dir"]), result["hit_radius_m"], result["weight"], result["cone_enabled"], math.radians(result["cone_angle_deg"])))
    return result


def _unit(armature, scene):
    unit = _finite(scene.unit_settings.scale_length)
    if unit <= 0. or not matrix_has_supported_scale(armature.matrix_world):
        raise SpringBoneError("预设需要有效单位与正统一骨架缩放")
    return unit


def _length_m(armature, names, unit):
    lengths = [((armature.matrix_world @ armature.data.bones[name].tail_local) - (armature.matrix_world @ armature.data.bones[name].head_local)).length * unit for name in names]
    if not lengths or min(lengths) <= 1e-8:
        raise SpringBoneError("预设包含零长骨")
    return median(lengths)


def _values(item, fields):
    return {name: list(getattr(item, name)) if name in {"gravity_dir", "head_offset_m", "tail_offset_m"} else getattr(item, name) for name in fields}


def _fingerprint(armature, scene):
    settings = armature.sb_settings
    payload = [armature.as_pointer(), scene.as_pointer(), _rest_token(armature), [list(row) for row in armature.matrix_world], scene.unit_settings.scale_length, [[chain.name, [b.name for b in chain.bone_names], _values(chain, PARAMETER_FIELDS)] for chain in settings.chains], [_values(collider, COLLIDER_FIELDS) for collider in settings.colliders], settings.active_chain]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def _plan(armature, scene, entries, notices):
    return {"target": armature.name, "fingerprint": _fingerprint(armature, scene), "entries": entries, "notices": notices}


def humanoid_roles(armature):
    try:
        from humanoid_retarget.classify import classify_by_name, normalize_bone_name
    except ModuleNotFoundError as exc:
        raise SpringBoneError("人形自动匹配需要安装 Humanoid Retarget；不需要启动重定向") from exc
    roles = classify_by_name(armature)
    for preset in _catalog_data()[0]:
        for row in preset.get("colliders", []) if preset["kind"] == "collider" else []:
            if row["role"] in roles:
                continue
            aliases = {normalize_bone_name(name) for name in row.get("bone_aliases", [])}
            matches = [bone.name for bone in armature.data.bones if normalize_bone_name(bone.name) in aliases]
            if len(matches) == 1 and matches[0] not in roles.values():
                roles[row["role"]] = matches[0]
    return roles


def _chain_parameters(armature, names, preset, unit):
    values = copy.deepcopy(preset["parameters"])
    ratio = _finite(preset["hit_radius_ratio"])
    if ratio < 0.:
        raise SpringBoneError("碰撞半径比例不能为负")
    values["hit_radius_m"] = _length_m(armature, names, unit) * ratio
    if values["inertia_space"] == "FOLLOW_TRANSLATION":
        parent = armature.data.bones[names[0]].parent
        values["ancestor_name"] = parent.name if parent else ""
    return _parameters(values)


def build_chain_plan(armature, preset, scene):
    unit = _unit(armature, scene)
    if preset.get("kind") != "chain":
        raise SpringBoneError("请选择骨骼链参数预设")
    tokens = preset.get("match_tokens", [])
    if not tokens or any(not isinstance(token, str) or not token for token in tokens):
        raise SpringBoneError("预设缺少识别关键词")
    if not armature.data.bones:
        raise SpringBoneError("目标骨架没有骨骼")
    _chain_parameters(armature, [armature.data.bones[0].name], preset, unit)
    try:
        from humanoid_retarget.classify import classify_by_name
        protected = set(classify_by_name(armature).values())
    except ModuleNotFoundError:
        protected = set()
    used = {b.name for chain in armature.sb_settings.chains for b in chain.bone_names}
    blocked = {c.bone_name for c in armature.sb_settings.colliders}
    bones = armature.data.bones
    controls = {bone.name for bone in bones if re.search(r"(?:^|[:_.])(ctrl|control|ik|mch|org)(?:[:_.]|$)", bone.name, re.IGNORECASE)}
    excluded = protected | controls
    matched = {bone.name for bone in bones if any(token.casefold() in bone.name.casefold() for token in tokens) and bone.name not in excluded}
    candidates = {bone.name for bone in bones if bone.name not in excluded and (bone.name in matched or any(parent.name in matched for parent in bone.parent_recursive))}
    entries, notices = [], []
    for bone in sorted(bones, key=lambda value: value.name):
        if bone.name not in candidates or (bone.parent and bone.parent.name in candidates and len(bone.parent.children) == 1):
            continue
        names, cursor = [], bone
        while cursor.name in candidates and len(cursor.children) <= 1:
            names.append(cursor.name)
            if not cursor.children:
                break
            cursor = cursor.children[0]
        if not names:
            notices.append(bone.name + "：分叉根跳过，分别识别子链")
            continue
        if set(names) & (used | blocked) or any(bones[name].length <= 1e-8 for name in names):
            notices.append(names[0] + "：已有链、碰撞绑定或无效骨，保留原配置")
            continue
        entries.append({"kind": "chain", "name": names[0], "bone_names": names, "parameters": _chain_parameters(armature, names, preset, unit)})
    return _plan(armature, scene, entries, notices)


def build_parameter_plan(armature, preset, scene):
    settings = armature.sb_settings
    if not settings.chains or not 0 <= settings.active_chain < len(settings.chains):
        raise SpringBoneError("请先选择一条已有动态链")
    chain = settings.chains[settings.active_chain]
    names = [b.name for b in chain.bone_names]
    return _plan(armature, scene, [{"kind": "parameters", "name": chain.name, "index": settings.active_chain, "bone_names": names, "parameters": _chain_parameters(armature, names, preset, _unit(armature, scene))}], [])


def _collider_row(armature, row, name, unit):
    bone = armature.data.bones.get(name)
    if bone is None or bone.length <= 1e-8 or row["shape"] not in {"SPHERE", "CAPSULE"}:
        raise SpringBoneError("碰撞体预设骨骼或形状无效")
    ratio = _finite(row["radius_ratio"])
    if ratio <= 0.:
        raise SpringBoneError("碰撞体半径必须为正")
    local_length = float(bone.length) * unit
    return {"kind": "collider", "name": row.get("name", row.get("role", name)), "bone_name": name, "shape": row["shape"], "radius_m": _length_m(armature, [name], unit) * ratio, "head_offset_m": [v * local_length for v in _vector(row["head_fraction"])], "tail_offset_m": [v * local_length for v in _vector(row["tail_fraction"])]}


def build_collider_plan(armature, preset, scene, roles=None):
    unit = _unit(armature, scene)
    if preset.get("kind") != "collider":
        raise SpringBoneError("请选择碰撞体预设")
    roles = humanoid_roles(armature) if roles is None else roles
    simulated = {b.name for chain in armature.sb_settings.chains for b in chain.bone_names}
    existing = {c.bone_name for c in armature.sb_settings.colliders}
    entries, notices = [], []
    for row in preset["colliders"]:
        name = roles.get(row["role"])
        if not name or name not in armature.data.bones:
            notices.append(row["role"] + "：未匹配，跳过")
            continue
        bone = armature.data.bones[name]
        if name in existing or any(b.name in simulated for b in (bone, *bone.parent_recursive)):
            notices.append(name + "：已有碰撞体或受模拟链驱动，跳过")
            continue
        entry = _collider_row(armature, row, name, unit)
        end_name = roles.get(row.get("end_role"))
        if row["shape"] == "CAPSULE" and end_name and end_name in armature.data.bones and bone in armature.data.bones[end_name].parent_recursive:
            end = armature.data.bones[end_name].head_local
            delta = bone.matrix_local.inverted() @ end
            if delta.length > 1e-8:
                for field, fraction_field in (("head_offset_m", "head_fraction"), ("tail_offset_m", "tail_fraction")):
                    fraction = _vector(row[fraction_field])
                    local = delta * fraction[1] + Vector((fraction[0], 0., fraction[2])) * delta.length
                    entry[field] = list(local * unit)
                entry["radius_m"] = ((armature.matrix_world @ end) - (armature.matrix_world @ bone.head_local)).length * unit * _finite(row["radius_ratio"])
        span_roles = row.get("radius_span", [])
        if len(span_roles) == 2 and all(roles.get(role) and roles[role] in armature.data.bones for role in span_roles):
            first, second = (armature.matrix_world @ armature.data.bones[roles[role]].head_local for role in span_roles)
            span = (second - first).length * unit
            if span > 1e-8:
                entry["radius_m"] = span * _finite(row["radius_ratio"])
        entries.append(entry)
        existing.add(name)
    return _plan(armature, scene, entries, notices)


def build_character_plan(armature, preset, scene):
    if preset.get("schema_version") != 1 or preset.get("kind") != "character":
        raise SpringBoneError("角色预设版本或类型无效")
    unit = _unit(armature, scene)
    entries = []
    for row in preset["chains"]:
        names = row["bone_names"]
        if any(name not in armature.data.bones for name in names):
            raise SpringBoneError("角色预设骨名不匹配，请使用对应骨架")
        values = dict(row["parameters"])
        values["hit_radius_m"] = _length_m(armature, names, unit) * _finite(row["hit_radius_ratio"])
        entries.append({"kind": "chain", "name": row["name"], "bone_names": names, "parameters": _parameters(values)})
    for row in preset["colliders"]:
        entries.append(_collider_row(armature, row, row["bone_name"], unit))
    return _plan(armature, scene, entries, [])


def _validate_entries(armature, entries, simulated, collider_names):
    from .operators import _selected_chain
    bones = armature.data.bones
    simulated, collider_names = set(simulated), set(collider_names)
    for row in entries:
        if row["kind"] in {"chain", "parameters"}:
            names = row["bone_names"]
            if not names or any(name not in bones for name in names) or [b.name for b in _selected_chain([bones[name] for name in names])] != names:
                raise SpringBoneError("预设链不连续或包含无效骨骼")
            values = _parameters(row["parameters"])
            if values["inertia_space"] == "FOLLOW_TRANSLATION" and values["ancestor_name"] not in {b.name for b in bones[names[0]].parent_recursive}:
                raise SpringBoneError("跟随平移需要有效祖先骨")
            if row["kind"] == "parameters":
                index = row["index"]
                if not 0 <= index < len(armature.sb_settings.chains) or [b.name for b in armature.sb_settings.chains[index].bone_names] != names:
                    raise SpringBoneError("当前链已变化")
            else:
                if simulated.intersection(names):
                    raise SpringBoneError("预设包含重复动态骨骼")
                simulated.update(names)
        elif row["kind"] == "collider":
            name = row["bone_name"]
            if name not in bones or name in collider_names or row["shape"] not in {"SPHERE", "CAPSULE"} or _finite(row["radius_m"]) <= 0.:
                raise SpringBoneError("碰撞骨、形状或半径无效或重复")
            _vector(row["head_offset_m"])
            _vector(row["tail_offset_m"])
            collider_names.add(name)
        else:
            raise SpringBoneError("未知预设配置类型")
    if any(any(b.name in simulated for b in (bones[name], *bones[name].parent_recursive)) for name in collider_names if name in bones):
        raise SpringBoneError("碰撞骨不能依赖动态链")


def _write_fields(item, values):
    for name, value in values.items():
        setattr(item, name, value)


def apply_plan(armature, plan):
    from .operators import active_session
    if active_session() is not None:
        raise SpringBoneError("请先停止动态骨骼预览或烘焙")
    scene = bpy.context.scene
    if armature.library or armature.data.library or armature.mode == "EDIT" or armature.name != plan["target"] or _fingerprint(armature, scene) != plan["fingerprint"]:
        raise SpringBoneError("目标或配置已变化，请重新匹配预设")
    settings = armature.sb_settings
    _validate_entries(armature, plan["entries"], {b.name for chain in settings.chains for b in chain.bone_names}, {c.bone_name for c in settings.colliders})
    chain_count, collider_count = len(settings.chains), len(settings.colliders)
    active_chain, active_collider, show = settings.active_chain, settings.active_collider, settings.show_gizmos
    updates = [(row["index"], _values(settings.chains[row["index"]], PARAMETER_FIELDS)) for row in plan["entries"] if row["kind"] == "parameters"]
    try:
        for row in plan["entries"]:
            if row["kind"] == "collider":
                _write_fields(settings.colliders.add(), {name: row[name] for name in COLLIDER_FIELDS})
                settings.active_collider = len(settings.colliders) - 1
            elif row["kind"] == "chain":
                chain = settings.chains.add()
                chain.name = row["name"]
                for name in row["bone_names"]:
                    chain.bone_names.add().name = name
                _write_fields(chain, row["parameters"])
                settings.active_chain = len(settings.chains) - 1
            else:
                _write_fields(settings.chains[row["index"]], row["parameters"])
        if plan["entries"]:
            settings.show_gizmos = True
    except Exception:
        while len(settings.chains) > chain_count:
            settings.chains.remove(len(settings.chains) - 1)
        while len(settings.colliders) > collider_count:
            settings.colliders.remove(len(settings.colliders) - 1)
        for index, values in updates:
            _write_fields(settings.chains[index], values)
        settings.active_chain, settings.active_collider, settings.show_gizmos = active_chain, active_collider, show
        raise
    return len(plan["entries"])


def save_character_preset(armature, scene, name, directory=None):
    if not re.fullmatch(r"[\w-]{1,48}", name):
        raise SpringBoneError("预设名只允许文字、数字、下划线和短横线")
    unit = _unit(armature, scene)
    chains, colliders = [], []
    for chain in armature.sb_settings.chains:
        names = [b.name for b in chain.bone_names]
        values = _parameters(_values(chain, PARAMETER_FIELDS))
        radius = values.pop("hit_radius_m")
        chains.append({"name": chain.name, "bone_names": names, "parameters": values, "hit_radius_ratio": radius / _length_m(armature, names, unit)})
    for collider in armature.sb_settings.colliders:
        bone = armature.data.bones.get(collider.bone_name)
        if bone is None or bone.length <= 1e-8:
            raise SpringBoneError("碰撞骨已失效，不能保存预设")
        colliders.append({"name": collider.name, "bone_name": bone.name, "shape": collider.shape, "radius_ratio": float(collider.radius_m) / _length_m(armature, [bone.name], unit), "head_fraction": [v / (bone.length * unit) for v in collider.head_offset_m], "tail_fraction": [v / (bone.length * unit) for v in collider.tail_offset_m]})
    if not chains and not colliders:
        raise SpringBoneError("当前角色没有可保存的动态配置")
    payload = {"schema_version": 1, "id": "user_" + name, "label": name, "kind": "character", "chains": chains, "colliders": colliders}
    plan = build_character_plan(armature, payload, scene)
    _validate_entries(armature, plan["entries"], set(), set())
    target = Path(directory) if directory is not None else PRESET_DIRECTORY / "user"
    target.mkdir(parents=True, exist_ok=True)
    path = target / (name + ".json")
    text = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(text + "\n")
    except FileExistsError as exc:
        raise SpringBoneError("同名预设已存在，请换一个名称") from exc
    refresh_catalog()
    return path
