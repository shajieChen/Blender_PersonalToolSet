"""Map a humanoid armature onto a fixed set of body roles.

Name aliases cover Mixamo, Unreal, Rigify and common Bip001 rigs.
When names are unknown (game extracts), rest-pose directions are used instead.
"""

from __future__ import annotations

import re

import bpy

CORE_ROLES = ("hips", "upperarm_l", "upperarm_r", "thigh_l", "thigh_r")

LIMB_ROLES = (
    "shoulder_l",
    "upperarm_l",
    "forearm_l",
    "hand_l",
    "shoulder_r",
    "upperarm_r",
    "forearm_r",
    "hand_r",
    "thigh_l",
    "shin_l",
    "foot_l",
    "toe_l",
    "thigh_r",
    "shin_r",
    "foot_r",
    "toe_r",
)

SPINE_ROLES = ("spine", "chest", "neck", "head")

ALL_ROLES = ("hips",) + SPINE_ROLES + LIMB_ROLES

# Exact matches after normalize().
_NAME_TOKENS = {
    "hips": ("hips", "pelvis"),
    "spine": ("spine", "spine01", "spine1"),
    "chest": ("spine2", "spine02", "spine3", "spine03", "chest", "upperchest"),
    "neck": ("neck",),
    "head": ("head",),
    "shoulder_l": ("leftshoulder", "lclavicle", "claviclel", "lshoulder", "shoulderl"),
    "shoulder_r": ("rightshoulder", "rclavicle", "clavicler", "rshoulder", "shoulderr"),
    "upperarm_l": ("leftarm", "leftupperarm", "lupperarm", "upperarml", "upperarmleft"),
    "upperarm_r": ("rightarm", "rightupperarm", "rupperarm", "upperarmr", "upperarmright"),
    "forearm_l": ("leftforearm", "lforearm", "forearml", "leftlowerarm", "lowerarml"),
    "forearm_r": ("rightforearm", "rforearm", "forearmr", "rightlowerarm", "lowerarmr"),
    "hand_l": ("lefthand", "lhand", "handl"),
    "hand_r": ("righthand", "rhand", "handr"),
    "thigh_l": ("leftupleg", "lupleg", "uplegl", "leftthigh", "lthigh", "thighl"),
    "thigh_r": ("rightupleg", "rupleg", "uplegr", "rightthigh", "rthigh", "thighr"),
    "shin_l": ("leftleg", "lcalf", "calfl", "leftcalf", "shinl", "lowerlegl", "lleg"),
    "shin_r": ("rightleg", "rcalf", "calfr", "rightcalf", "shinr", "lowerlegr", "rleg"),
    "foot_l": ("leftfoot", "lfoot", "footl"),
    "foot_r": ("rightfoot", "rfoot", "footr"),
    "toe_l": ("lefttoebase", "ltoe", "toel", "lefttoe", "toebasel"),
    "toe_r": ("righttoebase", "rtoe", "toer", "righttoe", "toebaser"),
}

_SKIP_NAME = re.compile(
    r"(twist|helper|dummy|corrective|eye|finger|thumb|index|middle|ring|pinky|"
    r"tongue|hair|skirt|cloth|weapon|attach|proc_|ik_|ctrl|control)",
    re.IGNORECASE,
)


def normalize_bone_name(name: str) -> str:
    text = name.lower().replace("mixamorig:", "")
    text = re.sub(r"[^a-z0-9]+", "", text)
    text = re.sub(r"^(bip001|bip01|bip|valvebipedbip01|def)", "", text)
    return text



def chest_parent_of_neck(arm_obj, spine_name, neck_name):
    """Bone directly under the neck when that bone still leads down to the spine."""
    if not arm_obj or not spine_name or not neck_name:
        return None
    neck = arm_obj.data.bones.get(neck_name)
    if neck is None or neck.parent is None or neck.parent.name == spine_name:
        return None
    bone = neck.parent
    seen = set()
    while bone is not None and bone.name != spine_name and bone.name not in seen:
        seen.add(bone.name)
        bone = bone.parent
    if bone is None:
        return None
    return neck.parent.name


