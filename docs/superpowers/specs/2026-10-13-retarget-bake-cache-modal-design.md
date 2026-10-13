# 重定向烘焙：作业缓存与主线程 modal 设计

日期：2026-10-13。状态：第二轮反证评审完成；实现待执行。

```text
同步导入 -> 一次作业缓存 -> 主线程逐帧 swing -> 约 16ms 后让出
                                         -> 成功：既有 same-clip 收尾
                                         -> Esc：清理本次作业并恢复入口状态
```

## 目标

通过缓存重复分类消除主要耗时，通过 modal 让剩余帧循环返回事件循环。保持姿势数学和已交付的同片段显示。

本规格和配套 `../plans/2026-10-13-retarget-bake-cache-modal.md` **取代以下未实施文档作为实施依据**，旧文件保留在磁盘：

- `2026-10-13-retarget-bake-responsiveness-design.md`
- `../plans/2026-10-13-retarget-bake-responsiveness.md`

`2026-10-13-retarget-same-clip-revision.md` **仍约束最终显示**。该文档的“尚未实施”状态已过时：本轮核对 `retarget.py:451-453, 512-537`，入口 Action/slot、来源与目标配对、单片段时间轴均已存在。不得回退到旧响应性文档的“来源最后一段、目标第一段”。

### 反证结果与计时边界

环境：Blender **5.1.2**，hash `ec6e62d40fa9`；加载 `H:\Blender_Plugin\humanoid_retarget\retarget.py`。输入固定为：

- 来源 `H:\SErsiko_ExtactedTool\output\c0000_突刺_wp_a_0300.glb`
- 目标 `C:\Users\chenshajie1\Downloads\body.FBX`
- 10 个片段，503 帧，19 对映射；来源 `model` 133825 顶点，目标 `body00` 615 顶点。
- REST、KEEP、双 IK 关闭；无需自动绑定。`a050_300000` 的整数范围为 **0..52，53 帧**，不能误算成 52 帧。

先找到并检查第一轮日志：

`C:\Users\chenshajie1\AppData\Local\Temp\retarget_review_r1_f86c90985b6d4898bab9faf22d2c5226\time_stages.log`

其中 `classify_armature` 是 cProfile 的函数累计时间，不是包住整个帧体的宽计时器：1008 次，161.652s；包含 `classify_by_name` 158.340s，其中 `skinned_bone_names` 127.333s；另含 `classify_by_geometry` 3.212s。整个 bake 为 169.534s，比例约 95.35%。名称、权重、几何都是分类的子调用，不能再与分类累计时间相加。外层 `frame_set`、`view_layer.update` 和 swing 不在分类调用栈中。1008 = 帧内 1006 + 自动映射准备 2。目标 `correct_deform_pairs` 额外扫描一次权重，在帧外。

原始无 cProfile 日志 `time_stages_raw.log` 的 114.481s 与 169.534s 来自两次运行；后者受 profiler 开销影响，不能相加，也不能用两个数字相减归因。

本轮另跑后台探针，无 cProfile。通过临时 AST 只在当前完整帧体前后加计时；用模块局部代理分别计 `frame_set` 和显式 `view_layer.update`；直接包装分类函数。没有改任何仓库 `.py`。对照组只把重复分类换成内存中的已算结果，保留每帧求解、所有更新和 `keyframe_insert`。映射先解析为相同的 19 对再传入，因此下表不含自动映射的两次准备分类。

