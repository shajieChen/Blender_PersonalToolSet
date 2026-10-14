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
