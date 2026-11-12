# Blender 角色操控与动画库实施档

```text
核心 RED -> 方向键移动 + 三动作播放 GREEN -> 持久动画库
-> 回归与用户核对 -> 临时诊断清理 -> 复验 -> 完成报告
```

日期：2026-11-04；界面修订、实施及 MCP 复测：2026-11-12。owner：本轮主代理。状态：独立插件当前 1.0.1 已安装并加载到用户当前 Blender；用户未确认完整走跑验收。当前 WIP，未完成正式验收及收尾复验。

相对链接以本文目录为基准；下述源码路径、命令和产物目录均以仓库根（本文上三级）为基准。完整合同见[设计档](../specs/2026-11-04-character-control-animation-library-design.md)。

## 目标

在真实 Blender 编辑器中控制单个已绑定角色：方向键行走、Shift 跑步、释放后待机，动画与移动同步。动画库支持登记、筛选、保存、重开和跨文件载入，保留后续 Motion Matching 所需原始片段、骨架、fps 与根运动来源。

默认页面按“选择角色 → 准备待机/行走/跑步 → 检查并开始”引导；已准备的兼容库无需用户输入 slot、ID 或文件路径。异常显示原因及下一步，高级字段按需展开。布局、默认值、失败文案和配置归属以设计档“三步引导页面”至“页面职责与配置保存”为唯一合同。

本期是恢复式操控预览，停止回到入口，不产出运动录制。2026-11-12 用户明确授权按两份文档实施；文档通过和夹具通过仍不代表正式验收。

## 修改范围

| 文件 | 责任 |
|---|---|
| `character_locomotion/locomotion.py` 新建 | 具体移动计算、按键、计时、预览会话与生命周期 |
| `character_locomotion/animation_library.py` 新建 | 片段记录、骨架校验、当前文件登记与自包含 blend 库读写 |
| `character_locomotion/animation_playback.py` 新建 | 临时 NLA、精确 slot、片段时间、过渡、恢复 |
| `character_locomotion/__init__.py` 新建 | 三步主面板、折叠库管理/高级设置、搜索和修复提示、注册与入口；首版 1.0.0 |
| `AGENTS.md`、`安装插件.bat` | 实施时加入正式插件清单及精确安装入口；不修改旧插件版本和行为 |
| `tests/test_locomotion.py`、`test_animation_library.py`、`test_animation_playback.py` 新建 | 数值合同、页面就绪/角色解析/稳定绑定、持久库、真实 NLA 求值及失败恢复 |
| `tests/run_character_control_tests.py` 新建 | 沿现有 unittest 模式运行上述三个文件；精确支持模式参数并强制 selected > 0 |
| `tests/run_character_control_ui_audit.py` 新建 | 独立测试场景的原生事件、前台生命周期审计；不写进生产插件 |
| `tests/character_control_fixtures.py`、`run_character_control_persistence.py`、`run_character_control_asset_roundtrip.py`、`run_character_control_layout_audit.py` | 共用真实骨架夹具、跨进程保存重开、FBX/重定向/库链路及布局审计；仅测试依赖 |

不修改相机、装备、弹簧骨和重定向功能；安装脚本只增加新插件入口，当前尚不包含新插件。证据保存在 `docs/superpowers/evidence/2026-11-04-character-control/`，本次自建运行资产保存在 `tests/out/character_control/`；实施时才创建。保留任务开始前已有未跟踪掌心诊断 JSON，不暂存、回退或清理。

## 实施步骤

### 1 固定材料与核心 RED

前置：确认实施授权。输入为本设计、根规则、减枝准则和当前 Git 状态。核对 Git root/remote、相关目录是否新增规则及当前插件版本。已读材料复用，亲自完整读取即将修改的具体代码及适用架构材料，不重读无变化的历史证据。

材料记录：2026-11-04 已读根 AGENTS.md、减枝准则、retarget/pipeline/mapping 的相关入口、既有 runner 和安装脚本；2026-11-12 完整读取框架模块地图规则与减枝准则，沿用两份已有任务文档承载局部关系，不新建知识库。当前 Git 基线 aedd0f7；本轮核对 `humanoid_retarget/__init__.py` 中 hr.import_source、hr.retarget_existing 及 IN_PLACE 中文标签。旧源码定位是历史记录，实施前只核对受影响差异；本轮无新增探子，不重做旧探索。联网依据与两轮修订记录见设计档。

