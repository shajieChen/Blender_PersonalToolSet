# impl_joint_limits.md

```text
旋转核 RED/GREEN
        |
公共烘焙接线 -> 两开关组合验证 -> 清理复验
```

目标文件：`H:\Blender_Plugin\docs\design\impl_joint_limits.md`  
状态：实施方案；代码未应用。所有执行证据保持 `NotRun`。

## 目标

移植 PBIK 旋转限位核，并为两个新功能建立显式开启分支。

以下代码不实现完整 PBIK，也不实现永久捕获参考下的 FK clamp 或胶囊硬投影。

## 修改范围

| 文件 | 位置 |
|---|---|
| 新增 `humanoid_retarget/joint_limits.py` | 数值类型、旋转分解、普通校正、FinalPass |
| `humanoid_retarget/retarget.py` | Options、参考准备、帧入口、开启路径坐标和失败恢复 |
| `humanoid_retarget/__init__.py` | 每骨配置、参数传递、UI 注册 |
| 新增 `tests/test_joint_limits.py` | 限位分支测试 |
| 已新增的公共测试入口 | 使用指定测试文件模式 |

`ik.py` 的原函数保持原样。开启路径通过 `retarget.py` 复用现有 `_two_bone`、`_aim_joint`、`_write_end_rotation`。

## 实施步骤

### 1. 材料与前置检查

已核验：

- `PBIKConstraint.cpp` 的完整旋转限位核。
- `PBIKBody.cpp` 的增量、锁定和每次输入更新。
- `PBIKSolver.h` 默认设置。
- `FindBetweenVectors`、`GetSafeNormal`、四元数逆、`FMath::Acos`。
- 当前实际烘焙函数、UI 和两跳复制点。

执行时先核对 `mathutils.Quaternion` 的 WXYZ 参数顺序。不能直接照搬 UE 的 XYZW 构造顺序。

UE 四元数逆在该路径是共轭，不能在尚未归一化的中间步骤中改成除以模平方的通用逆。

### 2. 新增 `joint_limits.py`

