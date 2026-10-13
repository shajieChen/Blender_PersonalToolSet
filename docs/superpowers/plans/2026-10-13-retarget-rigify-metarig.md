# Rigify human metarig 实施计划

> 执行方式：后续得到代码修改授权后，使用 writing-plans 对应的逐项执行流程，由主线程直接实施。不派子代理，不恢复 stash，不提交或推送。本轮仅编写本文和设计文档，不修改 `.py`。

```text
失败测试 -> 设置与加载 -> 两端校准 -> 两跳烘焙
                                      |
                   清理临时诊断 <- 聚焦与完整回归
                          |
                      清理后复验
```

## 目标

在步骤 1 上方选择 `Rigify human metarig` 中间标准，使用完整 Human 样本的身体 rest 定义，通过现有 swing solver 两跳转换；保留直接映射。

设计依据：`docs/superpowers/specs/2026-10-13-retarget-rigify-metarig-design.md`。

技术栈：Blender 5.1.2、现有 Python 插件、`bpy`、`mathutils`、现有 headless 测试脚本。不是 C++ 构建任务。

本计划不是代码修改授权，也不是手腕或 pelvis yaw 修复计划。两份 revision 的 `DO_NOT_PATCH` 保持有效。

## 修改范围

| 文件 | 后续修改职责 |
| --- | --- |
| `humanoid_retarget/__init__.py` | `HRSettings.standard_skeleton` 枚举、`HR_PT_panel.draw` 位置、`_options_from_settings` 传递选择 |
| `humanoid_retarget/retarget.py` | `RetargetOptions.standard_skeleton` 默认 `DIRECT`；不修改现有 swing 数学与链末端行为 |
| `humanoid_retarget/rigify_metarig.py`，新增 | 加载 Human 样本，身体定义值数据、语义角色表、两端校准数据及任务自有中间骨架创建/释放 |
| `humanoid_retarget/pipeline.py` | `retarget_existing`、`load_target_and_retarget`、`retarget_selected_meshes` 统一路径选择及两跳编排 |
| `tests/run_retarget_test.py` | 新模式失败测试、两跳合同、清理测试与既有回归，全部接入 `main()` |
| 两份本次文档 | 执行状态、临时诊断清单、证据和 NotRun 项；不替换既有 revision |

不预先扩展 `mapping.py`、`classify.py`、`ik.py` 或 auto-rig 算法。标准 role 映射放在新模块，复用现有来源/目标分类和用户映射结果。

```text
UI -> pipeline -> bake_retarget
             |
             +-> rigify_metarig -> rigify.metarigs.human
```

## 实施步骤

### 任务 1：复用已读材料，执行前预检

- [ ] 确认用户另行授权 `.py` 修改；未授权就不执行以下实现任务。
- [ ] 保存当前 dirty/deleted/untracked 状态和受影响文件哈希，只记录，不回退或暂存。
- [ ] 复用本轮定位：`HRSettings` 与 `_options_from_settings`、`HR_PT_panel.draw` 的站位/步骤 1 邻接关系、`RetargetOptions`、三个 pipeline 入口、测试 `main()`。
- [ ] `human.py` 的字段与样本事实直接复用用户核实输入；不再次阅读源码。本轮手册只搜索一次且未能重新打开，不追加搜索。
- [ ] 修改前由主线程完整读即将修改的精确函数；未变化的设计/revision 不重复通读。只有文件变化或具体证据冲突时局部刷新。
- [ ] 不安排探子批次。新增独立问题自行限域检查，不扩大到 Rigify 全源码。
- [ ] 核对 Blender 可执行文件、Python API、Action slots、EnumProperty 注册、当前链角色、对象模式切换、异常清理及测试入口。

目标执行入口是 `blender.exe`，配置为 background。受影响测试文件仅 `tests/run_retarget_test.py`；`tests/test_shortcut_hint.py` 不涉及此模式。

### 任务 2：先写不存在模式的失败测试

文件：`tests/run_retarget_test.py`。

- [ ] 增加下表测试并逐一接入 `main()`。测试在首次调用时打印自身名称，结束时记录实际执行数量；不引入默认跳过。
- [ ] 在未加入产品实现时运行。至少验证枚举不存在、Human 定义加载入口不存在、标准烘焙入口未接入这三类可归因失败。测试脚本首次失败会停止，因此各阶段 RED 按新增入口顺序分别保存；禁止靠导入语法错误充当全部 RED。
- [ ] 保存 RED 日志和退出码。`selected = 0`、错误过滤器、陈旧日志或跳过不计入验证。

