# impl_foot_ik.md

# Blender 重定向脚部 IK 实施档

日期：2026-10-14  
配套：`design_foot_ik.md`。  
状态：实施计划；未修改插件。

执行方式：主代理修改和验证；子代理仅做必要的只读探索。  
技术栈：Blender 4.2+、Python、`bpy`、`mathutils`。

```text
先写可归因测试
      |
坐标/参考 -> 数值公式 -> IK 写姿势 -> 烘焙接线
      |
版本兼容 -> 聚焦/回归 -> 真实动作 -> 清理/复验
```

## 目标

在现有 FK 后增加正确的链比例 Goal、髋部高度映射、Floor 和 SpeedPlanting。

“等价”指设计档列出的 UE 参数子集及分支语义。几何速度输入和两骨求解属于明确的 Blender 实现边界。

不承诺 UE 与 `mathutils` 逐位一致；两者浮点表示不同。数值验证使用长度、角度和速度容差。

## 修改范围

### 文件清单

| 文件 | 修改 |
|---|---|
| `humanoid_retarget/motion_space.py` | 新增米制空间转换 |
| `humanoid_retarget/foot_ik.py` | 新增参考值、设置和数值函数 |
| `humanoid_retarget/ik.py` | 替换 Goal 算法、关节瞄准和末端旋转 |
| `humanoid_retarget/retarget.py` | 新参数、固定参考、来源采样、帧调用和失败恢复 |
| `humanoid_retarget/__init__.py` | 新设置、UI、设置传递 |
| `humanoid_retarget/pipeline.py` | 最终跳传递新设置 |
| `tests/run_foot_ik_test.py` | 新增聚焦测试 |
| `tests/run_retarget_test.py` | 新增回归调用、更新旧 IK oracle、版本兼容 |
| `humanoid_retarget/classify.py` | 不修改 |

文档路径：

```text
H:\Blender_Plugin\docs\design\design_foot_ik.md
H:\Blender_Plugin\docs\design\impl_foot_ik.md
```

### 本次已读材料

| 材料 | 已确定内容 |
|---|---|
| 当前 `ik.py` | 使用 hips 锚点、全局 scale、bone tail 长度 |
| 当前 `retarget.py` | 同步逐 Action/逐帧；先 FK、髋部、IK、插帧 |
| 当前 `pipeline.py:469-529` | 两跳模式存在；第一跳关闭 IK |
| 当前 `__init__.py:164-179,274-275` | 设置传递与旧 IK 文案 |
| 当前测试 `:504-518` | 仍以旧 hips-scaled Goal 为 oracle，必须更新 |
| cache-modal 设计档 | 尚未实现；不能假设已有 `RetargetBakeJob` |
| metarig 设计档 | 第一跳关闭 IK；最终跳执行一次 |
| 本次 UE 源码 | 设计档中的精确公式、默认值和 spring 分支 |

同一任务中直接复用这些结论。只有代码变化、证据冲突或上下文缺失才定点复读。

实施时不重复全仓派探子。出现明确缺口才并发派发独立读取任务，等待终态后收敛。

## 实施步骤

### 1. 建立 RED 和构建前检查

- [ ] 保存 IK 关闭时的当前 FK 基准。
- [ ] 加入不同比例链的实际落点测试。
- [ ] 在当前实现上运行，确认 `selected>0`。
- [ ] RED 必须来自“链长映射后的实际末端位置错误”，不能只有新函数缺失。
- [ ] 再加入纯数值、状态和版本兼容测试。

Python 插件没有 C++ Build。适用入口是 Blender 自带 Python 的语法检查、导入和后台测试。

实施前确定三个实际 Blender 可执行文件：

```powershell
$blender42 = '实际 Blender 4.2 的 blender.exe 完整路径'
$blender44 = '实际 Blender 4.4 或 4.5 的 blender.exe 完整路径'
$blender5 = '实际 Blender 5.x 的 blender.exe 完整路径'
```

这些路径必须先实际核对，不能把历史安装位置当作当前事实。

编译前检查清单：

- [ ] `mathutils.Quaternion` 的乘法方向和 normalization。
- [ ] `PoseBone.matrix` 使用 armature 空间。
- [ ] 目标父子关系与实际关节距离。
- [ ] 无效单位、非统一缩放和 shear 已被拒绝。
- [ ] 所有 CURRENT IK 矩阵完整。
- [ ] 4.2 路径不直接访问 slots。
- [ ] 新代码不加入注释；关键行说明写在本档正文。
- [ ] 不修改无关文件、rest 和用户原数据。

### 2. 新增 `motion_space.py`

#### 2.1 类型与方法

```python
@dataclass(frozen=True)
class MotionSpace:
    axes: Matrix
    origin: Vector
    meters_per_unit: float
    object_matrix: Matrix

    def position(self, armature_position: Vector) -> Vector:
        return (
            self.axes.transposed()
            @ (armature_position - self.origin)
        ) * self.meters_per_unit

    def armature_position(self, position: Vector) -> Vector:
        return self.origin + self.axes @ (
            position / self.meters_per_unit
        )

    def rotation(self, armature_matrix: Matrix) -> Quaternion:
        rotation = armature_matrix.to_quaternion().to_matrix()
        return (
            self.axes.transposed() @ rotation
        ).to_quaternion().normalized()

    def armature_rotation(self, rotation: Quaternion) -> Matrix:
        return self.axes @ rotation.to_matrix()
```

导入：

```python
from dataclasses import dataclass

from mathutils import Matrix, Quaternion, Vector
```

所有 Matrix、Vector 必须保存副本。`frozen=True` 不会阻止其内部数据被修改；调用方不得原地改缓存成员。

#### 2.2 新函数

```python
def build_motion_space(
    obj,
    anatomical_body: Matrix,
    meters_per_blender_unit: float,
    floor_height_m: float,
) -> MotionSpace:
```

