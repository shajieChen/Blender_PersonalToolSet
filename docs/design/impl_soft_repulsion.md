# impl_soft_repulsion.md

```text
RED -> 纯数值核 -> 开启分支接线 -> 回归 -> 清理复验
```

目标文件：`H:\Blender_Plugin\docs\design\impl_soft_repulsion.md`  
状态：实施方案；以下为拟加入代码，尚未应用、运行或验收。

## 目标

实现 `design_soft_repulsion.md` 中明确限定的 Sphere 软力核和 Verlet Goal 修正。

不添加改变 UE 语义的强度归一化、方向兜底、位移 cap 或硬投影。

本功能和关节限共用烘焙接线。公共接线只实施一次，见 `impl_joint_limits.md` 的实施步骤。

## 修改范围

| 文件 | 函数或位置 | 修改 |
|---|---|---|
| 新增 `humanoid_retarget/soft_repulsion.py` | 下方全部定义 | 纯数值实现 |
| `humanoid_retarget/retarget.py` | `RetargetOptions.__init__` | 新增关闭开关与设置快照 |
| 同文件 | `_correct_arm_goals` | 修正手 Goal 和 forearm pole |
| `humanoid_retarget/__init__.py` | `HRSettings` | 新增 UI 参数 |
| 同文件 | `_options_from_settings` | 仅开启时构造设置 |
| 同文件 | `HR_PT_panel.draw` | 显示参数 |
| 新增 `tests/test_soft_repulsion.py` | 数值测试 | 独立预期值 |
| 新增 `tests/run_pose_channel_tests.py` | 测试入口 | 保证 `selected > 0` |

不修改骨架 rest、映射算法、导出算法或现有关闭路径的公式。

## 实施步骤

### 1. 材料读取和编译前检查

已读材料：

- 用户提供的证据档和四个代码输入。
- 当前完整 `design_foot_ik.md`。
- 当前烘焙、UI 和两跳参数传递位置。
- `CRSimSoftCollision.cpp`、RigVM 积分原文。
- UE 线段最近点原文。

复用这些材料。仅在文件变化、证据冲突或执行上下文缺失时重读对应范围。

源码核验已用一个并行批次完成软力和关节限探索。执行时不重复派发相同检索。

Python 无 C++ 编译步骤。适用硬门是：

1. Python AST/导入检查。
2. `mathutils` API 检查。
3. Blender 后台数值测试。
4. 烘焙回归和真实动作运行。

### 2. 新增 `soft_repulsion.py`

