# 独立 Datum 候选实施报告

日期：2026-10-21。本轮只修改独立候选 `tmp_forearm_roll\floor_candidate_root\humanoid_retarget\`；**正式插件保持 1.7.5（哈希复核不变）、未升版本、未合并**。全部数字为本轮实测。

## 1. 实施前检查

- 报告实际路径：`tmp_forearm_roll\foot_sink_investigation\{pelvis_fix_report.md, pelvis_floor_audit.md}`（任务所述 `tmp_forearm_foot_sink_investigation` 不存在）。
- Git：工作区既有脏状态（`humanoid_retarget/`、`tests/` 等）与候选目录的未跟踪状态均未触碰；候选以第二阶段状态为起点（`foot_ik.py D0089215…`、`retarget.py AC2505F1…`、`ik.py 0ED8BB56…`、`pipeline.py 33509C9C…`）。
- 备份：`foot_sink_investigation\backup_pre_datum_fix\`（上述四文件，与实施前候选逐字节一致，哈希见下表）。
- 测试进程导入断言：扫描脚本对四个被测模块逐一断言候选路径与 SHA-256（见 §3），不存在误测正式插件。

## 2. 精确 diff 与文件哈希

合并 diff：`datum_fix_candidate.diff`（分文件：`datum_fix_{foot_ik,retarget,ik,pipeline}.diff`），相对第二阶段候选。

| 文件 | 实施前 | 实施后 |
|---|---|---|
| `foot_ik.py` | `D00892151787BA373781AB537AFE96442ECA3AB68895769E0E984373B413E650` | `E10538A060FF90DB034C19A3B10323855BA8EB14B33D8F997C42943D5036A3CD` |
| `retarget.py` | `AC2505F17D18D2AB794779172C5B90C14392D1E712EFCD12E5C81EFC5546CEDA` | `2BF90D021E475208675401E7366F2EE3BFE695016FCB5D791B72D17946DCB1CE` |
| `ik.py` | `0ED8BB563226F5E5C7739249303AEEA5ACAEBCCFE5D3D987A3236D78E9CC0B3B` | `510331A44DF47D67DEB1CE5E88C0E214734B13ADEFBF5FC49790E81C48E135FB` |
| `pipeline.py` | `33509C9C4154F5849151FB89E4D5BBA6AA9DB0334D766B90663148FB5AFBDBDA` | `404D58C2B0B118EB05277C3FD3C4D59C41F3B7D4F21295D4C0908A23104D8368` |

改动要点（第二阶段的 σ 现场推算与两处 `+f` 已全部移除）：

- `foot_ik.PelvisReference`：删除 `source_ground_z/target_ground_z/target_ground_world_z`，新增 `source_datum_height/target_datum_height/source_datum_matrix/source_datum_scale`（默认 None）。
- `foot_ik.retarget_pelvis_position`：Datum 存在时 ratio、percent、两分支、裆偏全部用 Datum 高度（当前髋高经 `current_datum_z` 传入）；公式中不出现 `floor_height_m`。Datum 缺失时走与 1.7.5 逐项一致的旧公式（整体回退）。
- `retarget.capture_ground_datum/_load_ground_datum/_datum_height`：Datum 捕获、读取与高度换算；`_prepare_retarget_geometry` 只读取 Datum 计算参考髋/踝 Datum 高度，`height_offset` 改为双侧静止踝 Datum 高度差；`_hips_translation_with_floor` 由来源 pose 局部髋点经 Datum 矩阵算当前 Datum 高度。
- `ik.apply_contact_ik`：`constrain_goal_floor` 的来源踝高换为 Datum 高度（与骨盆同语义）；无 Datum 时保持旧运动空间高度。
- `pipeline.pick_armature`、`pipeline.load_target_and_retarget`（自动绑定分支）、`retarget.capture_reference`：登记/捕获时生成 Datum。

## 3. Datum 捕获、存储、读取、回退调用链

**捕获**（登记时，仅此时读取对象当前矩阵）：

```text
pipeline.load_source -> pick_armature -> retarget.capture_ground_datum(armature)
pipeline.load_target_and_retarget -> pick_armature / auto_rig -> capture_ground_datum(armature)
retarget.capture_reference -> capture_ground_datum(src) + capture_ground_datum(tgt)（刷新）
```

`capture_ground_datum` 用 `_extract_foot_skin_points`（与蒙皮复查同口径）取脚部 bind 点，以捕获时刻 `matrix_world` 最低者为静止脚底，并把 `{version, matrix（捕获矩阵）, sole（局部脚底点）, meters_per_unit}` 以 JSON 存入 Armature 对象自定义属性 `hr_ground_datum`。提取失败返回 None 且**不覆盖**已有 Datum。

**存储**：对象自定义属性（随 .blend 保存、随对象走），内容是 Armature 局部量与捕获矩阵，后续对象平移、地面改高均不重算。

**读取**（烘焙时）：`_prepare_retarget_geometry` 经 `_load_ground_datum` 解析；Datum 高度 \(h_D(a) = (M_{cap}\cdot a)_z \times \text{meters\_per\_unit}\)。参考髋高、静止踝高差、当前髋高（`_hips_translation_with_floor`）、当前踝高（`ik.py`）全部由此计算。实测每种配置下 Datum 髋高恒为来源 970.000 mm / 目标 537.015 mm、`height_offset` 恒为 −14.885 mm（F0/FP/FM/OBJ_ONLY/SRC_ONLY/T2/T3 全部一致）。

**回退**（整体、明示）：任一侧无 Datum（或姿势通道 `armature_coordinates` 路径）→ 骨盆与踝高整体走旧公式并打印警告「非零地面接地与平移不变性不保证」；禁止新旧混用（both-or-neither）。

**地面只应用一次**：配置地面仅经 `MotionSpace` 原点（`armature_position/world_position`）与运动空间内的蒙皮复查进入；骨盆/踝高公式不含 \(f\)，对象平移仅经对象矩阵在写回/求值时进入。

## 4. 测试结果（逐帧：`datum_fix_frames.csv`，1272 行；脚本断言候选四模块哈希）

### F0（地面 0，对归档基线）：通过

四动作骨盆/头部逐帧差 **≤0.001 mm**（第二阶段为 ≤0.186 mm），踝误差差 ≤0.0027 mm，接触脚底 min −1.000/−1.000/−0.955/−0.996 mm、复查抬升 163.0/149.9/160.6/160.3 mm 与归档逐项一致；已知例外数值精确恢复：`a050_300010` 第 15 帧膝 160.339°/12.942°（归档同值）、`a050_301000` 第 0 帧网格最低 −61.042 mm 且双脚脚底为正（非脚部，确认）。

### F1（地面 ±0.05 m）：通过

四动作 × FP/FM：骨盆、头部、双手世界轨迹相对 F0±50 mm 逐帧差 **≤0.001 mm**（标准 ≤2 mm）；膝角差 ≤0.002°，踝误差差 ≤0.0046 mm；接触脚底相对地面 min ≥ −1.000 mm（与各自 F0 相同），无脚底低于地面 −10 mm 的帧。接触分类帧的脚底最大值（如 301000 的 +90.152 mm）在归档 F0 中同值出现，属接触分类伪影而非接地失败，接地以 min/贴地帧判定。

### F2（参考模式）：通过

- CURRENT：`CURFM` 相对 `CUR0` 归一化骨盆/头部/双手差 ≤0.001 mm、膝差 0.089°，接触脚底 −0.997 mm；`CUR0` 相对 REST 差 15.075 mm 与旧公式的 15.066 mm 同量级，属参考语义本身（不主张等价，符合任务要求）。
- Datum 缺失回退（删属性）：`FB0/FBFM` 相对第一阶段对应结果骨盆差 **0.000 mm**；`FBFM` 接触脚底 +32.786…+55.479 mm，即旧失败模式原样复现——回退路径不保证非零地面接地，已明示。
- 无蒙皮提取失败：模拟 `_extract_foot_skin_points` 返回空集后 `capture_ground_datum` 双侧返回 None、不写属性；烘焙走整体回退（`NOSKIN0/NOSKINFM` 同样 0.000 mm 复现旧行为）。
- 公式分支：语料中来源 Datum 髋高从未超过静止 970 mm，分支 B 未被语料触发；已用合成向量单独对照（分支 A/B、权重 0.5/0.7/1.0、裆偏 0/0.02 共 4 例），Datum 公式与旧公式在 \(f=0\) 输出逐项相同（`datum_branch_probe.log`）。

### F3（坐标变换独立性）：通过

| 配置 | 结果（相对 F0） |
|---|---|
| 仅改地面（FP/FM） | 世界 = F0 ± 50 mm，差 ≤0.001 mm（见 F1） |
| 仅平移目标对象 +0.05（OBJ_ONLY，300000/301000） | 世界轨迹与 F0 差 ≤0.001 mm，接触脚底不变——对象平移不改变烘焙世界结果，地面相对量不变 |
| 仅平移来源对象 +0.05（SRC_ONLY） | 与 F0 差 ≤0.001 mm（第二阶段此处曾差 7.436 mm） |
| 地面+目标同移（T2，300000/301000） | 归一化骨盆/头部/双手差 ≤0.001 mm，膝差 ≤0.001°，接触脚底与 F0 相同（第二阶段此处为 +50.000 mm，已修复） |
| 来源+目标+地面同移（T3） | 归一化差 ≤0.001 mm，接触脚底 −0.999 mm（由既有限制变为通过） |

## 5. 失败帧、剩余风险与回滚

- 硬性测试失败帧：无。F2 回退路径的 FM 悬空（+32.8…+55.5 mm）是**已记录的不保证路径**，非 Datum 路径失败。
- 剩余风险：
  1. Datum 以捕获时刻的对象矩阵与场景单位为准；登记后若用户**旋转/缩放**对象，Datum 高度会陈旧，需重新登记或重新捕获参考（本轮只验证平移不变性）。
  2. 姿势通道路径（`armature_coordinates`）与 Rigify metarig 跳板路径未纳入 Datum（整体旧公式），本矩阵未覆盖，合并前需单独冒烟。
  3. 无蒙皮/提取失败的刚体只能走回退，非零地面不保证（已明示并实测复现）。
  4. 分支 B 仅有合成验证，语料无覆盖。
- 回滚：把 `backup_pre_datum_fix\` 的四文件覆盖回候选即恢复第二阶段状态（哈希见 §1/§2）；对象上的 `hr_ground_datum` 属性对旧代码无影响，可保留或删除。正式插件全程未动。

## 6. 结论

F0、F1、F2、F3 全部硬性判据通过，且 T2/T3 与第二阶段相比由失败变为逐帧等价。**从本轮测试范围看，Datum 候选已消除已知的合并 blockers**；合并仍需你审核裁决（姿势通道/metarig 路径不在本轮覆盖内）。本轮不合并、不升版本，到此停止。
