# Datum 候选 B1/B2 修复报告（仅候选副本，未合并）

正式插件保持 **1.7.5**（任务书「1.7.1.5」为笔误，已实测 `bl_info["version"] = (1, 7, 5)`，官方六文件哈希与历轮记录一致，未改动）。工作区 git 仍为原有 29 行未提交修改，未触碰。

## 修改范围

仅候选 `floor_candidate_root\humanoid_retarget\retarget.py` 一个文件。

| 文件 | 修复前 SHA-256 | 修复后 SHA-256 |
|---|---|---|
| 候选 `retarget.py` | `2BF90D021E475208675401E7366F2EE3BFE695016FCB5D791B72D17946DCB1CE` | `40B95B68D864B66DB80E57083305F7A9CDA8F7B893336C265E659D277BC0F9DA` |
| 候选其余文件 | 不变（`foot_ik E10538A0…`、`ik 510331A4…`、`pipeline 404D58C2…`） | 同左 |

- 修改前备份：`foot_sink_investigation\backup_pre_b1b2_fix\retarget.py`（哈希与修复前候选一致）。
- 精确 diff：`foot_sink_investigation\datum_guard_retarget.diff`（183 行，仅 `retarget.py`）。

## B1 修复：Datum 语义校验

新增 `_validated_ground_datum(arm, roles)`，在 `_prepare_retarget_geometry` 中替代原结构-only 的 `_load_ground_datum` 读取（原函数保留未删）。校验顺序：

1. 结构：可解析 JSON、`version == 1`、必需字段齐全、矩阵 4×4、脚底 3 分量、类型可转数值。
2. 有限性：全部数值 `isfinite`（含显式拒绝 Python `json` 接受的 `NaN`/`Infinity` 字面量），`meters_per_unit` 有限且 > 0（单位校验）。
3. 语义（脚底一致性）：从当前 armature-local bind 几何重算最低脚底点（`_foot_skin_points`，要求左右腿均有蒙皮点），与存储 `sole` 比较。bind 点与对象变换无关，故登记后平移/偏航不会误判；蒙皮编辑或伪造 Datum 会被检出。容差 `1e-4` armature 单位——依据是提取确定性 + JSON 全精度往返，未变几何重算应精确相等，容差仅吸收 min 选择的浮点舍入（代码注释已注明，未随意放大）。
4. 髋高合理性：Datum 髋高须有限且在 0.01–100 m（覆盖任何合理人形髋高量级；伪造单位矩阵曾给出 −153 mm 级荒谬值）。

任一侧无效 ⇒ 双侧整体回退旧公式（both-or-neither 不变），并打印带侧别与具体原因的警告，如「地面 Datum 不可用（目标: Datum 脚底基准与当前 bind 几何不一致（已过期或损坏）），骨盆/踝高整体回退旧公式：非零地面接地与平移不变性不保证。」捕获侧同时收紧：`capture_ground_datum` 改走 `_foot_skin_points`，左右腿缺一即捕获失败返回 None 且不覆盖既有 Datum（坐标空间/左右脚预期在捕获与校验两侧一致）。

## B2 修复：姿势通道路径

`_prepare_retarget_geometry` 在 `armature_coordinates=True` 且 `foot_ik` 开启时：`floor_height_m == 0` 行为完全不变；非零地面先打印日志（路径名、当前地面高度、限制原因），随即 `raise RetargetError` 阻止不受支持的烘焙，不再静默回退旧公式。未放宽任何接地阈值。Rigify 跳板、无蒙皮回退按既有范围未动。

## 实测结果（候选，`datum_guard_scan.py` / `datum_guard_regression_scan.py`）

### B1（对比 Datum 轮归档帧，53 帧/配置）