算法：

```text
取 matrix_world 的三个线性列
计算 sx、sy、sz
要求正值、近似相等
要求各归一化列互相正交
要求 determinant > 0

uniform_scale = 三列长度平均值
world_rotation = linear / uniform_scale

world_up = (0,0,1)
world_left = world_rotation × anatomical_body.left
world_left -= world_up × dot(world_left,world_up)

若投影近零：
    使用 world_rotation 的 X 列重新投影
仍近零：
    报错

world_left = normalize(world_left)
world_forward = normalize(world_up × world_left)

world_axes = columns(world_left,world_forward,world_up)
axes = transpose(world_rotation) × world_axes

floor_world =
    (object_world_x,object_world_y,
     floor_height_m / meters_per_blender_unit)

origin = inverse(matrix_world) × floor_world
u = meters_per_blender_unit × uniform_scale

返回保存副本的 MotionSpace
```

变换误差容差：`1e-5`，用于正交和统一缩放判断，不用于篡改输入矩阵。

新增：

```python
def validate_motion_space(obj, space: MotionSpace) -> None:
```

逐帧比较 `matrix_world` 与缓存副本，最大分量差超过 `1e-6` 就报错。不得沿用失效空间继续烘焙。

调用点：`retarget.py` 准备固定几何数据；来源预采样和正式帧循环都校验。

### 3. 新增 `foot_ik.py`

此文件不导入 `bpy`、`retarget.py` 或 UI。

#### 3.1 值类型

新增以下具体 dataclass：

```text
FootIKSettings
    设计档参数表中的全部可配置参数

PelvisReference
    source_name: str
    target_name: str
    source_position: Vector
    target_position: Vector
    inverse_source_height: float
    xy_offset: Vector

LimbReference
    roles: tuple[str,str,str]
    source_names: tuple[str,str,str]
    target_names: tuple[str,str,str]
    source_initial_length: float
    target_initial_length: float
    target_upper_length: float
    target_lower_length: float
    source_end_rotation: Quaternion
    target_end_rotation: Quaternion
    height_offset: float
    source_rest_end_height: float
    reference_pole: Vector

IKGoal
    position: Vector
    rotation: Quaternion

VectorSpringState
    velocity: Vector
    previous_target: Vector
    previous_target_valid: bool

LimbPlantState
    previous_goal: Vector
    spring: VectorSpringState

RetargetGeometry
    source_space: MotionSpace
    target_space: MotionSpace
    pelvis: PelvisReference
    limbs: tuple[LimbReference,...]
```

`FootIKSettings` 默认值逐项使用设计档参数表。只暴露这些真实参数，不加入任意字典配置。

`VectorSpringState.reset()`：

```text
velocity = zero
previous_target = zero
previous_target_valid = False
```

#### 3.2 设置校验

```python
def validate_foot_ik_settings(settings: FootIKSettings) -> None:
```

逐字段执行：

- 数值必须 `math.isfinite`。
- alpha、maintain、pelvis weight 在 0..1。
- falloff、速度阈值、stiffness、damping 和容差非负。
- contact window 非负。
- floor height 和 crotch offset 允许有限的有符号值。
- bool 字段必须明确转为 bool。
- 无效输入报 `ValueError`；由 `retarget.py` 转为 `RetargetError`。

#### 3.3 髋部函数

```python
def retarget_pelvis_position(
    current: Vector,
    reference: PelvisReference,
    settings: FootIKSettings,
    in_place: bool,
) -> tuple[Vector, Vector]:
```

核心代码：

```python
ratio = (
    reference.target_position.z
    * reference.inverse_source_height
)
base = current * ratio

if abs(settings.pelvis_floor_weight) > 1e-8:
    if current.z <= reference.source_position.z:
        source_initial_crotch = (
            reference.source_position.z
            - settings.source_crotch_offset_m
        )
        source_current_crotch = (
            current.z - settings.source_crotch_offset_m
        )
        percent = source_current_crotch / max(
            0.01, source_initial_crotch
        )
        constrained = (
            reference.target_position.z
            - settings.target_crotch_offset_m
        ) * percent + settings.target_crotch_offset_m
    else:
        constrained = (
            current.z
            + reference.target_position.z
            - reference.source_position.z
        )
    base.z += (
        constrained - base.z
    ) * settings.pelvis_floor_weight

position = base.copy()
position.x += reference.xy_offset.x
position.y += reference.xy_offset.y

if in_place:
    position.x = reference.target_position.x
    position.y = reference.target_position.y

return position, position - base
```

关键行说明：

| 行为 | 原因 |
|---|---|
| `current * ratio` | UE 使用当前位置高度归一化，不是 hips-to-head ratio |
| `max(0.01, ...)` | 保留 UE 的 1 cm 最小分母 |
| `<=` | 相等属于下蹲分支 |
| `position-base` | 保留 PelvisDelta 的源码定义 |

来源参考髋高正常时，倒数为 `1/SourceRefZ`。若低于 UE 初始化阈值对应的 `1e-6 m`，使用 `1/0.01 m`，保留 UE 的 1 cm fallback，并返回明确警告。不能偷偷改成腿长。

#### 3.4 Goal 函数

```python
def generate_limb_goal(
    source_start: Vector,
    source_end: Vector,
    source_end_rotation: Quaternion,
    target_start: Vector,
    reference: LimbReference,
    pelvis_delta: Vector,
) -> IKGoal:
```

核心代码：

```python
vector = source_end - source_start
length = vector.length

if length > 1e-10:
    direction = vector / length
else:
    direction = Vector((0.0, 0.0, 0.0))

normalized_length = length / reference.source_initial_length
inverse_affect = Vector((0.0, 0.0, 1.0))
correction = Vector(tuple(
    pelvis_delta[i] * inverse_affect[i]
    for i in range(3)
))
start = target_start - correction
position = start + direction * (
    normalized_length * reference.target_initial_length
)

delta = (
    source_end_rotation
    @ reference.source_end_rotation.inverted()
).normalized()
rotation = (
    delta @ reference.target_end_rotation
).normalized()

return IKGoal(position, rotation)
```

