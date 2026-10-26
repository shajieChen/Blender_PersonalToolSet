# 人形挂点插件实施文档

```text
首批右手挂载 -> 五个人形部位与管理 -> 生命周期与共存 -> 安装验证
保存证据 -> 用户核对 -> 清理临时诊断 -> 清理后复验 -> 最终报告
```

日期：2026-10-23；实施持续至 2026-10-24。状态：已完成实施、用户核对、精确清理及清理后复验。结论限本次 Blender 5.2.1 和程序化人形夹具。

依据：[人形挂点与武器挂载调研](../../design/research_attachment_points.md)。以下保留实施步骤与验收要求；实际完成证据见进度表和 final-report.md。

## 目标

### 当前实施进度

| 项目 | 当前事实与收据 |
|---|---|
| 原始基线 | Pose 13 / Spring Bone 67，退出 0；`baseline-pose.log`、`baseline-spring.log` |
| RED/GREEN | 已取得存在性、骨骼父空间、管理入口、人形归属和空动画容器的可归因 RED，再最小修正；各 `red-*.log` 与后续 GREEN |
| 功能与合同 | 清理后 34 项通过，无 skip；`post-cleanup-suite.log`；包括五部位新进程重开、Collection Append、按钮闭环、故障恢复和插件共存 |
| 既有回归 | 清理后 Spring Bone 68 / Pose 13，退出 0；`post-cleanup-spring.log`、`post-cleanup-pose.log`；其他工作更新 Spring 后新增 1 项，原修改保留，输出隔离 |
| 安装 | 六个源文件精确复制到 5.2.1 portable 的本包目录，哈希匹配；BAT 仅增两行 ASCII，原字节保留；`install-manifest.json` |
| 安装运行 | 已从安装目录加载、重开及独立启停；`post-cleanup-installed.log` |
| 前台 | 已验证自然播放和 Undo/Redo，查看两帧五部位/剑盾/折叠面板截图；进程身份、帧变化、退出见 UI 收据与 `visual.md` |
| 正式收尾 | 用户已确认“符合目标，继续清理复验”；精确清理后聚焦/整套/回归/安装/前台复验全部通过；见 `cleanup.md`、`final-report.md` |

证据目录：`H:\Blender_Plugin\docs\superpowers\evidence\2026-10-23-humanoid-mounts`。兼容结论仅覆盖本次 5.2.1 及程序化人形夹具，用户具体 Rig 未验证。

实施效率补记：前台测试先后暴露工厂设置重置后的上下文、Undo 后重绘、隔离配置首次启动弹窗差异，均保留失败收据后定向修复。后续演示使用独立 Scene、显式重绘、区域上下文和已准备的隔离配置；不原样重跑未修正命令。未新增探子批次。

新增独立的 `humanoid_mounts` 插件。用户选择人形角色及实际骨骼，创建右手、左手、背部、腰部、头部挂点，绑定刚性武器或道具；支持偏移编辑、解除、复制、重命名、删除、Undo、保存重开及原生动画跟随。

首批先交付“右手建挂点 → 准备剑柄握持根 → 吸附或保持位置绑定 → 播放跟随 → 解除并保持位置”的完整闭环。其余四个部位复用同一路径；不等待完整预设、复杂 Picker 或安装器完成才展示结果。

```text
人形 Armature 的实际骨骼 -> 挂点 Empty -> 武器握持根 Empty -> 刚性部件
```

挂点随 Blender 原生骨骼父级求值，插件不逐帧写骨骼，不生成 Action。人形由用户明确选定并校准；不能把任意 Armature 或自动识别结果认定为已验证人形。

本次功能不含非人形、通用物体 Socket、动画换手、双手 IK、自动握拳、衣甲蒙皮、碰撞避穿插、镜像、武器骨架动画和 UE/FBX 导出。已有调研中的这些材料不进入当前验收。

## 修改范围

