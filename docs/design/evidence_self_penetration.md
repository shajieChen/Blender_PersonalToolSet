# 证据档：重定向后肢体穿插身体（self-penetration）解法复核

日期：2026-10-14
复核轮次：三轮（联网搜索 → UE5.7.4 本地源码核对 → 交叉复核）
源码根：`C:\UE5.7.4\Engine`
关联设计档：`docs/design/design_foot_ik.md` §12（未来变化：肢体防穿插）

## 结论（一句话）

**UE5.7.4 的动画重定向栈（IKRig/PBIK）本身不做肢体自碰撞**；官方路线是在运行时用 **物理资产胶囊体 + Physical Animation 驱动** 解决手臂穿躯干等问题；学术前沿用 SDF+学习模型。对 Blender 烘焙式插件，可移植的轻量方案是"胶囊体检测+推出"离线通道。

---

## 第一轮：联网搜索结果

| 来源 | 结论 |
|---|---|
| [Epic 官方文档 IK Rig Retargeting](https://dev.epicgames.com/documentation/enreal-engine/ik-rig-animation-retargeting-in-unreal-engine) | IK Retargeter 只解决链映射/比例/姿态，**不含自碰撞** |
| [Epic 论坛：IK and self collision](https://forums.unrealengine.com/t/question-question-towards-ik-and-self-collision-penetration/234185) | 官方推荐的现成方案：给手臂/躯干骨挂 **capsules + Physical Animation**（物理马达把肢体从碰撞中推出）；"基于物理，快速运动会翻车，但大多数时候有效" |
| [Epic 论坛：Dynamic Collision](https://forums.unrealengine.com/t/character-customization-via-morphs-dynamic-collision/1926966) | 运行时改胶囊半径：`PhysAsset->SkeletalBodySetups[idx]->AggGeom.SphylElems` + `UpdateBoneBodyMapping()/RecreatePhysicsState()` |
| [EG 2024 论文：SDF Self-Collision Avoidance](https://diglib.eg.org/server/api/core/bitstreams/04ab2412-7804-4f57-9316-ca12f395308f/content) | 学术最优：身体分 6 个 segment cluster，逐对算穿透深度矩阵，学习模型预测去穿插姿态；4 个肢体模型独立训练、协同输出 |
| [MoCap Online T-Pose 指南](https://mocaponline.com/blogs/mocap-news/tpose-animation-retargeting-fix) | 大量"手臂位置错"其实是 T-pose/A-pose 参考不匹配——**先修参考姿势再谈碰撞**（本插件已有"捕获当前姿势"对应此点） |

## 第二轮：UE5.7.4 本地源码核对（逐文件证据）

### 2.1 IKRig 重定向栈：无自碰撞 ✗
`Engine\Plugins\Animation\IKRig\Source\IKRig\` 全目录 `rg -i "collision|penetrat"` 仅命中编辑器资产重命名/缩略图 SpawnCollision（`IKRetargetBatchOperation.cpp:678`、`IKRetargeterThumbnailRenderer.cpp:20-28`），**与骨骼碰撞无关**。
五个 Retarget Ops（FK/IK/Pelvis/Floor/SpeedPlanting）均只操作 goal/骨骼变换，无碰撞项。

### 2.2 PBIK（FullBodyIK 插件）：只有旋转关节限，无碰撞 ✗
`Engine\Plugins\Experimental\FullBodyIK\Source\PBIK\Public\Core\PBIKBody.h`：
- L52-77 `ELimitType {Free, Limited, Locked}` + `FBoneSettings` 的 X/Y/Z Min/Max（度）+ `PreferredAngles`
- 这是**姿态限制**（防关节反转/过伸），不是肢体间的碰撞求解
- 全插件 `rg -i collision|penetrat` 零命中
- `IKRigFullBodyIK.cpp:96-131`（`Engine\Plugins\Animation\IKRig\Source\IKRig\Private\Rig\Solvers\`）：effector 注入 + Iterations/SubIterations/MassMultiplier 等，无碰撞通道

### 2.3 物理资产：官方自碰撞载体 ✓
`Engine\Source\Runtime\Engine\Classes\PhysicsEngine\PhysicsAsset.h`：
- `TMap<FRigidBodyIndexPair,bool> CollisionDisableTable` —— 逐对开/关碰撞（相邻体默认禁用）
- `TArray<TObjectPtr<USkeletalBodySetups>> SkeletalBodySetups` —— 每骨胶囊/球/凸包（SphylElems）
- `FPhysicsAssetSolverSettings` L33-61：`PositionIterations` 注释明确 "responsible for depenetration"、`CullDistance`、`MaxVelocityDelta`（穿深速度钳制）

### 2.4 Physical Animation：驱动肢体离开穿透 ✓
`Engine\Source\Runtime\Engine\Classes\PhysicsEngine\PhysicalAnimationComponent.h`：
- L16-63 `FPhysicalAnimationData`：`OrientationStrength/AngularVelocityStrength/PositionStrength/VelocityStrength/MaxLinearForce/MaxAngularForce`
- L79-83 `ApplyPhysicalAnimationSettingsBelow(BodyName, ...)` —— 对某骨及其子树设驱动
`...Private\PhysicsEngine\PhysicalAnimationComponent.cpp`：
- L129-145 实现：`ForEachBodyBelow` + `SkeletalBodySetups[BI->InstanceBodyIndex]->BoneName`
- L322-331：`OrientationStrength * Multiplier * ConstraintSettings::AngularDriveStiffnessScale()` 注入 Chaos 角驱动

### 2.5 ControlRig 点模拟软碰撞：形体级、非骨对骨 ✗（部分参考价值）
`Engine\Plugins\Animation\ControlRig\Source\ControlRig\Public\Math\Simulation\CRSimSoftCollision.h`：
- L12-16 `ECRSimSoftCollisionType {Plane, Sphere, Cone}`
- L23-30 `MinimumDistance=10 / MaximumDistance=20 / Coefficient=64 / CubicEaseIn falloff`
- 语义：点云 vs 外部形体的**软斥力场**（距离场推离），可用于"手 vs 躯干胶囊"的离线推出——**这是最适合移植到 Blender 烘焙的数学形态**
- `Units\Collision\RigUnit_WorldCollision.h` L46：Sphere Trace 对世界几何，5.0 已弃用，与自碰撞无关

## 第三轮：交叉复核（源码 ↔ 搜索 ↔ 本插件现状）

| # | 断言 | 搜索证据 | 源码证据 | 一致？ |
|---|---|---|---|---|
| 1 | UE 重定向栈不含自碰撞 | 官方文档只讲链映射 | IKRig 全目录零碰撞命中 | ✓ |
| 2 | 官方方案=物理胶囊+马达 | 论坛官方回复 | PhysicsAsset + PhysicalAnimationComponent.cpp:129,322 | ✓ |
| 3 | PBIK 关节限≠碰撞 | — | PBIKBody.h L52-77 仅角度限 | ✓ |
| 4 | 软斥力场可离线移植 | — | CRSimSoftCollision.h 参数完整 | ✓（本插件可用） |
| 5 | 参考姿势错配是穿插主因之一 | MoCap Online | 本插件已有 capture_reference | ✓ |
| 6 | 本插件现状 | — | ik.py 只有链 goal，无碰撞 | 缺口确认 |

## 对本插件的可落地建议（按证据强度排序）

1. **软斥力推出通道**（CRSimSoftCollision 移植）：对 hand_l/hand_r/forearm 骨 vs 躯干胶囊（hips→chest 线段+半径）逐帧检测，穿透时沿最小推出向量移动 IK goal，用 `Coefficient×Falloff(CubicEaseIn)` 软推 + 上限，烘焙期离线执行——与现有 foot_ik.py 纯数值模块同构，工程量小
2. **关节限**（PBIK FBoneSettings 移植）：对肩/肘/髋/膝加 X/Y/Z 角度限，防极端反转姿态（部分"穿插"其实是关节反转）
3. **不做**：物理模拟通道（Blender 烘焙场景不适用 Chaos 运行时方案）、SDF 学习模型（需训练数据）

## 硬门自检
- 来源明确：每条结论有 URL 或本地源文件+行号 ✓
- 事实可核：行号可直接打开验证 ✓
- 关联清楚：源码↔搜索↔插件缺口三方对齐 ✓
- 推导可追：方案建议均从具体机制推出 ✓
- 结论可证：实施后可用"手骨与躯干轴距离 ≥ 胶囊半径"断言验证 ✓


---

# 第二轮复核附录（2026-10-14 第二次三轮复核）

## 第四轮：比软斥力更优的方案（联网搜索）

| 来源 | 结论 |
|---|---|
| [Macklin & Müller, Position Based Dynamics (原论文)](https://matthias-research.github.io/pages/publications/posBasedDyn.pdf) | 碰撞用不等式约束 + 位置投影（stiffness k=1），约束生成在求解循环外；对静态/动态碰撞统一为投影 |
| [PBD Survey 2017](http://mmacklin.com/2017-EG-CourseNotes.pdf) | 位置法直接解位置，稳定、可控、适合交互；力/力矩法精度高但难控 |
| [Advanced Character Physics (Verlet)](https://web.mat.upc.edu/toni.susin/files/AdvancedCharacterPhysics.pdf) | "offending points projected out of obstacle"——最小位移垂直推出；soft constraint = 每帧只修固定百分比偏差 |
| [DLR 人形自碰撞规避](https://elib.dlr.de/69984/1/Paper2.pdf) | 斥力场法的两个固有缺陷：阻尼设计难（缠结场景振荡）、存在"场力不够、必须急停"的不可防情形 |
| [GPU 布料自碰撞 (Wu 2020)](https://wanghmin.github.io/publication/wu-2020-sfr/Wu-2020-SFR.pdf) | 工业界最佳实践：**软斥力做预接触层（防患）+ 位置投影做兜底（保证不穿）** 双层结构 |

**综合判定**：单用软斥力（上一版证据档的建议 1）有 DLR 论文指出的振荡与失效风险；更优结构是
**"软斥力预层 + 硬投影兜底"双层**（Wu 2020 的 splitting 结构）。这正是 UE PBIK 的实际范式。

## 第五轮：UE5.7.4 源码二次深挖（关节限实施链全量证据）

### 5.1 PBIK 求解器结构（`Plugins\Experimental\FullBodyIK\Source\PBIK\Private\Core\PBIKSolver.cpp`）
- L221-278 `Solve()`：输入姿势 → body 更新 → root 钉定 → effector 更新 → 约束求解 → 回写骨骼
- L283-297 `UpdateBodies()` 四段式：`ApplyRootPrePull` → `ApplyPreferredAngles` → `ApplyPullChainAlpha` → `SolveConstraints`
- L531-605 `SolveConstraints()`：
  - L539-541 逐约束 `Solve()`
  - L544-550 末次迭代 `FinalPass()`（根到叶强制精确限位）
  - L553-561 `RemoveStretch(StretchAmount)`（进度=min(1,(i+1)/(N/2))，反向序）
  - L565-589 `RunSubIterations`：先锁非子链 body，跑 SubIterations 次
  - L591-597 `RunMainIterations`：解锁后跑 Iterations 次
- 默认值（`IKRigFullBodyIK.h` L159-167）：`Iterations=20`、`SubIterations=0`、`MassMultiplier=1.0`

### 5.2 关节限核心（`...\PBIK\Private\Core\PBIKConstraint.cpp`）
- L28-68 `FJointConstraint::Solve()`：父子 pin 对齐 + UpdateJointLimits
- L111-124 `UpdateJointLimits()`：max<min 修正为 min+1；**L131 锁定阈值 = Limited 且范围 <2° 视为 Locked**
- L135-148 三轴全锁 → FIXED（保持初始相对旋转）
- L152-170 两轴锁 → HINGE（单轴铰链，RotateToAlignAxes 对齐）
- L171-195 `DecomposeRotationAngles()` + L184/189/194 逐轴 `RotateWithinLimits(Min,Max,Angle,Axis,Cur,Ref)`
- L222-239 `RotateWithinLimits()`：越界 → 目标角四元数 → `RotateToAlignAxes(TgtVec, CurVec)`
- L242-264 `UpdateLocalRotateAxes()`：A/B 体旋转 = `当前 × 初始⁻¹`（增量式），轴随姿势更新
- L266-270 `DecomposeRotationAngles()`：父轴/子轴/投影分解
- 暴露面（`IKRigFullBodyIK.h` L77-100+）：每骨 `X/Y/Z ∈ {Free,Limited,Locked}` + `Min/Max（度，相对参考姿势）`；`RotationStiffness/PositionStiffness ∈ 0..1`（L67-72）

### 5.3 PBIK easing 函数（`...\PBIK\Public\Core\PBIKSolver.h` L24-27）
`QuarticEaseOut / CircularEaseOut / SquaredEaseOut`（数值模块可直接复用的平滑函数）

### 5.4 重定向管线可用性（关键确认）
`IKRigProcessor.cpp` L381-388：`RunIKRigOp` 逐个执行 IK Rig 资产里启用的求解器（含 FBIK）——即
**重定向管线（RunIKRigOp → IKRigProcessor）可以直接跑带关节限的 FBIK**，关节限是官方认可的
重定向期工具，不限于运行时。

### 5.5 FBoneSettings 完整定义（`...\PBIK\Public\Core\PBIKBody.h` L52-77）
```
RotationStiffness(0..1) PositionStiffness(0..1)
ELimitType {Free, Limited, Locked} × X/Y/Z
MinX/MaxX MinY/MaxY MinZ/MaxZ（度，相对参考姿势）
bUsePreferredAngles + PreferredAngles(FRotator)
```

## 第六轮：交叉复核（更新版）

| # | 断言 | 网络证据 | 源码证据 | 一致？ |
|---|---|---|---|---|
| 1 | 位置投影 > 纯软斥力 | PBD 原论文+survey；DLR 指出斥力场振荡/失效 | PBIK 用迭代约束投影（SolveConstraints） | ✓ |
| 2 | 最佳=软斥力预层+硬投影兜底 | Wu 2020 splitting | PBIK：PreferredAngles 预旋 + FinalPass 强制限位 | ✓ |
| 3 | 关节限可直接用于重定向期 | — | IKRigProcessor L381-388 求解器列表执行 | ✓ |
| 4 | 关节限语义=相对参考姿势的度数限位 | — | IKRigFullBodyIK.h L78-79 注释 | ✓ |
| 5 | "伪穿插"（关节反转）应由关节限处理 | DLR 缠结案例 | PBIK FIXED/HINGE/LIMITED 三级 | ✓ |
| 6 | 软斥力仍值得做预层 | Wu 2020 | CRSimSoftCollision CubicEaseIn falloff | ✓ |

## 修订后的落地建议（替换上一版建议 1）

1. **关节角度限通道（PBIK FBoneSettings 移植，主防线）**：肩/肘/髋/膝配置 X/Y/Z 限位，烘焙期在
   FK 之后、IK goal 之前逐轴 clamp（`DecomposeRotationAngles`+`RotateWithinLimits` 同构逻辑），
   末端迭代做 FinalPass 式精确限位。防关节反转类"伪穿插"。
2. **软斥力+硬投影双层（躯干防穿，兜底防线）**：手/前臂 vs 躯干胶囊——先 CRSimSoftCollision 式
   软推（预接触，平滑），穿透深度超阈值后切硬投影（最小位移推出，保证不穿）。参数：
   MinDist=0.10m/MaxDist=0.20m/Coefficient=64（软层）+ 1 次投影（硬层）。
3. 迭代次数与顺序参照 PBIK：主 Iterations（默认 20）+ 末迭代 FinalPass 反向序精确化。