2026-11-04 的源码探子超时后已停止，未采纳未返回结论；2026-11-12 页面修订没有重新派发。效率复盘：已知小范围直接读取；本轮首批合并读取输出过长，后续限定相关章节并降低单次输出量。实施前核对脚本参数、tokenize 和目标 Blender API；只有出现具体跨目录缺口才集中并发派只读探子，传达减枝规则路径及出处要求，随后等待收敛，不重复同一探索。

保存待改文件字节基线与无关 dirty 清单。新增能被 runner 收集的核心测试：方向与斜向速度、双 Shift、无键待机、真实骨架的三片段求值与停止恢复。测试体内断言待实现入口，取得 selected > 0 且失败原因可归因的 RED；模块导入失败、错误过滤器和零选择不算目标 RED。失败先修复测试入口，不绕过断言。

产物：`baseline.md`、`core-red.log`；记录命令、加载路径、版本、退出码及 selected 数。无正确 RED 或当前入口无法核实时停止实施，标记 Blocked。

### 2 最小完整操控 GREEN

输入为干净目标骨架与本地三个合成原地 Action。先验证固定场景帧下 NLA 手动时间、精确 slot 和过渡的真实求值，再接按键与位移；同一批次做出面板可启动、可移动、可走跑切换和可停止恢复的完整切片。

同批接入三步主页面，先给空场景、选蒙皮网格、多个骨架候选、三动作缺项、双会话互斥、失效检查结果及帧率未确认取得 selected-positive RED，再最小补齐角色解析、就绪状态和中文提示。高级配置默认折叠，读写与动作准备始终由显式操作触发；不为页面新建通用向导框架。单片段预览复用正式播放器，退出恢复后再开始操控。

落实 Scene 目标指针、角色 Object 配置、片段时间确认状态和非持久会话/校验缓存的归属。单片段预览不要求三动作齐全；手动清空或失效绑定不得触发自动回填。检查需保持响应，取消或失败不创建会话；外部更改 Action 后即使页面旧标记尚未刷新，开始前重查也必须拒绝失效数据。

实现设计规定的输入基准、单位换算、朝向轴、dt 限幅、双 Shift、暂停与恢复。首批可先直接指定三个本地 Action，但片段记录使用最终库合同，不造测试专用播放器。动画速率按片段 fps 与标称速度计算。临时轨道的 REPLACE 权重、自动控制开关、strip 时间和更新标签先用实际 API 核验；不要假定仅修改 Python 属性就已完成 depsgraph 重求值。

以对立姿势的两个夹具测量过渡首、中、尾骨骼结果，核对快速切换不会跳回旧姿势、残留未覆盖通道或无限新增轨道。无法闭合先修复播放模块；不得改为全场景时间轴播放或仅移动对象而无动画。相同测试达到 GREEN 后，再验证真实重定向结果、骨骼挂载子物体跟随及四向跑动。

产物：`core-green.log`、`playback-runtime.json`、独立可打开场景。失败删除本次临时轨道、恢复入口，不改源 Action。首批不等待外部库浏览器或 Motion Matching 特征工具。

### 3 完成可复用动画库

输入为已通过的本地片段和现有重定向流程。先补库往返、失效槽位、重名、不同 fps、非原地动画与异骨架拒绝的 RED，再实现列表/过滤、登记/解除、源与播放副本关联、保存与追加。移除条目不删除用户 Action。

为行内 Action 登记、按用途唯一回填空槽、保留手选绑定、库载入取消/失败、中文槽位选择及高级字段定位补测试。文件选择器处理路径，名称匹配仅作建议；校验结果不在 draw/poll 内执行全量扫描。成功载入后返回三步主页面，保存原配置、片段稳定 ID 和最近成功目录的各自归属。

源 Action、骨架 rest 与根运动数据原样保留；走跑使用现有 IN_PLACE 烘焙结果。用真实跨文件链路验证“原始导入 → 重定向原地副本 → 登记 → 保存库 → 新文件载入 → 操控”，而非只测 JSON 往返。不同骨架先沿现有面板重定向再登记，错误槽位不得兜底选首槽。