工程身份：`H:\Blender_Plugin`，remote 为 `https://github.com/shajieChen/Blender_PersonalToolSet.git`。

| 范围 | 精确文件与职责 |
|---|---|
| 插件注册 | 新增 `humanoid_mounts/__init__.py`；元数据、注册与注销，不操作用户物体 |
| 配置与界面状态 | 新增 `humanoid_mounts/properties.py`；部位枚举、当前角色/挂点/武器选择、持久化标记合同 |
| 骨骼挂点 | 新增 `humanoid_mounts/mounts.py`；创建、验证、改名、复制、换骨骼和删除挂点 |
| 武器挂载 | 新增 `humanoid_mounts/weapons.py`；准备握持根、绑定、解除及失败恢复 |
| 操作与面板 | 新增 `humanoid_mounts/operators.py`、`panels.py`；显式操作、Undo、N 面板和错误反馈 |
| 测试 | 新增 `tests/test_humanoid_mounts_transform.py`、`test_humanoid_mounts_lifecycle.py`、`test_humanoid_mounts_coexistence.py` |
| 测试与演示入口 | 新增 `tests/run_humanoid_mounts_tests.py`、`run_humanoid_mounts_demo.py` |
| 安装入口 | 最后局部修改 `安装插件.bat`，只增加本插件安装项和必要提示，保留原编码与既有行为 |
| 实施记录 | 更新本文；后续在 `docs/superpowers/evidence/2026-10-23-humanoid-mounts/` 保存证据；日期按实际实施调整 |
| 测试产物 | 仅写 `tests/out/humanoid_mounts/` 中明确命名的 fixture、副本和输出，不覆盖用户 blend |

不修改 `humanoid_retarget`、`spring_bone`、其他插件及其测试；保留当前所有 dirty/untracked。首次实施先记录精确状态，特别是重定向的 `__init__.py`、`pipeline.py`、`apose_export.py` 和现有弹簧骨材料。

依赖保持单向：注册入口依赖属性/操作/面板；操作依赖挂点和武器函数；武器函数可调用挂点验证；业务函数只依赖 `bpy`、`mathutils` 和本插件必要定义。禁止生产代码导入其他插件的私有模块。

## 实施步骤

### 1 固定材料与执行环境

前置：调研全文与适用规则可完整读取。输入：当前源码、Git 状态、Blender 路径和本文件。

动作：先记录规则、允许文件、原编码和工作树状态；主执行者亲自读调研及即将修改的确切代码。下表未变化材料直接复用，只针对内容变化或具体缺口补读。

| 已读材料 | 已确认结论与定位 |
|---|---|
| 调研全文 | 当前仅人形；五部位、原生跟随、握持根、保持姿势与吸附分开；高级能力延期 |
| 既有 Spring Bone 实施档全文 | 六段结构、按批验证、证据分层、用户核对后清理的工程惯例；其功能状态不作为本插件证据 |
| `humanoid_retarget/classify.py`、`mapping.py` | 已有角色分类和映射；不再实现别名/几何识别器。首批人工选骨骼，不接自动映射 |
| `humanoid_retarget/__init__.py:413`、`:419` | 已有角色行和骨骼搜索 UI 的参考；不是跨插件公共接口 |
| `spring_bone/operators.py:_sync_empty` | 已有骨骼父级 Empty；其中骨长补偿属于其显示职责，不复制为新矩阵公式 |
| 两个既有测试 runner、`tests/test_ik_pose.py` | 可复用 unittest、工作区路径与成功标记模式；`IkPoseTests` 为真实 unittest 类，不用脚本式测试冒充 discover 用例 |
| `tests/run_retarget_test.py:39` | 已有 `build_biped` 程序化人形 fixture；仅供测试复用，不执行该文件的 `main` |
| `安装插件.bat` 原始字节与入口 | 当前只安装 Retarget/Shortcut；严格 UTF-8 解码失败，不能擅自按 UTF-8 全文重写 |
| `.gitignore` | 已忽略 `tests/out/`、pycache；验证仍须核对实际产物路径 |

