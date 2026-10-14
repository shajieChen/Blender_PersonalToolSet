# design_foot_ik.md

# Blender 重定向脚部 IK 设计档

日期：2026-10-14  
目标：Blender 4.2+，Python、`bpy`、`mathutils`。  
状态：设计；插件实现、运行和视觉验收均为 NotRun。

```text
固定参考数据
     |
来源逐帧姿势 -> FK -> 髋部平移 -> IK Goal
                                  |
                           FloorConstraint
                                  |
                            SpeedPlanting
                                  |
                         两骨求解 + 末端旋转
                                  |
                             烘焙关键帧
```

## 1. 目标与验证边界

修正当前 IK 使用：

```text
目标髋位置 + (来源末端位置 - 来源髋位置) × 全局身高比
```

造成的跨比例落点误差。

迁移以下 UE 行为：

- IK 链首尾距离比例映射。
- 末端参考相对旋转。
- 髋部高度归一化与 crotch-to-floor。
- 地面附近的 Goal 高度混合。
- SpeedPlanting 状态分支和弹簧算法。

保留现有 FK 朝向算法、映射修正、全部 Action 烘焙和 same-clip 显示。

必须区分三层结果：

| 层级 | 本设计能验证什么 |
|---|---|
| Goal | 生成的位置、旋转符合所迁移的 UE 公式 |
| Skeleton | 可达 Goal 被两骨求解器实际实现 |
| Mesh | 脚底、膝盖、手臂和身体网格是否穿插，需要独立视觉或几何验证 |

这些 Op 不是网格碰撞求解器。不能据此保证任意模型的“网格脚底不穿地”或“所有肢体不穿插”。

## 2. 本次源码核验对调研摘要的修正

源码根：

```text
C:\UE5.7.4\Engine
```

下表中的 Op 文件位于：

```text
Plugins\Animation\IKRig\Source\IKRig\
Private\Retargeter\RetargetOps\
```

对应头文件位于 `Public\Retargeter\RetargetOps\`。

| 项目 | 本次核验结果 | 依据 |
|---|---|---|
| IK 初始链长 | 首骨与末骨参考位置的直线距离；不是骨长总和 | `IKChainsOp.cpp:39-58` |
| IK 链起点 | 腿用 thigh，手臂用 upperarm；不是统一使用 hips | `IKChainsOp.cpp:114-134` |
| Goal 旋转 | `SourceCurrent × SourceInitial⁻¹ × TargetInitial` | `IKChainsOp.cpp:80-104` |
| Floor 源高度 | `abs(SourceEnd.Z)` | `FloorConstraintOp.cpp:148-149` |
| Floor 最小衰减范围 | `max(1 cm, End-Start)` | `FloorConstraintOp.cpp:156` |
| 参考高度差 | 还要乘 `MaintainHeightOffset`；UE 默认是 0 | `FloorConstraintOp.cpp:159`、`.h:39-41` |
| 髋部下蹲分母 | `max(1 cm, SourceInitialCrotchHeight)` | `PelvisMotionOp.cpp:333-338` |
| 植步阈值边界 | `0 <= speed <= threshold` 才运行弹簧 | `SpeedPlantingOp.cpp:132-148` |
| 植步解除 | 高速或负速度直接放行，并重置 spring | 同上 |
| 植步锚点 | 低速分支不更新 `PrevGoalPosition` | 同上 |
| 弹簧指数 | 使用 `InvExpApprox`，不能换成 `math.exp` | `UnrealMathUtility.h:1545-1551` |
| 全局平移比例 | 初始目标髋高 / 初始来源髋高 | `PelvisMotionOp.cpp:222-225` |

`CR_Mannequin_BasicFootIK.uasset` 未解析。不能宣称它与这五个 Op 的组合已经得到等价验证。

此外，这些 Op 生成和修改 Goal；最终骨架 IK 求解属于另一阶段。本文的两骨求解器是插件实现，不冒充完整 UE IK Rig solver。

## 3. 方案选择

推荐采用“固定数值参考 + 显式逐帧状态 + 现有两骨求解”。

| 方案 | 结论 |
|---|---|
| 在当前髋部缩放结果后加脚高补丁 | 改动少，但仍保留错误的链比例和链起点；不采用 |
| 移植所需 UE 数值机制，继续使用两骨求解 | 依赖少、可单独测试；采用 |
| 给目标创建 Blender IK 约束控制骨 | 引入约束求值、控制骨和烘焙生命周期；本次不采用 |

代价：

- 几何植步需要额外的来源采样。
- 不可达 Goal 会被两骨求解器限制。
- 植步保留 UE 的实际分支，因此不是绝对锁脚。
- 任意坡面、台阶和网格碰撞不在本次范围。

## 4. 模块与依赖

```text
__init__.py
     |
 pipeline.py
     |
 retarget.py -> classify.py / mapping.py
     |
     +-> ik.py -> foot_ik.py
     |             |
     +-------------+
     |
 motion_space.py

