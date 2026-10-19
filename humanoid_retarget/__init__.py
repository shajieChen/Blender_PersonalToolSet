bl_info = {
    "name": "Humanoid Retarget",
    "author": "Blender Plugin",
    "version": (1, 7, 3),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > 重定向",
    "description": "导入带动画的模型，自动绑定或映射到另一个人形，再导出",
    "category": "Animation",
}

import json

import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty, StringProperty
from bpy.types import Operator, Panel, PropertyGroup, UIList

from .mapping import PresetError, build_pairs, load_preset, merge_preset, save_preset
from .pipeline import (
    PipelineError,
    apply_stand_layout,
    export_armature,
    initial_filepath,
    load_source,
    load_target_and_retarget,
    retarget_existing,
    retarget_selected_meshes,
    set_armature_bones_visible,
    set_bone_sphere_display,
)
from .retarget import (
    RetargetError,
    RetargetOptions,
    capture_reference,
    collect_actions,
    preview_source_and_target,
)
from .foot_ik import FootIKSettings
from .joint_limits import (
    AxisAngleLimit,
    BoneAngleLimits,
    JointLimitSettings,
    LimitType,
)
from .soft_repulsion import SoftRepulsionSettings
from .gizmos import register_draw, unregister_draw



def _recall_filepath(context, attr):
    stored = ""
    addon = bpy.context.preferences.addons.get(__package__)
    if addon is not None:
        stored = getattr(addon.preferences, attr, "") or ""
    if not stored:
        stored = getattr(context.scene.hr_settings, attr, "") or ""
    return initial_filepath(stored)


def _remember_filepath(context, attr, path):
    if not path:
        return
    settings = context.scene.hr_settings
    if hasattr(settings, attr):
        setattr(settings, attr, path)
    addon = bpy.context.preferences.addons.get(__package__)
    if addon is not None and hasattr(addon.preferences, attr):
        setattr(addon.preferences, attr, path)


def _armature_poll(_settings, obj):
    return obj.type == "ARMATURE"


def _source_action_items(self, _context):
    items = []
    if self.source and self.source.type == "ARMATURE":
        for action in collect_actions(self.source):
            label = action.name if len(action.name) <= 48 else action.name[:45] + "..."
            items.append((action.name, label, action.name))
    if not items:
        items = [("NONE", "无动画", "导入后来源上的动画会列在这里")]
    _source_action_items.cache = items
    return _source_action_items.cache


def _preview_selected_action(settings, context, jump):
    source = settings.source
    if source is None or settings.source_action in {"", "NONE"}:
        return None
    action = bpy.data.actions.get(settings.source_action)
    if action is None:
        return None
    preview_source_and_target(source, settings.target, action, context.scene, jump=jump)
    source.select_set(True)
    if context.view_layer is not None:
        context.view_layer.objects.active = source
    return action


def _on_source_changed(self, context):
    actions = collect_actions(self.source) if self.source and self.source.type == "ARMATURE" else []
    names = [action.name for action in actions]
    if self.source_action not in names:
        self.source_action = names[0] if names else "NONE"
    else:
        _preview_selected_action(self, context, jump=True)
    set_bone_sphere_display(self.source, self.show_bone_spheres)
    _apply_current_stand(self)


def _current_stand(settings):
    try:
        return settings.stand_layout
    except AttributeError:
        return "SIDE"


def _apply_current_stand(settings):
    apply_stand_layout(settings.source, settings.target, _current_stand(settings))


def _on_target_changed(self, _context):
    _apply_current_stand(self)


def _on_stand_layout(self, _context):
    _apply_current_stand(self)


_Y0_FLOOR_NAME = "HR_Y0_Floor"


def _sync_y0_floor(scene, visible):
    """Show or hide a gray square on the horizontal ground. It stays hidden until requested."""
    floor = bpy.data.objects.get(_Y0_FLOOR_NAME)
    if floor is None and not visible:
        return
    if floor is None:
        floor = bpy.data.objects.new(_Y0_FLOOR_NAME, bpy.data.meshes.new(_Y0_FLOOR_NAME))
        floor.hide_render = True
        for axis in range(3):
            floor.lock_location[axis] = True
            floor.lock_rotation[axis] = True
            floor.lock_scale[axis] = True
    size = 5.0
    mesh = floor.data
    mesh.clear_geometry()
    mesh.from_pydata(
        [(-size, -size, 0.0), (size, -size, 0.0), (size, size, 0.0), (-size, size, 0.0)],
        [],
        [(0, 1, 2, 3)],
    )
    mesh.update()
    gray = (0.45, 0.45, 0.45, 1.0)
    material = bpy.data.materials.get(_Y0_FLOOR_NAME)
    if material is None:
        material = bpy.data.materials.new(_Y0_FLOOR_NAME)
    material.diffuse_color = gray
    if mesh.materials:
        mesh.materials[0] = material
    else:
        mesh.materials.append(material)
    floor.color = gray
    floor.display_type = "SOLID"
    floor.show_wire = False
    floor.show_in_front = False
    if floor.name not in scene.collection.objects:
        scene.collection.objects.link(floor)
    floor.hide_viewport = not visible
    floor.hide_set(not visible)