本次 `H:\Blender\5.2.1\blender.exe --version` 退出 0，输出 **Blender 5.2.1 LTS**、hash `9e2066aef7ef`。这只确认执行环境，没有验证插件、矩阵或 UI。首个兼容目标限定此版本，其他 Blender 版本保持 `NotRun`。

探子安排：已知位置的小文件直接读；本次没有新增探子批次。后续若确有相互独立的跨目录缺口，一次并发派发只读任务，要求 file:line、符号与关键原文；派发后等待全部收敛，再改文件。禁止重复全仓检索或为了等待而重读同一材料。

效率记录：本轮一次读取巨型 Retarget 测试入口导致输出截断；已改用 `build_biped`、`main` 和写文件调用的定向定位。该入口会写映射预设，不把它整段运行作为默认回归，也不把完整大文件列为每批必读。入口复核还发现 `test_pose_channel_scale.py` 是依赖用户资产的脚本，不是 unittest；已从 discover 命令移除，改用 `test_ik_pose.py`，避免 selected=0。

构建前检查：本项目为 Python 插件，没有 C++ 编译目标。实施时先核对 `Object.parent/parent_type/parent_bone`、`matrix_world/matrix_basis/matrix_parent_inverse`、求值对象、Relative Parenting、PointerProperty、Undo 和保存加载的实际 API。用当前 Blender 的 RNA 与最小合同测试核实，不由文档或其他插件版本推定可用。

开始修改代码前，先执行步骤 6 中两个既有回归命令一次，保存 `baseline-regression.log`。既有失败单独记录，不归因于本插件、不改他人工作；可继续独立授权步骤，但必要共存门未闭合时不得宣布最终完成。

预期产物：`environment.md`、`materials.md`、基线和精确修改清单。失败：必读材料或必要 API 缺失记 `Blocked`；先保留错误，再修正，禁止原样重复失败命令。未改场景时无需恢复。

### 2 首批右手挂载闭环

前置：步骤 1 静态检查通过。输入：复用 `build_biped` 的独立人形 fixture、带动画的手骨、剑模型与偏离原点的握持位置。

1. 先建立新测试 runner 和可收集的合同用例。缺实现的断言放在用例内，取得 `selected > 0`、指向目标功能的 RED；模块导入崩溃、环境错误和空过滤不算目标 RED。随后用独立的矩阵预期取得实际行为 RED，再做最小实现。
2. 实现 `create_mount`、`validate_mount`、`prepare_grip_root`、`bind_weapon`、`detach_weapon` 的最小具体函数和错误类型；不增加框架、工厂或运行时会话管理器。
3. 角色和实际右手骨骼显式指定；新建挂点默认位于当前骨骼原点，允许用户再调至掌心，不声称自动找掌心。直接设置原生骨骼父级，保留原骨骼 Relative Parenting；不通过会切换该开关的父级操作器偷改现有子物体。
4. 挂点只存一份原生变换。不能硬编码骨长补偿：先用新 Empty 的单位 basis/父逆矩阵取得 Blender 实际骨骼父空间，再计算目标 basis。创建后的世界矩阵须与 `armature.matrix_world @ pose_bone.matrix` 的独立预期一致；覆盖非零骨长、bone roll、父链变换和 Relative Parenting 开/关。
5. 提供“从选中部件创建握持根”：以用户放置的 3D Cursor 位置和明确校准的轴向创建 Empty，把固定选中的刚性部件按保持世界姿势挂到该根下；源 Mesh 原点、顶点、材料和单位不变。校准光标的读法纳入实际 API 预检。首批拒绝武器待迁移输入中已有的动画、driver、约束、Armature modifier、不可编辑或复杂外部父级，并说明原因；这不禁止角色自身有骨骼动画或约束。
6. 绑定规则只有 `SNAP` 与 `KEEP_WORLD`。SNAP 令握持根的世界矩阵与挂点一致；KEEP_WORLD 保持绑定前世界矩阵。二者均显式处理父逆矩阵及 Delta，不靠清空位置或默认操作器选项猜测。部件相对握持根的校准保持不变。
7. 加最小 N 面板，完成右手创建、绑定、解除与原生时间轴播放。前台显示剑跟随手腕转动，解除后留在原位；不创建每帧 handler 或 Action。