```python
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum

from mathutils import Quaternion, Vector


_SMALL_NUMBER = 1e-8
_KINDA_SMALL_NUMBER = 1e-4


class LimitType(str, Enum):
    FREE = "FREE"
    LIMITED = "LIMITED"
    LOCKED = "LOCKED"


@dataclass
class AxisAngleLimit:
    kind: LimitType = LimitType.FREE
    minimum: float = 0.0
    maximum: float = 0.0


@dataclass
class BoneAngleLimits:
    role: str = ""
    x: AxisAngleLimit = field(default_factory=AxisAngleLimit)
    y: AxisAngleLimit = field(default_factory=AxisAngleLimit)
    z: AxisAngleLimit = field(default_factory=AxisAngleLimit)
    rotation_stiffness: float = 0.0


@dataclass
class JointLimitSettings:
    enabled: bool = False
    iterations: int = 20
    max_angle_degrees: float = 30.0
    bones: tuple = ()


@dataclass
class JointBody:
    rotation: Quaternion
    initial_rotation: Quaternion
    settings: BoneAngleLimits
    inverse_mass: float = 1.0
    sub_solve_locked: bool = False


@dataclass
class JointRotationConstraint:
    parent: JointBody
    child: JointBody
    reference_rotation: Quaternion


def validate_joint_limit_settings(
    settings: JointLimitSettings,
) -> None:
    if not isinstance(settings.iterations, int):
        raise ValueError("joint iterations must be an integer")
    if settings.iterations < 0:
        raise ValueError("joint iterations must be non-negative")
    if (
        not math.isfinite(settings.max_angle_degrees)
        or settings.max_angle_degrees < 0.0
    ):
        raise ValueError("maximum rotation increment must be finite and non-negative")

    seen = set()
    for bone in settings.bones:
        if not bone.role or bone.role in seen:
            raise ValueError("joint limit roles must be nonempty and unique")
        seen.add(bone.role)
        if (
            not math.isfinite(bone.rotation_stiffness)
            or not 0.0 <= bone.rotation_stiffness <= 1.0
        ):
            raise ValueError("rotation stiffness must stay within 0..1")
        for axis in (bone.x, bone.y, bone.z):
            if axis.kind not in tuple(LimitType):
                raise ValueError("unknown joint limit type")
            if not all(math.isfinite(value) for value in (
                axis.minimum, axis.maximum
            )):
                raise ValueError("joint angle limits must be finite")


def _inverse(q: Quaternion) -> Quaternion:
    return Quaternion((q.w, -q.x, -q.y, -q.z))


def _scale(q: Quaternion, factor: float) -> Quaternion:
    return Quaternion(tuple(value * factor for value in q))


def normalize_rotation(q: Quaternion) -> Quaternion:
    squared_length = sum(value * value for value in q)
    if squared_length < _SMALL_NUMBER:
        return Quaternion((1.0, 0.0, 0.0, 0.0))
    return _scale(q, 1.0 / math.sqrt(squared_length))


def _rotate(q: Quaternion, vector: Vector) -> Vector:
    xyz = Vector((q.x, q.y, q.z))
    first = xyz.cross(vector)
    return vector + (first * q.w + xyz.cross(first)) * 2.0


def _safe_normal(vector: Vector) -> Vector:
    squared_length = vector.length_squared
    if squared_length == 1.0:
        return vector.copy()
    if squared_length < _SMALL_NUMBER:
        return Vector((0.0, 0.0, 0.0))
    return vector / math.sqrt(squared_length)


def _axis_rotation(axis: Vector, degrees: float) -> Quaternion:
    half = math.radians(degrees) * 0.5
    sine = math.sin(half)
    return Quaternion((
        math.cos(half),
        axis.x * sine,
        axis.y * sine,
        axis.z * sine,
    ))


def _find_between(a: Vector, b: Vector) -> Quaternion:
    norm_ab = math.sqrt(a.length_squared * b.length_squared)
    w = norm_ab + a.dot(b)
    if w >= 1e-6 * norm_ab:
        xyz = a.cross(b)
    else:
        w = 0.0
        if abs(a.x) > abs(a.y) and abs(a.x) > abs(a.z):
            basis = Vector((0.0, 1.0, 0.0))
        else:
            basis = Vector((-1.0, 0.0, 0.0))
        xyz = a.cross(basis)
    return normalize_rotation(
        Quaternion((w, xyz.x, xyz.y, xyz.z))
    )


def _signed_angle(
    start: Vector,
    end: Vector,
    axis: Vector,
) -> float:
    value = min(1.0, max(-1.0, start.dot(end)))
    angle = math.degrees(math.acos(value))
    return angle if start.cross(end).dot(axis) >= 0.0 else -angle


def _joint_axes(joint: JointRotationConstraint):
    reference = joint.reference_rotation
    original = tuple(_rotate(reference, axis) for axis in (
        Vector((1.0, 0.0, 0.0)),
        Vector((0.0, 1.0, 0.0)),
        Vector((0.0, 0.0, 1.0)),
    ))
    parent_delta = (
        joint.parent.rotation @ _inverse(joint.parent.initial_rotation)
    )
    child_delta = (
        joint.child.rotation @ _inverse(joint.child.initial_rotation)
    )
    parent_axes = tuple(_rotate(parent_delta, axis) for axis in original)
    child_axes = tuple(_rotate(child_delta, axis) for axis in original)
    return parent_axes, child_axes


def decompose_rotation_angles(joint: JointRotationConstraint):
    parent_axes, child_axes = _joint_axes(joint)
    xa, ya, za = parent_axes
    _xb, yb, zb = child_axes

    projected_x = _safe_normal(zb - xa * zb.dot(xa))
    projected_y = _safe_normal(zb - ya * zb.dot(ya))
    projected_z = _safe_normal(yb - za * yb.dot(za))

    angles = (
        _signed_angle(za, projected_x, xa),
        -_signed_angle(za, projected_y, ya),
        _signed_angle(ya, projected_z, za),
    )
    return (
        angles,
        (xa, -ya, za),
        (projected_x, projected_y, projected_z),
        (za, za, ya),
    )


def _rotation_locked(body: JointBody) -> bool:
    return (
        body.sub_solve_locked
        or body.inverse_mass <= _SMALL_NUMBER
        or abs(body.settings.rotation_stiffness - 1.0) <= _SMALL_NUMBER
    )


def _apply_rotation_delta(
    body: JointBody,
    delta: Quaternion,
    max_angle_degrees: float,
) -> None:
    if _rotation_locked(body):
        return

    maximum = math.radians(max_angle_degrees)
    magnitude = math.sqrt(sum(value * value for value in delta))
    if magnitude > maximum:
        delta = _scale(delta, maximum / magnitude)

    change = _scale(delta @ body.rotation, 0.5)
    body.rotation = Quaternion(tuple(
        body.rotation[i] + change[i] for i in range(4)
    ))


def _apply_rotation_correction(
    joint: JointRotationConstraint,
    delta: Quaternion,
    max_angle_degrees: float,
) -> None:
    _apply_rotation_delta(
        joint.parent,
        _scale(delta, 1.0 - joint.parent.settings.rotation_stiffness),
        max_angle_degrees,
    )
    _apply_rotation_delta(
        joint.child,
        _scale(delta, -(1.0 - joint.child.settings.rotation_stiffness)),
        max_angle_degrees,
    )


def _align_axes(
    joint: JointRotationConstraint,
    axis_a: Vector,
    axis_b: Vector,
    final: bool,
    max_angle_degrees: float,
) -> None:
    if final:
        joint.child.rotation = (
            _find_between(axis_b, axis_a) @ joint.child.rotation
        )
        return

    cross = axis_a.cross(axis_b)
    magnitude = cross.length
    direction = (
        cross / magnitude
        if magnitude > _SMALL_NUMBER
        else Vector((0.0, 0.0, 0.0))
    )
    effective_inverse_mass = direction.dot(direction)
    if effective_inverse_mass < _KINDA_SMALL_NUMBER:
        return

    push = direction * (magnitude / effective_inverse_mass)
    delta = Quaternion((0.0, push.x, push.y, push.z))
    _apply_rotation_correction(joint, delta, max_angle_degrees)


def update_joint_limits(
    joint: JointRotationConstraint,
    final: bool,
    max_angle_degrees: float,
) -> None:
    axes = (
        joint.child.settings.x,
        joint.child.settings.y,
        joint.child.settings.z,
    )
    if all(axis.kind == LimitType.FREE for axis in axes):
        return

    for axis in axes:
        if axis.maximum < axis.minimum:
            axis.maximum = axis.minimum + 1.0

    locked = tuple(
        axis.kind == LimitType.LOCKED
        or (
            axis.kind == LimitType.LIMITED
            and axis.maximum - axis.minimum < 2.0
        )
        for axis in axes
    )

    if all(locked):
        original = (
            joint.parent.initial_rotation
            @ _inverse(joint.child.initial_rotation)
        )
        current = (
            joint.parent.rotation @ _inverse(joint.child.rotation)
        )
        delta = original @ _inverse(current)

        if final:
            joint.child.rotation = (
                _inverse(delta) @ joint.child.rotation
            )
        else:
            _apply_rotation_correction(
                joint,
                Quaternion((0.0, delta.x, delta.y, delta.z)),
                max_angle_degrees,
            )
        return

    hinge = next((
        index for index in range(3)
        if not locked[index]
        and all(locked[other] for other in range(3) if other != index)
    ), None)

    if hinge is not None:
        parent_axes, child_axes = _joint_axes(joint)
        _align_axes(
            joint,
            parent_axes[hinge],
            child_axes[hinge],
            final,
            max_angle_degrees,
        )

    limited = tuple(
        axis.kind == LimitType.LIMITED and not locked[index]
        for index, axis in enumerate(axes)
    )
    if not any(limited):
        return

    angles, rotation_axes, current_vectors, reference_vectors = (
        decompose_rotation_angles(joint)
    )
    for index, axis in enumerate(axes):
        if not limited[index]:
            continue

        angle = angles[index]
        if angle < axis.minimum:
            target_angle = axis.minimum
        elif angle > axis.maximum:
            target_angle = axis.maximum
        else:
            continue

        target_vector = _rotate(
            _axis_rotation(rotation_axes[index], target_angle),
            reference_vectors[index],
        )
        _align_axes(
            joint,
            target_vector,
            current_vectors[index],
            final,
            max_angle_degrees,
        )


def run_rotation_limit_pass(
    joints: tuple,
    final: bool,
    max_angle_degrees: float,
) -> None:
    for joint in joints:
        if final:
            if joint.child.sub_solve_locked:
                continue
            update_joint_limits(joint, True, max_angle_degrees)
            continue

        if (
            joint.parent.sub_solve_locked
            and joint.child.sub_solve_locked
        ):
            continue
        if abs(
            joint.parent.inverse_mass + joint.child.inverse_mass
        ) <= _SMALL_NUMBER:
            continue

        update_joint_limits(joint, False, max_angle_degrees)
        joint.parent.rotation = normalize_rotation(joint.parent.rotation)
        joint.child.rotation = normalize_rotation(joint.child.rotation)
```