```python
from __future__ import annotations

import math
from dataclasses import dataclass

from mathutils import Vector


_SMALL_NUMBER = 1e-8


@dataclass
class SoftRepulsionSettings:
    enabled: bool = False
    minimum_distance_m: float = 0.10
    maximum_distance_m: float = 0.20
    coefficient: float = 64.0
    inverted: bool = False
    mass: float = 1.0
    linear_damping: float = 0.01
    torso_radius_m: float = 0.15
    hand_radius_m: float = 0.025
    forearm_radius_m: float = 0.035


def validate_soft_repulsion_settings(
    settings: SoftRepulsionSettings,
) -> None:
    values = (
        settings.minimum_distance_m,
        settings.maximum_distance_m,
        settings.coefficient,
        settings.mass,
        settings.linear_damping,
        settings.torso_radius_m,
        settings.hand_radius_m,
        settings.forearm_radius_m,
    )
    if not all(math.isfinite(value) for value in values):
        raise ValueError("soft repulsion parameters must be finite")
    if any(value < 0.0 for value in (
        settings.torso_radius_m,
        settings.hand_radius_m,
        settings.forearm_radius_m,
    )):
        raise ValueError("collision proxy radii must be non-negative")


def closest_point_on_segment(
    point: Vector,
    start: Vector,
    end: Vector,
) -> Vector:
    segment = end - start
    to_point = point - start
    dot1 = to_point.dot(segment)
    if dot1 <= 0.0:
        return start.copy()
    dot2 = segment.dot(segment)
    if dot2 <= dot1:
        return end.copy()
    return start + segment * (dot1 / dot2)


def _safe_normal(vector: Vector) -> Vector:
    squared_length = vector.length_squared
    if squared_length == 1.0:
        return vector.copy()
    if squared_length < _SMALL_NUMBER:
        return Vector((0.0, 0.0, 0.0))
    return vector / math.sqrt(squared_length)


def sphere_force(
    position_m: Vector,
    center_m: Vector,
    size_m: float,
    settings: SoftRepulsionSettings,
) -> Vector:
    if settings.mass <= _SMALL_NUMBER:
        return Vector((0.0, 0.0, 0.0))

    direction = (position_m - center_m) * 100.0
    distance = max(direction.length - size_m * 100.0, 0.0)

    if distance > _SMALL_NUMBER:
        direction = _safe_normal(direction)

    if settings.inverted:
        direction = -direction

    minimum = settings.minimum_distance_m * 100.0
    maximum = settings.maximum_distance_m * 100.0

    if maximum <= minimum:
        if distance < minimum:
            falloff = 0.0 if settings.inverted else 1.0
        else:
            falloff = 1.0 if settings.inverted else 0.0
    else:
        ratio = 0.0
        if distance < minimum:
            ratio = 1.0
        elif distance < maximum:
            ratio = (distance - minimum) / (maximum - minimum)
            ratio = 1.0 - min(1.0, max(0.0, ratio))
        if settings.inverted:
            ratio = 1.0 - ratio
        falloff = ratio * ratio * ratio

    return direction * (falloff * settings.coefficient * 0.01)


def integrate_verlet(
    position: Vector,
    velocity: Vector,
    force: Vector,
    mass: float,
    linear_damping: float,
    blend: float,
    dt: float,
):
    if mass <= _SMALL_NUMBER:
        return position.copy(), velocity.copy()

    weight = min(1.0, max(0.0, blend * dt))
    damping = min(1.0, max(0.0, 1.0 - linear_damping))
    new_velocity = (
        velocity + (force / mass - velocity) * weight
    ) * damping
    return position + new_velocity * dt, new_velocity


def repel_capsule_point(
    position: Vector,
    axis_start: Vector,
    axis_end: Vector,
    point_radius_m: float,
    dt: float,
    settings: SoftRepulsionSettings,
) -> Vector:
    if not settings.enabled:
        return position.copy()

    center = closest_point_on_segment(
        position, axis_start, axis_end
    )
    size = settings.torso_radius_m + point_radius_m
    force = sphere_force(position, center, size, settings)
    result, _velocity = integrate_verlet(
        position,
        Vector((0.0, 0.0, 0.0)),
        force,
        settings.mass,
        settings.linear_damping,
        1.0,
        dt,
    )
    return result
```

关键语义：

- `sphere_force()` 是 UE 数值核，不检查插件总开关。
- 内部厘米计算保留 Sphere 内部未归一化方向的语义。
- `maximum <= minimum` 不调用 CubicEaseIn。
- `repel_capsule_point()` 是离线输入组合；不是硬碰撞求解。
- 不保存跨帧速度，不引入全局缓存。

### 3. `retarget.py`：软推 Goal 接线

增加导入：

```python
from .soft_repulsion import (
    SoftRepulsionSettings,
    repel_capsule_point,
    validate_soft_repulsion_settings,
)
```

新增函数：

```python
def _correct_arm_goals(
    tgt,
    geometry,
    goals,
    dt,
    settings,
    target_roles,
):
    space = geometry.target_space
    axis_start = space.position(
        tgt.pose.bones[target_roles["hips"]].head
    )
    axis_end = space.position(
        tgt.pose.bones[target_roles["chest"]].head
    )
    poles = {}

    for limb in geometry.limbs:
        if limb.roles[2] not in {"hand_l", "hand_r"}:
            continue

        end_role = limb.roles[2]
        goal = goals[end_role]
        goal.position = repel_capsule_point(
            goal.position,
            axis_start,
            axis_end,
            settings.hand_radius_m,
            dt,
            settings,
        )

        mid_pose = tgt.pose.bones[limb.target_names[1]]
        poles[end_role] = repel_capsule_point(
            space.position(mid_pose.head),
            axis_start,
            axis_end,
            settings.forearm_radius_m,
            dt,
            settings,
        )

    return poles
```