预期产物：`red.log`、`transform.log`、最小可播放场景和首批观察记录。失败：恢复入口处父级、骨骼名、矩阵、Delta、选择和模式；只删除本次明确创建的 Empty。恢复失败记 `Blocked`，不能仅返回 `CANCELLED`。

### 3 五部位管理与持久化

前置：右手闭环通过。输入：同一人形、第二个人形、第二把武器和五个部位。

动作与规则：

- 部位使用固定枚举 `hand_r`、`hand_l`、`back`、`waist`、`head`；它们是用途，不是硬编码骨名。背/腰/头同样由用户指定实际骨骼。缺某部位只阻止该部位，不要求完整全身映射。
- 当前人形由显式 Object 指针保存；选择武器不切换角色。挂点的原生 `parent`、`parent_type` 和 `parent_bone` 是归属真值，不另存可分歧的骨架/骨名副本。
- 挂点保存 kind、schema 和部位标记；插件创建或用户显式登记的握持根只保存其 kind/schema。标记随 blend 持久化，不能在停用时清掉。不用名称前缀认领物体，不建立 UUID 注册表。未知 schema 和断开的骨骼关系显示失效并拒绝绑定，不悄悄回落到角色原点。
- 列表只展示当前角色的已标记挂点。使用 Object 引用，名称仅供显示；原生名称冲突按 Blender 实际返回名处理。骨骼改名、删除、物体复制和多角色重复名称必须测试，不能默认旧字符串仍有效。
- 创建、复制、改名、换骨骼均为显式 Undo 操作。复制只复制挂点，不复制附件；换骨骼先保持世界姿势。编辑“挂点偏移”影响其所有附件，编辑“道具偏移”只影响选中的握持根。
- 删除挂点先预检全部直接子对象，默认解除并保持其世界姿势，再删除这一个插件挂点。绝不删除武器、部件或用户原有 Empty；存在无法无损解除的输入时整次拒绝。
- 握持根来源与选择部件在操作开始时固定；正常解除保持当前世界姿势，不恢复几分钟前的旧摆放。迁移现有绑定必须有明确动作，不能静默覆盖外部父级和约束。

面板顺序：人形角色 → 部位/实际骨骼 → 挂点列表 → 偏移 → 从选中部件创建握持根/选择已有根 → SNAP/KEEP_WORLD → 解除。显示空闲/绑定/失效及原因；复制、改名、删除只针对明确选中项。采用原生控件和变换工具，不先做人体轮廓 Picker。

预期产物：五部位操作、两角色隔离、保存重开与复制测试。失败：恢复本次操作的状态快照，不依赖用户连续 Undo 才恢复。新功能不支持的输入保持原状。

### 4 生命周期与共存

前置：步骤 3 通过。输入：已绑定场景、用户预置 Empty/约束、角色 Action/slot，以及可分别启用的其他插件。

注册只增加自身类、属性与面板；部分注册失败按本次成功项逆序注销。停用不删物体、绑定或持久化标记。重新启用后从保存状态读取，不运行一次性全场景修复。

不添加 timer、draw handler、depsgraph/frame/load handler、线程或持久全局缓存；播放由 Blender 原生父级完成。需要的“选中后编辑”使用原生 gizmo。若后续发现必须新增回调，先补明确 owner、注册/注销和 Undo/加载覆盖，再评估是否仍属于本范围。

操作前完成可编辑性、归属、骨骼存在、依赖环、输入动画和矩阵可表示性预检；主线程内计算方案并提交。故障注入覆盖：Empty 创建后、首个部件重绑后、记录写入前、批量解除中途、删除前。每一处均恢复精确入口状态，清理可重复，正常结果不被误删。