foot_ik.py / motion_space.py -> mathutils
ik.py / retarget.py          -> bpy
```

| 文件 | 职责 |
|---|---|
| `motion_space.py`，新增 | 米制坐标、位置和旋转转换；对象变换校验 |
| `foot_ik.py`，新增 | 固定参考值、髋部公式、Goal、Floor、几何速度输入、spring 数学 |
| `ik.py` | 调用 Goal 修正；执行两骨求解；写末端旋转 |
| `retarget.py` | 参考准备、Action 采样、帧顺序、状态生命周期和关键帧 |
| `__init__.py` | 参数显示和设置传递 |
| `pipeline.py` | 两跳模式仅在最终跳执行脚部处理 |
| `classify.py` | 保持现有分类；不加入接触检测或求解状态 |

不新增通用 Op 注册器、Manager、全局缓存或抽象接口。

## 5. 坐标和单位契约

### 5.1 计算空间

所有新公式使用米制的角色计算空间：

- Z 指向 Blender 世界上方。
- XY 是水平面。
- Z=0 对应配置的地面高度。
- X 使用角色参考姿势的左右方向，在水平面投影后归一化。
- Y 由 `Z × X` 得到。
- 来源和目标分别建立计算空间，排除左右站位偏移。

不直接使用 `_body_matrix` 的 up 列作为地面法线。该列可能包含参考姿势的身体倾斜。

令：

- `C`：计算空间轴在 armature 空间中的正交矩阵。
- `o`：计算空间原点在 armature 空间中的位置。
- `u`：每个 armature 单位对应多少米。

转换：

```text
P = u × Cᵀ × (ArmaturePosition - o)
ArmaturePosition = o + C × P / u

Q = Quaternion(Cᵀ × ArmatureRotation)
ArmatureRotation = C × Matrix(Q)
```

`o` 的世界 XY 使用对象原点；世界 Z 使用配置地面。

### 5.2 单位

```text
u = scene.unit_settings.scale_length × 对象正统一缩放
```

场景单位必须与输入资产的实际尺寸一致。设置单位不会自动修正错误的模型尺寸。

UE 长度单位 cm 转为 m 时：

```text
8 cm    -> 0.08 m
20 cm   -> 0.20 m
1 cm    -> 0.01 m
```

因此公式中的 `max(1, ...)` 必须换成 `max(0.01, ...)`。

UE SpeedPlanting 只是比较曲线标量，没有强制曲线量纲。Blender 几何速度明确使用 m/s；本设计将调研中的 15 cm/s 约定映射为 0.15 m/s。

### 5.3 支持限制

支持：

- 静态对象平移、旋转和正统一缩放。
- 来源 pose 动画、来源约束求值后的姿势。
- REST 和完整 CURRENT 参考。
- KEEP 和 IN_PLACE。

预检拒绝：

- 对象非统一缩放、镜像、shear。
- 动画过程中对象世界变换改变。
- 目标 IK 链含生效约束。
- 目标驱动器会覆盖待写入的姿势。
- 目标链存在动画伸缩或非固定关节距离。
- 目标三关节不能构成直接的两段父子链。

这些输入不能静默产生部分正确的烘焙结果。

## 6. 固定数据和运行状态

### 6.1 作业固定数据

| 数据 | 内容 |
|---|---|
| `MotionSpace` | `C`、`o`、`u`、初始化对象世界矩阵 |
| `PelvisReference` | 两侧骨名、初始位置、初始来源高度倒数、XY 参考对齐偏移 |
| `LimbReference` | 三个 role、两侧骨名、两侧首尾参考距离、目标两段长度、末端参考旋转、高度差 |
| `RetargetGeometry` | 两侧空间、髋部参考、已启用链 |

REST 取 `Bone.matrix_local`。

CURRENT 取已经捕获的 `source_matrix`、`target_matrix`。IK 所需链矩阵必须完整，不能混用捕获矩阵和缺失项的 rest fallback。

### 6.2 每个 Action 的状态

每条腿独立拥有：

```text
PrevGoalPosition
Spring.Velocity
Spring.PrevTarget
Spring.PrevTargetValid
```

状态只活在本次 Action。

开始下一 Action、取消、异常或重新烘焙时释放。不得跨 Action 复用。

## 7. 逐阶段输入、输出和不变量

| 阶段 | 输入 | 输出 | 不变量 |
|---|---|---|---|
| 预检 | 映射、参考、设置、骨架 | 固定几何数据 | 不写 rest；不创建目标 Action |
| 来源采样 | Action、帧范围、fps | 足部高度和水平速度序列 | 不写目标；来源 NLA 不混播 |
| FK | 来源当前 pose | 目标 FK pose | 关闭 IK 时保持原行为 |
| 髋部 | 当前来源髋、固定参考 | 目标髋位置、PelvisDelta | 不读取求解后的脚误差 |
| Goal | 来源链首尾、目标链首、固定参考 | 每链位置和旋转 | 不使用全局身高比替代链比例 |
| Floor | 来源末端高度、Goal | 修改后的 Goal | 只改 Z |
| Planting | Goal、速度、dt、独立状态 | 修改后的 Goal | 不改旋转；保留源码分支 |
| 两骨求解 | 根、两段长度、Goal、pole | 上段和下段姿势 | 不改骨长、不改 rest |
| 末端旋转 | Goal rotation、求解后末端位置 | 末端矩阵 | 不再次移动末端 |
| 烘焙 | 最终 pose | rotation/location keys | 所有处理后才插帧 |

## 8. 核心公式

### 8.1 IK Goal 位置

```text
Ls0 = |SourceEndRef - SourceStartRef|
Lt0 = |TargetEndRef - TargetStartRef|