调用位置由公共帧入口控制：Goal 生成后、两骨求解前。关闭时不调用本函数。

### 4. `__init__.py`：UI

增加导入：

```python
from .soft_repulsion import SoftRepulsionSettings
```

在 `HRSettings` 添加：

```python
use_soft_repulsion: BoolProperty(
    name="软斥力",
    default=False,
)
soft_minimum_distance_m: FloatProperty(
    name="完全作用距离（米）",
    default=0.10,
)
soft_maximum_distance_m: FloatProperty(
    name="作用结束距离（米）",
    default=0.20,
)
soft_coefficient: FloatProperty(
    name="斥力系数",
    default=64.0,
)
soft_inverted: BoolProperty(
    name="反转力场",
    default=False,
)
soft_torso_radius_m: FloatProperty(
    name="躯干半径（米）",
    default=0.15,
    min=0.0,
)
soft_hand_radius_m: FloatProperty(
    name="手部代理半径（米）",
    default=0.025,
    min=0.0,
)
soft_forearm_radius_m: FloatProperty(
    name="前臂代理半径（米）",
    default=0.035,
    min=0.0,
)
```

这些字段明确标米，不使用可能让用户误读场景单位的自动长度显示。

在 `_options_from_settings()` 的 `RetargetOptions(...)` 调用中添加：

```python
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
```

在 `HR_PT_panel.draw()` 的烘焙设置区域添加：

```python
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
```

不增加 timer、handler、绘制回调或后台采样。

### 5. 数值 RED/GREEN

新增 `tests/test_soft_repulsion.py`：

```python
import unittest

from mathutils import Vector

from humanoid_retarget.soft_repulsion import (
    SoftRepulsionSettings,
    closest_point_on_segment,
    integrate_verlet,
    sphere_force,
)


class SoftRepulsionTests(unittest.TestCase):
    def test_cubic_midpoint(self):
        settings = SoftRepulsionSettings()
        force = sphere_force(
            Vector((0.25, 0.0, 0.0)),
            Vector((0.0, 0.0, 0.0)),
            0.10,
            settings,
        )
        self.assertAlmostEqual(force.x, 0.08, places=6)

    def test_inside_keeps_raw_direction(self):
        force = sphere_force(
            Vector((0.05, 0.0, 0.0)),
            Vector((0.0, 0.0, 0.0)),
            0.10,
            SoftRepulsionSettings(),
        )
        self.assertAlmostEqual(force.x, 3.2, places=5)

    def test_center_has_zero_force(self):
        force = sphere_force(
            Vector((0.0, 0.0, 0.0)),
            Vector((0.0, 0.0, 0.0)),
            0.10,
            SoftRepulsionSettings(),
        )
        self.assertEqual(tuple(force), (0.0, 0.0, 0.0))

    def test_equal_range_uses_strict_boundary(self):
        settings = SoftRepulsionSettings(
            minimum_distance_m=0.10,
            maximum_distance_m=0.10,
        )
        force = sphere_force(
            Vector((0.10, 0.0, 0.0)),
            Vector((0.0, 0.0, 0.0)),
            0.0,
            settings,
        )
        self.assertEqual(tuple(force), (0.0, 0.0, 0.0))

    def test_inverted_far_field(self):
        settings = SoftRepulsionSettings(inverted=True)
        force = sphere_force(
            Vector((1.0, 0.0, 0.0)),
            Vector((0.0, 0.0, 0.0)),
            0.0,
            settings,
        )
        self.assertAlmostEqual(force.x, -0.64, places=6)

    def test_degenerate_segment(self):
        start = Vector((1.0, 2.0, 3.0))
        result = closest_point_on_segment(
            Vector((8.0, 9.0, 10.0)), start, start
        )
        self.assertEqual(tuple(result), tuple(start))

    def test_verlet_formula(self):
        position, velocity = integrate_verlet(
            Vector((0.0, 0.0, 0.0)),
            Vector((0.0, 0.0, 0.0)),
            Vector((0.08, 0.0, 0.0)),
            1.0,
            0.01,
            1.0,
            0.1,
        )
        self.assertAlmostEqual(velocity.x, 0.00792, places=7)
        self.assertAlmostEqual(position.x, 0.000792, places=8)
```