代码保持以下细节：

- 原始轴来自子骨参考旋转。
- `_inverse()` 使用共轭。
- 非单位中间四元数的向量旋转不隐式归一化。
- 反向向量的备用轴和 UE 一致。
- Limited 三轴使用同一次分解结果。
- FinalPass 不经过旋转刚度和 MaxAngle。
- `run_rotation_limit_pass()` 只运行旋转限位，不冒充 `FJointConstraint::Solve()` 的 pin 位置求解。

### 3. `retarget.py`：Options

增加导入：

```python
from copy import deepcopy

from .foot_ik import IKGoal, constrain_goal_floor, generate_limb_goal, plant_goal
from .ik import _aim_joint, _two_bone, _write_end_rotation
from .joint_limits import (
    BoneAngleLimits,
    JointBody,
    JointLimitSettings,
    JointRotationConstraint,
    normalize_rotation,
    run_rotation_limit_pass,
    validate_joint_limit_settings,
)
```

在 `RetargetOptions.__init__()` 参数尾部添加：

```python
soft_repulsion=False,
soft_repulsion_settings=None,
joint_limits=False,
joint_limit_settings=None,
```

在原有初始化末尾添加：

```python
self.soft_repulsion = bool(soft_repulsion)
self.joint_limits = bool(joint_limits)
self.soft_repulsion_settings = None
self.joint_limit_settings = None

if self.soft_repulsion or self.joint_limits:
    if self.standard_skeleton != "DIRECT":
        raise RetargetError("新姿势通道当前仅支持 DIRECT 模式")

if self.soft_repulsion:
    supplied = soft_repulsion_settings or SoftRepulsionSettings()
    if not isinstance(supplied, SoftRepulsionSettings):
        raise RetargetError("soft_repulsion_settings 必须是 SoftRepulsionSettings")
    self.soft_repulsion_settings = deepcopy(supplied)
    self.soft_repulsion_settings.enabled = True
    try:
        validate_soft_repulsion_settings(self.soft_repulsion_settings)
    except ValueError as exc:
        raise RetargetError(str(exc)) from exc

if self.joint_limits:
    supplied = joint_limit_settings or JointLimitSettings()
    if not isinstance(supplied, JointLimitSettings):
        raise RetargetError("joint_limit_settings 必须是 JointLimitSettings")
    self.joint_limit_settings = deepcopy(supplied)
    self.joint_limit_settings.enabled = True
    try:
        validate_joint_limit_settings(self.joint_limit_settings)
    except ValueError as exc:
        raise RetargetError(str(exc)) from exc
```

关闭时不校验未启用功能的参数，也不构造其设置对象。

### 4. 开启路径的几何准备

给 `_prepare_retarget_geometry()` 增加仅内部使用的关键字参数：

```python
def _prepare_retarget_geometry(
    src,
    tgt,
    pairs,
    options,
    scene,
    *,
    armature_coordinates=False,
    extra_arm_chains=False,
):
```

在其 `head_world()` 中替换函数体：

```python
def head_world(arm, matrix, space):
    if armature_coordinates:
        return space.position(matrix.translation)
    return space.position(arm.matrix_world @ matrix.translation)
```