`1e-10 m` 对应 UE `ToDirectionAndLength` 的 `1e-8 cm` 判断。

两侧参考首尾距离必须大于 `1e-6 m`。目标两段物理长度另外计算，禁止用它们的总和替换 `target_initial_length`。

#### 3.5 Floor 函数

```python
def constrain_goal_floor(
    goal: Vector,
    source_end_z: float,
    reference_height_offset: float,
    settings: FootIKSettings,
) -> Vector:
```

核心代码：

```python
result = goal.copy()
if not settings.floor_enabled:
    return result

height = abs(source_end_z)
start = settings.falloff_start_m
end = start + max(0.0, settings.falloff_distance_m)

if height >= end:
    return result

falloff_range = max(0.01, end - start)
falloff = (
    1.0 if height < start
    else 1.0 - (height - start) / falloff_range
)
weight = falloff * settings.floor_alpha
target_height = height + (
    reference_height_offset
    * settings.maintain_height_offset
)
result.z += (target_height - result.z) * weight
return result
```

不修改 XY。不得在函数末尾加入额外地面 clamp。

#### 3.6 精确弹簧函数

```python
def spring_damper(
    current: Vector,
    velocity: Vector,
    target: Vector,
    dt: float,
    stiffness: float,
    damping: float,
) -> tuple[Vector, Vector]:
```

固定 `Mass=1`、`TargetVelocityAmount=0`。

导入 `math`。辅助函数：

```python
def inverse_exp_approx(value: float) -> float:
    return 1.0 / (
        1.0
        + 1.00746054 * value
        + 0.45053901 * value * value
        + 0.25724632 * value * value * value
    )
```

核心代码：

```python
if dt <= 1e-8:
    return current.copy(), velocity.copy()

frequency = math.sqrt(stiffness) / (
    2.0 * 3.1415926535897932
)
w = frequency * 6.28318530717

if w < 1e-8:
    return current + velocity * dt, velocity.copy()

error = current - target

if damping < 1e-8:
    sine = math.sin(w * dt)
    cosine = math.cos(w * dt)
    position = target + error * cosine + (
        velocity / w
    ) * sine
    rate = velocity * cosine - error * (w * sine)
    return position, rate

if damping > 1.0:
    wd = w * math.sqrt(damping * damping - 1.0)
    c2 = -(
        velocity + error * (w * damping - wd)
    ) / (2.0 * wd)
    c1 = error - c2
    a1 = wd - damping * w
    a2 = -(wd + damping * w)
    e1 = inverse_exp_approx(-a1 * dt)
    e2 = inverse_exp_approx(-a2 * dt)
    position = target + c1 * e1 + c2 * e2
    rate = c1 * (e1 * a1) + c2 * (e2 * a2)
    return position, rate

if damping < 1.0:
    wd = w * math.sqrt(1.0 - damping * damping)
    a = error
    b = (velocity + error * (damping * w)) / wd
    sine = math.sin(wd * dt)
    cosine = math.cos(wd * dt)
    decay = inverse_exp_approx(damping * w * dt)
    offset = (a * cosine + b * sine) * decay
    rate = offset * (-damping * w)
    rate += (
        b * (wd * cosine) - a * (wd * sine)
    ) * decay
    return target + offset, rate

c1 = error
c2 = velocity + error * w
decay = inverse_exp_approx(w * dt)
position = target + (c1 + c2 * dt) * decay
rate = (
    c2 - c1 * w - c2 * (w * dt)
) * decay
return position, rate
```

依据：

```text
Runtime\Engine\Private\KismetMathLibrary.cpp:427-449
Runtime\Core\Public\Math\UnrealMathUtility.h:1665-1746
```

不可使用：

- 显式 Euler 替代。
- `math.exp` 替代。
- 默认二次细分 dt。
- 将接近 1 的阻尼比统一归到临界阻尼分支。

这些都会改变所核验源码的行为。

#### 3.7 Planting 函数

```python
def plant_goal(
    goal: Vector,
    speed: float,
    state: LimbPlantState,
    dt: float,
    settings: FootIKSettings,
) -> Vector:
```

核心代码：

```python
if (
    not settings.planting_enabled
    or speed < 0.0
    or speed > settings.speed_threshold_mps
):
    state.previous_goal = goal.copy()
    state.spring.reset()
    return goal.copy()

position, velocity = spring_damper(
    state.previous_goal,
    state.spring.velocity,
    goal,
    dt,
    settings.stiffness,
    settings.critical_damping,
)

if dt > 1e-8:
    state.spring.velocity = velocity
    state.spring.previous_target = goal.copy()
    state.spring.previous_target_valid = True

return position
```

不得把 `position` 回写给 `state.previous_goal`。

状态初始化：使用目标参考末端位置作为 `previous_goal`；spring 默认重置。

`previous_target` 虽然在固定 TargetVelocityAmount=0 下不影响速度项，仍按源码维护，便于验证状态语义。

#### 3.8 几何速度函数

```python
def geometric_foot_speeds(
    positions: tuple[Vector, ...],
    rest_end_height: float,
    dt: float,
    settings: FootIKSettings,
) -> tuple[float, ...]:
```

伪码：

```text
若样本数 < 2：
    返回全 -1

radius = max(1, ceil(contact_window_s / (2×dt)))

对每个 i：
    first = max(0,i-1)
    last = min(n-1,i+1)
    speed = XY距离(P[last],P[first]) / ((last-first)×dt)

    lo = max(0,i-radius)
    hi = min(n,i+radius+1)
    min_z = min(P[j].z，j属于[lo,hi))

    candidate =
        P[i].z >= 0
        且 P[i].z <= rest_end_height + height_tolerance
        且 P[i].z <= min_z + minimum_tolerance

    candidate 为真：
        返回 speed
    否则：
        返回 max(speed, threshold + 1.0)
```