| 项目 | 本轮秒数 | 范围 |
|---|---:|---|
| 来源导入 | 2.2962 | `load_source`，独立于 bake |
| 目标导入 | 2.0525 | `import_model`，独立于 bake |
| 单次来源分类 | 0.19509 | 完整 `classify_armature(source)` |
| 单次目标分类 | 0.007984 | 完整 `classify_armature(target)` |
| 来源分类 5 次平均 | 0.24345 | 单次与另 4 次重复；存在调度波动 |
| 目标分类 5 次平均 | 0.007953 | 同上 |
| 单片段当前 bake | 12.9482 | 53 帧；分类 106 次、11.9851s |
| 单片段帧体排除分类 | 0.94957 | 每帧平均 17.916ms |
| 单片段仅缓存分类 | 0.93515 | 帧内真实分类 0 次，缓存读取 106 次 |
| 全片段当前 bake | 115.7333 | 503 帧；分类 1006 次、107.3464s |
| 全片段帧体排除分类 | 8.35233 | 每帧平均 16.605ms |
| 全片段仅缓存分类 | 8.46679 | 帧内真实分类 0 次，缓存读取 1006 次 |

当前全片段 bake 的第一帧：排除分类 **21.515ms**，其中显式更新 **10.866ms**、`frame_set` **8.636ms**。这些子项已包含在帧体中，不再累加到帧体。

缓存对照组全片段：显式更新 9557 次、**5.72217s**；`frame_set` 505 次、**1.51570s**，其中 503 次是烘焙帧，其余为恢复和最终显示。剩余帧体平均 **16.751ms**、最大 **29.504ms**。显式更新约占剩余总时间 68%，但不是当前 114s 冻结的主因。此次仍不做父矩阵递推或删除更新。

仅缓存分类把本轮全片段时间降低约 **92.68%**。实际实现还有约一次来源与一次目标分类的缓存填充成本，自动映射另有常数准备成本。**足以移除 114s 中的大部分耗时**，不承诺产品总时间恰好 8.47s。主线程连续执行 8s 仍然冻结，modal 仍必需。

本轮比较了单片段及全部 10 个目标 Action 的所有 F-Curve：路径、分量、关键帧值、左右手柄、插值和手柄类型，逐项数值完全相同，摘要均相同。此结果支持该输入下的缓存等价；不是对 CURRENT、IK、约束、所有导入文件的通用证明。

### 姿势不变性攻击

源码依据：

- `classify.py:208-212`：`_bone_world` 使用 **`matrix_world @ Bone.head_local/tail_local`**。
- `classify_by_geometry` 读 rest、对象世界变换和骨骼层级，**不读 `PoseBone.head`**。它并非完全与世界变换无关。
- `retarget.py:135-166`：`_body_matrix` 只读 rest `head_local` 与角色名，不读 pose，也不直接读 `matrix_world`。
- `_chain_end` 只读修正后的映射和骨骼层级；`_chain_vector(..., posed=True)` 才读每帧的 pose heads，后者不能缓存。

`a050_300000` 实测：

| 帧 | 来源 roles | 目标 roles | 来源 body columns | 目标 body columns |
|---:|---|---|---|---|
| 1 | 基准 19 项 | 基准 19 项 | 基准 | 基准 |
| 20 | 与帧 1 完全相同 | 与帧 1 完全相同 | 最大差 0 | 最大差 0 |
| 37 | 与帧 1 完全相同 | 与帧 1 完全相同 | 最大差 0 | 最大差 0 |
| 52 | 与帧 1 完全相同 | 与帧 1 完全相同 | 最大差 0 | 最大差 0 |

身体坐标系的列依次为 left、up、forward；以下仅为显示舍入，判断相等使用未舍入数据：

```text
source:
left    ( 1.000000000, -0.000002963, -0.000038393)
up      ( 0.000038496,  0.053088721,  0.998589814)
forward (-0.000000920, -0.998589814,  0.053088721)

target:
left    ( 0.000005481,  1.000000000, -0.000096876)
up      (-0.020122800,  0.000096967,  0.999797523)
forward ( 0.999797523, -0.000003530,  0.020122800)
```

来源上臂 pose head 在四个采样帧变化，故不是因未播放动画而得到假不变。目标在导入后仍挂有自己的动画，采样时 `matrix_world` 变化，但上述 roles 和 body columns 仍相同。实际 bake 清除目标原动画后，矩阵状态与导入播放阶段不同。