| 测试名称 | 具体断言与实施前失败原因 |
| --- | --- |
| `test_standard_skeleton_selector` | 注册插件后 RNA 枚举含 `RIGIFY_HUMAN_METARIG` 和 `DIRECT`，前者排第一，默认 `DIRECT`；当前没有该属性 |
| `test_standard_skeleton_panel_order` | 用记录调用的 layout 替身调用 `HR_PT_panel.draw`；标准选择位于 stand_layout 后、首个动画来源 box 前；当前没有该 UI 调用 |
| `test_human_metarig_definition` | 实际加载完整 Human，验证 spine/thigh.L 的 head/tail/roll、thigh.L parent、三段左臂 roll；检查左右身体链与祖先，定义不含首版排除项；当前没有 loader |
| `test_metarig_calibration_keeps_rest` | 保存来源/目标 rest 矩阵、骨 parent 与世界变换；两端校准后逐项不变，同一标准定义分别生成两跳映射；当前没有校准入口 |
| `test_metarig_two_hop_bake` | 合成异名/异 roll 双骨架，同一动作先有中间 Action 再有目标 Action；帧范围一致，链方向按身体坐标满足现有误差容限；当前仅单跳路径 |
| `test_metarig_swing_limits` | IK 关闭的 REST 模式：逐跳 hand_l/r 局部四元数为 identity；纯绕身体 up 的 hips yaw 不被恢复；不得期待手腕/yaw 修复 |
| `test_metarig_same_clip` | 使用多个原始 clip，最终来源/目标显示同一原始 clip；临时中间 Action 不成为用户来源选项 |
| `test_metarig_root_reference_and_ik` | 两跳高度比例乘积等于来源到目标比例；IN_PLACE 只作用最终跳，IK 只最终跳一次；CURRENT 使用各跳独立参考数据 |
| `test_metarig_failure_cleanup` | loader、第一跳及第二跳分别失败：任务临时对象/armature/未交付 Action 消失，原 Action/slot/姿势和 UI 上下文恢复，用户对象不受影响 |
| `test_direct_mode_without_rigify` | 显式 DIRECT，即使 loader 替身报错也不调用它；现有直接烘焙与 same-clip 回归保持有效 |

不得伪造完整 metarig 几何。实际 loader 合同测试在指定 Blender 5.1.2 安装运行；缺少 Rigify 必须报前置条件失败，不静默 skip 并打印成功。

### 任务 3：加入设置及定义加载，取得局部 GREEN

文件：`humanoid_retarget/__init__.py`、`humanoid_retarget/retarget.py`、新增 `humanoid_retarget/rigify_metarig.py`。

- [ ] 在 `HRSettings` 的 stand_layout 后加入 `standard_skeleton: EnumProperty`，标签 `标准人形骨架`。items 顺序为 `RIGIFY_HUMAN_METARIG` / `Rigify human metarig`、`DIRECT` / `当前直接映射`；default 为 `DIRECT`。
- [ ] 在 `HR_PT_panel.draw` 中 stand_layout 的 prop 后、`source_box = layout.box()` 前绘制该字段。
- [ ] `_options_from_settings` 将该值传入 `RetargetOptions.standard_skeleton`。非法值明确拒绝；旧调用未传参时仍为 DIRECT，不静默替换标准。
- [ ] 实现 `load_human_metarig_definition()`：只在标准模式导入 `rigify.metarigs.human`，在主线程创建任务自有样本 armature，调用 `create(obj)`，提取身体字段和必要祖先，随后在 `finally` 清理提取样本。
- [ ] 用清晰的身体骨记录保存 name、parent、head、tail、roll；从样本读取完整字段，不只硬编码给定示例。以实际 rest 与链连接核验显式 role 映射，不凭骨名猜 hips。
- [ ] 输出定义版本身份；排除 face、breast、ear 和首版不用的手指，保留身体祖先原始 parent。缺失核心链、零长骨、循环 parent 或错误样本应报错。
- [ ] 对前三项测试取得可归因 GREEN；不得修改求解器以让字段/UI 测试通过。

不调用 Generate Rig，不匹配 ORG/DEF/MCH/控制骨，不引入通用接口或全局定义缓存。

### 任务 4：校准来源与目标，创建中间 armature

文件：`humanoid_retarget/rigify_metarig.py`、`tests/run_retarget_test.py`。