共存分两层验证：独立插件在未注册 Retarget/Spring Bone 时能工作；同时启用时，本插件只读最终骨骼，不写 pose、Action、slot、NLA、网格权重或其他插件状态。存在异步烘焙/预览作业时不在其中重设关系，使用其既有停止入口或待作业结束，不新增跨插件全局锁。

复核 `humanoid_retarget/pipeline.py` 对角色关联 Mesh 的收集：挂入武器可能被其现有导出选择包含。只记录当前行为并测试无异常；导出过滤与 A-Pose 导出不属于本次修复，不擅自改动该插件。

预期产物：`lifecycle.log`、`coexistence.md`、用户数据前后差异、故障回滚结果。失败：定位具体写入点；涉及范围外缺口记 `Concern` 或 `Blocked`，不扩大修改范围。

### 5 编码与格式复核

前置：每批补丁完成，尚未开始该批验证。输入：本次 diff 和完整受影响函数。

检查业务命名、局部职责、单向依赖、显式对象归属、无新增注释/docstring、无私有跨插件导入、无隐式回调状态。使用内存 `compile` 检查语法，不生成工作树 pycache。复核原生矩阵乘法、逆矩阵条件、实际 RNA、PointerProperty、Undo、编码/行尾/行尾空格及无关 diff。

本仓库是 Blender Python 工程，未创建或修改 C/C++；MiniGameCode/RainbowEngine 的工具链与格式规则不适用。namespace Tab、三元参数、`m_` 对齐、普通 `=` 对齐、项目 allocator、unique_ptr label 与 raw pointer 门均为 `NotApplicable`。

预期产物：`static-review.md`，逐文件列出 Passed/NotApplicable/Blocked。发现违规先局部修正，再复核；只修本次补丁，不借机回退既有工作。再次改代码后重跑本步骤，不以测试通过替代专项复核。

### 6 构建与测试

前置：静态复核通过。输入：固定 fixture、工作区插件和实际 5.2.1。以下是后续命令，本次没有执行功能测试：

```powershell
$blenderExe = 'H:\Blender\5.2.1\blender.exe'
& $blenderExe --background --factory-startup --python-exit-code 1 --python 'H:\Blender_Plugin\tests\run_humanoid_mounts_tests.py' -- test_humanoid_mounts_transform.py
& $blenderExe --background --factory-startup --python-exit-code 1 --python 'H:\Blender_Plugin\tests\run_humanoid_mounts_tests.py' -- test_humanoid_mounts_lifecycle.py
& $blenderExe --background --factory-startup --python-exit-code 1 --python 'H:\Blender_Plugin\tests\run_humanoid_mounts_tests.py' -- 'test_humanoid_mounts_*.py'
& $blenderExe --background --factory-startup --python-exit-code 1 --python 'H:\Blender_Plugin\tests\run_spring_bone_tests.py' -- 'test_spring_bone_*.py'
& $blenderExe --background --factory-startup --python-exit-code 1 --python 'H:\Blender_Plugin\tests\run_pose_channel_tests.py' -- test_ik_pose.py
```

新 runner 记录 Blender version/hash、插件 `__file__`、过滤器和实际选择数；输出 `HUMANOID_MOUNTS_SELECTED n`。只有 `n > 0`、用例全部成功、无 skip/expected failure、退出码 0 才输出 `HUMANOID_MOUNTS_TEST_OK`。导入失败产生的假用例不计作业务 RED。

聚焦 GREEN 后跑新插件整套及上述两项既有回归；分别核对 `SPRING_BONE_SELECTED`/`SPRING_BONE_TEST_OK`、`POSE_CHANNEL_SELECTED`/`POSE_CHANNEL_TEST_OK`。完整 Retarget runner 会运行导出和预设写入，不默认执行；如发现具体影响，先限定隔离输入和写入目录，再补对应回归。