def _on_show_y0_floor(self, context):
    scene = bpy.context.scene if context is None else context.scene
    _sync_y0_floor(scene, self.show_y0_floor)


def _on_show_spheres(self, _context):
    set_bone_sphere_display(self.source, self.show_bone_spheres)


def _on_show_bones(self, _context):
    _apply_saved_view_now()


def _on_draw_gizmos(self, context):
    screen = getattr(context, "screen", None)
    if screen is None:
        return
    for area in screen.areas:
        if area.type == "VIEW_3D":
            area.tag_redraw()


_on_draw_labels = _on_draw_gizmos


def _on_source_action_changed(self, context):
    _preview_selected_action(self, context, jump=True)


def _pairs_from_settings(settings):
    pairs = []
    for item in settings.mappings:
        if item.role and item.source_bone and item.target_bone:
            pairs.append((item.role, item.source_bone, item.target_bone))
    return pairs or None


def _fill_mapping(settings, pairs):
    settings.mappings.clear()
    for role, source_name, target_name in pairs:
        item = settings.mappings.add()
        item.role = role
        item.source_bone = source_name
        item.target_bone = target_name
    settings.mapping_index = 0


def _options_from_settings(settings, use_mapping=True):
    data = None
    if settings.reference_json:
        try:
            data = json.loads(settings.reference_json)
        except json.JSONDecodeError:
            data = None
    return RetargetOptions(
        pairs=_pairs_from_settings(settings) if use_mapping else None,
        reference=settings.reference_pose,
        reference_data=data,
        root_motion=settings.root_motion,
        foot_ik=settings.use_foot_ik,
        hand_ik=settings.use_hand_ik,
        standard_skeleton=settings.standard_skeleton,
        foot_ik_settings=FootIKSettings(
            floor_enabled=settings.foot_floor_enabled,
            floor_alpha=settings.foot_floor_alpha,
            maintain_height_offset=settings.foot_maintain_height_offset,
            falloff_start_m=settings.foot_falloff_start_m,
            falloff_distance_m=settings.foot_falloff_distance_m,
            pelvis_floor_weight=settings.foot_pelvis_floor_weight,
            source_crotch_offset_m=settings.foot_source_crotch_offset_m,
            target_crotch_offset_m=settings.foot_target_crotch_offset_m,
            planting_enabled=settings.foot_planting_enabled,
            speed_threshold_mps=settings.foot_speed_threshold_mps,
            stiffness=settings.foot_stiffness,
            critical_damping=settings.foot_critical_damping,
            contact_window_s=settings.foot_contact_window_s,
            contact_height_tolerance_m=settings.foot_contact_height_tolerance_m,
            contact_minimum_tolerance_m=settings.foot_contact_minimum_tolerance_m,
            floor_height_m=settings.foot_floor_height_m,
        ),
        soft_repulsion=settings.use_soft_repulsion,
        soft_repulsion_settings=(
            SoftRepulsionSettings(
                enabled=True,
                minimum_distance_m=settings.soft_minimum_distance_m,
                maximum_distance_m=settings.soft_maximum_distance_m,
                coefficient=settings.soft_coefficient,
                inverted=settings.soft_inverted,
                torso_radius_m=settings.soft_torso_radius_m,
                hand_radius_m=settings.soft_hand_radius_m,
                forearm_radius_m=settings.soft_forearm_radius_m,
            )
            if settings.use_soft_repulsion else None
        ),
        joint_limits=settings.use_joint_limits,
        joint_limit_settings=(
            JointLimitSettings(
                enabled=True,
                iterations=settings.joint_iterations,
                max_angle_degrees=settings.joint_max_angle_degrees,
                bones=tuple(
                    BoneAngleLimits(
                        role=item.role,
                        x=AxisAngleLimit(
                            LimitType(item.x_type), item.min_x, item.max_x
                        ),
                        y=AxisAngleLimit(
                            LimitType(item.y_type), item.min_y, item.max_y
                        ),
                        z=AxisAngleLimit(
                            LimitType(item.z_type), item.min_z, item.max_z
                        ),
                        rotation_stiffness=item.rotation_stiffness,
                    )
                    for item in settings.joint_limit_bones
                ),
            )
            if settings.use_joint_limits else None
        ),
    )


def _remember_generated_pairs(settings, options, had_mapping):
    if not had_mapping and options.resolved_pairs:
        _fill_mapping(settings, options.resolved_pairs)
        return
    resolved = {role: (source_name, target_name) for role, source_name, target_name in options.resolved_pairs or []}
    for item in settings.mappings:
        if item.role in {"chest", "neck", "head"} and item.role in resolved:
            item.source_bone, item.target_bone = resolved[item.role]


def _set_status(context, text, level="INFO"):
    context.scene.hr_settings.status = text
    print("[HumanoidRetarget]\n" + text)
    return level


class HRMapItem(PropertyGroup):
    role: StringProperty(name="部位")
    source_bone: StringProperty(name="来源骨骼")
    target_bone: StringProperty(name="目标骨骼")


class HR_UL_mappings(UIList):
    bl_idname = "HR_UL_mappings"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.label(text=item.role)
        settings = context.scene.hr_settings
        if settings.source and settings.source.type == "ARMATURE":
            row.prop_search(item, "source_bone", settings.source.data, "bones", text="")
        else:
            row.prop(item, "source_bone", text="")
        if settings.target and settings.target.type == "ARMATURE":
            row.prop_search(item, "target_bone", settings.target.data, "bones", text="")
        else:
            row.prop(item, "target_bone", text="")