v = SourceEndCurrent - SourceStartCurrent
Lc = |v|
d = normalize(v)

a = (AffectIKHorizontal, AffectIKHorizontal, AffectIKVertical)
start = TargetStartCurrent - PelvisDelta ⊙ (1-a)

Goal = start + d × (Lc/Ls0) × Lt0
```

UE 默认：

```text
a = (1, 1, 0)
```

`PelvisDelta` 是髋部附加修改产生的差值，不是髋部相对上一帧的位移。

来源当前首尾重合时方向为零，Goal 落在计算后的 start。不能凭空改成向下方向来生成 Goal。

参考：`IKChainsOp.cpp:114-134`；近零方向分支：`Math/Vector.h:1792-1803`。

本次固定以下 UE 可选项为中性值：

```text
BlendToSource = 0
StaticOffset = 0
StaticLocalOffset = 0
StaticRotationOffset = identity
ScaleVertical = 1
Extension = 1
```

因此只承诺该明确参数子集的公式等价。

### 8.2 IK Goal 旋转

```text
SourceDelta = normalize(SourceCurrentEndQ × inverse(SourceRefEndQ))
GoalQ = SourceDelta × TargetRefEndQ
```

乘法顺序不可交换。

参考：`IKChainsOp.cpp:88-102`。

### 8.3 髋部平移

```text
ratio = TargetInitialHeight / SourceInitialHeight
Base = SourceCurrentPosition × ratio
```

令 `Si/Sc/Ti` 为初始来源、当前来源、初始目标髋高；`os/ot` 为 crotch offset。

下蹲，包括相等：

```text
Sc <= Si

SourceInitialCrotch = Si - os
SourceCurrentCrotch = Sc - os
Percent = SourceCurrentCrotch / max(0.01, SourceInitialCrotch)

ConstrainedZ = (Ti-ot) × Percent + ot
```

站立或跳起：

```text
Sc > Si
ConstrainedZ = Sc + Ti - Si
```

最后：

```text
Base.Z = Lerp(Base.Z, ConstrainedZ, PelvisFloorWeight)
```

参考：`PelvisMotionOp.cpp:321-345`。

插件的水平参考对齐：

```text
XYOffset = TargetRef.XY - SourceRef.XY × ratio
Position.XY = Base.XY + XYOffset
```

它相当于配置 UE 的静态水平平移偏移，用来保留两侧参考位置，不是新的高度公式。

IN_PLACE 再令：

```text
Position.XY = TargetRef.XY
```

输出：

```text
PelvisDelta = Position - Base
```

本次不增加“脚抬高 Δ 后反向移动髋部”的反馈步骤。给出的五个 Op 证据没有建立这种反馈算法；不能把 `2Δ` 或平均脚误差包装成 UE 行为。

### 8.4 FloorConstraint

```text
H = abs(SourceEndCurrent.Z)
Start = HeightFalloffOffset
End = Start + max(0, HeightFalloffDistance)
```

若 `H >= End`，直接保留 Goal。

否则：

```text
Range = max(0.01, End-Start)

