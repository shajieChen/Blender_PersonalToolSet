# design_joint_limits.md

```text
本帧 FK 输入 -> IK 修改 -> PBIK 旋转限位核 -> FinalPass -> 烘焙
                  |
           限制相对本帧输入的变化
```

目标文件：`H:\Blender_Plugin\docs\design\design_joint_limits.md`  
日期：2026-10-14  
状态：设计；运行、视觉与正式验收均为 `NotRun`。

## 1. 结论与源码修正

移植 PBIK 的旋转限位核，不能用 Blender Euler clamp 替代。

输入证据遗漏了一个重要运行事实：

```text
FPBIKSolver::Solve()
    -> Body.UpdateFromInputs()
    -> Rotation = InitialRotation = Bone.Rotation
```

依据：

- `Plugins\Experimental\FullBodyIK\Source\PBIK\Private\Core\PBIKSolver.cpp:239-248`
- 同模块 `Private\Core\PBIKBody.cpp:82-96`

因此，PBIK 的 `InitialRotation` 会随每次求解输入更新，不能直接改成永久固定的 REST/CURRENT 捕获旋转后仍宣称完整行为等价。

本严格版本：

- 参考姿势提供关节原始 XYZ 轴。
- 本帧 FK 姿势提供 A/B 的 `InitialRotation`。
- 当前姿势提供 A/B 的 `Rotation`。
- 限制 IK 等后续求解相对本帧输入产生的旋转变化。

这能限制 IK 造成的关节反转，但不能保证修复 FK 输入中已经存在的反转。

如果产品要求“永久相对捕获姿势限制所有 FK”，需要明确批准这种参考基准策略差异，或提供另一条准确源码依据。本版不偷偷改变该语义。

## 2. 模块和数据契约

```text
__init__.py -> retarget.py -> joint_limits.py -> mathutils
                              |
                       无 bpy、无全局状态
```

| 数据 | 含义 |
|---|---|
| `AxisAngleLimit` | Free/Limited/Locked 和 Min/Max，单位度 |
| `BoneAngleLimits` | 具体 role 的三轴配置和旋转刚度 |
| `JointBody` | 当前旋转、当前求解初始旋转、旋转锁定条件 |
| `JointRotationConstraint` | 实际父 A、子 B、参考轴旋转 |
| 作业参考 | REST 或完整 CURRENT 的子骨参考轴 |
| 帧输入 | FK/髋部完成后的旋转快照 |

约束使用实际 `PoseBone.parent`，不能把 role 列表中相邻两项当父子。

未配置的祖先在插件通道中固定。配置的父子共享 `JointBody`，避免各关节使用互不相干的父旋转副本。

这是旋转核组合，不是完整 PBIK。以下内容不在范围内：

- pin 位置约束、质心和骨架质量计算。
- PrePull、PullChainAlpha。
- PreferredAngles。
- SubIterations 和子链锁定调度。
- RemoveStretch 和完整 body-to-bone 回写。

不暴露没有实现的参数。

## 3. 精确分支

依据 `Private\Core\PBIKConstraint.cpp:111-297`。

### Free

三轴全部 Free，立即返回。此时不修正倒置范围。

### 范围修正和隐式锁定

```text
Max < Min -> Max = Min + 1°

Locked
或 Limited 且 Max-Min < 2°
    -> 该轴视为锁定
```

严格使用 `<2°`。宽度恰好 2° 仍是 Limited。

### FIXED

三轴锁定：

```text
OrigOffset = AInitial × inverse(BInitial)
CurOffset  = ACurrent × inverse(BCurrent)
Delta      = OrigOffset × inverse(CurOffset)
```

普通阶段：取 Delta 的 XYZ，令 W=0，执行增量修正。

FinalPass：

```text
BCurrent = inverse(Delta) × BCurrent
```

直接修改 B，不使用 stiffness、质量权重或单轮 MaxAngle。

### HINGE

恰好两轴锁定，先对齐剩余轴：

```text
X 未锁 -> 对齐 XA、XB
Y 未锁 -> 对齐 YA、YB
Z 未锁 -> 对齐 ZA、ZB
```

一个轴 Locked、另外两个 Free，并没有独立的单轴 clamp 分支。不能根据字段名字擅自补出该行为。

### Limited