新增公共测试入口 `tests/run_pose_channel_tests.py`：

```python
import pathlib
import sys
import types
import unittest

root = pathlib.Path(__file__).resolve().parents[1]
package = types.ModuleType("humanoid_retarget")
package.__path__ = [str(root / "humanoid_retarget")]
sys.modules["humanoid_retarget"] = package

arguments = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
pattern = arguments[0] if arguments else "test_*repulsion.py"
suite = unittest.defaultTestLoader.discover(
    str(root / "tests"), pattern=pattern
)
selected = suite.countTestCases()
print("selected =", selected)
if selected == 0:
    raise RuntimeError("no pose channel tests selected")

result = unittest.TextTestRunner(verbosity=2).run(suite)
if not result.wasSuccessful():
    raise RuntimeError("pose channel tests failed")
```

执行命令，前提是对应版本的 `blender` 已在 PATH：

```powershell
blender --background --factory-startup --python-exit-code 1 --python tests/run_pose_channel_tests.py -- test_soft_repulsion.py
```

先只加入测试，确认导入缺失产生可归因 RED，`selected=7`。再加入最小数值实现，要求退出码 0，七项全部通过。

这些预期值能检查关键分支，但不能替代 UE 同输入样本对照。

## 强制约束

- 数值模块不导入 `bpy`、`retarget` 或插件 UI。
- 新代码不添加注释和 docstring。
- UI 默认关闭；关闭不构造新设置或作业状态。
- 所有 `bpy` 读写在主线程。
- 骨长、rest、来源动画数据块保持原有所有权。
- 新通道的失败恢复见公共烘焙接线。
- 不执行 Git 暂存、提交、推送或清理。
- 本次新增临时诊断清单：无。
- 执行时若临时增加日志、探针、计数或脚本，逐项记录、保存证据后移除，再复验。

## 验收标准

| 门 | 要求 |
|---|---|
| Static | 数学核无 bpy 依赖；关闭入口完整旁路 |
| Contract | 七项测试通过；补充 Min/Max 倒置、质量边界和 UE 对照样本 |
| Regression | 原关闭配置的姿势矩阵、关键帧数值逐位一致 |
| Runtime | REST/CURRENT、KEEP/IN_PLACE、左右手、不可达 Goal |
| Visual | 检查实际网格；不得用 Goal 外移替代 |
| Cleanup | 临时诊断移除后重跑聚焦与回归 |

现有回归入口：

```powershell
blender --background --factory-startup --python-exit-code 1 --python tests/run_retarget_test.py
```

要求退出码 0，并出现 `RETARGET_TEST_OK`。Blender 4.2 和使用 slotted Actions 的较新版本分别验证。Action slots 的版本差异应按 [Blender 官方迁移说明](https://developer.blender.org/docs/release_notes/4.4/upgrading/slotted_actions/) 处理。

当前所有执行结果均为 `NotRun`。

## 禁止事项

- 把 `64` 当成 64 米或直接位移。
- 把 Sphere 内部方向改成单位方向。
- 在轴心自行添加备用推出方向。
- 交换 Min/Max。
- 每轮关节迭代重复软推。
- 宣称软推保证骨段或网格无穿插。
- 将未经移植的硬投影包装成 UE 等价实现。

---