Falloff = 1                         , H < Start
Falloff = 1-(H-Start)/Range          , 其他

Weight = Falloff × Alpha
Offset = HeightOffsetInRefPose × MaintainHeightOffset

TargetHeight = H + Offset
Goal.Z = Lerp(Goal.Z, TargetHeight, Weight)
```

```text
HeightOffsetInRefPose = TargetEndRef.Z - SourceEndRef.Z
```

参考：`FloorConstraintOp.cpp:104-108,143-163`。

不额外执行 `max(Goal.Z, 0)`。该钳制会改变 UE 公式。

### 8.5 SpeedPlanting

```text
speed < 0 或 speed > threshold
    PrevGoalPosition = 当前 Goal
    Reset spring
    输出当前 Goal

0 <= speed <= threshold
    输出 VectorSpringInterp(
        Current = PrevGoalPosition,
        Target = 当前 Goal,
        Mass = 1,
        TargetVelocityAmount = 0
    )
```

低速分支不把输出保存回 `PrevGoalPosition`。

参考：`SpeedPlantingOp.cpp:132-148`。

因此它不是严格锁脚，也不是高速解除后弹簧恢复。验收必须比较源码数值行为，不能要求它天然满足零水平位移。

### 8.6 几何速度输入

这是 Blender 替代动画速度曲线的输入层。不是 UE 接触检测算法。

先逐帧记录来源脚骨 head。CURRENT 的 IK 参考不用于定义地面接触高度；接触高度基线使用来源 REST 脚骨高度。

KEEP：

```text
SamplePosition = SourceFootPosition
```

IN_PLACE：

```text
SamplePosition.XY =
    SourceFootPosition.XY
    - SourceHipsCurrent.XY
    + SourceHipsRef.XY
```

这样速度与最终根运动策略一致。

中心差分：

```text
velocityXY =
    (P[i+1].XY-P[i-1].XY) / (2×dt)