所有位置已为米。此函数不移动 Goal、不维护锚点。

### 4. 修改 `ik.py`

#### 4.1 替换公开入口

旧入口：

```python
apply_contact_ik(src, tgt, pairs, scale, feet, hands)
```

替换为：

```python
def apply_contact_ik(
    src,
    tgt,
    geometry: RetargetGeometry,
    settings: FootIKSettings,
    states: dict[str, LimbPlantState],
    speeds: dict[str, float],
    pelvis_delta: Vector,
    dt: float,
) -> None:
```

遍历 `geometry.limbs`。

每条链执行：

```text
读当前来源 start/end/末端旋转
读当前目标 start
用两侧 MotionSpace 转入米制计算空间
generate_limb_goal

若 end_role 是 foot_l 或 foot_r：
    constrain_goal_floor
    plant_goal

_solve_chain
```

手臂不进入 Floor 和 Planting。

#### 4.2 `_solve_chain`

新签名：

```python
def _solve_chain(
    tgt,
    space: MotionSpace,
    reference: LimbReference,
    goal: IKGoal,
) -> float:
```

返回最终位置残差，单位 m。

执行顺序：

```text
读取目标 upper/mid/end 当前 head
转入计算空间
读取固定两段关节距离

以当前 mid head 为 pole
pole 退化时使用 reference_pole

_two_bone 得到计划 knee 与可达 end

_aim_joint(upper,mid,knee-root)
view_layer.update()

重新读取求值后的 mid/end head
_aim_joint(mid,end,可达end-当前mid)
view_layer.update()

_write_end_rotation(end,goal.rotation)
view_layer.update()

重新读取最终 end head
返回它与原 Goal 的距离
```

禁止：

```text
knee = upper.tail
```

关节位置必须使用映射的 `mid.head`。

#### 4.3 替换 `_aim_bone`

新增：

```python
def _aim_joint(
    obj,
    start_name: str,
    end_name: str,
    space: MotionSpace,
    desired_direction: Vector,
) -> None:
```

核心步骤：

```text
current_direction_arm =
    end_pose.head - start_pose.head

desired_direction_arm =
    space.axes × desired_direction

swing =
    normalize(current_direction_arm).rotation_difference(
        normalize(desired_direction_arm)
    )

matrix = start_pose.matrix.copy()
rotation = swing.to_matrix().to_4x4()

rotated = rotation × matrix
rotated.translation = matrix.translation
start_pose.matrix = rotated
```

保留已有 roll，并将真实关节向量瞄准目标。不要重新假设骨骼 Y 轴就是映射链方向。

方向近零时报告链错误，不继续构造任意姿势。

#### 4.4 `_two_bone`

新签名：

```python
def _two_bone(
    root: Vector,
    upper_len: float,
    lower_len: float,
    target: Vector,
    pole: Vector,
    fallback_direction: Vector,
) -> tuple[Vector, Vector]:
```

返回 `(knee, reachable_end)`。

保留余弦定理：

```text
d = |target-root|
minimum = |upper_len-lower_len| + epsilon
maximum = upper_len+lower_len-epsilon
d = clamp(d,minimum,maximum)

cos_angle =
    (upper_len²+d²-lower_len²)/(2×upper_len×d)
```

`epsilon=min(1e-6,0.01×min(upper_len,lower_len))`，单位 m。

修正原函数零距离逻辑：

```text
若 target-root 近零：
    direction = normalize(fallback_direction)
    distance = minimum
```

不能把距离直接改成 `1.0 m`。

pole 处理：

```text
pole_direction =
    pole-root-direction×dot(pole-root,direction)

退化时：
    选择与 direction 绝对点积最小的 X/Y/Z 轴
    再投影并归一化

upper_direction =
    direction×cos(angle)+pole_direction×sin(angle)

knee = root+upper_direction×upper_len
reachable_end = root+direction×distance
```

输入两段长度必须正且有限。

#### 4.5 末端旋转

新增：

```python
def _write_end_rotation(
    pose_bone,
    space: MotionSpace,
    rotation: Quaternion,
) -> None:
```

执行：

```text
保存当前 pose_bone.matrix.translation
由 space.armature_rotation(rotation) 生成 4×4 矩阵
恢复保存的位置
写回 pose_bone.matrix
```

目标 pose scale 在预检和逐帧检查中要求为单位值，因此不丢弃有效缩放。

`_rest_world_length` 不再用于新 IK 路径；无剩余调用时移除。

### 5. 修改 `retarget.py`

#### 5.1 `RetargetOptions.__init__`

在现有参数末尾增加：

```python
foot_ik_settings=None
```

构造并校验 `FootIKSettings` 的独立副本，避免调用方烘焙中修改设置。

保留既有参数顺序和默认 `foot_ik=False`。

#### 5.2 新增固定参考准备

```python
def _prepare_retarget_geometry(
    src,
    tgt,
    pairs,
    options,
    scene,
) -> RetargetGeometry:
```

调用位置：映射修正完成之后、创建目标 Action 之前。

步骤：

```text
验证角色和目标骨唯一性
按现有 _anatomical_roles + _body_matrix 获取左右参考方向
构造两侧 MotionSpace

按 REST/CURRENT 获取每个启用链的参考矩阵
CURRENT 缺项立即报错

pelvis：
    转换两侧参考位置
    计算来源髋高倒数
    计算 XY 参考对齐偏移

每条 limb：
    source_initial_length = 来源参考 start/end head 距离
    target_initial_length = 目标参考 start/end head 距离

    target_upper_length = 目标 rest start/mid head 距离
    target_lower_length = 目标 rest mid/end head 距离

    CURRENT 目标的两段距离必须与 rest 一致
    缓存两侧参考末端旋转
    height_offset = target_ref_end.z-source_ref_end.z
    source_rest_end_height = 来源 REST 末端米制高度
    reference_pole = 目标参考 mid 位置
```