手臂选择条件替换为：

```python
if options.hand_ik or extra_arm_chains:
    wanted.extend(_IK_CHAIN_ROLES[2:])
```

`rest_head_world()` 替换为：

```python
def rest_head_world(arm, name, space):
    if armature_coordinates:
        return space.position(arm.data.bones[name].head_local)
    return space.position(arm.matrix_world @ arm.data.bones[name].head_local)
```

末端旋转矩阵准备替换为：

```python
if armature_coordinates:
    src_end_matrix = src_mats[src_names[2]]
    tgt_end_matrix = tgt_mats[tgt_names[2]]
else:
    src_end_matrix = src.matrix_world @ src_mats[src_names[2]]
    tgt_end_matrix = tgt.matrix_world @ tgt_mats[tgt_names[2]]
```

原重复骨名检查只在旧路径执行。开启路径使用独立的来源、目标集合，不能把两侧同名骨视为重复：

```python
if not armature_coordinates:
    seen = set()
    for _role, src_name, tgt_name in pairs:
        if src_name in seen or tgt_name in seen:
            raise RetargetError("映射中存在重复骨骼，无法准备 IK 几何。")
        seen.add(src_name)
        seen.add(tgt_name)
```

`_hips_translation_with_floor()` 增加同名关键字参数，当前来源位置替换为：

```python
if armature_coordinates:
    current = geometry.source_space.position(src_pose.head)
else:
    current = geometry.source_space.position(src.matrix_world @ src_pose.head)
```

`_sample_foot_motion()` 同样增加该关键字参数。仅替换其中两处采样：

```python
if armature_coordinates:
    hips_now = geometry.source_space.position(src_pose_hips.head)
else:
    hips_now = geometry.source_space.position(src.matrix_world @ src_pose_hips.head)
```

```python
if armature_coordinates:
    pos = geometry.source_space.position(foot_pose.head)
else:
    pos = geometry.source_space.position(src.matrix_world @ foot_pose.head)
```

其余 Floor、Planting 和采样公式保持原样。所有旧调用继续使用默认 `False`。

### 5. 开启路径预检与关节参考

新增：

```python
def _bone_depth(pose_bone):
    depth = 0
    parent = pose_bone.parent
    while parent is not None:
        depth += 1
        parent = parent.parent
    return depth


def _prepare_pose_channels(src, tgt, pairs, options, scene):
    if scene.render.fps <= 0 or scene.render.fps_base <= 0:
        raise RetargetError("姿势通道需要有效帧率")

    for column in (0, 1, 2):
        names = [pair[column] for pair in pairs]
        if len(names) != len(set(names)):
            raise RetargetError("姿势通道不接受重复 role 或骨骼")

    roles = {role: name for role, _source, name in pairs}
    needed = set()

    if options.soft_repulsion:
        needed.update((
            "hips", "chest",
            "upperarm_l", "forearm_l", "hand_l",
            "upperarm_r", "forearm_r", "hand_r",
        ))

    configurations = {}
    references = {}
    if options.joint_limits:
        for limits in options.joint_limit_settings.bones:
            if limits.role not in roles:
                raise RetargetError(f"关节限 role 未映射: {limits.role}")
            name = roles[limits.role]
            pose = tgt.pose.bones[name]
            if pose.parent is None:
                raise RetargetError(f"关节限骨没有实际父骨: {name}")
            configurations[name] = limits
            needed.add(limits.role)

            if options.reference == "CURRENT":
                table = (options.reference_data or {}).get("target_matrix", {})
                if name not in table:
                    raise RetargetError(f"当前参考缺少关节轴: {name}")
                matrix = Matrix(table[name])
            else:
                matrix = tgt.data.bones[name].matrix_local
            references[name] = matrix.to_quaternion().normalized()

    missing = needed - roles.keys()
    if missing:
        raise RetargetError("姿势通道缺少映射: " + ", ".join(sorted(missing)))

    if tgt.animation_data and tgt.animation_data.drivers:
        raise RetargetError("姿势通道不支持目标骨架驱动器")

    for name in roles.values():
        pose = tgt.pose.bones[name]
        if any(
            not constraint.mute and constraint.influence != 0.0
            for constraint in pose.constraints
        ):
            raise RetargetError(f"姿势通道不支持目标生效约束: {name}")
        if max(abs(value - 1.0) for value in pose.scale) > 1e-6:
            raise RetargetError(f"姿势通道不支持目标骨缩放: {name}")

    geometry = None
    if options.foot_ik or options.hand_ik or options.soft_repulsion:
        geometry = _prepare_retarget_geometry(
            src,
            tgt,
            pairs,
            options,
            scene,
            armature_coordinates=True,
            extra_arm_chains=options.soft_repulsion,
        )

        expected = []
        if options.foot_ik:
            expected.extend(_IK_CHAIN_ROLES[:2])
        if options.hand_ik or options.soft_repulsion:
            expected.extend(_IK_CHAIN_ROLES[2:])
        actual = {limb.roles for limb in geometry.limbs}
        if any(chain not in actual for chain in expected):
            raise RetargetError("姿势通道需要完整且非退化的启用链")

        for limb in geometry.limbs:
            upper, mid, end = (
                tgt.pose.bones[name] for name in limb.target_names
            )
            if mid.parent != upper or end.parent != mid:
                raise RetargetError("姿势通道需要直接两段父子链")
            if min(
                limb.target_upper_length,
                limb.target_lower_length,
            ) <= 1e-6:
                raise RetargetError("姿势通道链长度退化")

    return geometry, roles, configurations, references
```