- [ ] 实现 `create_human_metarig_armature(definition)`，仅操作任务自有骨架，按定义重建身体 parent/head/tail/roll。
- [ ] 实现 `calibrate_source_to_metarig` 和 `calibrate_target_to_metarig`，生成明确的 role/bone 对应、身体坐标、高度比例及参考姿势值；不修改来源/目标 rest 或 matrix_world。
- [ ] 对 `REST` 使用各跳 rest；对 `CURRENT` 在同一参考帧分别调用既有 `capture_reference`，捕获来源到 metarig、以及 metarig 到目标这两组数据。
- [ ] 保持同一个标准定义，不把来源绝对 orientation 写入标准 rest；骨骼局部轴由 head/tail/roll 决定。
- [ ] 两端 core roles 缺失则在目标写入前失败，错误指出缺失角色；直接模式仍沿用原有错误行为。
- [ ] 验证校准不改变原对象、左右 role 不混淆、临时骨架从正确定义创建；再取得校准测试 GREEN。

### 任务 5：统一 pipeline 入口，逐跳复用 swing

文件：`humanoid_retarget/pipeline.py`、`tests/run_retarget_test.py`。

- [ ] 增加 `retarget_through_human_metarig(source, target, options)`，作为一个明确业务函数，不建 Manager/Context/注册器。
- [ ] 三个产品入口都经 `retarget_existing` 选择 DIRECT 或标准模式。导入、自动绑定和原有失败封装保持原职责。
- [ ] 标准模式先完成定义和两端校准，再为每个原始来源 clip 调用 `bake_retarget(source, metarig, first_options)`，随后调用 `bake_retarget(metarig, target, second_options)`。
- [ ] 每跳传各自映射和 reference_data；中间 Action 只参与当前 clip 的第二跳，避免跨 clip 或重复转换。
- [ ] 第一跳关闭手脚 IK，root_motion 为 KEEP；第二跳按用户设置处理 IK 与 root_motion。验证两跳比例连乘，没有最终比例重复乘两次。
- [ ] 记录原始 clip 与最终 Action 的关系，保持同帧范围、同采样时刻、Action slots 和 same-clip 显示。不能从临时 Action 名推测原始 clip。
- [ ] 将第二跳结果映射回原始来源到最终目标的用户映射；`options.resolved_pairs` 不泄漏中间骨名。
- [ ] 在 `try/finally` 释放本次拥有的中间对象、数据和未交付 Action；失败恢复用户原状态，成功保留最终 Action。
- [ ] 依次取得两跳、限制、same-clip、root/reference/IK、失败清理与 DIRECT 测试 GREEN。

不得修改现有 swing、hand 链末端或 hips-to-spine 数学。限制测试在 REST FK / IK 关闭条件下检查；CURRENT 或 IK 结果不拿来否定用户已核实限制。

### 任务 6：完整验证与临时诊断清理

- [ ] 修改后先核对 API、导入方向、类型、模式、Action slots 和清理对称性；确认没有 bpy worker thread、全局状态或依赖环，再启动 Blender。
- [ ] 运行聚焦测试；记录实际执行数量、每项结果和进程退出码。不要新增永久过滤框架。
- [ ] 在 PATH 已含 Blender 安装目录的 PowerShell 中运行指定命令：

```powershell
blender.exe --background --python H:\Blender_Plugin\tests\run_retarget_test.py
```

预期最终输出 `RETARGET_TEST_OK`，同时进程退出码为 `0`。脚本中异常输出 `RETARGET_TEST_FAIL` 或非零退出码均不计 GREEN。没有该标记也不计通过。

- [ ] 完整回归必须实际调用新增测试及既有 `test_swing_preserves_target_roll`、`test_bake_displays_same_source_clip`、映射/root/reference/IK、站位、导入/导出和其余 main 测试，不只跑新枚举。
- [ ] 如遇明确 API/导入/语法错误，停止本次运行，保存日志，最小修复后才重跑；禁止在代码不变时重复尝试。
- [ ] 在 Blender UI 检查选择器位置、第一项/默认值、同 clip 显示以及临时骨架不可见。Visual 单独记录，headless 输出不能替代。
- [ ] 如另行执行真实 GLB/FBX 核验，记录同一原始 clip、第 37 帧手和 pelvis 测量；这只是新路径测量，不自动解除 DO_NOT_PATCH，也不要求匹配旧直接模式的数值。
- [ ] 保存必要 RED/GREEN/回归日志、输入身份和测量证据，不覆盖用户资产或场景。
- [ ] 清理本次临时埋点、调试日志、采样/计数、轮询、诊断钩子、配套开关及仅为诊断加入的脚本/依赖。仅删除本次可归因且非正式功能依赖的内容。
- [ ] 清理后检查差异，再跑聚焦和上面完整命令；涉及运行开销则复核中间对象生命周期、后台无残留和双跳耗时。UI 路径变更需重新 Visual 检查。

### 材料与效率记录

