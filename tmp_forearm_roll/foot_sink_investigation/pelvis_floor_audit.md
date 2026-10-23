# 骨盆高度映射缺陷审计

状态：仅审计与方案，未修改任何代码。候选副本与正式插件保持原状
（正式 `foot_ik.py` `B0B86DB6...`、`ik.py` `AD87866E...`、`retarget.py` `EDBFAFB5...`；
候选 `ik.py` `0ED8BB56...`、`retarget.py` `18B9DCE2...`，`foot_ik.py` 与正式版相同）。

候选路径：`H:\Blender_Plugin\tmp_forearm_roll\floor_candidate_root\humanoid_retarget\`；
正式路径：`%APPDATA%\Blender Foundation\Blender\5.1\scripts\addons\humanoid_retarget\`。
除已实施的三处（候选 `retarget.py` 构建几何处来源地面 0、`ik.py` 复查转换）外，
骨盆链代码两处一致，下文行号以候选为准，正式版对应函数相同。

## 一、调用顺序与坐标

逐帧调用顺序（`retarget.py` `_pose_one_frame`，约 `:1979-2036`）：

```text
_apply_body_orientations（FK 身体姿势）
  -> _hips_translation_with_floor（retarget.py:1063-1080）
       current = 来源髋在来源运动空间的位置
       retarget_pelvis_position（foot_ik.py:133-179）-> position, pelvis_delta
       目标髋 pose.matrix.translation = target_space.armature_position(position)
  -> apply_contact_ik（ik.py:131-196）
       generate_limb_goal（foot_ik.py:182-217，用 pelvis_delta.z 修正腿根）
       constrain_goal_floor（foot_ik.py:220-248）
       plant_goal -> _solve_chain（双骨 IK，运动空间内求解）
       _recheck_foot_contact（候选已改为地面相对测量）
  -> 高度计划（规划遍 CONTACT_LOG -> build_height_plan -> 关键帧遍应用）
  -> 写关键帧