只有开启时运行。两侧同名骨合法；各自内部重复非法。

### 6. 关节 pass 和骨架回写

新增：

```python
def _apply_target_joint_pass(
    tgt,
    configurations,
    references,
    initial_rotations,
    settings,
    final,
):
    if not configurations:
        return

    bodies = {}
    for name in configurations:
        pose = tgt.pose.bones[name]
        while pose is not None:
            if pose.name not in bodies:
                limits = configurations.get(pose.name)
                if limits is None:
                    limits = BoneAngleLimits(rotation_stiffness=1.0)
                    inverse_mass = 0.0
                else:
                    inverse_mass = 1.0
                bodies[pose.name] = JointBody(
                    rotation=pose.matrix.to_quaternion().normalized(),
                    initial_rotation=initial_rotations[pose.name].copy(),
                    settings=limits,
                    inverse_mass=inverse_mass,
                )
            pose = pose.parent

    names = sorted(
        configurations,
        key=lambda name: (_bone_depth(tgt.pose.bones[name]), name),
        reverse=not final,
    )
    joints = tuple(
        JointRotationConstraint(
            bodies[tgt.pose.bones[name].parent.name],
            bodies[name],
            references[name],
        )
        for name in names
    )
    run_rotation_limit_pass(
        joints, final, settings.max_angle_degrees
    )

    for name in sorted(
        configurations,
        key=lambda name: (_bone_depth(tgt.pose.bones[name]), name),
    ):
        pose = tgt.pose.bones[name]
        orient = normalize_rotation(
            bodies[name].rotation
        ).to_matrix()
        rest = _rot3(pose.bone.matrix_local)
        parent = pose.parent
        if parent is None:
            basis = rest.inverted() @ orient
        else:
            basis = (
                rest.inverted()
                @ _rot3(parent.bone.matrix_local)
                @ _rot3(parent.matrix).inverted()
                @ orient
            )
        pose.rotation_mode = "QUATERNION"
        pose.rotation_quaternion = basis.to_quaternion()
        bpy.context.view_layer.update()
```

这里的 `inverse_mass=0/1` 只表达插件通道的固定/可旋转 body，不冒充 PBIK 骨架质量计算。

只写旋转，不写骨长、location 或 rest。实际父骨更新后再计算子骨 basis。

### 7. 统一 Goal 和两骨入口

新增：

```python
def _build_pose_channel_goals(
    src,
    tgt,
    geometry,
    options,
    states,
    speeds,
    pelvis_delta,
    dt,
):
    goals = {}
    if geometry is None:
        return goals

    for limb in geometry.limbs:
        role = limb.roles[2]
        source_start = src.pose.bones[limb.source_names[0]]
        source_end = src.pose.bones[limb.source_names[2]]
        target_start = tgt.pose.bones[limb.target_names[0]]
        target_end = tgt.pose.bones[limb.target_names[2]]
        source_space = geometry.source_space
        target_space = geometry.target_space

        if role in {"hand_l", "hand_r"} and not options.hand_ik:
            goal = IKGoal(
                target_space.position(target_end.head),
                target_space.rotation(target_end.matrix),
            )
        else:
            source_end_position = source_space.position(source_end.head)
            goal = generate_limb_goal(
                source_space.position(source_start.head),
                source_end_position,
                source_space.rotation(source_end.matrix),
                target_space.position(target_start.head),
                limb,
                pelvis_delta,
            )
            if role in {"foot_l", "foot_r"}:
                goal.position = constrain_goal_floor(
                    goal.position,
                    source_end_position.z,
                    limb.height_offset,
                    options.foot_ik_settings,
                )
                state = states.get(role)
                if state is not None:
                    goal.position = plant_goal(
                        goal.position,
                        speeds.get(role, -1.0),
                        state,
                        dt,
                        options.foot_ik_settings,
                    )

        goals[role] = goal
    return goals


def _solve_pose_channel_chain(tgt, space, limb, goal, pole_goal):
    upper_name, mid_name, end_name = limb.target_names
    root = space.position(tgt.pose.bones[upper_name].head)
    pole = (
        pole_goal
        if pole_goal is not None
        else space.position(tgt.pose.bones[mid_name].head)
    )
    if (pole - root).length < 1e-6:
        pole = limb.reference_pole

    knee, reachable = _two_bone(
        root,
        limb.target_upper_length,
        limb.target_lower_length,
        goal.position,
        pole,
        limb.reference_pole - root,
    )
    _aim_joint(tgt, upper_name, mid_name, space, knee - root)
    bpy.context.view_layer.update()

    knee_now = space.position(tgt.pose.bones[mid_name].head)
    _aim_joint(tgt, mid_name, end_name, space, reachable - knee_now)
    bpy.context.view_layer.update()

    _write_end_rotation(tgt, end_name, space, goal.rotation)
    bpy.context.view_layer.update()


def _apply_pose_channels(
    src,
    tgt,
    geometry,
    target_roles,
    configurations,
    references,
    options,
    states,
    speeds,
    pelvis_delta,
    dt,
):
    initial_rotations = {
        pose.name: pose.matrix.to_quaternion().normalized()
        for pose in tgt.pose.bones
    }
    goals = _build_pose_channel_goals(
        src, tgt, geometry, options,
        states, speeds, pelvis_delta, dt,
    )
    poles = {}
    if options.soft_repulsion:
        poles = _correct_arm_goals(
            tgt, geometry, goals, dt,
            options.soft_repulsion_settings,
            target_roles,
        )

    iterations = (
        options.joint_limit_settings.iterations
        if options.joint_limits else 1
    )
    for _iteration in range(iterations):
        if geometry is not None:
            for limb in geometry.limbs:
                role = limb.roles[2]
                _solve_pose_channel_chain(
                    tgt,
                    geometry.target_space,
                    limb,
                    goals[role],
                    poles.get(role),
                )
        if options.joint_limits:
            _apply_target_joint_pass(
                tgt, configurations, references,
                initial_rotations,
                options.joint_limit_settings,
                False,
            )

    if options.joint_limits and iterations > 0:
        _apply_target_joint_pass(
            tgt, configurations, references,
            initial_rotations,
            options.joint_limit_settings,
            True,
        )
```