def correct_chest_pairs(src, tgt, pairs):
    """Keep chest on the spine instead of a side bone such as Bone02."""
    if not pairs:
        return pairs
    roles = {role: (source_name, target_name) for role, source_name, target_name in pairs}
    if "spine" not in roles or "neck" not in roles:
        return list(pairs)
    source_chest = chest_parent_of_neck(src, roles["spine"][0], roles["neck"][0])
    target_chest = chest_parent_of_neck(tgt, roles["spine"][1], roles["neck"][1])
    corrected = []
    for role, source_name, target_name in pairs:
        if role == "chest":
            if source_chest and source_chest in src.data.bones:
                source_name = source_chest
            if target_chest and target_chest in tgt.data.bones:
                target_name = target_chest
        corrected.append((role, source_name, target_name))
    return corrected


def classify_armature(arm_obj: bpy.types.Object) -> dict[str, str]:
    """Return role -> bone name. Missing roles are omitted."""
    if arm_obj is None or arm_obj.type != "ARMATURE":
        return {}
    by_name = classify_by_name(arm_obj)
    by_geo = classify_by_geometry(arm_obj)
    name_score = sum(1 for role in CORE_ROLES if role in by_name)
    geo_score = sum(1 for role in CORE_ROLES if role in by_geo)
    if name_score >= geo_score and name_score >= 4:
        primary, secondary = by_name, by_geo
    else:
        primary, secondary = by_geo, by_name
    merged = dict(primary)
    for role, bone_name in secondary.items():
        merged.setdefault(role, bone_name)
    used = set()
    unique = {}
    for role in ALL_ROLES:
        bone_name = merged.get(role)
        if bone_name and bone_name not in used and bone_name in arm_obj.data.bones:
            unique[role] = bone_name
            used.add(bone_name)
    chest_name = chest_parent_of_neck(arm_obj, unique.get("spine"), unique.get("neck"))
    if chest_name:
        owner = next((role for role, name in unique.items() if name == chest_name), None)
        if owner is None or owner == "chest":
            unique["chest"] = chest_name
    return unique


def skinned_bone_names(arm_obj):
    """Bones that actually move a mesh bound to this armature."""
    names = set()
    if arm_obj is None:
        return names
    meshes = []
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        bound = obj.parent == arm_obj
        for modifier in obj.modifiers:
            if modifier.type == "ARMATURE" and modifier.object == arm_obj:
                bound = True
        if bound:
            meshes.append(obj)
    bone_names = set(arm_obj.data.bones.keys())
    for mesh in meshes:
        weighted = set()
        for vertex in mesh.data.vertices:
            for slot in vertex.groups:
                if slot.weight > 0.001:
                    weighted.add(slot.group)
        for group in mesh.vertex_groups:
            if group.index in weighted and group.name in bone_names:
                names.add(group.name)
    return names


def correct_deform_pairs(src, tgt, pairs):
    """Use the weighted bone when a preset names an unweighted duplicate."""
    skinned = skinned_bone_names(tgt)
    if not skinned:
        return list(pairs)
    by_key = {}
    for name in skinned:
        by_key.setdefault(normalize_bone_name(name), name)
    corrected = []
    for role, source_name, target_name in pairs:
        if target_name not in skinned:
            alias = by_key.get(normalize_bone_name(target_name))
            if alias and alias in tgt.data.bones:
                target_name = alias
        corrected.append((role, source_name, target_name))
    return corrected


def classify_by_name(arm_obj: bpy.types.Object) -> dict[str, str]:
    found = {}
    used = set()
    bones = list(arm_obj.data.bones)
    skinned = skinned_bone_names(arm_obj)
    for role, tokens in _NAME_TOKENS.items():
        token_set = set(tokens)
        matches = [bone for bone in bones if bone.name not in used and normalize_bone_name(bone.name) in token_set]
        if not matches:
            continue
        weighted = [bone for bone in matches if bone.name in skinned]
        bone = weighted[0] if weighted else matches[0]
        found[role] = bone.name
        used.add(bone.name)
    return found


def _bone_world(arm_obj: bpy.types.Object, bone: bpy.types.Bone):
    matrix = arm_obj.matrix_world
    head = matrix @ bone.head_local
    tail = matrix @ bone.tail_local
    return head, tail, tail - head