未完整映射的可选链省略并报告；缺 hips 报错。

#### 5.3 `_hips_translation`

保留旧函数作为 IK 关闭路径。新增：

```python
def _hips_translation_with_floor(
    src,
    tgt,
    geometry: RetargetGeometry,
    settings: FootIKSettings,
    in_place: bool,
) -> Vector:
```

步骤：

```text
读取来源 hips 当前 head
转入 source_space
调用 retarget_pelvis_position

复制目标 hips.matrix
translation =
    target_space.armature_position(目标髋位置)

写回
返回 pelvis_delta
```

分支：

```text
foot_ik=True：
    使用新髋部高度映射

foot_ik=False：
    保持现有 _hips_translation
    pelvis_delta=zero
```

手 IK 单独开启时，不顺手改变原髋部平移合同。

`rig_height` 仅保留给旧路径和旧摘要。禁止把它当新 IK 比例。

#### 5.4 来源采样

新增：

```python
def _sample_foot_motion(
    src,
    action,
    frame_range: tuple[int, int],
    geometry: RetargetGeometry,
    settings: FootIKSettings,
    in_place: bool,
    scene,
) -> dict[str, tuple[float, ...]]:
```

只在脚 IK 和 planting 都开启时执行。

```text
确认来源已经绑定此 Action 与正确 slot
临时关闭来源 NLA 混播

dt = scene.render.fps_base / scene.render.fps
要求 fps、fps_base 正且有限

遍历 start..end：
    frame_set
    view_layer.update
    validate_motion_space
    读取 hips、左右脚
    转入 source_space
    IN_PLACE 时移除 hips 的 XY 位移
    保存 Vector 副本

对每脚调用 geometric_foot_speeds
返回按帧顺序排列的速度序列
```

采样后从起始帧重新进入正式烘焙。不得用采样阶段末帧姿势作为第一帧。

#### 5.5 `bake_retarget`

本次当前源码入口在 `retarget.py:535`，帧调用在 `:578-598`。实施时按符号定位，修改后的行号会改变。

每个 Action：

```text
绑定来源 Action
读取帧范围
执行必要的足部预采样
创建本次目标 Action并记录身份

为每条腿创建独立 LimbPlantState
previous_goal = 目标参考末端
spring.reset()

逐帧：
    frame_set
    view_layer.update
    校验两侧空间与目标骨架条件

    执行原 _apply_body_orientations
    view_layer.update

    按 foot_ik 开关选择髋部函数
    view_layer.update

    若 foot_ik 或 hand_ik：
        按当前帧索引取左右脚速度
        apply_contact_ik
        view_layer.update

    对所有映射骨骼插 rotation_quaternion/location key

释放当前 Action的采样和植步状态
```

使用采样对应的帧索引，不能使用 `frame` 直接索引从非零开始的数组。

保持：

- 所有来源 Action 都烘焙。
- 所有原 `view_layer.update()` 的必要求值边界。
- 目标 Action 名称和返回顺序。
- 入口来源片段优先的 same-clip 收尾。
- 关键帧在全部 IK 修改之后插入。
- 不实现 cache-modal，不借本次重写调度器。

#### 5.6 失败恢复

新增三个专用函数：

```python
def _capture_bake_state(src, tgt, scene) -> dict:
def _restore_bake_state(src, tgt, scene, state) -> None:
def _discard_bake_outputs(actions, tracks) -> None:
```

快照内容：

```text
两侧原 Action、slot、use_nla
目标原 NLA track mute
目标每根待写骨骼的 matrix_basis、rotation_mode
场景当前帧、subframe、frame_start、frame_end
目标原 hr_retarget_from、hr_actions 的存在性和值
目标入口是否已有 animation_data
```

预检拒绝受目标 driver/constraint 覆盖的写入路径，因此不需要删除或重建它们。

修改：

- 移除开头的 `tgt.animation_data_clear()`。
- 暂停原 NLA 求值，不删除旧 track。
- 记录本次创建的 Action、track 身份。
- 异常时先解绑本次 Action，再移除本次输出。
- 恢复旧绑定、NLA、帧和姿势。
- 若入口没有 animation_data，且恢复后只剩本次创建的空状态，才清除该自有状态。

恢复顺序：

```text
旧 Action/slot和NLA -> frame_set -> update
                   -> 原 matrix_basis/rotation_mode -> update
```

必须保留首次异常，不让清理异常覆盖它。

#### 5.7 `_stash_nla`

保持函数业务用途，但不再删除目标全部旧 track。

```text
为本次其他输出 Action 新建各自 track/strip
记录本次新建身份
保留旧 track
最终 anim.use_nla=False
```

失败只移除本次创建的数据。

### 6. Blender Action 版本兼容

Blender 4.4 引入 slots/layers/channelbags。当前代码声明支持 4.2，却在 `_new_target_action` 和 `_stash_nla` 直接使用 slots，必须修正。