```

几何在烘焙前由 `_prepare_retarget_geometry`（`retarget.py:897`）构建：
`PelvisReference` 在 `:962-968`，其中 `source_position`、`target_position`
分别是源/目标静止髋在**各自运动空间**中的位置（`:946-952`）；
`LimbReference.height_offset = tgt_end.z - src_end.z` 在 `:1035`，
同样是各自运动空间的静止踝高之差。

各量的坐标（候选现状，地面高度记为 f）：

| 量 | 坐标 | 地面为 f 时的值 |
| --- | --- | --- |
| 来源当前髋高 S | 来源运动空间（地面 0） | 来源世界髋高 |
| 来源静止髋高 Hs | 来源运动空间 | 来源世界静止髋高（约 0.53 m） |
| 目标静止髋高 Ht(f) | 目标运动空间（零点在 f） | 目标世界静止髋高 Ht_w - f |
| 输出 position.z | 目标运动空间 | 经 `armature_position` 后世界高 = f + position.z |
| pelvis_delta.z | 目标运动空间 | position - base 的 Z 分量，供 `generate_limb_goal` 修正腿根 |

## 二、数学推导：-50 mm 为何只剩约 -13 mm

`retarget_pelvis_position`（`foot_ik.py:133-179`）在测试参数
（髋部地面权重 1、裆偏 0）下化简为两支（`:139-169`）：

- 支 A（S <= Hs，绝大多数帧）：
  `position.z = S * Ht(f) / Hs`
- 支 B（S > Hs，接近站立的帧）：
  `position.z = S + Ht(f) - Hs`（地面权重分支与 base 抵消后的结果）

世界髋高 P(f) = f + position.z。代入 Ht(f) = Ht_w - f：

- 支 A：`P(f) = f + S*(Ht_w - f)/Hs = P(0) + f*(1 - S/Hs)`
- 支 B：`P(f) = f + S + Ht_w - f - Hs = P(0)`，地面偏移**完全抵消**。

即地面偏移被乘法比例衰减为 `(1 - S/Hs)` 倍。本动作 S/Hs 中位约 0.73，
-50 mm 只剩约 -13.5 mm；站立帧 S 接近 Hs，衰减到近 0。

逐帧验证（`floor_fix_frames.csv`，`a050_300000`，FP/FM 骨盆世界高减 F0）：

| 帧 | F0 骨盆世界高 | FP 差 | FM 差 | 公式 f*(1-S/Hs) 的定性 |
| --- | ---: | ---: | ---: | --- |
| 0 | 521.9 mm | +1.4 mm | -1.4 mm | S 接近 Hs，衰减最大 |
| 1 | 453.1 | +7.82 | -7.81 | 中间 |
| 4 | 360.5 | +16.44 | -16.44 | S 低，保留最多 |
| 全程中位 | 392.9 | +13.41 | -13.41 | 与 0.27 倍系数吻合 |

差值与骨盆高度逐帧负相关、正负地面严格对称，证明主因就是支 A 的
乘法比例（把地面偏移当作骨架尺寸变化来缩放），支 B 则整段抵消。
这不是输出端少加了一次偏移：偏移在 `Ht(f)` 进入比例的那一刻就被缩放了，
在最终位置上补加只会掩盖中间错误且破坏支 B 与 `pelvis_delta` 的一致性。

第二个抵消点在脚目标：`constrain_goal_floor` 的
`target_height = |source_end_z| + height_offset`（`foot_ik.py:243-246`），
其中 `height_offset`（`retarget.py:1035`）的目标项含 -f。
当衰减权重为满时，踝运动高被钳到「来源踝高 + 含地面偏移的静止高差」，
换算回世界后恰好回到 F0 的踝高，地面偏移再次被抵消。

第三个因素解释正负不对称：复查与高度计划只能上抬（候选已地面相对）。
FP 时原始脚在地面之下（相对 -50 mm 量级），上抬可以闭环，所以通过；
FM 时原始脚在地面之上悬空，任何现有环节都不能下压，所以失败。
三者共同作用：比例衰减（主因）+ 目标高抵消（次因）+ 单向复查（不对称的放大器）。

`pelvis_delta.z` 不是独立元凶：支 A、权重 1 时它恒为 0（两支结果相同），
支 B 时它等于两支之差。修正比例项后必须让它继续在同一套
「离地高度」坐标里计算，否则 `generate_limb_goal` 的腿根修正
（`foot_ik.py:199-207`，只取 Z 分量）会与髋位置脱节。

## 三、解耦方案

原则：地面平移与姿势映射分离。姿势映射只处理「离地高度」
（髋/踝相对各自接地面），地面偏移只在运动空间原点转换时应用一次
（`MotionSpace.armature_position` 已具备，`motion_space.py:34-38`）。

定义目标静止脚底在目标运动空间的高度 σt
（脚底世界高减 f；F0/T2 时为 0，F± 时为 -f），来源同理 σs（约定 0）。
把比例映射改写为离地形式：

```text
修正前（候选）                        修正后（离地坐标）
                                     