fixture 复用 `run_retarget_test.build_biped`，只导入定义、不执行 `main`，并先检查当前模块顶层副作用；其测试依赖不得进入产品包。简单手工基准采用已知平移、90 度旋转和单位缩放，预期不能从被测函数生成。

核心矩阵合同：SNAP 后握持根等于挂点；KEEP_WORLD/解除前后世界矩阵相同；武器部件相对握持根不变。对本计划支持的无剪切 TRS 输入，16 个矩阵元素最大绝对误差不超过 `1e-5`。同时覆盖两种 Relative Parenting、不同 bone roll、非原点握位、角色统一缩放、骨骼约束后的最终姿势、反复绑定与失败回滚。

首批不承诺剪切、奇异矩阵或带反射的绑定。对非均匀/负缩放等输入，使用实际重构检查判定；无法保持合同就预检拒绝。不能把没有异常当作矩阵正确，不能用测试要求去强行修改骨架或全场景单位。

前台用 `run_humanoid_mounts_demo.py` 生成独立人形、可见手掌、两把握位不同的武器和五部位挂点；不覆盖当前文件。实际观察选角色/选骨骼、调偏移、武器切换、手腕转动、走跑动画、解除、一次 Undo/Redo、保存重开及停用/重启用。

如核对真实 Rig，只使用用户已指定资产的测试副本。未取得或未验证的资产保持 `NotRun`；程序化 fixture 不代替对该具体资产的兼容结论。

本任务不新增播放期调度。记录无本插件 timer/handler、无插件逐帧写入；在同一场景中比较启停插件后的原生绑定结果。首批不另设未经需求确认的性能预算；若出现持续轮询、每帧 Python 写入或明显交互停顿，则停止扩展并定位。

预期产物：完整命令/退出码、`transform.log`、`lifecycle.log`、`regression.log`、`runtime.md`、实际查看后的 `visual.md` 和 fixture SHA。进程必须自然退出；后台成功不代替前台视觉。首次明确错误保留日志、先修复，不原样重复；只对新变化影响的范围追加验证。失败场景按步骤 2 至 4 恢复；测试文件只处理声明目录中的本次副本，不恢复或清理用户原文件。

### 7 安装与资产复用验证

前置：步骤 6 通过。输入：本插件目录和已核实的 5.2.1 安装目标。

先按原始字节确定 BAT 编码，再局部增加 `humanoid_mounts` 安装项；无法安全保留编码时记 `Blocked`，不全文转换中文脚本。默认不运行会分发多个旧插件/多个版本的整份 BAT。实际安装只复制本包到由目标 Blender 资源路径确认的目录，先备份该包并记录源/目标 hash；失败只回退该包。

重新加载或重启目标 Blender，核对安装目录中的真实 `__file__`、版本及独立注册；不测到工作区副本后宣称已安装。确认加载前不覆盖其他插件，也不自动结束用户 Blender 进程。

复用验证：把握持根和部件保存为无旧角色引用的武器 Collection，再 Append 到第二个人形场景，绑定后检查两个角色互不串绑。使用本地可编辑数据；Link/Library Override 不纳入首批。保存重开须在新进程核对，不能只在当前会话读取缓存。

预期产物：`install.md`、安装前后包快照、第二角色复用场景。失败：恢复该包与本次测试文件，保留用户场景；不回退其他插件。

### 8 用户核对与临时诊断清理及复验

前置：目标功能通过并已保存必要证据。输入：可观察的人形挂载结果、限制和临时内容登记表。

先请用户核对右手/左手/背/腰/头、两把武器、保持位置/吸附、解除和保存重开。用户核对前保留其核对所需诊断；尚待核对不宣告最终完成。

本文编写未新增临时诊断。实施时登记临时矩阵转储、额外日志、故障注入开关、遍历统计、关系探针、截图/采样脚本、轮询、回调及专用依赖的精确文件和调用点。正式 fixture、必要测试、验收证据、挂点显示和用户握持根属于保留项。