使用带库元数据的专用参考骨架及 Action 写入自包含 blend，不把用户网格、装备或场景意外打包。库写入临时文件成功后原子替换，失败保留旧文件；载入失败只释放本次追加数据。新增仅骨长变化的拒绝夹具；源与播放 Action 槽位分别验证。按 clip_id 去重并回收跳过的追加 Action、参考骨架和假用户数据，重复导入后数据块数不得增长。同名不同 ID 消歧，绑定使用稳定 ID。路径基准按设计执行。产物：`library-green.log`、`library-roundtrip.json`、测试库及搬目录重开场景。失败恢复库条目和本次新数据，不覆盖已有文件或用户场景。

区分合法异骨架与损坏库：前者载入保留并显示“需重定向”，只拒绝绑定/播放；后者拒绝载入并回滚。rest/骨长拒绝夹具验证的是播放兼容门，不能误写成所有载入均失败。同 ID 内容冲突取消本次载入，原库和绑定不变。保存当前角色骨架分组前显示包含/排除数量，排除的异骨架数据留在 blend；不扩展成混合骨架单文件库。

### 4 编码与格式复核

前置：代码完成；输入为实际 diff。主代理逐一核对全部改动文件，检查单向 import、无重复实现、无新增注释/docstring、保留现有编码/换行、无行尾空格。检查实际 bpy API、slot 和 channelbag、NLA 手动属性、timer.time_duration（禁止依赖 Event.timer）、frame/subframe、单位、引用有效性以及注册/注销。

预览入口快照覆盖实际触及状态；校验 timer 创建/移除、load/save/undo handlers 添加/移除、会话启动/停止、所有早退与异常恢复。未知 schema、多槽歧义、外链/override、驱动/约束竞争等必须先拒绝且不写入。代码变更后重做局部复核，合格才测试。产物：`static-review.md`。不合格先修复，不带病重复运行。

### 5 构建与测试

本工程是 Blender Python 插件，无 C++ target 或编译配置。构建前先内存 compile 所有受影响 Python，避免创建无用 pycache；再核对 Blender 实际版本和启动路径。本轮实际启动核对的版本为 Blender 5.1.2，入口 `C:/Program Files/Blender Foundation/Blender 5.1/blender.exe`；另有 Blender 5.2.1 LTS，入口 `H:/Blender/5.2.1/blender.exe`。外部程序无法相对仓库稳定定位，因此显式指定。短期实验代码已撤除，不能把其结果作为后续交付源码通过证据。

所有命令从显式仓库工作目录执行。计划新增 runner 完成后运行：

```powershell
$blenderExe = 'C:/Program Files/Blender Foundation/Blender 5.1/blender.exe'
& $blenderExe --background --factory-startup --python-exit-code 1 --python ./tests/run_character_control_tests.py -- 'test_locomotion.py'
& $blenderExe --background --factory-startup --python-exit-code 1 --python ./tests/run_character_control_tests.py -- 'test_animation_playback.py'
& $blenderExe --background --factory-startup --python-exit-code 1 --python ./tests/run_character_control_tests.py -- 'test_animation_library.py'
& $blenderExe --background --factory-startup --python-exit-code 1 --python ./tests/run_retarget_test.py
& $blenderExe --background --factory-startup --python-exit-code 1 --python ./tests/run_humanoid_mounts_tests.py -- 'test_humanoid_mounts_*.py'
& $blenderExe --background --factory-startup --python-exit-code 1 --python ./tests/run_wasd_fly_test.py
```

新 runner 每次打印真实模块路径、版本/hash、过滤器、selected 和失败数；selected > 0、无 skip/expected failure、退出码 0 才算 GREEN。旧 retarget/WASD 为现有脚本入口，不宣称它们已有同样计数协议；保存脚本退出码和自身成功标志。失败区分既有问题与本次回归，修复后重跑受影响项，不在未改动时反复跑整套。

前台使用独立新进程运行新增 UI audit；原生事件模拟仅测试进程启用，不改用户启动参数。人工核对方向键、左右 Shift、同时按两 Shift、斜向、释放、移出/失焦、多视口、Esc、停止、异常、删除对象、Undo/Redo、切文件、保存、注销与再次启用。记录真实角色位置与骨骼变化；后台直接调用 modal 不能替代原生事件或 Visual。