`iterations=0` 不运行本新求解通道，保持与 PBIK 零轮循环相同的调度含义。需要在 UI 明示零轮不会执行新通道中的 IK/限位。

这段组合调度不是完整 PBIK 求解器等价声明。尤其不能据此保证软推、Goal 到达和多轴限位同时成立。

### 8. 开启路径的 Action 所有权和失败恢复

现有代码会调用 `animation_data_clear()`，并移除旧 NLA。新开启路径不能沿用这些破坏性步骤。

新增以下函数：

```python
def _capture_channel_bake_state(src, tgt, scene):
    objects = []
    for obj in (src, tgt):
        anim = obj.animation_data
        objects.append((
            obj,
            anim is not None,
            anim.action if anim else None,
            getattr(anim, "action_slot", None) if anim else None,
            anim.use_nla if anim else None,
            tuple(
                (pose.name, pose.rotation_mode, pose.matrix_basis.copy())
                for pose in obj.pose.bones
            ),
        ))
    return {
        "objects": objects,
        "frame": scene.frame_current,
        "start": scene.frame_start,
        "end": scene.frame_end,
        "actions": [],
        "tracks": [],
        "properties": {
            key: (key in tgt, tgt.get(key))
            for key in ("hr_retarget_from", "hr_actions")
        },
    }


def _new_channel_action(target, name, state):
    action = bpy.data.actions.new(name)
    state["actions"].append(action)
    action.use_fake_user = True
    slots = getattr(action, "slots", None)
    if slots is not None:
        try:
            slots.new(id_type="OBJECT", name=target.name)
        except TypeError:
            slots.new("OBJECT", target.name)
    _assign_action(target, action)
    return action


def _stash_channel_actions(target, actions, state):
    anim = target.animation_data or target.animation_data_create()
    for action in actions:
        track = anim.nla_tracks.new()
        state["tracks"].append((target, track))
        track.name = action.name
        strip = track.strips.new(
            action.name[:60], int(action.frame_range[0]), action
        )
        slots = getattr(action, "slots", None)
        if slots and hasattr(strip, "action_slot"):
            strip.action_slot = slots[0]
    anim.use_nla = False


def _restore_channel_bake_state(tgt, scene, state):
    for obj, track in reversed(state["tracks"]):
        if obj.animation_data is not None:
            obj.animation_data.nla_tracks.remove(track)

    for obj, had_anim, action, slot, use_nla, _poses in state["objects"]:
        if not had_anim:
            if obj.animation_data is not None:
                obj.animation_data_clear()
        else:
            anim = obj.animation_data or obj.animation_data_create()
            anim.action = action
            if hasattr(anim, "action_slot") and slot is not None:
                anim.action_slot = slot
            anim.use_nla = use_nla

    for action in reversed(state["actions"]):
        bpy.data.actions.remove(action, do_unlink=True)

    for key, (existed, value) in state["properties"].items():
        if existed:
            tgt[key] = value
        elif key in tgt:
            del tgt[key]

    scene.frame_start = state["start"]
    scene.frame_end = state["end"]
    scene.frame_set(state["frame"])

    for obj, _had_anim, _action, _slot, _use_nla, poses in state["objects"]:
        for name, mode, basis in poses:
            pose = obj.pose.bones.get(name)
            if pose is not None:
                pose.rotation_mode = mode
                pose.matrix_basis = basis
    bpy.context.view_layer.update()
```

只删除本次明确记录的 Action 和 track。原 Action 和 NLA 数据块保持存在。

将原 `bake_retarget()` 改名为 `_bake_retarget()`，增加参数 `channel_state=None`。新增公共入口：

```python
def bake_retarget(src, tgt, options=None):
    options = options or RetargetOptions()
    enabled = options.soft_repulsion or options.joint_limits
    if not enabled:
        return _bake_retarget(src, tgt, options)

    if (
        src is None or tgt is None
        or src.type != "ARMATURE"
        or tgt.type != "ARMATURE"
        or src == tgt
    ):
        raise RetargetError("姿势通道需要两个不同的骨架")

    scene = bpy.context.scene
    state = _capture_channel_bake_state(src, tgt, scene)
    try:
        return _bake_retarget(src, tgt, options, state)
    except BaseException:
        _restore_channel_bake_state(tgt, scene, state)
        raise
```

### 9. `_bake_retarget()` 的准确插入点

以下均为原函数中的局部替换，其他分支保留原码。

在原 `ik_geometry` 准备位置：