S（髋运动高）                         S - σs（髋离地高）
Ht(f) = Ht_w - f（随地面变）          Ht_i = Ht(f) - σt（骨架固有静止髋离地高）
position.z = S * Ht(f)/Hs             position.z = (S-σs) * Ht_i/(Hs-σs)   （支 A）
world = f + position.z（只剩残差）    world = f + position.z（地面完整平移）
```

σt 可在 `_prepare_retarget_geometry` 内由已有的
`_extract_foot_contact_local`（`retarget.py:835`）算出：把目标脚骨
静止局部接触点经静止矩阵变到世界再经 `target_space.world_position`
取最低 Z。CURRENT 参考模式下应使用同一套参考脚矩阵而不是静止骨，
这一点要在实施时与 `reference_matrices` 的取值保持一致；
取不到接触点时回退 σt = 0（即候选现状，不新增失败模式）。

支 B 同理换为离地量：`position.z = Ht_i + ((S-σs) - (Hs-σs))`。
`pelvis_delta.z` 在离地坐标内按原定义（position - base）计算，
base 的 Z 也用离地式，使 `generate_limb_goal` 的修正与髋位置同坐标。
X/Y 的缩放比同步改用固有比 `Ht_i/(Hs-σs)`：F0 时不变，
非零地面时消除现在按 `(Ht_w - f)/Hs` 缩放平面位移的附带畸变
（根运动 KEEP 的水平分量在 F0 之外也会受益；IN_PLACE 本就覆盖 X/Y）。

连带一处：`height_offset`（`retarget.py:1035`）改用离地静止踝高差
`(tgt_end.z - σt) - (src_end.z - σs)`，使 `constrain_goal_floor`
的目标高成为踝离地高，消除第二个抵消点。`foot_ik.py` 的
`constrain_goal_floor` 本体不动，它接收的偏置语义被修正。

## 四、最小修改清单（不实施）

| 文件 | 函数/位置 | 修改 |
| --- | --- | --- |
| `retarget.py` | `_prepare_retarget_geometry`（PelvisReference 构建，约 `:962-968`） | 计算 σt（及 σs=0 约定），存入 `PelvisReference` 新增字段（如 `source_ground_z`、`target_ground_z`，单位为各自运动空间 Z）；`height_offset`（`:1035`）改用离地静止踝高差。 |
| `foot_ik.py` | `PelvisReference`（约 `:36-43`） | 增加两个地面字段（默认 0.0，保持其他构造点兼容）。 |
| `foot_ik.py` | `retarget_pelvis_position`（`:133-179`） | 比例、percent、constrained 全部改用离地量；`position.z` 与 `pelvis_delta.z` 在离地坐标内输出（position 仍为目标运动空间坐标，因运动空间零点即地面）。 |
| `ik.py`、`motion_space.py` | 不改 | 候选的地面相对复查已正确；空间转换机制无误。 |

Z=0 等价性：σt=σs=0 且 f=0 时，离地式逐项退化为候选现状，
F0 结果必须与归档基线一致（硬性验收）。
T2（地面与目标同移 +0.05）：σt=0、Ht_i 与 F0 相同，position 不变，
世界整体 +50，逐帧等价应当成立。
T3（来源也同移）：σs 仍按约定 0，来源髋高整体含 +50，
percent 与衰减仍会漂移——这是来源地面约定的固有边界，
本次方案不声称解决，继续按「接地守住、姿态记录」验收。

影响评估：

- `pelvis_delta.z`：支 A 仍为 0；支 B 数值在非零地面下变为地面无关，
  与髋位置同坐标，脚目标腿根修正保持一致。
- 脚目标：髋完整平移后腿根随之平移；`height_offset` 修正后地面衰减
  不再抵消，踝目标直接落在目标地面附近，复查回到毫米级兜底角色。
- 根运动：KEEP 的 Z 由公式决定（已分析）；X/Y 缩放比改为固有比，
  F0 不变，非零地面下不再被地面值缩放。IN_PLACE 不受影响。
- 膝角：FM 应恢复到与 F0 同轨迹（身体真正下降 50 mm，而不是靠伸膝够地）；
  FP 膝角不应被计划过度抬升改变，逐帧对比验收。
- 手部 IK：手目标仍相对肩根，整个上身随髋平移，手世界轨迹应为
  F0 轨迹加地面偏移；世界锁定手的既有缺失不变，不在本次范围。

## 五、修正前后坐标示意

```text
修正前（候选，FM 地面 -0.05）
  来源髋 S ──x (Ht_w - f)/Hs──> 目标运动髋高（被 f 缩放）
        world = f + position ──> 只剩 f*(1-S/Hs) ≈ -13 mm
  踝目标高含 -f 偏置 ──> 世界踝高回到 F0，脚悬空在世界 0 附近

修正后（离地坐标）
  来源髋离地高 S-σs ──x Ht_i/(Hs-σs)（骨架固有比，与 f 无关）──> 髋离地高
        position 即目标运动高 ──armature_position──> world = 离地高 + f
  踝目标高 = 来源踝离地高 + 固有踝高差 ──> 脚落在 f 平面上