第一次监测误把导入动画帧 52 的矩阵当作所有 bake 帧的基准，自动总旗标因此为 false；这不是角色或曲线差异。随后独立运行验证：以第一帧实际求值矩阵为基准，在全部 503 帧比较；名称分类预先保存，几何分类仍每帧实际重算并经原合并规则生成角色图。世界矩阵变化、角色变化、身体坐标系变化均为 **0**。另在实际 bake 内记录了帧 1、20、37、52 的两侧角色和列。

结论：**缓存对本作业是 pose-invariant，反证没有推翻它。** 一般作业仍需世界矩阵失效处理，不能把这一结论扩展为跨调用永久缓存。

### 方案排序攻击

| 顺序 | 方案 | 结论与代价 |
|---:|---|---|
| 1 | 作业缓存 + 主线程 modal 时间片 | 有本轮直接测量支持；无需复制场景，现有求解与撤销边界最小 |
| 2 | 第二 Blender 进程 | 独立进程可以使用自己的 bpy；隔离较强，但要传未保存场景、映射/参考、Action slots，并导回结果与实现取消、撤销 |
| 3 | multiprocessing + 已复制数值 | 仅可计算独立数值；主线程仍负责依赖图、读 pose 和写 Action。Windows spawn、序列化和传输增加边界，剩余 swing 时间未证明值得搬出 |
| 排除 | bpy 工作线程 | 官方 5.1.2 明确不支持；不得排在缓存之前 |