页面验收覆盖空白/已配置场景、骨架/蒙皮网格/多候选、中文长名、重名动作、320px 与 480px 侧栏及 100%/150% UI 缩放。检查缺项原因不依赖 tooltip 才能发现；宽度不足允许原生滚动和换行，不截断关键恢复按钮。验证首次三步、日常直接开始、预览互斥、错误后原配置保留、重开 blend 后角色/动作/速度仍在。记录操作步骤和截图，不能以 ASCII 示意图代替实际 Visual。

补做第二轮修订的验收路径：只配置一条也可原地预览；手动清空后载入库不偷偷补选；同 ID 冲突回滚；异骨架可浏览但不能启动；确认过的素材重开不重复询问；保存前结束预览；移出/失焦暂停清键，切场景/工作区和关闭原视口结束并恢复原 owner，不污染新场景。检查中取消和连续快速启动不得残留 timer 或临时轨道。

产物：上述聚焦/回归日志、`ui-runtime.json`、`visual.md`、必要截图。性能在同一角色和场景对照关闭/开启，保存 timer 数、对象/Action/轨道数与帧耗时；连续启动/停止 20 次和持续操控 60 秒不得累计资源。目标 timer 60Hz 不是性能通过证据，记录实际开销，持续卡顿必须修复后再验收。

### 6 用户核对与临时诊断清理及复验

输入为运行场景、截图和必要收据。先完成目标并保存证据，再请用户核对真实角色的移动、跑步及动作库体验。未核对前保留所需诊断，状态为待用户核对，不能宣告最终完成。

文档交付状态不保留新增埋点、timer、脚本或运行依赖；短暂实现、配套测试和诊断均已精确撤除。后续实施如加入临时事件日志、骨骼采样、耗时计数、异常注入、轮询和开关，在 `cleanup.md` 逐项登记文件/符号、用途与调用/注册/依赖；默认仅在测试中存在，不进入正式热路径。用户核对后移除这些临时生产内容及仅为诊断新增的依赖，保留必要测试与验收证据，不按名字批量删目录。

清理后重新 diff 审查、内存 compile、三个新测试文件及受影响回归；补前台移动/停止/重开和性能对照。未清理、未复验或复验失败保持未完成。回滚只针对确认属于本次的修改，不覆盖原有 dirty，也不执行 Git 清理命令。

### 7 完成报告

输入为清理后收据。逐项报告实现、版本、来源路径、安装副本一致性、注册/注销、硬门结论与分层证据；列出任何 NotRun 或 Concern。安装到实际用户目录时再哈希核对全部受影响源码，验证禁用/启用不重置场景配置；文档阶段不安装。只有用户核对、清理和必要复验全部闭合才报告功能完成。

### 实施进度 2026-11-12

证据相对目录为 `../evidence/2026-11-04-character-control/`；可运行夹具、截图和安装包相对仓库根为 `tests/out/character_control/`。旧规则“仅文档”授权已由本次实施指令替代，不自动授权提交或推送。

#### 当前编辑器 MCP 复测与 1.0.1 修复

连接当前进程的 BlenderMCP 已有桥接 `127.0.0.1:9876`，经其主线程命令队列执行。当前用户明确禁止 Computer Use；后续验证只使用 MCP、CLI、文件和 API。曾尝试的窗口激活被用户 Escape 终止，未继续；黑色截图不作为 Visual 通过证据，实际界面可视验收保持未完成。