```

## 六、回归测试矩阵（实施后执行，本轮只规划）

四个动作 `a050_300000`、`a050_300010`、`a050_301000`、`a050_302011`（0-52 帧），
沿用 `floor_fix_scan.py` 的逐帧口径，候选断言与基线沿用归档值。

| 编号 | 条件 | 硬性验收 |
| --- | --- | --- |
| F0 | 地面 0 | 与归档 A 组逐帧一致：脚底最低 -1.000/-1.000/-0.999/-0.996 mm、踝误差 <=0.056 mm、复查抬升 163.0/149.9/160.6/160.3 mm 量级；骨盆/头部逐帧偏差在既有残差内（<=0.1 mm） |
| F+ | 地面 +0.05 | 接触脚底相对地面 >= -1 mm（容差抖动逐帧记录）；无低于地面 -10 mm 的帧；骨盆世界高 = F0 + 50 mm（逐帧差 <=2 mm）；踝误差与 F0 同级 |
| F- | 地面 -0.05 | 同 F+，骨盆世界高 = F0 - 50 mm（逐帧差 <=2 mm）；脚底相对地面在 ±2 mm 内 |
| T2 | 地面与目标同移 +0.05（300000、301000） | 归一到地面后脚底、膝角、踝、骨盆与 F0 逐帧差 <=0.1 mm / 0.01° 量级 |
| T3 | 整体同移 +0.05（300000） | 脚底相对地面 >= -1 mm、无深穿地为硬性项；膝角差逐帧记录，不放宽脚底标准 |
| 例外 | 已知基线 | `a050_300010` 第 15 帧右膝 12.942°、`a050_301000` 第 0 帧非脚部 -61.042 mm 单独记录，不计脚底失败 |

新增验收量：骨盆世界高逐帧差（F± 对 F0 应为常数 ±50 mm，这是本缺陷的
直接判据）、头部与双手世界轨迹（应为 F0 轨迹加地面偏移，归一差 <=2 mm）。

## 七、风险、回滚与置信度

风险：

1. σt 估计依赖目标脚的静止接触点；接触点提取失败或 CURRENT 参考下
   静止/参考姿势不一致时，固有髋高会偏，表现为整体离地误差。
   缓解：取不到时回退 σt=0（候选现状），且 F0/T2 不受影响（σt 本为 0）。
2. `retarget_pelvis_position` 被姿势通道路径共用
   （`_hips_translation_with_floor` 的 `armature_coordinates` 分支）：
   离地式对通道坐标同样成立，但必须做通道冒烟测试再合并。
3. 支 B（S>Hs）在现有数据中帧数少（站立帧），其离地改写主要靠推导，
   实测覆盖弱；测试矩阵中站立帧（第 0、51、52 帧）要单独核对骨盆差。
4. 来源地面约定（σs=0）不变：来源本身不在世界 0 接地的资产、
   以及 T3 整体平移，仍是已知边界，不在本方案承诺内。

回滚：方案只动 `retarget.py`（几何构建一处 + `height_offset` 一处）与
`foot_ik.py`（`PelvisReference` 加字段 + `retarget_pelvis_position` 改写）。
实施时先备份这两文件并记哈希；回滚即恢复候选现状
（候选 `foot_ik.py` 与正式版同哈希 `B0B86DB6...`，可直接核对）。

置信度：

- 根因（乘法衰减 + 目标高抵消 + 单向复查）：高。
  公式与逐帧数据定量吻合（中位 ±13.41 mm、站立帧 ±1.4 mm、
  与骨盆高度负相关），且 FP/FM/T2/T3 四组现象都能被同一组公式解释。
- 解耦方案能修复 F- 且不回归 F0/F+/T2：中高。
  数学上离地式在 σt=0 时逐字退化、在 F± 时给出完整平移；
  不确定性在 σt 的数据来源（接触点/CURRENT 参考）与支 B 的实测覆盖，
  需实施后用测试矩阵证伪或证实，尤其是骨盆 ±50 mm 逐帧判据。

本轮只审计与规划，未修改候选或正式代码。完成后停止，等待确认。