核对后仅清理本次临时内容，移除配套调用、注册、配置和专用依赖。需长期保留的正式诊断记录用途并默认关闭；关闭时不求值日志参数、不遍历、分配或加锁。

清理后重新审查 diff，执行聚焦/整套新插件和适用回归；重验撤销、保存重开与停用/重启用。若关系求值或热路径改变，再做对应动画与性能观察。失败保留未完成状态，不能用“功能已完成”跳过清理或复验。

预期产物：用户核对记录、`cleanup.md`、保留项理由与清理后收据。没有临时项也要明确登记“无”，不能跳过差异确认。

### 9 完成报告

前置：用户核对、清理和必要复验通过。输入：精确 diff、分层证据和清理清单。

报告实际修改文件、已验证的 Blender 版本、五部位与武器边界、失败输入、未解决问题、安装身份和各项门状态。功能只部分通过时报告已验证 WIP；不能把本文完成、后台 GREEN 或已安装称为正式完成。

预期产物：`final-report.md` 和完整证据索引。缺证据或复验失败则保留 WIP/Blocked，返回对应步骤补齐；本步骤不修改场景，无新增场景回滚动作。

## 强制约束

以下 owner 均为本任务主执行者；产品内责任再分到明确入口。证据相对路径统一位于本计划声明的证据目录。任一前置静态门失败先修复或记 `Blocked`，不得带着已知问题进入功能验证。

| 门 | owner 与检查对象 | 判定与证据 | 失败处理 |
|---|---|---|---|
| 规则与范围 | 主执行者；Git、六个插件文件、测试和 BAT | 无无关改动；编码、行尾和命名通过；`environment.md`、`static-review.md` | 停止扩大范围，保留原工作 |
| 仅人形 | 面板/`validate_mount`；角色、部位、实际骨骼 | 人工明确角色，非人形无通用模式；缺映射不误绑；`transform.log` | 拒绝并指出部位 |
| 禁止重复实现 | 主执行者；映射、矩阵、显示 | 不复制 classifier、骨长补偿或另造逐帧跟随；原生 RNA/mathutils 为机制；`materials.md` | 回到既有 owner 或收紧功能 |
| 坐标与状态 | `mounts.py`、`weapons.py` | 原生父空间正确；SNAP/KEEP_WORLD/解除独立合同；无 pose/Action 写入；`transform.log` | 恢复入口，最小修复 |
| 归属与依赖 | 业务函数；标记、Object 引用、parent 链 | 真值唯一；不按名认领；无跨插件生产依赖和环；`static-review.md` | Blocked |
| 生命周期 | 注册入口、各操作；创建/删除、提交/恢复 | 部分注册、重复启停、Undo、加载、故障注入全部覆盖；`lifecycle.log` | Blocked，不冒称取消成功 |
| 线程与持续开销 | 所有 bpy 入口 | 主线程；无插件 timer/handler/worker/逐帧写骨；`runtime.md` | 移除多余调度后复验 |
| 用户数据保护 | 操作与共存测试 | 父级/矩阵失败恢复；原 Action、权重、骨架、其他约束和物体不变；`coexistence.md` | 恢复；不能精确恢复则 Blocked |
| 测试与兼容 | 新 runner、实际 Blender | selected-positive RED/GREEN、0 退出、无必需跳过；5.2.1 实测；`red.log`、`regression.log` | 修复错误再重跑，不降级门槛 |
| 安装 | 主执行者；仅目标 `humanoid_mounts` 包 | 源/目标 hash、真实加载路径、编码保持；`install.md` | 仅恢复该包，缺证据则未验证 |
| 临时诊断 | 主执行者；登记的精确文件和调用点 | 用户核对后清理并复验；`cleanup.md` | 未完成，不宣告正式交付 |

