import bpy
from bpy.props import EnumProperty, PointerProperty, StringProperty
from bpy.types import PropertyGroup

SCHEMA = 1
PARTS = (
    ("hand_r", "右手", "角色自己的右手"),
    ("hand_l", "左手", "角色自己的左手"),
    ("back", "背部", "由实际胸部或脊柱骨骼承载"),
    ("waist", "腰部", "由实际骨盆骨骼承载"),
    ("head", "头部", "由实际头部骨骼承载"),
)


def armature_object(self, obj):
    return obj.type == "ARMATURE"


def mount_object(self, obj):
    return self.armature is not None and self.armature.type == "ARMATURE" and obj.type == "EMPTY" and obj.get("hm_kind") == "MOUNT" and obj.parent == self.armature and obj.get("hm_part") == self.part


def grip_object(self, obj):
    if obj.type != "EMPTY" or obj.get("hm_kind") != "GRIP":
        return False
    return obj.parent is None or obj.parent.get("hm_kind") == "MOUNT" and obj.parent.parent == self.armature


class HumanoidMountSettings(PropertyGroup):
    armature: PointerProperty(name="人形角色", type=bpy.types.Object, poll=armature_object)
    mount: PointerProperty(name="当前挂点", type=bpy.types.Object, poll=mount_object)
    grip: PointerProperty(name="武器握持根", type=bpy.types.Object, poll=grip_object)
    part: EnumProperty(name="部位", items=PARTS)
    bone_name: StringProperty(name="实际骨骼")
    mount_name: StringProperty(name="挂点名称")
    edit_target: EnumProperty(name="编辑对象", items=(("MOUNT", "挂点偏移", ""), ("GRIP", "道具偏移", "")))
    status: StringProperty(name="状态")
