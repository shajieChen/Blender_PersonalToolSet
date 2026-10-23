# 第二阶段候选修复报告：骨盆离地坐标映射 + `height_offset` 去重

日期：2026-10-21。本轮只实施候选修复与验证；**未修改正式插件（仍 1.7.5）、未升版本、未合并**。结论与全部数字均为本轮实测（标注来源）。

## 0. 路径核实（任务给定路径有误）

- 任务所述 `tmp_forearm_foot_sink_investigation\pelvis_floor_audit.md`、`tmp_forearm_root` 在工作区不存在。
- 实际审计报告：`tmp_forearm_roll\foot_sink_investigation\pelvis_floor_audit.md`。
- 实际候选（第一阶段已通过 F0/正地面、负地面失败）：`tmp_forearm_roll\floor_candidate_root\humanoid_retarget\`。
- 本轮在此候选上继续，正式插件目录（`%APPDATA%\...\addons\humanoid_retarget\`）未触碰。

## 1. 保护与备份（实测哈希）

实施前备份目录 `foot_sink_investigation\backup_pre_pelvis_fix\`，与实施前候选逐字节一致：

| 文件 | 实施前（候选=备份） | 实施后（候选） |
|---|---|---|
| `foot_ik.py` | `B0B86DB6241ADEEFD39D4A60E1FC652B99BEB991330D6549F130408DB4CC08CE` | `D00892151787BA373781AB537AFE96442ECA3AB68895769E0E984373B413E650` |
| `retarget.py` | `18B9DCE2AC5C05DC516599211C00ED1521E64193B5CBDA1490EB56182F8C1806` | `AC2505F17D18D2AB794779172C5B90C14392D1E712EFCD12E5C81EFC5546CEDA` |
| `ik.py` | `0ED8BB563226F5E5C7739249303AEEA5ACAEBCCFE5D3D987A3236D78E9CC0B3B` | 不变（本轮未改） |

正式插件 1.7.5 实施后复核不变：`__init__.py E5AF5096…`、`retarget.py EDBFAFB5…`、`foot_ik.py B0B86DB6…`、`ik.py AD87866E…`、`motion_space.py 4DA6582C…`。未强制骨骼缩放为 1；未改 Two Bone IK、接触容差、首次脚底修正；未覆盖任何历史报告/CSV（本轮新文件：`pelvis_fix_scan.py`、`pelvis_fix_frames.csv`、`pelvis_fix_curfb_frames.csv`、`*_probe*.py/log`、两份分文件 diff 与合并 `pelvis_fix_candidate.diff`）。

## 2. σt 来源核实（先测后改）

审计假设的接触点 σt（`_extract_foot_contact_local`， heel/fore 点）实测：目标静止接触点世界高恒为 **+6.511 mm**（三地面下固有髋高 530.504 mm 恒定，提取本身可靠），但若直接用作 datum，F0 骨盆比值变为 `530.504/965.553`，相对现行 `537.015/970.0` 偏移 **−0.76%（骨盆约 −3~−4 mm）**，必然突破 F0 基线。故未采用接触点 σt（不机械照搬审计公式）。

改用与接触复查同口径的**蒙皮 bind 点**（`_extract_foot_skin_points`，脚部区域权重 >0.2 的 bind 顶点，静止姿势、目标运动空间取最低 z）：

| 量 | 来源（source） | 目标（target） |
|---|---|---|
| σ（运动空间，f=0） | 3.984 mm | 2.499 mm |
| 静止髋高（运动空间） | 970.000 mm | 537.015 mm |
| 固有髋高（减 σ） | 966.016 mm | 534.516 mm |

固有比值 `534.516/966.016 = 0.553505` vs 现行比值 `537.015/970.0 = 0.553624`，差 −0.0215%（F0 骨盆约 −0.08 mm）。

σ 的地面/平移不变性在扫描中实测：FP 时 σt=−47.501、FM 时 σt=+52.499（即世界恒 2.499）；T3 时 σs=53.984、来源固有髋高仍 966.016。提取失败（任一刚体无可用脚部蒙皮）时采用 **both-or-neither 回退**：双侧 σ 全置 0、地面回加量置 0，严格退化为第一阶段候选公式（见 F2 实测 0.000 mm）。

## 3. 公式：修正前 → 修正后（代码，`foot_ik.py:retarget_pelvis_position`）

修正前（第一阶段候选，与 1.7.5 同式）：

```
ratio       = Ht / Hs
base        = current * ratio
branch A: percent = (S - cs) / (Hs - cs);  constrained = (Ht - ct) * percent + ct
branch B: constrained = S + Ht - Hs
position.z  = base.z + (constrained - base.z) * weight        （Ht = Ht_w - f，乘法衰减 f）
```

修正后（离地坐标；σs、σt 为静止蒙皮脚底的运动空间高度，`Ht_i = Ht - σt`、`Hs_i = Hs - σs`，回加量 `σt_world = σt + f`）：

```
ratio       = Ht_i / Hs_i
base.z      = σt_world + (S - σs) * ratio        （x/y 同乘 ratio）
branch A: percent = (S - σs - cs) / (Hs_i - cs); constrained = (Ht_i - ct) * percent + ct + σt_world
branch B: constrained = (S - σs) + Ht_i - Hs_i + σt_world
```

世界地面偏移只经运动空间原点（`armature_position`）应用一次；ratio、percent、constrained、`pelvis_delta`（结构未变，z 分量仍由 `position - base` 得出）全部使用同一离地语义。σs=σt=0 时新公式逐项退化为旧公式。

`height_offset`（`retarget.py`，LimbReference 构造）：`tgt_end.z - src_end.z` → `tgt_end.z - src_end.z + floor_height_m`（tgt_end 在以地面为原点的运动空间测得，加回 f 后恢复世界 datum，消除重复计入的 −f）；`armature_coordinates` 姿势通道路径保持旧式不变。实测四配置下 `height_offset` 在 F0/FP/FM 恒为 −14.885 mm（地面无关），CURRENT 下 −15.884/−15.900 mm。

第一阶段已验证的目标运动空间与蒙皮复查修正（`ik.py`、`retarget.py` 第一阶段改动）全部保留，`ik.py` 本轮零改动。

## 4. 测试矩阵结果（实测，`pelvis_fix_frames.csv` 1060 行；基线为第一阶段 `floor_fix_frames.csv`，其 F0 已经归档 A 组核对）

### F0 默认地面：通过

| 动作 | Δ骨盆Zmax | Δ头Zmax | Δ踝误差max | 接触脚底min | 复查抬升max | 膝min |
|---|---|---|---|---|---|---|
| a050_300000 | 0.138 mm | 0.139 mm | 0.0031 mm | −1.000（n=27） | 163.0 mm | 15.000° |
| a050_300010 | 0.127 | 0.126 | 0.0015 | −0.999（27） | 149.9 | 13.042° |
| a050_301000 | 0.186 | 0.186 | 0.0017 | −0.955（24） | 160.5 | 15.000° |
| a050_302011 | 0.145 | 0.145 | 0.0019 | −0.996（25） | 160.2 | 15.000° |

接触脚底最差帧与第一阶段逐帧相同（如 301000 第 22 帧右脚 −0.955）；复查抬升量与归档值一致（163.0/149.9/160.6→160.5/160.3→160.2，0.1 mm 级舍入差）。

### F1 正负地面：通过（负地面悬空消除）

四动作 × FP/FM，逐帧与自身 F0 比较（世界坐标减去地面偏移）：

- 骨盆世界高度差 **≤0.001 mm**（要求 ≤2 mm）；头部 ≤0.001 mm；双手 ≤0.001 mm；膝角差 ≤0.010°。
- 接触脚底相对地面 min 与 F0 完全相同（−1.000/−0.999/−0.955/−0.996）；无任何帧脚底低于地面 −10 mm。
- 对照第一阶段：FM 接触脚底悬空 +16.9…+55.5 mm 已消除；骨盆世界高度由仅 −13.4 mm（衰减）变为精确 −50 mm 平移。
- 全帧网格最低点（相对地面）除已知例外外 ≥−2.7 mm（300010 第 17 帧 −2.7 mm 在 F0 基线中同样存在，非脚部、非本轮引入）。

### F2 特殊路径：通过（附归因）

- **CURRENT 参考**（300000 第 0 帧捕获）：`CURFM` 相对 `CUR0` 归一化骨盆/头部差 0.001 mm，接触脚底 −0.997 mm，地面平移在 CURRENT 模式下同样成立。`CUR0` 相对 REST 烘焙骨盆差 15.066 mm、头部 55.894 mm——归因实测：σ=0 回退版 CURRENT（`CURFB0`）相对 REST 同样差 15.066/55.894 mm，而 σ 在 CURRENT 中的贡献仅 0.105 mm；该差为 CURRENT 参考语义本身（捕获的来源髋高 942.771 而非静止 970），非本轮引入。
- **σ 提取失败回退**：`FB0`、`FBFM` 相对第一阶段对应结果骨盆差 **0.000 mm**，严格复现旧行为；`FBFM` 接触脚底最大悬空 +45.804 mm，即旧失败模式原样保留、无新失败模式（回退的已知代价，报告明示）。
- **公式分支覆盖**：分支 A 覆盖全部 F0/FP/FM 帧（站立与下蹲）；分支 B（来源髋高于静止）在 T3 第 0/50/51/52 帧与 SRC_RAISED 第 0/52 帧实测触发（来源髋世界 z>970 mm）。

### F3 平移不变性与已知例外：**T2 回归、T3 恶化（本轮主要问题）**

- **T2（地面与目标同 +0.05）由第一阶段的等价变为失败**：归一化骨盆/头部差 **+50.000 mm**（全部帧），接触脚底最小悬空 +34.706（300000）/+41.488 mm（301000），膝角差最大 13.4°/20.3°。根因：回加量 `σt + f` 与 `height_offset + f` 都把“目标物体自身平移”误作地面偏移重复计入（T2 中 `tgt_ground_world` 实测 52.499 mm、`height_offset` +35.115 mm）。已证明这是 datum 三难：回加量若只依赖运动空间量则 F± 无法平移
...[truncated 3079 chars]