```python
use_channels = channel_state is not None
channel_roles = {}
channel_configurations = {}
channel_references = {}

ik_geometry = None
if use_channels:
    (
        ik_geometry,
        channel_roles,
        channel_configurations,
        channel_references,
    ) = _prepare_pose_channels(
        src, tgt, pairs, options, bpy.context.scene
    )
elif use_foot_ik or use_hand_ik:
    ik_geometry = _prepare_retarget_geometry(
        src, tgt, pairs, options, bpy.context.scene
    )
```

原清除动画位置：

```python
if not use_channels and tgt.animation_data:
    tgt.animation_data_clear()
if use_channels:
    src.animation_data_create().use_nla = False
    tgt.animation_data_create().use_nla = False
```

原新建 Action 位置：

```python
if use_channels:
    target_action = _new_channel_action(
        tgt, f"{tgt.name}_{action.name}", channel_state
    )
else:
    target_action = _new_target_action(
        tgt, f"{tgt.name}_{action.name}"
    )
```

开启路径的脚采样传入：

```python
speeds = _sample_foot_motion(
    src,
    action,
    (start, end),
    ik_geometry,
    ik_settings,
    in_place,
    scene,
    armature_coordinates=use_channels,
)
```

开启路径的髋部 Floor 调用传入：

```python
pelvis_delta = _hips_translation_with_floor(
    src,
    tgt,
    ik_geometry,
    ik_settings,
    in_place,
    armature_coordinates=use_channels,
)
```

在原 `apply_contact_ik()` 所在位置，先按原码生成 `frame_speeds`，再分支：

```python
if use_channels:
    _apply_pose_channels(
        src,
        tgt,
        ik_geometry,
        channel_roles,
        channel_configurations,
        channel_references,
        options,
        plant_states,
        frame_speeds,
        pelvis_delta,
        dt,
    )
elif ik_geometry is not None:
    apply_contact_ik(
        src, tgt, ik_geometry, ik_settings,
        plant_states, frame_speeds, pelvis_delta, dt,
    )
```

注意：`frame_speeds={}` 应在两个分支之前定义，不能仍只在 `ik_geometry is not None` 内定义。关节限可以在没有 IK 几何时单独开启。

原成功后的 NLA 存储位置：

```python
remaining_actions = [
    action for index, (action, _start, _end) in enumerate(baked)
    if index != selected_index
]
if use_channels:
    _stash_channel_actions(
        tgt, remaining_actions, channel_state
    )
else:
    _stash_nla(tgt, remaining_actions)
```

关键帧写入仍放在 `_apply_pose_channels()` 之后。不得在 FinalPass 之后再次调用末端旋转写入，否则会覆盖限位。

### 10. `__init__.py`：每骨配置

增加导入：

```python
from .joint_limits import (
    AxisAngleLimit,
    BoneAngleLimits,
    JointLimitSettings,
    LimitType,
)
```

在 `HRSettings` 前新增：

```python
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
```

`HRSettings` 添加：

```python
use_joint_limits: BoolProperty(
    name="关节角度限", default=False
)
joint_iterations: IntProperty(
    name="求解轮数", default=20, min=0, max=1000
)
joint_max_angle_degrees: FloatProperty(
    name="单轮增量上限（度）",
    default=30.0,
    min=0.0,
    max=45.0,
)
joint_limit_bones: CollectionProperty(type=HRJointLimitItem)
```

`45°` 与 PBIK 参数的编辑器 `ClampMax` 一致；数值核仍使用传入值计算，不偷偷 clamp。

在 `_options_from_settings()` 中添加：

```python
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
```

面板添加：

```python
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
```

将 `HRJointLimitItem` 放在 `CLASSES` 中 `HRSettings` 之前；两个 Operator 放在面板之前。继续使用现有正向注册、反向注销，不新增全局回调。

### 11. 数值测试

新增 `tests/test_joint_limits.py`：