后续扩展只验证边界，不提前实现：动画换手可增加独立操作；新导出目标可读取现有挂点；不同人形骨架只更改已确认部位映射。三者均不要求当前增加注册表、抽象后端或通用 Context。

## 验收标准

| 层级或硬门 | 必须取得的结果 | 当前状态 |
|---|---|---|
| 文档 | 六段结构、首批闭环、精确文件、读取/探子/编译前计划、用户核对与清理顺序齐全 | Passed，仅文档静态核对 |
| 环境 | 当前路径 `--version` 退出 0，5.2.1 LTS，hash `9e2066aef7ef` | Passed，仅环境 |
| Static | 业务命名、无注释、单向依赖、原编码/行尾、无无关 diff，全部入口预检通过 | Passed，见 static-review.md |
| Contract | 可归因 RED 与 GREEN；三个矩阵合同误差不超过 `1e-5`；bone roll、Relative Parenting、原点偏移及统一缩放覆盖 | Passed，34 项 |
| 人形功能 | 五部位创建/编辑/复制/改名/换骨骼/删除，武器根准备、SNAP/KEEP_WORLD、解除、两把武器复用 | Passed，夹具范围 |
| 数据与失败 | 非支持输入不变；失败回滚精确；正常解除保留当前姿势；用户 Action/slot/权重/rest pose 不变 | Passed，覆盖见测试与生命周期收据 |
| 生命周期 | 首次注册、部分注册失败、注销后重启、Undo/Redo、删除与加载均无残留或误删 | Passed，后台及前台分别核验 |
| Process | 新旧适用 runner 自然退出 0、选择数大于 0、正确加载路径和成功标记 | Passed，零选择负控退出 1，不计业务 RED |
| Runtime | 原生播放跟随、暂停/倒放/跳帧、前台操作、保存重开、独立及共存均通过 | Passed，5.2.1 夹具范围 |
| Visual | 亲自查看可见人形与武器，掌心校准、手腕旋转、五部位和两把武器无错误跳位；记录限制 | Passed，程序化演示；用户具体资产 NotRun |
| 资产与安装 | 无旧角色引用的武器 Collection 可复用；单包安装后真实身份核对通过 | Passed，本包六文件 |
| 兼容 | 5.2.1 按上述层级验证；未测版本不声明支持 | 5.2.1 Passed，其他 NotRun |
| Build/C/C++/Generated | 纯 Python；无 C/C++ 编译、代码生成、allocator、unique_ptr、raw pointer、namespace/成员/参数格式形态 | NotApplicable |
| RealTransport/Apply/Resim | 无网络、引擎预测或回滚目标 | NotApplicable |
| 正式完成 | 目标结果经用户核对，临时诊断清理，清理后必要验证通过，证据可追溯 | Passed，见 completion-audit.md |

独立新进程才证明保存重开与安装加载；源码和 API 存在只证明 Static。测试夹具通过不等于任意人形 Rig 兼容。任一必要验收仍为 `NotRun`、`Concern` 或 `Blocked` 时，不宣告插件实施最终完成。

## 禁止事项

- 不实现非人形、通用物体挂点或当前范围外的动画、蒙皮、导出能力；不把高级功能按钮做成可用假象。
- 不改角色骨架拓扑、rest pose、Relative Parenting、源 Mesh 原点/顶点、Action/slot/NLA、权重或其他插件私有状态。
- 不添加自动骨骼识别器、手写骨长补偿、实时跟随 handler、跨插件锁、全局注册表或无业务意义的抽象层。
- 不强行处理不可编辑链接、复杂外部父级、动画根、奇异矩阵或不可保持的剪切；不吞掉恢复失败。
- 不按前缀、目录名或孤儿状态批量删除；只移除能证明属于本次操作的对象和临时内容。
- 不复制第三方或 UE 实现，不引入无关依赖；不得因为旧插件使用某 API 就跳过本机合同验证。
- 不执行 Git 暂存、提交、推送、stash、清理或回退；发布与版本扩展不包含在本文编写任务中。
