# design_soft_repulsion.md

```text
FK -> IK Goal -> UE 软斥力 -> UE 点积分 -> 两骨 IK -> 烘焙
                    |
             躯干胶囊提供查询中心
```

目标文件：`H:\Blender_Plugin\docs\design\design_soft_repulsion.md`  
日期：2026-10-14  
目标：Blender 4.2+、Python、`mathutils`。  
状态：设计。未写入文件；Contract、Runtime、Visual、正式验收均为 `NotRun`。

## 1. 结论与等价范围

移植 `CRSimSoftCollision` 的 **Sphere + CubicEaseIn 数值核**，再使用 `FRigVMSimPoint::IntegrateVerlet` 将其输出转换成 Goal 位移。

必须修正输入证据中的三点：

| 输入摘要 | 本次源码事实 |
|---|---|
| `Coefficient × Falloff` 可直接作为推出位移 | `CalculateForPoint()` 返回 Force；还需要明确积分方式 |
| Sphere 内部始终使用单位推出方向 | 当 `Distance <= SMALL_NUMBER`，源码保留未经归一化的中心偏移向量 |
| PBIK 证明了胶囊软推与硬投影的组合 | PBIK 的旋转限位不能证明胶囊自碰撞算法等价 |

源码根为 `C:\UE5.7.4\Engine`：

- `Plugins\Animation\ControlRig\Source\ControlRig\Public\Math\Simulation\CRSimSoftCollision.h:23-32`：默认参数。
- 同模块 `Private\Math\Simulation\CRSimSoftCollision.cpp:7-96`：距离、方向、衰减、Force。
- `Plugins\Runtime\RigVM\Source\RigVM\Private\RigVMFunctions\Math\RigVMMathLibrary.cpp:57-65`：Verlet 积分。
- 同模块 `Public\RigVMFunctions\Math\RigVMMathLibrary.h:113-119`：点默认质量和阻尼。
- `Source\Runtime\Core\Private\Math\UnrealMath.cpp:1694-1717`：线段最近点。

等价承诺限于：**相同输入下，上述数值核保持公式、分支和默认值语义。**

胶囊提供 Sphere 查询中心、将躯干半径并入 `Point.Size`、每帧以零初速度积分一次，属于 Blender 通道的输入组织方式。它不是 UE 已有的重定向自碰撞通道，也不等价于完整 ControlRig 点模拟容器。

本严格版本不添加无对应源码的位移上限、穿深阈值或胶囊硬投影。若要求“保证不穿”，需要另立位置投影通道及其等价来源；当前保持 `Blocked`。

## 2. 架构与数据流

```text
__init__.py
    |
retarget.py -> ik.py 的现有两骨求解函数
    |
    +-> soft_repulsion.py -> mathutils
    +-> joint_limits.py   -> mathutils
    +-> foot_ik.py        -> mathutils
    +-> motion_space.py   -> mathutils
```

| 文件 | 职责 |
|---|---|
| `soft_repulsion.py` | 线段最近点、Sphere Force、CubicEaseIn、Verlet 数学 |
| `retarget.py` | 参数预检、躯干轴读取、Goal 修正、烘焙生命周期 |
| `__init__.py` | 开关与参数 UI |
| `ik.py` | 复用现有两骨求解，不增加碰撞状态 |
| `motion_space.py` | 保留现有坐标契约 |

逐帧顺序：

1. 运行现有 FK 和髋部处理。
2. 生成每条链的 Goal；脚部继续运行 Floor/Planting。
3. 读取目标 `hips`、`chest` 的当前 head，建立躯干轴。
4. 分别修正 hand Goal 和 forearm head 候选 pole。
5. 使用现有两骨算法求解。
6. 若关节限开启，执行关节限通道。
7. 所有处理结束后插入关键帧。

软推只执行一次。不能在关节迭代中重复积分，否则强度会随迭代数变化。

forearm 修正只改变两骨求解的 pole 候选。pole 不是独立位置约束，不能保证求解后的 forearm head 到达该点。

## 3. 坐标、单位和公式

### 坐标契约

`MotionSpace.position()` 接收 **armature 空间位置**。新通道应调用：

```python
space.position(pose_bone.head)
space.rotation(pose_bone.matrix)
```

不能先乘 `matrix_world`。对象的旋转、统一缩放和原点已由 `MotionSpace` 管理。

现有旧调用含有先乘 `matrix_world` 的路径。为满足关闭时逐位一致，仅在新通道开启分支使用正确坐标；不顺带修改旧路径。

### 胶囊查询中心

令躯干轴端点为 `A、B`，查询点为 `P`：