_LIMIT_ITEMS = (
    ("FREE", "Free", "不限制"),
    ("LIMITED", "Limited", "按 PBIK 范围分支处理"),
    ("LOCKED", "Locked", "按 PBIK 锁定组合处理"),
)


class HRJointLimitItem(PropertyGroup):
    role: StringProperty(name="骨骼 role", default="forearm_l")
    x_type: EnumProperty(name="X", items=_LIMIT_ITEMS, default="FREE")
    y_type: EnumProperty(name="Y", items=_LIMIT_ITEMS, default="FREE")
    z_type: EnumProperty(name="Z", items=_LIMIT_ITEMS, default="FREE")
    min_x: FloatProperty(name="X 最小（度）", default=0.0)
    max_x: FloatProperty(name="X 最大（度）", default=0.0)
    min_y: FloatProperty(name="Y 最小（度）", default=0.0)
    max_y: FloatProperty(name="Y 最大（度）", default=0.0)
    min_z: FloatProperty(name="Z 最小（度）", default=0.0)
    max_z: FloatProperty(name="Z 最大（度）", default=0.0)
    rotation_stiffness: FloatProperty(
        name="旋转刚度", default=0.0, min=0.0, max=1.0
    )


class HR_OT_add_joint_limit(Operator):
    bl_idname = "hr.add_joint_limit"
    bl_label = "添加关节限"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        context.scene.hr_settings.joint_limit_bones.add()
        return {"FINISHED"}


class HR_OT_remove_joint_limit(Operator):
    bl_idname = "hr.remove_joint_limit"
    bl_label = "删除关节限"
    bl_options = {"REGISTER", "UNDO"}
    index: IntProperty(default=-1)

    def execute(self, context):
        items = context.scene.hr_settings.joint_limit_bones
        if 0 <= self.index < len(items):
            items.remove(self.index)
        return {"FINISHED"}