依据：[Blender 4.4 Python API](https://developer.blender.org/docs/release_notes/4.4/python_api/)、[Slotted Actions 升级说明](https://developer.blender.org/docs/release_notes/4.4/upgrading/slotted_actions/)。

#### 6.1 `_new_target_action`

```python
action = bpy.data.actions.new(name)
action.use_fake_user = True
anim = target.animation_data or target.animation_data_create()
slots = getattr(action, "slots", None)
slot = None

if slots is not None:
    try:
        slot = slots.new(id_type="OBJECT", name=target.name)
    except TypeError:
        slot = slots.new("OBJECT", target.name)

anim.action = action

if slot is not None:
    anim.action_slot = slot

return action
```

#### 6.2 `_stash_nla`

```python
slots = getattr(action, "slots", None)
if slots is not None and len(slots):
    strip.action_slot = slots[0]
```

`_assign_action` 已有 capability guard，保留。

已有 source_slot 访问使用 `getattr`；赋值仅在 slot 非 None 时执行。

#### 6.3 测试兼容

当前测试存在直接 slots 访问，覆盖以下函数：

- `test_geometry_and_bake`
- `test_bake_displays_same_source_clip`
- `test_source_clip_picker`
- `test_playback_switches_target_clip`
- `test_gltf_animation_scope`
- metarig 多片段 fixture

测试辅助函数统一增加：

```python
def action_slot_or_none(action):
    slots = getattr(action, "slots", None)
    return slots[0] if slots is not None and len(slots) else None
```

创建 slot 先检查 `getattr(action,"slots",None)`。4.2 验证 Action 绑定和曲线；4.4+ 另外验证 slot。

适用于“同一 Action 多 slot”的测试：

- 4.4+ 保留多 slot fixture。
- 4.2 构造独立 Action 的等价播放 fixture。
- 报告版本覆盖差异，不能声称 4.2 运行了 slots 测试。

### 7. 修改 `__init__.py`

#### 7.1 `HRSettings`

增加设计档参数表对应字段。

UI 属性的数值使用米制值；传递时直接读取数值，不因面板显示单位再乘除 `scale_length`。

最小 UI：

```text
脚 IK
  地面约束
  保留参考脚高
  衰减起点 / 距离
  髋部地面权重
  速度植步
  速度阈值
  高级：crotch offset、spring、几何检测容差、地面高度
```

脚 IK 关闭时高级控件停用，不触发烘焙。

旧说明：

```text
按身高缩放后的来源落点
```

改为：

```text
按来源链伸展比例生成目标落点，并可处理地面和速度植步
```

手 IK 文案改为链长比例落点；不宣称处理手部碰撞。

#### 7.2 `_options_from_settings`

在现有 `RetargetOptions(...)` 中传递：

```python
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
)
```

设置名称与构造字段逐项核对，不新增第二份参数默认值。

### 8. 修改 `pipeline.py`

位置：`retarget_through_human_metarig` 当前 `:494-512`。

第一跳：

```text
foot_ik=False
hand_ik=False
root_motion=KEEP
```

保持。

第二跳新增：

```python
foot_ik_settings=options.foot_ik_settings
```

由 `RetargetOptions` 复制成独立设置。

第二跳对中间来源重新采样。不得直接套用原来源的速度数组，也不得假设第一跳复制了速度曲线。

标准模式的来源是中间骨架，因此与直接模式的接触判断可能不同。分别验收。

### 9. 测试文件与断言

#### 9.1 新增 `tests/run_foot_ik_test.py`

使用 Blender 内置 Python 的 `unittest`，不要求外部安装 pytest。

新增测试：

| 测试函数 | 独立验证 |
|---|---|
| `test_motion_space_roundtrip` | 平移、旋转、统一缩放和单位往返 |
| `test_motion_space_rejects_nonuniform_scale` | 不支持输入在写目标前被拒绝 |
| `test_goal_uses_endpoint_reference_length` | 弯曲参考链不能误用长度总和 |
| `test_goal_uses_chain_start` | thigh/upperarm 起点，排除 hips 错锚点 |
| `test_goal_rotation_order` | 非交换旋转的乘法顺序 |
| `test_pelvis_crouch_and_jump` | 两段式公式、offset和1 cm分母 |
| `test_floor_boundaries` | abs、Start、End、距离0、窄衰减范围 |
| `test_planting_speed_boundaries` | -1、0、threshold、threshold+ε |
| `test_planting_keeps_anchor_in_low_speed_branch` | 低速不更新 previous_goal |
| `test_spring_damping_branches` | 0、0.5、1、2和stiffness=0 |
| `test_geometric_speed_units_and_minima` | fps_base、水平速度、局部低点 |
| `test_action_state_isolation` | Action顺序和重复烘焙不污染 |
| `test_joint_solver_uses_heads` | bone tail 与下一关节不重合 |
| `test_reachable_goal_is_realized` | 实际求值末端达到Goal |
| `test_unreachable_goal_reports_residual` | 不能把Goal正确误报为骨架正确 |
| `test_failure_restores_target_state` | 原动画、NLA、pose和场景恢复 |

关键固定数值：

```python
self.assertAlmostEqual(floor_mid_result, 0.39, places=6)
self.assertAlmostEqual(floor_negative_result, 0.13, places=6)
self.assertAlmostEqual(floor_narrow_result, 0.1656, places=6)
self.assertAlmostEqual(pelvis_crouch_result, 0.9111111111, places=6)
```

对应输入：

```text
Floor中段：
    goalZ=.5，sourceZ=.18，offset=.1
    maintain=1，start=.08，distance=.20，alpha=1

Floor负高度：
    同上，sourceZ=-.03

Floor窄范围：
    goalZ=.5，sourceZ=.082，offset=0
    start=.08，distance=.005，alpha=1

Pelvis：
    Si=1，Sc=.6，Ti=1.5
    os=.1，ot=.2，weight=.5
```

临界 spring 首步：

```text
current=(0,0,0)
target=(1,0,0)
velocity=(0,0,0)
stiffness=250
damping=1
dt=1/30
```

断言：

```python
self.assertAlmostEqual(position.x, 0.0984438139, places=5)
self.assertAlmostEqual(velocity.x, 4.9199348654, places=4)
```

Goal 参考长度测试：

```text
来源两段长度总和=1.0
来源参考首尾距离=.8
来源当前首尾距离=.4
目标参考首尾距离=1.2

期望 Goal 到 target start 距离=.6
```

这能识别误用来源骨长总和的实现。

实际求解容差：

```text
位置 <= 1e-4 m
末端旋转误差 <= 1e-4 rad
```

只在可达、固定长度、无目标约束的 fixture 上使用上述断言。

#### 9.2 测试选择器

聚焦脚本支持：

```text
-- --case all
-- --case 数个明确测试名
```

解析失败或没有选中测试时退出非零。

输出：

```text
FOOT_IK_SELECTED N
FOOT_IK_TEST_OK
```

只有 `N>0`、无失败且进程退出0，才能记 GREEN。

#### 9.3 更新旧回归

`run_retarget_test.py:504-518` 的旧 `contact_error` 使用：

```text
tgt_hip + (src_end-src_hip)
```

必须改成独立构造的新链 Goal 期望值，并关闭 Floor/Planting，以隔离链比例求解。

新 oracle 不调用被测试的 `generate_limb_goal`，避免实现和测试一起错。

保留原 FK、CURRENT、root motion、roll、左右映射、same-clip、metarig回归。

脚 IK 开启的旧数值期望应按新合同更新；IK 关闭的基准不得放宽。

### 10. 执行命令

聚焦：

```powershell
& $blender42 --background --factory-startup --python-exit-code 1 `
    --python 'H:\Blender_Plugin\tests\run_foot_ik_test.py' -- --case all
if ($LASTEXITCODE -ne 0) { throw 'Foot IK focused failed' }
```

回归：

```powershell
& $blender42 --background --factory-startup --python-exit-code 1 `
    --python 'H:\Blender_Plugin\tests\run_retarget_test.py'
if ($LASTEXITCODE -ne 0) { throw 'Retarget regression failed' }
```

对 `$blender44`、`$blender5` 执行相同入口。

日志必须包含本次版本、脚本路径、selected count和最终标记。旧日志不能作为本次通过证据。

出现语法、导入或 API 错误后，保留日志，先修正该错误；禁止未经修正重复运行同一失败命令。

## 强制约束

- 不使用 UE 类型。
- 不改所核验公式的运算顺序和分支。
- 不将链首尾参考距离替换为骨长总和。
- 不将髋部比例替换为腿长或 hips-to-head 比例。
- 不把 Floor 写成简单的 `max(Z,0)`。
- 不把低速输出回写到植步锚点。
- 不增加高速解除后的 spring。
- 不新增髋部反向反馈算法。
- 不修改 target rest、骨长、parent、roll。
- 不让数值模块反向导入 UI、pipeline或retarget。
- 不使用工作线程执行 `bpy`。
- 不实现旧 cache-modal 计划中的调度改动。
- 不暂存、不提交、不推送、不清理用户原工作。
- 关键行解释放在文档正文；生成代码不加入注释。

## 验收标准

### 核心检查矩阵

| 项目 | 必须覆盖 |
|---|---|
| 比例 | 不同上下身、不同手臂、不同左右腿长度 |
| 参考 | REST、CURRENT、CURRENT缺项 |
| 根运动 | KEEP、IN_PLACE |
| 地面 | 低于Start、Start、中段、End、负Z、距离0 |
| 植步 | 未知、高速、低速、恰好阈值、首帧 |
| spring | 无阻尼、欠阻尼、临界、过阻尼、dt为0 |
| 求解 | 可达、过远、过近、pole共线、head/tail不同 |
| 状态 | 双脚、双Action、换顺序、重复调用 |
| 生命周期 | 失败恢复、只清理本次输出、原NLA保留 |
| 版本 | 4.2 legacy、4.4+ slots、5.x |
| 回归 | IK关闭基准、same-clip、标准两跳 |
| 视觉 | 脚底、膝盖、手臂和躯干实际穿插 |

### 真实动作

至少选择站立、行走、下蹲、跳跃、踢腿五类。

固定模型、Action、帧、参数和视角。检查每张输出图，不能仅保存截图文件后宣称通过。

报告：

```text
Goal 数值结果
Skeleton 实际残差
Visual 实际观察
```

分别列出。

不以“接触帧水平位移严格为零”验收 UE SpeedPlanting。该断言与实际源码不一致。

### 临时诊断清理

本次可能新增的临时内容：

| 临时项 | 放置位置 | 收尾 |
|---|---|---|
| 原始/修改后 Goal日志 | 测试或TEMP脚本 | 保存证据后移除 |
| spring锚点/速度日志 | 测试或TEMP脚本 | 移除运行调用 |
| 帧耗时和分类计数 | 测试或TEMP脚本 | 移除埋点 |
| Goal/pole辅助对象 | 测试fixture | 按对象身份删除 |
| 异常注入 | 测试 | 保留必要自动测试，不留产品开关 |
| 采样缓存统计 | 测试 | 移除临时输出 |

不得按名称前缀批量删除对象或文件。

清理后：

- [ ] 核对差异和剩余调用。
- [ ] 确认无临时handler、timer、开关和辅助依赖。
- [ ] 重跑语法/导入、聚焦和回归。
- [ ] 运行路径发生变化时重跑相应Runtime/Visual。
- [ ] 核对采样数据和植步状态已经释放。

未清理或未复验，不得宣布实施完成。

### 当前证据状态

| 层级 | 当前状态 |
|---|---|
| Static：源码公式与调用点核验 | 已执行 |
| Contract：新API和版本合同 | NotRun |
| Generate：插件代码生成 | NotRun |
| Build：C++ | 不适用 |
| Python语法/导入 | NotRun |
| Process/Runtime | NotRun |
| Visual | NotRun |
| 正式功能验收 | NotRun |
| 指定文档路径写入 | Blocked：环境只读 |

## 禁止事项

不使用大范围重构解决局部脚 IK。

不引入第二套播放、接触锚点或持久全局状态。

不将 Goal 通过等同于 Skeleton、Mesh 或正式验收通过。

不声称已经修复所有穿地、脚滑和肢体穿插。

不执行任何形式的 Git commit 或 push。
tokens used
169,830
```text
源码核验完成 -> 两份文档正文如下
磁盘写入：Blocked（当前环境只读）
```

**尚未写入 `H:\Blender_Plugin\docs\design\`。** 以下正文可分别保存为指定文件。

已按本次 UE 源码修正调研摘要：初始链长取首尾距离；Floor 使用 `abs(Z)`；高速解除植步直接放行，不经过弹簧。

---


---

# 附录A：关节角度限实施档（PBIK FBoneSettings 移植，防肩/肘反转伪穿插）

依据：`evidence_self_penetration.md` 第二轮复核附录 5.1-5.5。
目标：把 UE PBIK 的逐轴关节限移植进本插件烘焙管线，消除"手臂反转/过伸"类伪穿插。

## A.1 数据与默认值（对应 IKRigFullBodyIK.h L67-100）

```python
# foot_ik.py 新增（纯数值，无 bpy）
from dataclasses import dataclass
from enum import Enum

class LimitType(Enum):
    FREE = 0
    LIMITED = 1
    LOCKED = 2

@dataclass
class AxisLimit:
    type: LimitType = LimitType.FREE
    min_deg: float = 0.0    # -180..0，相对参考姿势
    max_deg: float = 0.0    # 0..180

@dataclass
class JointLimitSettings:
    rotation_stiffness: float = 0.0   # 0..1
    x: AxisLimit = field(default_factory=AxisLimit)
    y: AxisLimit = field(default_factory=AxisLimit)
    z: AxisLimit = field(default_factory=AxisLimit)

# 人形默认限位表（度；source pose 常见约定，用户可改）
HUMANOID_LIMITS = {
    "upperarm_l": JointLimitSettings(  # 肩：外展/内收
        y=AxisLimit(LimitType.LIMITED, -60, 180),
        z=AxisLimit(LimitType.LIMITED, -90, 90),
    ),
    "forearm_l": JointLimitSettings(   # 肘：仅弯曲
        x=AxisLimit(LimitType.LIMITED, 0, 150),
        y=AxisLimit(LimitType.LOCKED),
        z=AxisLimit(LimitType.LOCKED),
    ),
    # _r 侧镜像（min/max 取反交换）
}
```

锁定阈值（PBIKConstraint.cpp L131）：`Limited 且 (max-min) < 2° → 视为 Locked`。

## A.2 限位算法（对应 PBIKConstraint.cpp L111-239）

```python
def clamp_joint_rotation(
    parent_rest: Quaternion,   # 参考姿势下父骨世界旋转
    child_rest: Quaternion,    # 参考姿势下子骨世界旋转
    parent_now: Quaternion,    # 当前父骨世界旋转
    child_now: Quaternion,     # 当前子骨世界旋转
    settings: JointLimitSettings,
) -> Quaternion:
    """返回修正后的子骨世界旋转（PBIK 分解-限位-回转 同构实现）。"""
    a_rot = parent_now @ parent_rest.inverted()   # UpdateLocalRotateAxes L247
    b_rot = child_now @ child_rest.inverted()     # L248

    # 1. 修 max<min（L124）与三轴 Free 提前返回（L118-121）
    # 2. 三轴全锁 → FIXED：child = parent_now @ (parent_rest⁻¹ @ child_rest)
    #    （等价 L135-148 的相对旋转保持）
    # 3. 两轴锁 → HINGE：对自由轴 RotateToAlignAxes（L152-170）
    # 4. Limited 轴：分解角（L266）→ 越界轴 RotateWithinLimits（L222-239）
    #    TgtRot = Quaternion(axis=旋转轴, angle=目标边界角)
    #    RotateToAlignAxes(TgtVec, CurVec) → child_now 乘修正四元数
```

实现要点：
- 分解角用"子骨 Z 轴在父骨 X/Y/Z 上的投影角"（DecomposeRotationAngles L266-290），
  不是欧拉角直接 clamp——语义必须与 PBIK 一致
- 修正应用于 `child_now`，父骨不动（本插件 FK 链向下传播）
- 末帧（或每帧最后一次迭代）执行 FinalPass 式"根到叶反向序"精确化（L544-550）

## A.3 接线点（retarget.py 烘焙循环）

```text
现有顺序：FK(_apply_body_orientations) → 髋部 → IK goal → 烘焙关键帧
插入位置：FK 之后、髋部之前，逐链执行：
    for (parent, child) in 启用限位的关节对:
        clamp_joint_rotation(...)
仅当 joint_limits_enabled 开启时执行；关闭时路径与现状逐位一致。
```

- 配置入口：`HRSettings` 新增 `joint_limits_enabled: BoolProperty`（默认 False）+
  高级折叠面板（每关节 X/Y/Z 类型与 min/max）
- 限位在**米制计算空间外**的骨骼世界旋转上做（直接 mathutils 四元数，无需 MotionSpace）
- `retarget_through_human_metarig` 两跳：仅第二跳启用（同 foot_ik 约定）

## A.4 边界情况

| 情况 | 行为（对应 PBIK） |
|---|---|
| max < min | 修为 min+1（L124） |
| Limited 范围 <2° | 视为 Locked（L131） |
| 参考姿势缺 CURRENT 矩阵 | 报错重捕获（沿用现有合同） |
| 限位与 IK goal 冲突 | IK 在限位后执行，goal 落点以限位为界（PBIK 同序：constraint 先于 effector 最终混合） |
| 手臂链未完整映射 | 跳过该侧限位并报告 |

## A.5 测试断言

```python
# 肘关节 x 限 [0,150]：输入 -30°（过伸）→ 输出 0°
# 肩 y 限 [-60,180]：输入 200° → 输出 180°
# Locked 轴：任意输入 → 与参考姿势相对角一致
# max<min 输入 (10,-10) → 生效范围 (10,11)
# 限位关闭 → 输出与现状逐位一致（回归保护）
```