| 本轮检查 | 事实与结果 | 证据与限制 |
|---|---|---|
| 当前应用 | Blender 5.1.2、未保存工程、第 15 帧；角色“骨架”146 根骨骼驱动 body/clothing/hair/head 等网格 | mcp-final-logic.json；已绑定 Scene 的角色目标，不自动保存用户工程 |
| 插件加载 | 当前进程已启用 1.0.1，Scene/Object 属性和 VIEW_3D/角色操控主面板均已注册 | MCP 逻辑核验；不等价于人工界面验收 |
| 真实角色播放 | 当前骨架绑定的 10 个候选 Action 通过现有技术门；临时预览实际改变 145 根骨骼及 body 采样顶点 | mcp-current-session.json；按场景 24fps 临时采样，不能冒充素材原始 fps 或 Idle/Walk/Run 语义确认 |
| 恢复缺陷与归因 | 1.0.0 播放器与运行中的动态骨骼 app timer 双写同一角色；动态骨骼 guard 自取消并移除自有 RealtimeInput，导致旧恢复检查 Action/slot 失败 | 已明确保存失败收据；不是所有恢复项 Passed，也不归因于原始 FBX 被删除 |
| 现场恢复 | 保留的原来源 Action 仍在，已通过动态骨骼原启动入口重建同名实时输入及 sampler，恢复实时预览、轨道、帧和对象变换 | 动态积分历史重置，运行时 Action 身份重建，不宣称字节级/历史级完全恢复。结束阶段选中地面，已通过 MCP 精确恢复入口 Mount_hand_r 选择，未回退对象编辑 |
| 最小修复 | 同角色动态骨骼预览/烘焙活动时，在变更 Action 前明确拒绝启动；版本 1.0.1 | 仅新增业务前置门；不自动停止其他插件，不修改 spring_bone 业务代码 |
| RED → GREEN | 同骨架真实 SpringBone 夹具 11 项选中、1 项失败；修复后源码/安装副本 5.1.2 及源码 5.2.1 各 24/24 通过 | spring-owner-red.log、spring-owner-green.log、spring-owner-installed-green.log、spring-owner-52-green.log |
| 当前现场保护 | MCP 确认同一恢复后的 spring 会话及其 Action 保持不变，前置门返回明确拒绝原因，帧仍为 15 | mcp-current-session.json、mcp-final-logic.json；没有再次双写真实角色 |
| 当前缺项 | 已登记片段数 0；idle/walk/run 均 UNSET；动态骨骼实时预览仍按原需求开启 | 用户先停止同角色实时预览，再确认或提供待机/原地走/原地跑片段、fps 和循环范围；不能擅自把编号动作塞进三槽 |

本轮临时探针位于 `tests/out/character_control/`：`mcp_review_client.py`、`mcp_inspect_current.py`、`mcp_enable_validate.py`、`mcp_start_preview.py`、`mcp_measure_restore.py`、`mcp_restore_audit.py`、`mcp_inspect_recovery.py`、`mcp_recover_spring.py`、`mcp_reload_guard.py`、`mcp_final_scene.py`、`mcp_capture_current.py`、`mcp_logic_finish.py`、`mcp_restore_selection.py`，共 13 个；按实际文件逐一清理，不按通配符删除。`bpy.app.driver_namespace["character_locomotion_mcp_review"]` 保存现场核对快照，无新增轮询或 timer；必要证据已写 JSON，用户核对后移除此键及上述临时脚本并复验。原有两个探针和正式回归测试仍按下文清单处理。

另有未闭合兼容 Concern：直接登记外来 Action 时，骨架记录来自当前目标，尚不能可靠证明该 Action 的真实来源骨架；已复现同名骨骼、不同骨长的外来 Action 被接受。当前使用既有目标的真实重定向结果，不把本次成功扩展为任意 FBX 即插即用。

| 产物或检查 | 实际结果 | 证据与边界 |
|---|---|---|
| 独立插件、三步页面、动作预览、走跑、短过渡、库读写 | 可试用 WIP；原插件业务未改 | `character_locomotion/` 四个源码文件；安装清单与 BAT 仅增加新插件 |
| selected-positive RED | 方向计算 6 个选中、3 失败；根骨坐标门 8 个选中、2 个失败/错误 | core-red.log、root-space-red.log；不是导入失败或零测试 |
| 聚焦与回归 GREEN | Blender 5.1.2 源码、安装副本及 5.2.1 LTS 各 23/23 | core-green.log、installed-green.log、blender52-green.log；包括真实骨骼求值、混合中点、快速切换、20 次资源恢复、失效原 Action 恢复、库去重与冲突 |
| 真实文件资产链 | FBX 导出/导入 → 既有 DIRECT/IN_PLACE 重定向 → 保存库 → 新骨架载入 → 骨骼播放 Passed | asset-roundtrip.log；合成人形输入，不是用户真实素材，也不证明标准人形双跳模式通过 |
| 配置持久化 | 禁用/启用保留配置、独立进程重开 blend Passed | persistence-save.log、persistence-reopen.log |
| 原生前台事件 | 方向键、左右 Shift、释放一侧仍跑、待机、移出暂停、Esc、原地预览与保存前恢复 Passed | ui-process.log、ui-runtime.json；独立进程，已有用户编辑器未修改 |
| 60 秒资源检查 | 两骨测试夹具持续操控无 Action/轨道累计；timer 处理耗时约 0.167ms 平均、1.577ms 最大 | ui-runtime.json；仅 timer 处理，不含延迟骨骼求值、绘制及真实角色预算 |
| Visual | 默认约 350px 主面板截图已检查，无启动弹窗遮挡 | main-panel.png；320/480px、100%/150% 与真实角色视觉验收未完成 |
| 多尺寸自动化 | Blocked：region_scale 需要原生 action zone 上下文，模拟拖拽未改变侧栏宽度 | layout-process.log、layout-runtime.json；测试入口失败，不记产品界面失败，也不记 GREEN；后续用真实 UI 完成四组合检查 |
| 相关既有回归 | 挂载 117/117；相机 14 组、111 个检查 Passed；重定向整套失败 | mounts-regression.log、navigation-regression.log、retarget-regression.log |
| 重定向失败归因边界 | 未加载 character_locomotion 的独立进程仍复现“final hop removes horizontal root travel” | retarget-isolated.log；现有 `test_metarig_root_reference_and_ik` Concern，未修改或绕过上游实现 |
| 安装与打包 | 5.1 用户 addons 中的新插件四文件哈希一致；ZIP 校验通过 | installed-green.log、source-manifest.json；外部安装目录由 APPDATA 确定，源码与脚本仍从仓库根解析 |
| 用户核对与最终收尾 | Pending；用户明确尚未试用确认 | 保留核对场景及证据；未宣告最终完成 |