class HRSettings(PropertyGroup):
    source: PointerProperty(name="动画来源", type=bpy.types.Object, poll=_armature_poll, update=_on_source_changed)
    source_action: EnumProperty(
        name="动画",
        description="选择要预览的来源动画",
        items=_source_action_items,
        update=_on_source_action_changed,
    )
    target: PointerProperty(name="目标角色", type=bpy.types.Object, poll=_armature_poll, update=_on_target_changed)
    show_y0_floor: BoolProperty(
        name="显示地板",
        description="在水平地面上放一块灰色方片，用来对照角色高度。默认关闭",
        default=False,
        update=_on_show_y0_floor,
    )
    stand_layout: EnumProperty(
        name="站位",
        description="来源和目标在场景里的站位。默认来源在原点左侧，目标在右侧",
        items=(
            ("SIDE", "原点左右", "来源站在原点左侧，目标站在右侧"),
            ("SWAP", "左右对调", "目标站在左侧，来源站在右侧"),
            ("OVERLAP", "重叠原点", "两边都站在原点，用来对照骨骼是否重合"),
            ("SOURCE_ORIGIN", "来源在原点", "动画来源留在原点，目标站到右侧"),
            ("TARGET_ORIGIN", "目标在原点", "重定向目标留在原点，来源站到左侧"),
            ("DEPTH", "原点前后", "来源站在原点前方，目标站在后方"),
        ),
        default="SIDE",
        update=_on_stand_layout,
    )
    standard_skeleton: EnumProperty(
        name="标准人形骨架",
        description="选择重定向使用的中间标准。默认仍是来源直接映射到目标",
        items=(
            ("RIGIFY_HUMAN_METARIG", "Rigify human metarig", "用 Rigify 的完整 Human metarig 作为中间骨架"),
            ("DIRECT", "当前直接映射", "不创建中间骨架，来源直接映射到目标"),
        ),
        default="DIRECT",
    )
    status: StringProperty(name="状态", default="先导入带动画的模型，再导入要接收动作的角色。")
    mappings: CollectionProperty(type=HRMapItem)
    mapping_index: IntProperty(default=0)
    preset_name: StringProperty(name="预设", default="onimusha")
    reference_pose: EnumProperty(
        name="参考姿势",
        items=(
            ("REST", "Rest", "以绑定姿势为零点"),
            ("CURRENT", "当前姿势", "以两边当前姿势为零点，用来对齐 T-Pose 和 A-Pose"),
        ),
        default="REST",
    )
    reference_json: StringProperty(name="参考姿势数据", default="")
    root_motion: EnumProperty(
        name="根运动",
        items=(
            ("KEEP", "保留位移", "保留髋部的水平移动"),
            ("IN_PLACE", "原地", "去掉水平移动，保留上下起伏"),
        ),
        default="KEEP",
    )
    use_foot_ik: BoolProperty(name="脚 IK", description="按来源链伸展比例生成目标落点，支持地面约束和速度植步，身体仍用 FK", default=False)
    use_hand_ik: BoolProperty(name="手 IK", description="按来源链伸展比例生成手部落点，身体仍用 FK", default=False)
    foot_floor_enabled: BoolProperty(name="地面约束", description="脚 IK 开启时把脚部目标高度钳制到地面附近", default=True)
    foot_floor_alpha: FloatProperty(name="地面强度", description="地面约束的混合权重", default=1.0, min=0.0, max=1.0)
    foot_maintain_height_offset: FloatProperty(name="保留参考脚高", description="保留来源与目标在参考姿势下的脚部高度差", default=1.0, min=0.0, max=1.0)
    foot_falloff_start_m: FloatProperty(name="衰减起点", description="低于此高度（米）时脚部目标被完全拉向地面", default=0.08, min=0.0, unit="LENGTH")
    foot_falloff_distance_m: FloatProperty(name="衰减距离", description="从起点向上渐变到此距离（米）后约束关闭", default=0.20, min=0.0, unit="LENGTH")
    foot_pelvis_floor_weight: FloatProperty(name="髋部地面权重", description="髋部高度按蹲姿比例映射的强度", default=1.0, min=0.0, max=1.0)
    foot_planting_enabled: BoolProperty(name="速度植步", description="接触地面且速度低的帧钉住脚部目标，减少脚滑", default=True)
    foot_speed_threshold_mps: FloatProperty(name="植步速度阈值", description="低于此水平速度（米/秒）视为触地", default=0.15, min=0.0)
    foot_stiffness: FloatProperty(name="弹簧刚度", description="植步解除后目标回位的弹簧刚度", default=250.0, min=0.0)
    foot_critical_damping: FloatProperty(name="临界阻尼", description="植步弹簧阻尼比，1.0 为临界阻尼", default=1.0, min=0.0, max=1.0)
    foot_contact_window_s: FloatProperty(name="接触窗口", description="判定局部最低点的时间窗口（秒）", default=0.08, min=0.0)
    foot_contact_height_tolerance_m: FloatProperty(name="接触高度容差", description="脚部低于参考高度加此容差（米）才算接触", default=0.02, min=0.0, unit="LENGTH")
    foot_contact_minimum_tolerance_m: FloatProperty(name="最低点容差", description="窗口内高于局部最低点超过此值（米）不算接触", default=0.01, min=0.0, unit="LENGTH")
    foot_floor_height_m: FloatProperty(name="地面高度", description="世界空间地面平面的高度（米）", default=0.0, unit="LENGTH")
    foot_source_crotch_offset_m: FloatProperty(name="来源胯部偏移", description="髋部到胯部参考点的垂直偏移（米）", default=0.0, unit="LENGTH")
    foot_target_crotch_offset_m: FloatProperty(name="目标胯部偏移", description="目标髋部到胯部参考点的垂直偏移（米）", default=0.0, unit="LENGTH")
    use_soft_repulsion: BoolProperty(
        name="软斥力", description="手臂目标被躯干胶囊软推离开，减少手部穿入身体", default=False,
    )
    soft_minimum_distance_m: FloatProperty(name="完全作用距离（米）", description="低于此距离时软推达到最大强度", default=0.10, min=0.0)
    soft_maximum_distance_m: FloatProperty(name="作用结束距离（米）", description="超过此距离后软推完全关闭", default=0.20, min=0.0)
    soft_coefficient: FloatProperty(name="斥力系数", description="软推力场强度", default=64.0, min=0.0)
    soft_inverted: BoolProperty(name="反转力场", description="把斥力改为吸力（一般保持关闭）", default=False)
    soft_torso_radius_m: FloatProperty(name="躯干半径（米）", description="躯干胶囊代理半径", default=0.15, min=0.0)
    soft_hand_radius_m: FloatProperty(name="手部代理半径（米）", description="手部球代理半径", default=0.025, min=0.0)
    soft_forearm_radius_m: FloatProperty(name="前臂代理半径（米）", description="前臂球代理半径", default=0.035, min=0.0)
    use_joint_limits: BoolProperty(
        name="关节角度限", description="按 PBIK 语义限制肩肘等关节的旋转范围，防关节反转", default=False,
    )
    joint_iterations: IntProperty(name="求解轮数", description="限位与两骨求解的交替轮数", default=20, min=0, max=1000)
    joint_max_angle_degrees: FloatProperty(name="单轮增量上限（度）", description="每轮旋转修正的最大角度增量", default=30.0, min=0.0, max=45.0)
    joint_limit_bones: CollectionProperty(type=HRJointLimitItem)
    export_format: EnumProperty(
        name="格式",
        items=(
            ("GLB", "glTF", "导出单个 .glb"),
            ("FBX", "FBX", "导出 .fbx"),
        ),
        default="GLB",
    )
    automatic_bone_orientation: BoolProperty(
        name="FBX 自动骨骼朝向",
        description="Mixamo 下载的 FBX 建议打开。游戏提取的骨架如果已经朝向正确，保持关闭",
        default=False,
    )
    last_source_path: StringProperty(name="上次动画来源", subtype="FILE_PATH")
    last_target_path: StringProperty(name="上次目标模型", subtype="FILE_PATH")
    draw_bone_gizmos: BoolProperty(
        name="绘制骨骼 Gizmo",
        description="在关节上画标记，并沿着身体关节连线。不使用 Blender 默认的八面体骨骼",
        default=True,
        update=_on_draw_gizmos,
    )
    show_gizmo_labels: BoolProperty(
        name="显示标准骨骼名",
        description="在每个关节旁显示标准人形骨架名（UE 风格）及该骨架自身的骨骼名",
        default=False,
        update=_on_draw_labels,
    )
    show_bones: BoolProperty(
        name="显示骨骼",
        description="显示导入模型的骨骼。关闭后只保留网格，避免骨骼挡住角色",
        default=False,
        update=_on_show_bones,
    )
    show_bone_spheres: BoolProperty(
        name="显示骨骼球体",
        description="显示导入骨架上的球体骨形和碰撞球。导入后默认关闭",
        default=False,
        update=_on_show_spheres,
    )