def _usable_bones(arm_obj: bpy.types.Object, height: float):
    usable = []
    min_len = max(height * 0.02, 1e-4)
    deform_exists = any(bone.use_deform for bone in arm_obj.data.bones)
    for bone in arm_obj.data.bones:
        if deform_exists and not bone.use_deform:
            continue
        if _SKIP_NAME.search(bone.name):
            continue
        _head, _tail, vec = _bone_world(arm_obj, bone)
        if vec.length < min_len:
            continue
        usable.append(bone)
    if usable:
        return usable
    return [bone for bone in arm_obj.data.bones if _bone_world(arm_obj, bone)[2].length > 1e-5]


def classify_by_geometry(arm_obj: bpy.types.Object) -> dict[str, str]:
    points = []
    for bone in arm_obj.data.bones:
        head, tail, _vec = _bone_world(arm_obj, bone)
        points.append(head)
        points.append(tail)
    if len(points) < 2:
        return {}
    min_z = min(point.z for point in points)
    max_z = max(point.z for point in points)
    height = max(max_z - min_z, 1e-6)
    heads_x = sorted(_bone_world(arm_obj, bone)[0].x for bone in arm_obj.data.bones)
    center_x = heads_x[len(heads_x) // 2]
    usable = _usable_bones(arm_obj, height)
    usable_names = {bone.name for bone in usable}

    def vec_of(bone):
        return _bone_world(arm_obj, bone)

    down = []
    for bone in usable:
        head, _tail, vec = vec_of(bone)
        if vec.z < -0.45 * vec.length and head.z < min_z + height * 0.75:
            down.append(bone)

    def pick_side(sign: float):
        side = [bone for bone in down if (vec_of(bone)[0].x - center_x) * sign > height * 0.01]
        if not side:
            return None
        return max(side, key=lambda bone: (vec_of(bone)[0].z, vec_of(bone)[2].length))

    thigh_l = pick_side(1.0)
    thigh_r = pick_side(-1.0)
    if thigh_l is None or thigh_r is None:
        return {}

    hips = _common_ancestor(thigh_l, thigh_r)
    if hips is None:
        hips = thigh_l.parent or thigh_r.parent
    if hips is None:
        return {}

    roles = {"hips": hips.name, "thigh_l": thigh_l.name, "thigh_r": thigh_r.name}
    _fill_leg(arm_obj, roles, "l", thigh_l, usable_names)
    _fill_leg(arm_obj, roles, "r", thigh_r, usable_names)

    spine_child = _best_upward_child(arm_obj, hips, usable_names, center_x, height)
    if spine_child is not None:
        chain = _upward_chain(arm_obj, spine_child, usable_names, center_x, height)
        _assign_spine(roles, chain)

    _fill_arm(arm_obj, roles, "l", 1.0, usable, center_x, min_z, height)
    _fill_arm(arm_obj, roles, "r", -1.0, usable, center_x, min_z, height)
    return roles


def _common_ancestor(bone_a: bpy.types.Bone, bone_b: bpy.types.Bone):
    seen = set()
    bone = bone_a
    while bone is not None:
        seen.add(bone.name)
        bone = bone.parent
    bone = bone_b
    while bone is not None:
        if bone.name in seen:
            return bone
        bone = bone.parent
    return None


def _best_upward_child(arm_obj, parent, usable_names, center_x, height):
    best = None
    best_rise = 0.0
    for child in parent.children:
        if child.name not in usable_names:
            continue
        head, _tail, vec = _bone_world(arm_obj, child)
        if vec.length < 1e-6 or vec.z < 0.45 * vec.length:
            continue
        if abs(head.x - center_x) > height * 0.35:
            continue
        if vec.z > best_rise:
            best_rise = vec.z
            best = child
    return best


def _upward_chain(arm_obj, start, usable_names, center_x, height):
    chain = []
    bone = start
    seen = set()
    while bone is not None and bone.name not in seen:
        seen.add(bone.name)
        chain.append(bone.name)
        bone = _best_upward_child(arm_obj, bone, usable_names, center_x, height)
        if len(chain) >= 8:
            break
    return chain


def _assign_spine(roles: dict, chain: list[str]):
    if not chain:
        return
    roles["spine"] = chain[0]
    if len(chain) == 1:
        return
    roles["head"] = chain[-1]
    if len(chain) == 2:
        return
    roles["neck"] = chain[-2]
    middle = chain[1:-2]
    if middle:
        roles["chest"] = middle[-1]
    elif len(chain) >= 3:
        roles["chest"] = chain[1]


def _fill_leg(arm_obj, roles, side: str, thigh, usable_names):
    shin = _longest_down_child(arm_obj, thigh, usable_names)
    if shin is None:
        return
    roles[f"shin_{side}"] = shin.name
    foot = _best_child(arm_obj, shin, usable_names, exclude_down=True)
    if foot is None:
        foot = _best_child(arm_obj, shin, usable_names, exclude_down=False)
    if foot is None:
        return
    roles[f"foot_{side}"] = foot.name
    toe = _best_child(arm_obj, foot, usable_names, exclude_down=False)
    if toe is not None:
        roles[f"toe_{side}"] = toe.name


def _longest_down_child(arm_obj, parent, usable_names):
    best = None
    best_len = 0.0
    for child in parent.children:
        if child.name not in usable_names:
            continue
        _head, _tail, vec = _bone_world(arm_obj, child)
        if vec.z > -0.25 * max(vec.length, 1e-6):
            continue
        if vec.length > best_len:
            best_len = vec.length
            best = child
    return best


def _best_child(arm_obj, parent, usable_names, exclude_down=False):
    kids = []
    for child in parent.children:
        if child.name not in usable_names:
            continue
        _head, _tail, vec = _bone_world(arm_obj, child)
        if exclude_down and vec.z < -0.45 * max(vec.length, 1e-6):
            continue
        kids.append(child)
    if not kids:
        return None
    return max(kids, key=lambda child: _bone_world(arm_obj, child)[2].length)


def _fill_arm(arm_obj, roles, side, sign, usable, center_x, min_z, height):
    laterals = []
    for bone in usable:
        head, _tail, vec = _bone_world(arm_obj, bone)
        if head.z < min_z + height * 0.55:
            continue
        if (head.x - center_x) * sign <= height * 0.02:
            continue
        if abs(vec.x) < max(abs(vec.z), abs(vec.y)):
            continue
        if abs(vec.x) < 0.35 * vec.length:
            continue
        laterals.append(bone)
    if not laterals:
        return
    laterals.sort(key=lambda bone: abs(_bone_world(arm_obj, bone)[0].x - center_x))
    first = laterals[0]
    chain = _outward_chain(arm_obj, first, {bone.name for bone in usable}, sign)
    if len(chain) >= 2:
        first_len = _bone_world(arm_obj, arm_obj.data.bones[chain[0]])[2].length
        second_len = _bone_world(arm_obj, arm_obj.data.bones[chain[1]])[2].length
        if first_len < second_len * 0.65:
            roles[f"shoulder_{side}"] = chain[0]
            chain = chain[1:]
    keys = (f"upperarm_{side}", f"forearm_{side}", f"hand_{side}")
    for key, bone_name in zip(keys, chain):
        roles[key] = bone_name


def _outward_chain(arm_obj, start, usable_names, sign: float):
    chain = [start.name]
    bone = start
    for _ in range(4):
        best = None
        best_score = 0.0
        for child in bone.children:
            if child.name not in usable_names or child.name in chain:
                continue
            _head, _tail, vec = _bone_world(arm_obj, child)
            score = vec.x * sign
            if score > best_score:
                best_score = score
                best = child
        if best is None:
            break
        chain.append(best.name)
        bone = best
    return chain


def rig_height(arm_obj: bpy.types.Object, roles: dict[str, str]) -> float:
    matrix = arm_obj.matrix_world
    if "hips" in roles and "head" in roles:
        hips = arm_obj.data.bones[roles["hips"]].head_local
        head = arm_obj.data.bones[roles["head"]].tail_local
        return max((matrix @ head).z - (matrix @ hips).z, 1e-4)
    zs = []
    for bone in arm_obj.data.bones:
        zs.append((matrix @ bone.head_local).z)
        zs.append((matrix @ bone.tail_local).z)
    if not zs:
        return max(arm_obj.dimensions.z, 1e-4)
    return max(max(zs) - min(zs), 1e-4)


def describe_roles(roles: dict[str, str]) -> str:
    missing = [role for role in CORE_ROLES if role not in roles]
    lines = [f"已识别 {len(roles)} 个身体部位"]
    if missing:
        lines.append("缺少: " + ", ".join(missing))
    else:
        lines.append("躯干和四肢主骨已对齐")
    return "\n".join(lines)