```text
ARot = ACurrent × inverse(AInitial)
BRot = BCurrent × inverse(BInitial)

XA/YA/ZA = ARot × 原始子骨 XYZ 轴
XB/YB/ZB = BRot × 原始子骨 XYZ 轴
```

投影和角度：

```text
PX = SafeNormal(ZB - XA×dot(ZB,XA))
PY = SafeNormal(ZB - YA×dot(ZB,YA))
PZ = SafeNormal(YB - ZA×dot(YB,ZA))

AngleX =  SignedAngle(ZA,PX,XA)
AngleY = -SignedAngle(ZA,PY,YA)
AngleZ =  SignedAngle(YA,PZ,ZA)
```

有符号角：

```text
Angle = degrees(acos(clamp(dot(From,To),-1,1)))
Sign  = dot(cross(From,To),Axis) >= 0 ? +1 : -1
```

`PBIKConstraint.cpp` 没有显式 clamp，但调用的 `FMath::Acos` 在 `GenericPlatformMath.h:533-534` 内部 clamp。Python 应保留这一最终语义。

越界才修正，等于端点不修正。

X/Y/Z 按顺序使用一次分解出的角度和向量；不在每轴校正后重新分解。Y 校正轴为 `-YA`。

### 普通修正和 FinalPass

普通阶段：

```text
Push = 基于 cross(AxisA,AxisB) 的源码增量

A: DeltaQ × (1-A.RotationStiffness)
B: DeltaQ × -(1-B.RotationStiffness)
```

没有实际质量分配权重。

每个 body：

```text
Phi = |DeltaQ|
Phi > radians(MaxAngle) -> 缩短 DeltaQ

Q = Q + 0.5 × DeltaQ × Q
```

普通 joint 阶段结束后归一化 A/B。

FinalPass 使用 UE `FindBetweenVectors(AxisB,AxisA)`，直接左乘 B。

## 4. 参数与顺序

| 参数 | 默认值 | 实现范围 |
|---|---:|---|
| 总开关 | `False` | 插件开关 |
| 每轴类型 | `Free` | UE 默认配置 |
| 每轴 Min/Max | `0°/0°` | UE 默认 |
| RotationStiffness | `0.0` | UE 默认 |
| 主迭代 | `20` | UE 默认；插件只运行旋转核与现有两骨 IK |
| MaxAngle | `30°` | PBIK 默认 |
| SubIterations | `0` | 不暴露，不实现子链 |
| PositionStiffness | `0.0` | 旋转通道不暴露 |
| PreferredAngles | 关闭 | 不暴露 |

不提供未经源码支持的“人体通用肩/肘/膝角度默认表”。骨轴和 roll 不同，统一角度表可能限制错误方向。

PBIK 源码中的普通 joint 顺序为叶到根，最后一次 FinalPass 反向执行，实际为根到叶：

- `PBIKSolver.cpp:531-604`
- `PBIKSolver.cpp:796-873`

本插件保持旋转核的这两个顺序。完整求解顺序和最终姿势不宣称与完整 PBIK 相同。

## 5. 失败、风险和验收

- 开关关闭时完全旁路，不做归一化或参考采样。
- 所有配置必须有限，旋转刚度在 0..1。
- 缺失配置 role、重复目标骨或无实际父骨时预检失败。
- CURRENT 参考缺少原始子骨矩阵时失败，不回退到 REST。
- 对目标约束、驱动器、非单位骨缩放进行开启路径预检。
- FinalPass 是源码校正步骤，不是任意多轴配置都能收敛的数学保证。
- 极端姿势、投影退化和互相冲突的范围保持 `Concern`，必须测实际结果。
- 关节限不能代替肢体碰撞检测。

未来变化检查：

| 变化 | 局部改动 | 保持稳定 |
|---|---|---|
| 永久捕获参考限位 | 单独增加参考基准策略，并重新定义等价范围 | 当前旋转核 |
| 替换两骨求解器 | 烘焙求解入口 | 限位数据与源码分支 |
| 完整 PBIK 位置约束 | 新增完整求解模块 | 不把质量、pin、stretch 塞入当前旋转核 |

验收必须分别覆盖 Free、FIXED、HINGE、Limited、2° 边界、倒置范围、Y 符号、反向向量、普通增量和 FinalPass。

关闭输出的逐位一致、UE 数值样本对照、骨架运行和网格检查均为独立门。

---