class HR_OT_import_source(Operator):
    bl_idname = "hr.import_source"
    bl_label = "导入含动画的模型"
    bl_description = "导入 FBX、glTF 或 BVH。文件里需要有骨架和动画"
    bl_options = {"REGISTER", "UNDO"}

    filepath: StringProperty(subtype="FILE_PATH")
    filter_glob: StringProperty(default="*.fbx;*.glb;*.gltf;*.bvh", options={"HIDDEN"})
    automatic_bone_orientation: BoolProperty(
        name="FBX 自动骨骼朝向",
        description="Mixamo 的 FBX 建议打开。游戏提取的骨架保持关闭",
        default=False,
    )

    def invoke(self, context, event):
        self.automatic_bone_orientation = context.scene.hr_settings.automatic_bone_orientation
        remembered = _recall_filepath(context, "last_source_path")
        if remembered:
            self.filepath = remembered
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        try:
            armature, summary = load_source(
                self.filepath,
                automatic_bone_orientation=self.automatic_bone_orientation,
            )
        except PipelineError as exc:
            self.report({"ERROR"}, str(exc))
            _set_status(context, str(exc))
            return {"CANCELLED"}
        settings = context.scene.hr_settings
        _remember_filepath(context, "last_source_path", self.filepath)
        settings.source = armature
        settings.automatic_bone_orientation = self.automatic_bone_orientation
        settings.show_bone_spheres = False
        settings.show_bones = False
        set_bone_sphere_display(armature, False)
        set_armature_bones_visible(armature, False)
        actions = collect_actions(armature)
        if actions and settings.source_action not in {action.name for action in actions}:
            settings.source_action = actions[0].name
        _set_status(context, summary)
        self.report({"INFO"}, summary.splitlines()[0])
        return {"FINISHED"}


class HR_OT_play_source(Operator):
    bl_idname = "hr.play_source"
    bl_label = "播放"
    bl_description = "播放或暂停当前选中的动画，重定向角色同步切换到对应片段"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = context.scene.hr_settings
        if settings.source is None:
            self.report({"ERROR"}, "请先导入动画来源")
            return {"CANCELLED"}
        actions = collect_actions(settings.source)
        if not actions:
            self.report({"ERROR"}, "来源上没有动画")
            return {"CANCELLED"}
        if settings.source_action not in {action.name for action in actions}:
            settings.source_action = actions[0].name
        try:
            _preview_selected_action(settings, context, jump=False)
        except RetargetError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        screen = context.screen
        if bpy.app.background or screen is None:
            return {"FINISHED"}
        try:
            bpy.ops.screen.animation_play()
        except RuntimeError as exc:
            self.report({"WARNING"}, "动画已切到时间轴，但当前窗口无法开始播放: " + str(exc))
        return {"FINISHED"}


class HR_OT_import_target(Operator):
    bl_idname = "hr.import_target_retarget"
    bl_label = "导入目标并重定向"
    bl_description = "导入另一个模型。没有骨架时按直立 T/A Pose 自动绑定，然后把来源动画烘焙过去"
    bl_options = {"REGISTER", "UNDO"}

    filepath: StringProperty(subtype="FILE_PATH")
    filter_glob: StringProperty(default="*.fbx;*.glb;*.gltf;*.obj", options={"HIDDEN"})

    def invoke(self, context, event):
        if context.scene.hr_settings.source is None:
            self.report({"ERROR"}, "请先导入含动画的模型")
            return {"CANCELLED"}
        remembered = _recall_filepath(context, "last_target_path")
        if remembered:
            self.filepath = remembered
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        settings = context.scene.hr_settings
        options = _options_from_settings(settings, use_mapping=False)
        try:
            armature, summary, _baked, _auto = load_target_and_retarget(self.filepath, settings.source, options)
        except PipelineError as exc:
            self.report({"ERROR"}, str(exc))
            _set_status(context, str(exc))
            return {"CANCELLED"}
        _remember_filepath(context, "last_target_path", self.filepath)
        settings.target = armature
        settings.show_bones = False
        set_armature_bones_visible(armature, False)
        if options.resolved_pairs:
            _fill_mapping(settings, options.resolved_pairs)
        _set_status(context, summary)
        self.report({"INFO"}, "重定向完成")
        return {"FINISHED"}