| 案例 | 修复前 | 修复后 |
|---|---|---|
| 合法 Datum（FM/FP） | 正常使用 | 与 Datum 轮逐值一致（Δ 0.000 mm），接触脚底 min −1.000 mm |
| 缺失 Datum（双侧/单侧） | 回退+警告 | 与旧公式 FBFM/FB0 逐值一致（0.000），警告注明侧别与「未捕获 Datum」 |
| 乱码 `{}`、残缺矩阵、字符串 scale、NaN 矩阵 | 回退 | 全部拒绝并回退 FBFM 逐值一致，警告给出具体原因 |
| 伪造单位矩阵（目标侧 / 来源侧） | **静默信任：骨盆偏差 +720.876 mm、脚底穿地约 748 mm**（本轮复测 LWRONG vs FBFM：719.472 mm / 接触 −686.149 mm） | **被拒绝**：整体回退， 与 FBFM 逐值一致（0.000），警告「脚底基准与当前 bind 几何不一致」 |
| 登记后平移 +50 mm | 正常 | Datum 不误判：TRANSL_F0 与 OBJ_ONLY 逐值一致，TRANSL_FM 与 FM ≤0.001 mm |
| 登记后偏航 30° | 正常 | Datum 不误判：YAW_F0/YAW_FM 与修复前 LYAW/LYAWFM 逐值一致（0.000） |

损坏 Datum 是否全部被拒绝：**是**（本轮 6 类目标侧损坏 + 来源侧伪造，全部整体回退且有警告）。

### B2（姿势通道，`joint_limits` 触发）

| 地面 | 修复前 | 修复后 |
|---|---|---|
| Z=0（CHAN0） | 静默旧公式 | 烘焙成功，与修复前 CHAN0 逐值一致（0.000） |
| Z=+0.05（CHANFP） | 静默旧公式（骨盆误差不报告） | **明确报错阻止**：`RetargetError` 含路径 `armature_coordinates`、`floor_height_m=0.050` 与原因 |
| Z=−0.05（CHANFM） | 静默旧公式（归一化骨盆 Δ 48.597 mm） | **明确报错阻止**：同上，`floor_height_m=-0.050` |

姿势通道是否能明确识别不支持的地面配置：**是**（日志 + 异常双通道，含路径、地面高度、限制原因）。

### 核心回归（四动作 × 三地面 + CUR/T2/T3/FB/NOSKIN/OBJ/SRC，共 1272 帧）

`datum_guard_regression_frames.csv` 与 Datum 轮 `datum_fix_frames.csv` **逐值完全一致**：骨盆/头部/踝/脚底/求解误差/膝角最大差均为 **0.0**；F0/F1/F2/F3 结论保持；已知基线异常保留（`a050_300010` 第 15 帧右膝 12.942°；`a050_301000` 第 0 帧非脚网格最低 −61.042 mm，脚底 +2.206/+14.060 mm）。无核心回归失败。

## 剩余限制（与验证轮一致，不在本轮扩展）

- 登记后倾斜姿态、登记后均匀缩放：Datum 地面语义之外/单位换算固有限制（缩放需重新导入），验证轮已定性。
- 姿势通道与 Rigify 跳板：非零地面仍不支持（B2 后由「静默错误」变为「明确拒绝」；Rigify 维持既有限制声明）。
- 无蒙皮回退：非零地面接地不保证（既有文档化行为）。
- 分支 B 仅合成等价覆盖（语料未触发）。

## 回滚与合并建议

- 回滚：将 `backup_pre_b1b2_fix\retarget.py` 拷回候选 `floor_candidate_root\humanoid_retarget\retarget.py` 即恢复修复前候选（其余文件未动）。
- 合并建议：B1/B2 两项阻塞已消除且核心回归零变化，建议按验证轮结论走「限制范围后可以合并」复审（支持范围与限制清单见 `datum_validation_report.md`，外加本轮 B2 的明确拒绝行为）。**本轮未合并、未升级版本、未动正式插件，等待审核。**

## 证据文件

- `datum_guard_frames.csv`（守卫 901 行）、`datum_guard_run.log`（警告/BAKE_ERROR 原文）
- `datum_guard_regression_frames.csv`（1272 行）、`datum_guard_regression_run.log`
- `datum_guard_retarget.diff`、`_analyze_datum_guard.py`、`_analyze_transl.py`、`_analyze_datum_regression2.py`