```python
import math
import unittest

from mathutils import Quaternion

from humanoid_retarget.joint_limits import (
    AxisAngleLimit,
    BoneAngleLimits,
    JointBody,
    JointRotationConstraint,
    LimitType,
    decompose_rotation_angles,
    run_rotation_limit_pass,
    update_joint_limits,
)


def make_joint(limits, degrees=0.0, axis=(0.0, 0.0, 1.0)):
    identity = Quaternion((1.0, 0.0, 0.0, 0.0))
    parent = JointBody(
        identity.copy(),
        identity.copy(),
        BoneAngleLimits(rotation_stiffness=1.0),
        inverse_mass=0.0,
    )
    child = JointBody(
        Quaternion(axis, math.radians(degrees)),
        identity.copy(),
        limits,
    )
    return JointRotationConstraint(parent, child, identity.copy())


class JointLimitTests(unittest.TestCase):
    def test_free_does_not_repair_range(self):
        limits = BoneAngleLimits(
            x=AxisAngleLimit(LimitType.FREE, 10.0, -10.0)
        )
        joint = make_joint(limits, 50.0)
        before = tuple(joint.child.rotation)
        update_joint_limits(joint, True, 30.0)
        self.assertEqual(tuple(joint.child.rotation), before)
        self.assertEqual(limits.x.maximum, -10.0)

    def test_reversed_range_becomes_min_plus_one(self):
        limits = BoneAngleLimits(
            x=AxisAngleLimit(LimitType.LIMITED, 10.0, -10.0)
        )
        update_joint_limits(make_joint(limits), True, 30.0)
        self.assertEqual(limits.x.maximum, 11.0)

    def test_two_degrees_is_limited(self):
        limits = BoneAngleLimits(
            x=AxisAngleLimit(LimitType.LOCKED),
            y=AxisAngleLimit(LimitType.LOCKED),
            z=AxisAngleLimit(LimitType.LIMITED, 0.0, 2.0),
        )
        joint = make_joint(limits, 20.0)
        run_rotation_limit_pass((joint,), True, 30.0)
        angle = decompose_rotation_angles(joint)[0][2]
        self.assertAlmostEqual(angle, 2.0, places=3)

    def test_less_than_two_degrees_is_fixed(self):
        limits = BoneAngleLimits(
            x=AxisAngleLimit(LimitType.LOCKED),
            y=AxisAngleLimit(LimitType.LOCKED),
            z=AxisAngleLimit(LimitType.LIMITED, 10.0, 11.0),
        )
        joint = make_joint(limits, 20.0)
        run_rotation_limit_pass((joint,), True, 30.0)
        self.assertAlmostEqual(abs(joint.child.rotation.w), 1.0, places=5)

    def test_hinge_final_limit(self):
        limits = BoneAngleLimits(
            x=AxisAngleLimit(LimitType.LOCKED),
            y=AxisAngleLimit(LimitType.LOCKED),
            z=AxisAngleLimit(LimitType.LIMITED, -30.0, 30.0),
        )
        joint = make_joint(limits, 60.0)
        run_rotation_limit_pass((joint,), True, 0.0)
        angle = decompose_rotation_angles(joint)[0][2]
        self.assertAlmostEqual(angle, 30.0, places=3)

    def test_y_angle_has_source_negative_sign(self):
        joint = make_joint(
            BoneAngleLimits(), 30.0, (0.0, 1.0, 0.0)
        )
        angle = decompose_rotation_angles(joint)[0][1]
        self.assertAlmostEqual(angle, -30.0, places=3)

    def test_single_locked_axis_has_no_extra_branch(self):
        limits = BoneAngleLimits(
            x=AxisAngleLimit(LimitType.LOCKED)
        )
        joint = make_joint(limits, 30.0, (1.0, 0.0, 0.0))
        before = tuple(joint.child.rotation)
        update_joint_limits(joint, True, 30.0)
        self.assertEqual(tuple(joint.child.rotation), before)
```

执行：

```powershell
blender --background --factory-startup --python-exit-code 1 --python tests/run_pose_channel_tests.py -- test_joint_limits.py
```

要求 `selected=7`。先确认缺少模块的 RED，再加入最小实现得到 GREEN。

进一步的 Contract 必须加入：

- 非零父旋转、非零初始父子旋转和不同 bone roll。
- 普通阶段双方 stiffness 与增量上限。
- 180° 反向轴和投影退化。
- 多轴缓存分解语义。
- FinalPass 的子链锁定分支。
- UE 同输入数值样本对照。

## 强制约束

- 两个开关同时关闭，调用原烘焙主体的旧分支。
- 不对关闭路径的旋转做额外归一化。
- 不改变关闭路径的 MotionSpace 调用、Action 或 NLA 行为。
- 新开启路径预检必须在新建 Action 前完成。
- 每帧 `InitialRotation` 在 FK/髋部处理后取一次，不能每轮刷新。
- 普通限位叶到根，FinalPass 根到叶。
- FinalPass 后不再次写 Goal 旋转。
- 无全局 body、Action、参考或速度缓存。
- 失败删除只限本作业登记对象。
- 所有临时诊断默认不保留；移除后必须复验。

## 验收标准

| 验证门 | 必须覆盖 |
|---|---|
| Static | 无 bpy 数值依赖；命名、依赖、所有权和关闭旁路审查 |
| Contract | 数值分支、默认值、乘法顺序、UE 同输入对照 |
| Regression | 两开关关闭，姿势和关键帧 float 编码逐位一致 |
| Runtime | 仅软推、仅限位、两者同时；REST/CURRENT、KEEP/IN_PLACE |
| Failure | 中途异常恢复原 Action/slot、NLA、pose、场景帧；仅删除本次对象 |
| Skeleton | 在 FinalPass 后读取实际手/肘位置和关节角，不使用中间 Goal 代替 |
| Visual | 检查真实动作和网格 |
| Cleanup | 临时诊断清理、差异核对、聚焦与回归复验 |

关闭逐位一致应比较相同 Blender 版本、相同 `.blend` 输入和相同配置下的矩阵、关键帧值，使用 float 的二进制编码。不能用 `allclose` 代替。

回归命令：

```powershell
blender --background --factory-startup --python-exit-code 1 --python tests/run_retarget_test.py
```

Blender 4.2 与较新 slotted Actions 版本分别执行。不能把较新版本通过替代 4.2 验证。

本次仅完成设计、实施代码编写和源码静态核对。代码未应用；测试、失败恢复、Runtime、Visual 和正式验收均为 `NotRun`。多轴收敛、既有 FK 反转修复和严格无穿插仍分别为 `Unproven`、`Blocked`、`Blocked`。

## 禁止事项

- 用 `to_euler()` clamp 替换 PBIK 投影分解。
- 交换倒置的 Min/Max。
- 将 `<2°` 改为 `<=2°`。
- 添加源码没有的单轴 Locked 修正。
- 在每轴修正后重新分解。
- 给 FinalPass 添加 stiffness 混合或 MaxAngle cap。
- 永久固定 `InitialRotation` 后仍宣称完整 UE 行为等价。
- 暴露未实现的质量、PreferredAngles、SubIterations 或 PositionStiffness。
- 把旋转限位称为自碰撞求解器。
- 宣称实现或验收已经完成。
DONE_EXIT=0