class HR_OT_retarget_existing(Operator):
    bl_idname = "hr.retarget_existing"
    bl_label = "重定向到当前目标"
    bl_description = "用来源骨架上的动画，烘焙到面板里指定的目标骨架"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.hr_settings
        had_mapping = bool(settings.mappings)
        options = _options_from_settings(settings, use_mapping=True)
        try:
            summary, _baked = retarget_existing(settings.source, settings.target, options)
        except PipelineError as exc:
            self.report({"ERROR"}, str(exc))
            _set_status(context, str(exc))
            return {"CANCELLED"}
        _remember_generated_pairs(settings, options, had_mapping)
        _set_status(context, summary)
        self.report({"INFO"}, "重定向完成")
        return {"FINISHED"}


class HR_OT_retarget_selected_mesh(Operator):
    bl_idname = "hr.retarget_selected_mesh"
    bl_label = "绑定选中网格并重定向"
    bl_description = "把当前选中的人体网格自动绑定，再接收来源动画"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.hr_settings
        meshes = [obj for obj in context.selected_objects if obj.type == "MESH"]
        options = _options_from_settings(settings, use_mapping=False)
        try:
            armature, summary, _baked = retarget_selected_meshes(settings.source, meshes, options)
        except PipelineError as exc:
            self.report({"ERROR"}, str(exc))
            _set_status(context, str(exc))
            return {"CANCELLED"}
        settings.target = armature
        settings.show_bones = False
        set_armature_bones_visible(armature, False)
        if options.resolved_pairs:
            _fill_mapping(settings, options.resolved_pairs)
        _set_status(context, summary)
        self.report({"INFO"}, "自动绑定并重定向完成")
        return {"FINISHED"}


class HR_OT_export(Operator):
    bl_idname = "hr.export_result"
    bl_label = "导出下载"
    bl_description = "把目标角色和已经烘焙好的动画导出"
    bl_options = {"REGISTER"}

    export_all_actions: BoolProperty(
        name="全量动画",
        description="导出全部动画。取消勾选则只导出当前动画",
        default=True,
    )

    def invoke(self, context, event):
        settings = context.scene.hr_settings
        if settings.target is None:
            self.report({"ERROR"}, "还没有重定向结果")
            return {"CANCELLED"}
        self.export_all_actions = True
        if settings.export_format == "FBX":
            return bpy.ops.hr.export_result_file("INVOKE_DEFAULT", export_all_actions=True)
        return context.window_manager.invoke_props_dialog(self, title="导出 glTF 动画")

    def draw(self, context):
        column = self.layout.column()
        column.prop(self, "export_all_actions")
        if self.export_all_actions:
            column.label(text="将导出全部动画")
        else:
            column.label(text="将只导出当前动画")

    def execute(self, context):
        return bpy.ops.hr.export_result_file("INVOKE_DEFAULT", export_all_actions=self.export_all_actions)


class HR_OT_export_file(Operator):
    bl_idname = "hr.export_result_file"
    bl_label = "选择导出文件"
    bl_description = "选择 glTF 或 FBX 的保存位置"
    bl_options = {"REGISTER"}

    filepath: StringProperty(subtype="FILE_PATH")
    filter_glob: StringProperty(default="*.glb;*.gltf;*.fbx", options={"HIDDEN"})
    export_all_actions: BoolProperty(name="全量动画", default=True, options={"HIDDEN"})

    def invoke(self, context, event):
        settings = context.scene.hr_settings
        if settings.target is None:
            self.report({"ERROR"}, "还没有重定向结果")
            return {"CANCELLED"}
        ext = ".fbx" if settings.export_format == "FBX" else ".glb"
        self.filepath = bpy.path.ensure_ext(settings.target.name + "_retarget" + ext, ext)
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        settings = context.scene.hr_settings
        path = self.filepath
        if settings.export_format == "FBX" and not path.lower().endswith(".fbx"):
            path = bpy.path.ensure_ext(path, ".fbx")
        if settings.export_format == "GLB" and not path.lower().endswith((".glb", ".gltf")):
            path = bpy.path.ensure_ext(path, ".glb")
        export_all = True if settings.export_format == "FBX" else self.export_all_actions
        try:
            export_armature(settings.target, path, export_all_actions=export_all)
        except PipelineError as exc:
            self.report({"ERROR"}, str(exc))
            _set_status(context, str(exc))
            return {"CANCELLED"}
        scope = "全量动画" if export_all else "当前动画"
        text = f"已导出{scope}: {path}"
        _set_status(context, settings.status + "\n" + text)
        self.report({"INFO"}, text)
        return {"FINISHED"}


class HR_OT_build_mapping(Operator):
    bl_idname = "hr.build_mapping"
    bl_label = "生成映射"
    bl_description = "按骨骼名或几何重新生成映射表，之后可以逐行修改"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.hr_settings
        if settings.source is None or settings.target is None:
            self.report({"ERROR"}, "请先指定来源和目标骨架")
            return {"CANCELLED"}
        pairs = build_pairs(settings.source, settings.target)
        if not pairs:
            self.report({"ERROR"}, "没有识别到可对应的骨骼")
            return {"CANCELLED"}
        _fill_mapping(settings, pairs)
        text = f"已生成 {len(pairs)} 行映射，可直接改骨骼名"
        _set_status(context, text)
        self.report({"INFO"}, text)
        return {"FINISHED"}