```

首尾使用单边差分。单帧 Action 返回未知速度 `-1`。

接触候选：

```text
0 <= FootZ <= RestFootZ + ContactHeightTolerance
FootZ <= 窗口最小 FootZ + ContactMinimumTolerance
```

候选帧把测得水平速度送入 SpeedPlanting；其他帧送入明确大于阈值的值，解除植步。

不增加第二套“接触锚点”。锚点仍由 SpeedPlanting 分支维护。

## 9. 参数表

插件默认参数只在用户开启 `foot_ik` 后生效。`foot_ik=False` 时保留现有默认路径。

| 参数 | 插件默认 | UE 默认/来源 | 单位 |
|---|---:|---|---|
| `foot_ik` | False | 插件开关 | bool |
| `hand_ik` | False | 插件开关 | bool |
| `floor_enabled` | True | UE 默认 False；插件开启脚 IK 后启用 | bool |
| `floor_alpha` | 1.0 | 1.0 | 无量纲，0..1 |
| `maintain_height_offset` | 1.0 | UE 默认 0；插件保留踝参考高度差 | 无量纲，0..1 |
| `falloff_start_m` | 0.08 | 8 cm | m |
| `falloff_distance_m` | 0.20 | 20 cm | m |
| `pelvis_floor_weight` | 1.0 | UE 默认 0；插件启用两段高度映射 | 无量纲，0..1 |
| `source_crotch_offset_m` | 0.0 | 0 | m |
| `target_crotch_offset_m` | 0.0 | 0 | m |
| `planting_enabled` | True | 插件组合开关 | bool |
| `speed_threshold_mps` | 0.15 | 曲线标量默认 15；采用 cm/s 输入约定 | m/s |
| `stiffness` | 250.0 | 250 | 固定 Mass=1 下的 s⁻² |
| `critical_damping` | 1.0 | 1.0 | 阻尼比 |
| `contact_window_s` | 0.08 | Blender 几何输入参数 | s |
| `contact_height_tolerance_m` | 0.02 | Blender 几何输入参数 | m |
| `contact_minimum_tolerance_m` | 0.01 | Blender 几何输入参数 | m |
| `floor_height_m` | 0.0 | 世界平面位置；转入计算空间后为 Z=0 | m |
| `AffectIKHorizontal` | 固定 1.0 | 1.0 | 无量纲 |
| `AffectIKVertical` | 固定 0.0 | 0.0 | 无量纲 |
| spring Mass | 固定 1.0 | 实际调用参数 1.0 | 数值质量 |
| spring TargetVelocityAmount | 固定 0.0 | 实际调用参数 0.0 | 无量纲 |

所有参数必须有限。权重在 0..1；时间和容差非负；stiffness、阻尼比非负。

crotch offset 按源码执行 `PelvisZ-offset`。正值表示 crotch 低于 pelvis，不按头文件的模糊文字反转符号。

## 10. 边界情况

| 情况 | 行为 |
|---|---|
| 缺少 shin/foot | 跳过该侧 IK并报告缺链；另一侧继续 |
| 缺少 hips | 预检失败 |
| 重复 role 或重复目标骨 | 预检失败，避免后一次覆盖前一次 |
| 参考首尾长度近零 | 拒绝该链 |
| CURRENT 数据缺项 | 报错，要求重新捕获 |
| 极深下蹲 | 保留源码比例和最小分母；不额外限制比例 |
| `FalloffDistance=0` | H<Start 全权重；H>=Start 关闭 |
| 衰减距离小于 1 cm | 仍使用 1 cm 分母，保留结束边界行为 |
| 来源脚 Z<0 | Floor 仍用 abs；几何接触输入不把它当正常触地 |
| `MaintainHeightOffset=0` | 忽略参考高度差 |
| 速度恰好等于阈值 | 执行 spring |
| 单帧 Action | 不植步 |
| 不连续帧处理 | 重新开始 Action 状态，不能沿用旧积分状态 |
| Goal 不可达 | 求解到可达点，报告残差；不改骨长 |
| pole 共线 | 使用稳定参考弯曲方向和确定的备用轴 |
| 双脚高度冲突 | 分别求解；不隐式增加髋部反馈 |
| 手 IK | 使用链比例和末端旋转；不运行 Floor/Planting |
| 网格厚底鞋、脚尖接触 | 骨 head 不是脚底；需要单独网格验证 |
| 坡面或台阶 | 本次只支持水平平面 |
| 两跳 metarig | 只在最终跳处理；不得声称与直接模式数值相同 |

## 11. 所有权、失败与回滚

- 一次 `bake_retarget` 调用拥有固定几何数据和采样数据。
- 每个 Action 拥有自己的植步状态。
- 所有 `bpy` 调用在 Blender 主线程。
- 数值模块不读取 `bpy.context`。
- 取消和异常只删除本次创建的 Action、NLA strip/track。
- 保留原 Action 数据块、原 NLA、原驱动器和用户骨架。
- 失败恢复入口 Action/slot、NLA 状态、目标 pose、场景帧和范围。
- 不使用 `animation_data_clear()` 提前销毁原目标动画状态。
- 成功后保持来源与目标同片段显示；旧 NLA 数据保留并停用。

## 12. 未来变化检查

| 变化 | 局部扩展位置 | 保持稳定的部分 |
|---|---|---|
| 有真实速度曲线 | 替换速度输入采样；仍提供每帧标量 | SpeedPlanting 和 spring |
| 增加坡面 | 新增有明确证据的 Goal 地面修正步骤 | 链比例、参考旋转和求解入口 |
| 替换两骨求解器 | `ik.py` | `IKGoal`、Floor 和 Planting 数学 |

现在没有第二个求解实现，不提前添加接口、工厂或注册器。

## 13. 验收

1. 数值公式、边界分支和矩阵乘法顺序通过测试。
2. 可达模型的实际末端位置与最终 Goal 误差在规定容差内。
3. IK 关闭时，原 FK 输出和 same-clip 行为保持一致。
4. KEEP/IN_PLACE、REST/CURRENT、单帧、双 Action、左右脚独立状态覆盖。
5. Blender 4.2、4.4+ slotted Actions 和 5.x 分别运行适用测试。
6. 真实动作逐图检查脚底和肢体穿插，独立报告 Visual。
7. 清理临时诊断后重跑聚焦和回归。

本次只完成源码静态核验。插件 Contract、Process、Runtime、Visual 和正式验收均为 NotRun。

---