| 已读/已给定材料 | 结论及复用边界 |
| --- | --- |
| 用户核实 `human.py` 摘要 | 样本保存 rest 字段和 pose 类型；实施时从安装的 human.py 加载，不凭摘要补造缺失字段 |
| `__init__.py` 设置/面板/选项片段 | 设置名及 selector 的精确邻接位置；后续改动前局部刷新 |
| `retarget.py` 选项与用户 solver 事实 | 默认 REST；不把标准切换当成手腕/yaw 修复 |
| `pipeline.py` 三个入口 | 统一路径选择，不分散在 UI 中重复烘焙 |
| `tests/run_retarget_test.py` main/check | 现有测试串行执行；异常失败，最终 `RETARGET_TEST_OK` |
| 两份 revision | `DO_NOT_PATCH` 和给定测量保持有效，不重新搜索候选公式 |

本轮宽输出出现截断，已改用精确入口片段核对，后续不重复整份输出。追加读取必须记录具体缺口；可避免的运行失败记录 API 预检遗漏及修正。没有子代理批次。

## 强制约束

- 标准是完整 Human 的身体样本定义，不是 Basic Human，也不是生成控制 rig。
- `DIRECT` 默认值保证旧行为；只有显式选择标准才触发两跳，失败不静默降级。
- 目标 rest、蒙皮绑定、用户来源和目标对象身份不变。校准不意味着把两端 Edit Mode 骨轴改成一样。
- 中间数据 owner 为当前 pipeline 调用；保存用户状态，成功与异常都清理任务自有临时资源。
- 不复制绝对来源骨轴，不实施已否决 wrist-delta/pelvis 补丁；每跳保持当前 solver 限制。
- 运行上下文、Action/slot 和失败恢复均在主线程。未知 API 兼容性保持 Concern，未运行证据保持 NotRun。
- 代码不新增任何注释；用业务命名表达职责，不用 Adapter、Composition 或泛化 Context/Manager。

## 验收标准

| 层级 | 后续需要的证据 | 状态 |
| --- | --- | --- |
| Static | 两份文档覆盖 UI、标准字段、两端校准、两跳和限制 | 设计与本计划已存在 |
| Contract | 新枚举、loader 数据、错误与所有权测试 | `tests/run_retarget_test.py` 10 项新测试通过 |
| Generate | 任务自有 metarig 创建/销毁；不运行 Generate Rig | 加载后删除样本；烘焙后删除中间骨架；未调用 Generate Rig |
| Build | Python 导入/API 预检；无 C++ 构建项 | `python -m py_compile` 通过 |
| Process / Runtime | selected > 0 RED/GREEN 与退出码 0 的完整 `RETARGET_TEST_OK` | `METARIG_TEST_COUNT 10`，随后原有套件，`RETARGET_TEST_OK`，退出码 0 |
| Visual | UI 顺序、同 clip、无临时骨架泄漏 | headless 调用 `draw()` 核对了顺序。没有在打开的 Blender 窗口里点选 |
| 正式功能验收 | 以上适用证据、诊断清理及清理后复验全部满足 | 代码验收完成。窗口里的目视验收还未做 |

### 临时诊断清单

本轮新增生产诊断为无。本轮只新增两份文档，没有生成探针、日志脚本或依赖。

后续默认不新增生产临时诊断。若确有需要，实施时逐项记录具体文件、调用点、注册项、开关、资源 owner、清理动作和复验结果。测试替身仅在独立测试进程使用并恢复；必要测试与验收证据保留。

中间 armature 和第一跳 Action 属于正式转换机制，不是应删除的实现代码；它们在每次调用结束必须释放。不得按文件名或对象前缀批量清理。

## 禁止事项

此次不执行上述代码任务，不改任何 `.py`，不重读 Rigify 源码，不追加网页搜索。不恢复 stash，不暂存、不提交、不推送，不派子代理。不修改目标 Edit Mode rest，不线程执行 bpy，不移除 same-clip。不把新增选择器或 headless 成功当成手部、pelvis yaw、Visual 或正式验收完成。

## 实施结果

插件版本为 `(1, 7, 0)`。`标准人形骨架` 在站位和步骤 1 之间。默认 `DIRECT`。选择 `RIGIFY_HUMAN_METARIG` 时，来源和目标都校准到安装的 `rigify.metarigs.human` 身体样本，再用现有 swing 求解器两跳烘焙。中间骨架在视口里用隐藏开关收起，并在调用结束时删除。没有调用 Generate Rig，没有改 swing 数学。

手部仍是单位四元数。来源 40° 的骨盆 yaw 不会原样出现在目标上；human 样本的 spine 链本身不是竖直的，第一跳测得绕世界上方的扭转约 10.4°，第二跳目标低于 5°。这不是手腕或骨盆修订。
