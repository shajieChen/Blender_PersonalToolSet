import json

from .mounts import HumanoidMountError, editable_object

PART_ROLES = {
    "hand_r": ("hand_r",),
    "hand_l": ("hand_l",),
    "back": ("chest", "spine"),
    "waist": ("hips",),
    "head": ("head",),
}


def resolve_bone(armature, part):
    editable_object(armature)
    if armature.type != "ARMATURE" or part not in PART_ROLES:
        raise HumanoidMountError("请选择人形角色和有效部位")
    stored = armature.get("hr_bone_roles")
    if not isinstance(stored, str):
        raise HumanoidMountError("角色没有最终映射，请先重新执行一次重定向；或在自定义中选骨")
    try:
        payload = json.loads(stored)
    except (ValueError, TypeError):
        raise HumanoidMountError("角色骨骼记录损坏，请重新重定向") from None
    if not isinstance(payload, dict) or type(payload.get("schema")) is not int or payload["schema"] != 1 or not isinstance(payload.get("roles"), dict):
        raise HumanoidMountError("角色骨骼记录版本无效，请重新重定向")
    roles = payload["roles"]
    for role in PART_ROLES[part]:
        if role not in roles:
            continue
        bone_name = roles[role]
        if not isinstance(bone_name, str) or bone_name not in armature.pose.bones:
            raise HumanoidMountError("该部位骨骼已失效，请重新重定向或使用自定义骨骼")
        if sum(name == bone_name for name in roles.values()) != 1:
            raise HumanoidMountError("角色映射存在重复骨骼，请重新重定向")
        return bone_name
    raise HumanoidMountError("该部位未映射，请在自定义中指定骨骼")
