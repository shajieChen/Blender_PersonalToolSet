import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import PropertyGroup


class SpringBoneBoneName(PropertyGroup):
    name: StringProperty(name="骨骼", default="")


class SpringBoneChain(PropertyGroup):
    name: StringProperty(name="名称", default="链")
    bone_names: CollectionProperty(type=SpringBoneBoneName)
    stiffness: FloatProperty(name="刚度", default=1.0, min=0.0)
    drag_force: FloatProperty(name="拖曳", default=0.5, min=0.0, max=1.0)
    gravity_power: FloatProperty(name="重力", default=0.0, min=0.0)
    gravity_dir: FloatVectorProperty(name="重力方向", size=3, default=(0.0, 0.0, -1.0))
    hit_radius_m: FloatProperty(name="碰撞半径米", default=0.01, min=0.0)
    weight: FloatProperty(name="混合", default=1.0, min=0.0, max=1.0)
    cone_enabled: BoolProperty(name="锥限", default=False)
    cone_angle_deg: FloatProperty(name="锥角", default=60.0, min=0.0, max=180.0)
    inertia_space: EnumProperty(
        name="惯性",
        items=(
            ("WORLD", "世界", "保留整体平移惯性"),
            ("FOLLOW_TRANSLATION", "跟随平移", "抵消祖先平移差"),
        ),
        default="WORLD",
    )
    ancestor_name: StringProperty(name="祖先", default="")
    warmup_seconds: FloatProperty(name="预热秒", default=0.5, min=0.0, max=5.0)


class SpringBoneCollider(PropertyGroup):
    name: StringProperty(name="名称", default="代理")
    shape: EnumProperty(
        name="形状",
        items=(("SPHERE", "球", ""), ("CAPSULE", "胶囊", "")),
        default="SPHERE",
    )
    bone_name: StringProperty(name="绑定骨", default="")
    radius_m: FloatProperty(name="半径米", default=0.05, min=0.0)
    head_offset_m: FloatVectorProperty(name="起点米", size=3, default=(0.0, 0.0, 0.0))
    tail_offset_m: FloatVectorProperty(name="终点米", size=3, default=(0.0, 0.1, 0.0))
    display_object: PointerProperty(name="显示", type=bpy.types.Object)
    display_tail: PointerProperty(name="末端显示", type=bpy.types.Object)


class SpringBoneSettings(PropertyGroup):
    schema_version: IntProperty(name="版本", default=1)
    show_gizmos: BoolProperty(name="显示动态骨骼与碰撞体", default=False, description="青色显示动态链，黄色显示当前链，粉色显示碰撞范围")
    chains: CollectionProperty(type=SpringBoneChain)
    colliders: CollectionProperty(type=SpringBoneCollider)
    active_chain: IntProperty(name="当前链", default=0)
    active_collider: IntProperty(name="当前代理", default=0)
    result_action_name: StringProperty(name="结果动作", default="")
    result_start: IntProperty(name="结果起点", default=1)
    result_end: IntProperty(name="结果终点", default=1)
    result_penetration_m: FloatProperty(name="残余穿深米", default=0.0)
    source_action: PointerProperty(name="基础动作", type=bpy.types.Action)