```text
S = B-A
d1 = dot(P-A, S)

d1 <= 0       -> C = A
dot(S,S)<=d1  -> C = B
其他          -> C = A + S × d1/dot(S,S)
```

分支顺序保持 `FMath::ClosestPointOnSegment`。退化线段直接返回 A。

Sphere 输入：

```text
Sphere.Center = C
Point.Size = TorsoRadius + ProtectedPointRadius
```

这里没有修改 UE Sphere 公式。

### Sphere Force

为保留包含单位敏感分支的 UE 行为，内核先把米转换成厘米：

```text
Pcm = 100 × Pm
Ccm = 100 × Cm
Sizecm = 100 × Sizem

V = Pcm-Ccm
D = max(|V|-Sizecm, 0)

D > 1e-8 -> Direction = GetSafeNormal(V)
其他     -> Direction = V
```

若 `bInverted=True`，先反转方向。

当 `MaximumDistance <= MinimumDistance`：

```text
D < MinimumDistance -> Falloff = inverted ? 0 : 1
其他                 -> Falloff = inverted ? 1 : 0
```

否则：

```text
Ratio = 1                                      , D < MinimumDistance
Ratio = 1-clamp((D-Min)/(Max-Min), 0, 1)         , D < MaximumDistance
Ratio = 0                                      , 其他

inverted -> Ratio = 1-Ratio

Falloff = Ratio³
```

最后：

```text
Mass <= 1e-8 -> Force = 0
其他         -> Force = Direction × Falloff × Coefficient

Force_m = 0.01 × Force_cm
```

`CalculateForPoint()` 不使用 `dt`，不除以质量。

### Verlet 积分

```text
w = clamp(Blend × dt, 0, 1)

Vnew = Lerp(Vold, Force/Mass, w)
       × clamp(1-LinearDamping, 0, 1)

Pnew = Pold + Vnew × dt
```

本烘焙通道每帧输入：

```text
Vold = 0
Blend = 1
dt = fps_base/fps
```

这是一条明确的离线调用策略，不冒充完整 UE 固定步长容器、跨帧速度状态或插值输出。

## 4. 参数表

| 参数 | 默认值 | 来源与语义 |
|---|---:|---|
| 总开关 | `False` | 插件开关 |
| `minimum_distance_m` | `0.10` | UE 10 cm |
| `maximum_distance_m` | `0.20` | UE 20 cm；是绝对结束距离，不是附加宽度 |
| `coefficient` | `64.0` | UE 默认；不是位移或牛顿 |
| `inverted` | `False` | UE 默认 |
| falloff | 固定 CubicEaseIn | UE 默认子集 |
| `mass` | `1.0` | `FRigVMSimPoint` 默认 |
| `linear_damping` | `0.01` | `FRigVMSimPoint` 默认 |
| `torso_radius_m` | `0.15` | 插件代理体参数，不是 UE 默认 |
| `hand_radius_m` | `0.025` | 插件代理点参数 |
| `forearm_radius_m` | `0.035` | 插件代理点参数 |

Min/Max 倒置或相等时保留 UE 阶跃分支，不交换、不补 epsilon。

不自动根据网格包围盒猜半径。用户应根据模型设置代理体。

## 5. 边界与验收

| 情况 | 行为 |
|---|---|
| 总开关关闭 | 不建立代理体、不计算 Force、不积分；进入原路径 |
| `hand_ik=False`、软推开启 | 使用目标 FK 手部位置作为基础 Goal |
| 缺少任一受保护手臂、hips 或 chest | 开启路径预检失败 |
| 查询点在躯干轴上 | UE Sphere Force 为零；不能添加备用法线 |
| 查询点已深入代理体 | 保留 UE 非单位方向分支 |
| Goal 不可达 | 保留骨长；记录实际末端残差 |
| 关节限导致重新穿入 | 报告残余穿深，不宣称解决 |
| 对象镜像、非统一缩放或 shear | 开启路径拒绝 |
| 目标链含约束或驱动器 | 开启路径拒绝 |
| 两跳 metarig 模式 | 本版开启路径明确拒绝，避免参数在中间跳丢失 |
| forearm 骨段中部穿插 | head/pole 检测不足以证明骨段安全 |
| 网格穿插 | 需要独立网格或视觉验收 |

验收分三层：

- **Contract**：Sphere Force、阶跃边界、反转、厘米转换、Verlet 与 UE 样本一致。
- **Skeleton**：检查最终 hand/forearm head，而不是只检查修正后的 Goal。
- **Visual**：检查网格、肩部、腋窝、交叉手臂和快速动作。

当前没有数值对照运行、骨架运行或视觉证据，均为 `NotRun`。

---