这不是测量过三种实现后的普适安全排行榜。第二进程更适合未来需要隔离同步导入的任务；纯数值进程在独立 CPU 工作很大时可能比第二 Blender 更便宜。本任务里两者没有性能实测，也没有撤销/导回证据，不能据此推翻第一名。官方 Python 文档支持独立进程，但不代表可以复制 Blender RNA 指针到另一进程。[multiprocessing 官方文档](https://docs.python.org/3/library/multiprocessing.html)、[Blender 5.1 命令行](https://docs.blender.org/manual/en/5.1/advanced/command_line/arguments.html)。

本轮实际重开官方 5.1.2 threading 页面，原文：

> “no work has been done to make Blender's Python integration thread safe”

因此本实现禁止工作线程中的任何 bpy 调用。该页甚至要求受支持的有限线程示例在 Blender 主线程被阻塞期间运行，并在继续 Blender API 前 join；这不能用来实现并行 UI 烘焙。[5.1.2 threading 原文](https://raw.githubusercontent.com/blender/blender/v5.1.2/doc/python_api/rst/info_gotchas_threading.rst)。检索未发现能由 5.1.2 官方文档支持的“Blender 5 已使 bpy 线程安全”声明；导入器内部线程或 C++ jobs 不能证明这个声明。

重开的 [modal timer 模板](https://raw.githubusercontent.com/blender/blender/v5.1.2/scripts/templates_py/operator_modal_timer.py) 注册事件计时器和 modal handler，并在 TIMER 中执行 Python。它没有创建工作线程。主线程结论也由 5.1.2 的 [窗口事件源码](https://raw.githubusercontent.com/blender/blender/v5.1.2/source/blender/windowmanager/intern/wm_window.cc) 的主线程断言及定时器事件入队支持。**modal 是协作式让出，不是把 solve 搬到另一个线程。** [WindowManager 5.1 API](https://docs.blender.org/api/5.1/bpy.types.WindowManager.html) 直开被网页服务拒绝；使用精确版本模板和源码交叉核验，不冒充成功读取该页面全文。

## 修改范围

后续实现仅涉及 `retarget.py`、`pipeline.py`、`__init__.py`、`tests/run_retarget_test.py`。`gizmos.py` 仅在现有开关无法可靠短路时修改。版本从 `(1, 6, 6)` 升为 **`(1, 6, 7)`**。

依赖继续为 `__init__.py -> pipeline.py -> retarget.py -> classify/mapping/ik`。缓存与帧作业属于 `retarget.py`；计时器与界面状态由操作器持有。不得让求解模块反向导入 UI 或 Gizmo 模块。

## 实施步骤

### 一次作业缓存

新增具体类型 `RetargetBakeCache` 与 `RetargetBakeJob`，只活在一次作业内。同步 `bake_retarget` 驱动同一 Job 至完成，保持参数、摘要和返回 Action 顺序。

缓存修正后的 pairs、两侧映射角色、链末端名称（包括 None）、目标父优先顺序、rest 数据、参考头位置和固定参考矩阵、原身高比例。链末端计算仍调用原 `_chain_end`，身体坐标系仍调用原 `_body_matrix`，不得由映射左右代替 anatomical 左右。

分类与 body frame 在**首次实际帧 `frame_set` 和原更新之后**填充，随后命中缓存；避免用尚未求值的入口姿势代表第一帧。每帧仍读来源 posed heads、CURRENT 的来源 pose 矩阵、目标求值父矩阵，并执行原 swing 和更新顺序。

每帧比较两侧求值 `matrix_world` 的副本；变换改变时只刷新该侧 anatomical roles 和 body frame，不冻结第一帧结果。静止输入的分类次数是常数；对象变换动画的刷新次数可以随帧增加，不能为了计数指标改变分类语义。

失效规则：新作业必定新缓存；armature 对象或数据、骨骼 rest/层级、绑定 mesh、网格数据/顶点组、权重或 mapping 身份变化，旧缓存立即失效。作业运行中禁止用户编辑这些输入；检测到身份变化就取消并要求重启，不用混合新旧结果继续。外部脚本并行原地写权重不受轻量身份检查保证，属于禁止的并发写入条件；不得声称比较指针就能检测它。结束、取消和异常均释放缓存，**不跨 operator 调用保留**，不借用 Gizmo 的 `_ROLE_CACHE`。

### 主线程调度与 Gizmo

invoke 启动作业；需要文件路径时保留当前文件选择器，确认后的 execute 进入同一启动函数。导入 FBX/glTF、目标判定和必要自动绑定保持同步。

自己的 TIMER 事件每次处理约 **0.016s**，以完整帧为边界。至少执行一帧，在完成该帧后检查预算；超时不再开始下一帧。不要处理别的计时器的 TIMER。界面每 0.25s 更新动作/帧进度，配对 `progress_begin/update/end`。

风险边界：一帧或一个时间片超过预算时，主线程仍会冻结到这帧完成；TIMER 不能抢占 Python 求解。同步 FBX/glTF 导入与自动绑定也仍有阻塞窗口。后台缓存计时不能证明这两段或前台 UI 已响应。

作业启动前保存 `settings.draw_bone_gizmos` 并暂设 False。当前 `draw_callback` 已在读取求值骨架前检查该开关；成功、取消、异常和注销恢复原值。若实现需要额外暂停标记，它必须由活动操作器明确持有/释放，关闭时不得读求值骨架。不得改用户的永久 Gizmo 偏好。

运行期间阻止第二次烘焙及会修改输入的操作、属性回调和编辑事件；不把所有非 TIMER 事件无条件 PASS_THROUGH。保留必要的视图导航、重绘与 Esc。

### 完成、取消与 Undo

成功保留既有同片段尾部：入口来源 Action 优先，未进入有效结果则第一成功对；双方赋对应 Action/slot；来源及目标关闭 NLA 播放；目标其余全部片段留各自 NLA strip；时间轴只覆盖选中片段并跳到起始帧。所有 `collect_actions` 片段仍烘焙。

Esc 先清理数据再返回 CANCELLED：取消未完成与已完成的本次新 Action；只按本作业记录的数据块身份删除，不按名称或全局“零用户”条件清理。保留所有原有 Action。恢复来源/目标入口 Action、slots、动画状态、pose 和场景范围/帧。导入或自动绑定产生的对象、绑定和网格改动由其准备记录精确回滚，不能误删用户原对象。

实现必须保存入口目标动画状态，不能沿用“先 animation_data_clear、取消时只恢复来源”的旧草案。目标旧 NLA/driver 等需要保留到成功提交；准备期间临时隔离其求值，取消原地恢复，成功才按现有成功语义替换。失败时不能用 CANCELLED 充当自动回滚。[5.1.2 Undo 官方说明](https://raw.githubusercontent.com/blender/blender/v5.1.2/doc/python_api/examples/bpy.types.Operator.1.py) 明确说明 CANCELLED 不建立撤销步骤。

操作器保留 `REGISTER`、`UNDO`，整次导入与烘焙仍是一整步撤销；不逐帧 push，不关闭全局 undo。同步导入调用的嵌套 operator 是否产生额外步骤必须前台核验，后台不能证明此项。停止计时器、结束进度、恢复 Gizmo、清空活动作业必须成对且可重复清理。注销插件或切换文件也走取消路径。

## 强制约束

- swing 数学、矩阵乘法顺序、四元数符号、链末端、双手 identity、rest、参考模式、根运动和 IK 不变。
- 只缓存稳定输入，绝不缓存每帧 pose heads、`parent.matrix` 或求解输出。
- 保留所有 `view_layer.update`、`frame_set` 和 `keyframe_insert`。不换 `foreach_set`。
- Action 名称、fake user、Blender 5 slots、所有片段、返回顺序和 same-clip 行为不变。
- 不增加线程、进程、父矩阵递推、全局求解缓存或推测性接口。

## 验收标准

1. 稳定骨架、显式 pairs 的双片段计数测试：当前 20 帧实测 **40 次分类**，新实现必须为 **2 次**；短、长片段均保持同一常数。自动映射额外常数分类单独统计。RED 必须来自次数断言，selected > 0。
2. 修改前保存的未舍入 float32 姿势基准与新同步/切片路径逐位一致；`q` 与 `-q` 不视为相同。既有同片段四 fixture、双手 identity、swing roll、分裂父级、CURRENT/root/IK 与全部回归通过。
3. 实际输入全片段重新计时，缓存填充与帧循环分开计；记录单帧最大值，不能把后台进程通过称为 UI 已响应。
4. 前台能重绘进度、Esc 中途清理和恢复状态、一次 Ctrl+Z 撤销整次成功操作。测试取消当前半成品 Action、finish 前异常、原有目标 Action/NLA/driver、原 Gizmo 关闭状态和连续两次作业。
5. 临时计时、计数、探针和异常注入只在测试或 TEMP；保存必要收据后清除临时代码、调用、注册和开关，并重跑聚焦与回归。

本轮证据位于 `C:\Users\chenshajie1\AppData\Local\Temp\retarget_review_r2_c18ac112f8224ec38d4b5893b12184c5`：`probe.log`、`results.json`、`validation.log`、`validation_results.json`、`focused.log`。最终不变性判断使用修正了矩阵基准的 `validation_results.json`。

本轮 Static、后台 Process、分类隔离计时、曲线对照及不变性验证已运行；既有同片段、swing、分裂父级聚焦测试通过。新增缓存计数条件已通过外部探针得到可归因 RED。**正式缓存代码、modal、Undo、Esc、Visual、整套新增回归和安装部署仍为 NotRun**。上述 8.47s 是实验对照，不是已交付功能。

## 禁止事项

本轮只写两份文档，不改任何 `.py`，不复制安装目录。后续实现也不执行暂存、提交或推送。不删除旧规格/计划，不回退 same-clip，不改姿势数学，不实施旧计划的更新删减、父矩阵递推、持久基准文件或仓库内性能探针。