复核与资源门：业务命名、零新增注释、单向依赖、bpy 主线程、精确资源身份清理为 Passed，详见 static-review.md。C++ 格式/namespace/参数分组、unique_ptr label、raw pointer、USE_TEST_UNIT、网络预测与 Build(C++) 均 NotApplicable。Generate 为 ZIP 生成/完整性校验，不能代替 Runtime。正式验收、真实角色性能及清理后复验保持 NotRun。

临时诊断清单：生产代码无临时日志、采样或诊断开关；会话 timer、状态提示、验证分批及临时 NLA 是正式功能，不删除。`tests/out/character_control/playback_probe.py` 与 `upstream_regression_check.py` 是本轮临时探针，用户核对前保留；用户核对后精确删除这两个探针，保留必要测试、截图和日志，再跑静态、23 项聚焦、资产往返及前台恢复。测试内的耗时包装只存在独立审计进程，退出即消失，不进入安装包。

效率复盘：NLA influence 属性被 Blender 重求值覆盖，改为会话自有 influence 曲线；FBX 资产链发现局部骨轴与世界轴不可混同，先补 RED 再修正。文件保存后审计程序直接调用新 modal 时，旧 modal 还未接收退出事件，现补原生移动事件排空后继续。布局自动化尝试已停止，不继续重复无有效上下文的调用；补人工检查优先，不修改生产 UI 来迎合测试。未重复读取无变化的奠基材料，未新增探子批次。

## 强制约束

各项 owner 均为主实施者，具体文件与符号范围按修改范围表；记录集中在证据目录，不另建重复台账。

| 门 | 检查与通过标准 | 证据与失败处理 |
|---|---|---|
| 复用与范围 | 实施前重新确认 原生 Action 选择、NLA 精确赋槽与既有 IN_PLACE 准备链；不增加同职责实现 | baseline.md；未闭合 Blocked，禁止实施 |
| 依赖与状态 | 三业务模块无环、bpy 主线程、单个角色写入者；预览不写源曲线 | static-review.md；修复后再测 |
| 生命周期 | 快照→会话→停止，timer/handler 成对，失败幂等恢复；20 次启停无累计资源 | lifecycle 日志与 ui-runtime.json；缺证据 Blocked |
| 持久化 | schema/slot/rest/fps 校验、单文件原子库、相对路径有固定基准；保存前恢复预览 | library-roundtrip.json；旧库保留，拒绝提交半成品 |
| 编码与兼容 | 新代码零注释/docstring；不改无关布局；真实 API 和静态元数据一致 | static-review.md；违规先局部修正 |
| 测试 | selected-positive RED→GREEN；聚焦、相关回归、前台事件和 Visual 分开 | 各日志；未运行 NotRun，必要门失败 Blocked |
| 页面易用性 | 主路径三步、技术字段折叠；原因和下一步可见；错误后配置不丢；开始重查且 draw/poll 无重工作 | ui-runtime.json、visual.md；失败修复交互再复验，不放宽播放硬门 |
| 诊断收尾 | 用户核对后精确清理并复验，无临时热路径开销 | cleanup.md；未闭合不完成 |
| 适用性 | 无 C/C++、网络、MiniGame 构建或引擎诊断修改 | C++ 对齐/namespace/参数分组、unique_ptr label、raw pointer、USE_TEST_UNIT、预测传输门均 NotApplicable |