class HR_OT_save_preset(Operator):
    bl_idname = "hr.save_preset"
    bl_label = "保存预设"
    bl_description = "把当前映射表存成可重复加载的预设"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = context.scene.hr_settings
        pairs = _pairs_from_settings(settings)
        if not pairs:
            self.report({"ERROR"}, "映射表是空的")
            return {"CANCELLED"}
        try:
            path = save_preset(settings.preset_name, pairs)
        except PresetError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        text = "已保存映射预设: " + path
        _set_status(context, text)
        self.report({"INFO"}, text)
        return {"FINISHED"}


class HR_OT_load_preset(Operator):
    bl_idname = "hr.load_preset"
    bl_label = "加载预设"
    bl_description = "加载预设。当前骨架上不存在的骨骼会退回自动识别"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.hr_settings
        if settings.source is None or settings.target is None:
            self.report({"ERROR"}, "请先指定来源和目标骨架")
            return {"CANCELLED"}
        try:
            stored = load_preset(settings.preset_name)
        except PresetError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        merged = merge_preset(build_pairs(settings.source, settings.target), stored, settings.source, settings.target)
        _fill_mapping(settings, merged)
        text = f"已加载预设 {settings.preset_name}，共 {len(merged)} 行"
        _set_status(context, text)
        self.report({"INFO"}, text)
        return {"FINISHED"}


class HR_OT_capture_reference(Operator):
    bl_idname = "hr.capture_reference"
    bl_label = "捕获当前姿势"
    bl_description = "把两边骨架现在的姿势记为零点，适合 T-Pose 对 A-Pose"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.hr_settings
        if settings.source is None or settings.target is None:
            self.report({"ERROR"}, "请先指定来源和目标骨架")
            return {"CANCELLED"}
        pairs = _pairs_from_settings(settings)
        if not pairs:
            pairs = build_pairs(settings.source, settings.target)
            if pairs:
                _fill_mapping(settings, pairs)
        if not pairs:
            self.report({"ERROR"}, "没有可捕获的映射")
            return {"CANCELLED"}
        bpy.context.view_layer.update()
        settings.reference_json = json.dumps(capture_reference(settings.source, settings.target, pairs))
        settings.reference_pose = "CURRENT"
        text = "已捕获当前姿势作为零点"
        _set_status(context, text)
        self.report({"INFO"}, text)
        return {"FINISHED"}


class HR_PT_panel(Panel):
    bl_label = "人形重定向"
    bl_idname = "HR_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "重定向"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.hr_settings
        layout.prop(settings, "stand_layout", text="站位")
        layout.prop(settings, "standard_skeleton", text="标准人形骨架")

        source_box = layout.box()
        source_box.label(text="1. 动画来源")
        source_box.prop(settings, "automatic_bone_orientation")
        source_box.operator("hr.import_source", icon="IMPORT")
        source_box.prop(settings, "source")
        clip_row = source_box.row(align=True)
        clip_row.enabled = settings.source is not None
        clip_row.prop(settings, "source_action", text="动画")
        playing = bool(context.screen and context.screen.is_animation_playing)
        clip_row.operator(
            "hr.play_source",
            text="暂停" if playing else "播放",
            icon="PAUSE" if playing else "PLAY",
        )

        target_box = layout.box()
        target_box.label(text="2. 目标角色")
        target_box.operator("hr.import_target_retarget", icon="ARMATURE_DATA")
        target_box.operator("hr.retarget_selected_mesh", icon="MOD_ARMATURE")
        target_box.prop(settings, "target")

        map_box = layout.box()
        map_box.label(text="映射表")
        map_box.operator("hr.build_mapping", icon="PRESET")
        map_box.template_list("HR_UL_mappings", "", settings, "mappings", settings, "mapping_index", rows=6)
        preset_row = map_box.row(align=True)
        preset_row.prop(settings, "preset_name", text="")
        preset_row.operator("hr.save_preset", text="保存")
        preset_row.operator("hr.load_preset", text="加载")

        option_box = layout.box()
        option_box.label(text="烘焙")
        option_box.prop(settings, "reference_pose", text="参考姿势")
        option_box.operator("hr.capture_reference", icon="POSE_HLT")
        option_box.prop(settings, "root_motion", text="根运动")
        option_box.prop(settings, "use_foot_ik")
        option_box.prop(settings, "use_hand_ik")
        foot_col = option_box.column()
        foot_col.enabled = settings.use_foot_ik
        foot_col.prop(settings, "foot_floor_enabled")
        if settings.foot_floor_enabled:
            floor_col = foot_col.column()
            floor_col.prop(settings, "foot_floor_alpha")
            floor_col.prop(settings, "foot_maintain_height_offset")
            floor_col.prop(settings, "foot_falloff_start_m")
            floor_col.prop(settings, "foot_falloff_distance_m")
        foot_col.prop(settings, "foot_pelvis_floor_weight")
        foot_col.prop(settings, "foot_planting_enabled")
        if settings.foot_planting_enabled:
            plant_col = foot_col.column()
            plant_col.prop(settings, "foot_speed_threshold_mps")
            plant_col.prop(settings, "foot_stiffness")
            plant_col.prop(settings, "foot_critical_damping")
            plant_col.prop(settings, "foot_contact_window_s")
            plant_col.prop(settings, "foot_contact_height_tolerance_m")
            plant_col.prop(settings, "foot_contact_minimum_tolerance_m")
        foot_col.prop(settings, "foot_floor_height_m")
        option_box.prop(settings, "use_soft_repulsion")
        if settings.use_soft_repulsion:
            soft_col = option_box.column()
            soft_col.prop(settings, "soft_minimum_distance_m")
            soft_col.prop(settings, "soft_maximum_distance_m")
            soft_col.prop(settings, "soft_coefficient")
            soft_col.prop(settings, "soft_inverted")
            soft_col.prop(settings, "soft_torso_radius_m")
            soft_col.prop(settings, "soft_hand_radius_m")
            soft_col.prop(settings, "soft_forearm_radius_m")
            soft_col.label(text="软推不保证网格无穿插")
        option_box.prop(settings, "use_joint_limits")
        if settings.use_joint_limits:
            joint_col = option_box.column()
            joint_col.prop(settings, "joint_iterations")
            joint_col.prop(settings, "joint_max_angle_degrees")
            joint_col.label(text="限制相对本帧 FK 输入的求解变化")
            joint_col.operator("hr.add_joint_limit")
            for index, item in enumerate(settings.joint_limit_bones):
                box = joint_col.box()
                row = box.row()
                row.prop(item, "role")
                operator = row.operator("hr.remove_joint_limit", text="删除")
                operator.index = index
                for axis in ("x", "y", "z"):
                    row = box.row(align=True)
                    row.prop(item, axis + "_type")
                    row.prop(item, "min_" + axis)
                    row.prop(item, "max_" + axis)
                box.prop(item, "rotation_stiffness")
        option_box.operator("hr.retarget_existing", icon="ACTION")

        export_box = layout.box()
        export_box.label(text="3. 下载")
        export_box.prop(settings, "export_format", text="")
        export_box.operator("hr.export_result", icon="EXPORT")

        note = layout.box()
        for line in settings.status.splitlines():
            note.label(text=line[:80])

        settings_box = layout.box()
        settings_box.label(text="Settings")
        settings_box.prop(settings, "draw_bone_gizmos")
        settings_box.prop(settings, "show_gizmo_labels")
        settings_box.prop(settings, "show_bones")
        settings_box.prop(settings, "show_bone_spheres")
        settings_box.prop(settings, "show_y0_floor")