## 验收标准

| 验收项 | 必须观察到的结果 |
|---|---|
| 输入与移动 | 四方向符合启动基准；斜向同速、反向抵消；正常 dt 下 30/60/120Hz 合成积分误差 ≤1e-5；超大 dt 按限幅合同 |
| 页面引导 | 从选定角色与兼容素材完成三步；配置重开后可直接开始；无需填写内部 ID；缺项逐行指出原因和下一步 |
| 页面误操作 | 多候选不猜选；首次空槽才回填；手选、清空和失效槽不覆盖；取消/冲突不丢配置；单片段可预览且与操控互斥；长名及窄侧栏可操作 |
| Shift 与待机 | 单侧/双侧 Shift 正确；Shift 无方向不移动；松键立即停止平移，显示待机 |
| 动画 | Idle/Walk/Run 真实骨骼求值变化；不同 fps 时间正确；过渡连续，快速切换无轨道增长；走跑速率匹配标称速度 |
| 资产闭环 | 真实导入与 IN_PLACE 重定向结果可登记、保存、新文件追加、操控；搬动库目录后数据仍可用 |
| 兼容失败 | 合法异骨架载入保留但拒绝播放；错槽、缺骨、rest/骨长差异、零时长、根位移与竞争写入拒绝绑定/播放；未知 schema 或缺数据拒绝载入；失败不破坏已有状态 |
| 恢复与隔离 | 所有退出路径恢复 Action/slot/NLA/pose/对象变换/帧；其他角色时间不推进；装备正常跟随 |
| 磁盘与资源 | 保存文件无临时 NLA；写入失败旧库完整；20 次启停及 60 秒操控无资源累计 |
| 版本与安装 | 当前 1.0.1 字面量列表名匹配 bl_info，主标题动态生成；注册/注销、安装副本及当前进程均核对；1.0.0 仅为历史首版 |
| 收尾 | 用户目标核对、精确诊断清理及复验全部完成；未运行等级保留 NotRun |

两轮复核记录：第一轮把主页面、逐行修复和折叠设置落到步骤 2/3；第二轮补齐稳定绑定、单片段预览、确认状态、异骨架浏览、导出分组、同 ID 冲突及跨场景退出，落到步骤 2/3/5 和上述验收行。发现、修订和边界详见设计档“两轮界面复核与修订记录”；未新增独立报告或框架。

当前状态以“实施进度”实际收据为准；两轮文档复核 Passed。Contract、Generate、Process、夹具 Runtime 有通过证据；完整 Visual、真实角色性能、正式验收及清理后复验未闭合。RealTransport/Resim、C++ Build 不适用，不以低等级证据替代目标验收。

减枝检查：DP-01 Passed（三步页面与走跑、动画库、MM 数据目标均对应验收）；DP-02 Passed（新增 UI 只解决选择、错误及配置负担，不做网页或通用向导）；DP-03 Passed（原生控件与既有重定向准备复用，文案引用设计合同）；DP-04 Passed（步骤 2 首批同时闭合移动、播放和三步 UI）；DP-05 Passed（步骤 2/3/5/6 覆盖取消、误操作、兼容、恢复、用户核对、清理及复验）；DP-06 Passed（六项结构保留，两轮具体发现均有修订和可执行验证）。

## 禁止事项

本次允许按文档实施、测试与安装独立新插件；禁止 Git 暂存/提交/推送及覆盖现有用户场景。禁止重复实现重定向、工作线程调用 bpy、推进全场景时间轴充当单角色播放、猜首槽、改源动画去根位移、偷偷给用户 Action 插关键帧或保存临时预览。会话专有副本和 NLA 曲线不属于用户 Action，必须按资源身份释放。禁止清理已有掌心证据、临时备份或无关用户资源。Motion Matching 搜索、碰撞和网络不以占位接口进入本期。