class HR_AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    last_source_path: StringProperty(name="上次动画来源", subtype="FILE_PATH")
    last_target_path: StringProperty(name="上次目标模型", subtype="FILE_PATH")

    def draw(self, _context):
        return


CLASSES = (
    HR_AddonPreferences,
    HRMapItem,
    HR_UL_mappings,
    HRJointLimitItem,
    HRSettings,
    HR_OT_import_source,
    HR_OT_play_source,
    HR_OT_import_target,
    HR_OT_retarget_existing,
    HR_OT_retarget_selected_mesh,
    HR_OT_build_mapping,
    HR_OT_save_preset,
    HR_OT_load_preset,
    HR_OT_capture_reference,
    HR_OT_export,
    HR_OT_export_file,
    HR_OT_add_joint_limit,
    HR_OT_remove_joint_limit,
    HR_PT_panel,
)


def _apply_saved_stand(_dummy=None):
    scene = getattr(bpy.context, "scene", None)
    if scene is None or not hasattr(scene, "hr_settings"):
        return
    settings = scene.hr_settings
    if settings.source is None and settings.target is None:
        return
    apply_stand_layout(settings.source, settings.target, settings.stand_layout)


def _apply_saved_view_now():
    """Hide bones after the file has finished loading.

    Writing bone.hide while Blender is still reading the file, or from the
    source-pointer callback that runs during that read, locks the main thread.
    """
    scene = getattr(bpy.context, "scene", None)
    if scene is None or not hasattr(scene, "hr_settings"):
        return None
    settings = scene.hr_settings
    if settings.source is not None:
        set_bone_sphere_display(settings.source, settings.show_bone_spheres)
    set_armature_bones_visible(settings.source, bool(settings.show_bones))
    set_armature_bones_visible(settings.target, bool(settings.show_bones))
    return None


def _schedule_saved_view():
    if bpy.app.background:
        _apply_saved_view_now()
        return
    if not bpy.app.timers.is_registered(_apply_saved_view_now):
        bpy.app.timers.register(_apply_saved_view_now, first_interval=0.2)


def _apply_saved_sphere_setting(_dummy=None):
    _schedule_saved_view()


def register():
    for cls in CLASSES:
        try:
            bpy.utils.register_class(cls)
        except ValueError:
            pass
    if not hasattr(bpy.types.Scene, "hr_settings"):
        bpy.types.Scene.hr_settings = PointerProperty(type=HRSettings)
    if _apply_saved_sphere_setting not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_apply_saved_sphere_setting)
    if _apply_saved_stand not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_apply_saved_stand)
    register_draw()
    _apply_saved_sphere_setting()
    _apply_saved_stand()


def unregister():
    unregister_draw()
    if bpy.app.timers.is_registered(_apply_saved_view_now):
        bpy.app.timers.unregister(_apply_saved_view_now)
    if _apply_saved_sphere_setting in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_apply_saved_sphere_setting)
    if _apply_saved_stand in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_apply_saved_stand)
    if hasattr(bpy.types.Scene, "hr_settings"):
        del bpy.types.Scene.hr_settings
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
