# 动态骨骼插件实施文档

```text
首批短链预览 -> 腿部碰撞与锥限 -> 裙摆多链 -> 安装与回归
完成目标并保存证据 -> 用户核对 -> 临时诊断清理 -> 清理后复验 -> 完成报告
```

日期：2026-10-23。状态：待实施；本次不改插件代码、不安装插件。

设计依据：[动态骨骼插件设计](../specs/2026-10-23-spring-bone-design.md)。公式依据：[Spring Bone公式证据](2026-10-23-spring-bone-formula-evidence.md)。

## 目标

新增与 `humanoid_retarget` 同级的 `spring_bone` 插件，使已有裙摆骨骼在基础动作上生成二次运动，支持球/胶囊代理碰撞、锥限、预览、取消恢复及独立结果Action。Retarget无需启用，也能使用本插件；启用两者时按先重定向、后动态骨骼的顺序操作。

首批必须交付三段链可观察的摆动预览与停止恢复，先证明尾点历史、父子传递和旋转写回有效，再加碰撞和完整裙摆。不得先做通用框架、大量预设或实时求值handler。

## 修改范围

| 范围 | 文件与职责 |
| --- | --- |
| 独立插件 | 新增 `spring_bone/__init__.py`、`properties.py`、`panels.py`、`operators.py`、`animation.py`、`solver.py`，职责按设计文档 |
| 聚焦测试 | 新增 `tests/test_spring_bone_solver.py`、`tests/test_spring_bone_animation.py`、`tests/test_spring_bone_lifecycle.py` |
| 测试入口 | 新增 `tests/run_spring_bone_tests.py`；导入工作区路径，数量>0，失败退出非零 |
| 场景与视觉 | 新增 `tests/run_spring_bone_demo.py`；程序化生成裙骨和测试裙网格，可选加载用户已确认的资产；不覆写用户blend |
| 安装 | 最后局部修改 `安装插件.bat`，新增安装项与提示；保留原编码、行尾和已有安装行为 |
| 实施证据 | 后续新增 `docs/superpowers/evidence/2026-10-23-spring-bone/`，记录环境、命令、计数、退出码、指标和人工验收结果；日期可按实际运行更新 |

默认不改 `humanoid_retarget` 的任何源码，不共享其私有函数、配置、`hr_actions` 或烘焙作业。只读当前实现以确认共存边界。发现必须修改既有插件时先说明实际缺口，不顺手扩大范围。

## 实施步骤

### 1 固定材料与执行入口

前置：本设计和公式证据可完整读取。输入：当前Git状态、源码和目标Blender。

动作：记录Git root/remote、所有适用AGENTS/CLAUDE规则、授权文件及哈希。保留现有untracked公式证据。主执行者亲自读两份依据和即将修改的具体代码。

本轮已读材料与可复用结论：

| 材料 | 已确认内容 |
| --- | --- |
| 公式证据全文 | VRM/UE参数不可映射；center只核到平移；碰撞和奇异方向的证明边界 |
| `retarget.py:1472-1591,1765-1808` | 现有动画状态恢复、同步烘焙和Action显示；不是跨插件公共接口 |
| `__init__.py:867-895,1435-1477` | 当前操作器、注册与注销位置 |
| `soft_repulsion.py`、对应设计和实施档 | 已有Goal积分语义不同；不复制同职责模块，也不误用公式 |
| 旧Retarget modal设计和计划全文 | 主线程切片、取消恢复风险；其旧版本与行号不得当成当前实现 |
| `run_pose_channel_tests.py`、`run_retarget_test.py`入口 | 可复用测试方式，分别有数量和成功标记 |
| 安装BAT、5.2.1版本与RNA查询 | 安装入口和所需基础API存在 |

未变化材料直接复用。仅对修改、冲突或缺失范围复读。本轮一次探子超过等待预算后被中断，未取得终态报告；已由主执行者定向定位补齐，不将其过程信号当证据。实施时独立缺口一次并发安排，要求file:line、符号和关键原文；派发后等待收敛，不重复全仓探索。

构建前检查：本项目无C++编译目标；先核对Python语法、工作区导入路径、mathutils乘法顺序、`convert_local_to_pose`参数、Action/slot及旋转曲线访问、子帧采样、modal取消入口。5.2.1仅确认API存在，实际矩阵和slot行为仍须测试。明确API异常先留日志并修正，再重跑，禁止原样重复失败命令。

预期产物：执行环境清单、材料索引、输入/输出范围、初始资源快照。失败：必读规则或所需API缺失标记Blocked；未改数据时直接退出。

### 2 首批短链预览

前置：步骤1通过。输入：程序化骨架，固定父骨加三段连接骨；父骨具有平移和旋转动画。

1. 新增纯数值测试和测试入口。测试类中显式断言模块/API存在，以保证缺实现时仍收集到真实测试。记录 `selected>0` 的可归因RED；导入崩溃、空过滤或环境缺mathutils不算目标RED。
2. 实现 `SpringChainState` 和 `step_chain`，只含尾点历史、方向恢复、重力、长度及父子递推。单步手算基准固定为：head=(0,0,0)，length=1，current=previous=(0,1,0)，drag=0.5，stiffness=0，gravity=(0,0,-1)，gravityPower=1，dt=1/60；尾点为 normalize(0,1,-1/60)。预期值不能从被测函数生成。
3. 加最小配置和链预检，拒绝分支、重复占用、零长、非法比例和特殊继承。数值GREEN后再接bpy，不建立实时handler。
4. 实现采样、模拟、结果写入的同一 `SpringBoneBakeJob`。每步先恢复基础输入，再求值并复制；写入在独立Action副本上完成。矩阵转换使用设计给出的父参考递推，验证基础twist与父段模拟都传到子段。
5. 加生成预览与停止两个操作。主线程modal以约16ms为预算，在完整采样/模拟/写入单元后检查预算，至少执行一个单元；自己的TIMER才推进。进度每0.25秒更新。后台同步入口驱动同一作业至完成，不注册窗口timer。
6. 前台播放三段链，显示滞后与衰减；停止预览恢复输入Action/slot、旋转模式、姿势和入口时间。保存最小场景、指标和观察记录。

预期产物：数值RED/GREEN日志、可播放预览、停止恢复测试。失败：停止调度，恢复入口，仅删除本次结果副本；基础动作与用户对象保持原状。

### 3 增加碰撞与限制

前置：短链预览和恢复通过。输入：球、胶囊及非模拟腿骨绑定。

动作：先加入球外/内/切触、胶囊端点/轴中/退化、轴心零方向、锥边界、反平行四元数的独立断言并取得RED，再实现有序投影。遵循积分后长度与锥限、每次碰撞后再长度与锥限的顺序。只支持外球和外胶囊，不提前加入内部形状或平面。

代理体配置采用非模拟骨的局部米制偏移、两端及半径；采样后转换世界坐标。显示Empty与配置同步由显式更新操作完成，不依赖持续轮询。只读取已确认绑定，动态链与碰撞绑定存在反馈则拒绝。

追加 `WORLD` 和 `FOLLOW_TRANSLATION` 的对照：同一平移加到两帧历史后惯性差保持相同；参考旋转不抵消；重力保持世界方向。零向量与确定性备用方向由测试固定。

预期产物：数值GREEN、腿部碰撞短链演示、最终姿势残余穿深表。失败：恢复入口，记录冲突输入；不能加无限迭代、改骨长或宣称已无穿模。

### 4 完成裙摆和动画事务

前置：步骤3通过。输入：8条链、每链3段的程序化裙摆网格，左右腿和骨盆动画；基础Action可来自Retarget或手工动画。

动作：多链父优先、固定配置顺序，拒绝同骨被两链写入。模拟稳定60Hz，预热0.5秒，支持子帧输出、结束帧插值、四元数半球连续和LINEAR键。24/30/60及30000/1001帧率以相同物理时间输入比较。

Action事务先测试再完成：复制单slot输入；仅替换指定链的旋转曲线，按原QUATERNION或Euler模式写键，不改变rotation_mode；Euler使用与上一输出角兼容的转换。保留其他通道和输入原数据，切回基础Action仍能正确播放。AXIS_ANGLE、旋转模式动画、多slot、多层Action、活动NLA、链骨约束/driver及不可编辑数据预检报错。正式结果保留fake user；不新增NLA，不登记 `hr_actions`。结果属性及预览时间轴记录请求范围，范围外模拟旋转不作为交付。

测试初次开始、采样中断、第二链失败、Action创建后slot失败、写入中断和提交前异常。开始就登记创建物，取消可重复，成功后的清理不能删除结果。连续生成、停止、再次生成、正式烘焙、文件加载、Undo、注销均验证资源恢复。

预期产物：完整裙摆预览/烘焙、Action曲线对照、错误注入和生命周期日志。失败：精确回滚本次事务；不能恢复的路径标记Blocked，禁止只返回CANCELLED。

### 5 编码与格式复核

前置：每批补丁完成，尚未开始该批测试。输入：本次diff和完整受影响函数。

动作：检查业务命名、无新增注释或docstring、单向依赖、无Retarget导入、显式资源所有权、无bpy线程和全局数值缓存。检查编码/行尾/行尾空格、源Action未修改、参数边界和数学API。AST编译采用内存 `compile`，不生成仓库pycache。代码再改后重新复核。

本任务不创建或修改C/C++；namespace Tab、三元参数、`m_`声明、普通赋值对齐、unique_ptr label及Engine内存硬门均为NotApplicable，不套用MiniGameCode/RainbowEngine规则。

预期产物：逐文件复核表。失败：最小局部修正后复核，不带已知静态错误进入测试。

### 6 构建与测试

前置：步骤5通过。输入：工作区代码及固定测试fixture。以下命令为后续实施入口，本次未运行功能测试：

```powershell
$blenderExe = 'H:\Blender\5.2.1\blender.exe'
& $blenderExe --background --factory-startup --python-exit-code 1 --python 'H:\Blender_Plugin\tests\run_spring_bone_tests.py' -- test_spring_bone_solver.py
& $blenderExe --background --factory-startup --python-exit-code 1 --python 'H:\Blender_Plugin\tests\run_spring_bone_tests.py' -- 'test_spring_bone_*.py'
& $blenderExe --background --factory-startup --python-exit-code 1 --python 'H:\Blender_Plugin\tests\run_pose_channel_tests.py' -- 'test_*repulsion.py'
& $blenderExe --background --factory-startup --python-exit-code 1 --python 'H:\Blender_Plugin\tests\run_retarget_test.py'
```

新入口打印 `SPRING_BONE_SELECTED <实际测试数>` 和 `SPRING_BONE_TEST_OK`；无匹配、skip和导入错误不能当GREEN。既有入口分别检查 `POSE_CHANNEL_TEST_OK` 和 `RETARGET_TEST_OK`，所有GREEN退出码必须为0。环境日志包含Blender版本、hash、插件 `__file__`、输入Action/slot及测试选择数，防止测到安装目录旧副本。

前台通过 `run_spring_bone_demo.py` 生成独立测试场景，核验播放、进度、Esc、一次Undo、保存重开与禁用插件。性能样本为24动态骨、5代理体、300帧@30fps，约600固定步另加预热；记录准备、采样、求解、写入、峰值内存、最长单元和最长切片。目标总生成<=10秒、95%切片<=50ms；这是待验证预算，超限记Concern并定位，不用平均值隐去长阻塞。

兼容声明先限定通过验证的5.2.1。若要发布Blender4.2最低版本，必须用实际4.2可执行文件再跑数值、Action、生命周期与前台测试；未取得版本或未运行时兼容性保持NotRun，不照抄Retarget的最低版本声明。

后台通过后才局部扩展BAT安装项。安装仅分发spring_bone目录，记录源/目标哈希；人工安装或重启对应Blender后核对实际加载路径、注册次数和独立启停。安装器运行另行按实施时授权执行，本次文档交付不运行BAT。

预期产物：测试日志、性能表、前台清单、按版本的安装核验。失败：保留首个明确错误日志，修复后重跑对应聚焦项；新改动影响到回归时才追加整套执行。

### 7 用户核对与临时诊断清理及复验

前置：功能验证通过，必要证据已保存。输入：用户可查看的裙摆结果与诊断清单。

先展示同一动作的基础/模拟结果、行走、转身、深蹲和快速抬腿场景，给出残余穿模与限制。用户核对目标结果前保留核对所需诊断；尚待核对不宣告最终完成。

本次文档编写未新增临时诊断。后续实施须逐项登记：临时tail轨迹、穿深可视化、计时wrapper、采样计数、额外日志、故障注入开关、轮询/handler、调试脚本及仅为它们增加的依赖。正式测试fixture、验收证据、用户代理体和功能所需modal TIMER保留，不当作临时物删除。

核对后仅清理本任务临时内容，同时移除其调用、注册、配置和专用依赖。确需保留的正式诊断注明用途、默认关闭，关闭时不求值日志参数、不遍历或分配。清理后复核diff、重跑聚焦与回归，并复验取消/注销/Undo；运行路径改变时重做裙摆和性能样本。

预期产物：用户核对记录、清理清单、保留理由、清理后测试。失败：保持未完成状态，不删除用户资产、原有修改和必要证据。

### 8 完成报告

前置：用户核对、诊断清理及必要复验均通过。输入：本次源文件diff、收据和清理表。

报告实际文件、可用版本、功能边界、残余穿模及性能数据；列出下表所有门的Passed/NotApplicable/Blocked，不用一句已测试替代。Build对纯Python为NotApplicable，未运行证据明确NotRun。只完成部分批次时报告已验证WIP，不宣告整插件完成。

## 强制约束

| 门 | owner与检查对象 | 判定及证据 | 失败处理 |
| --- | --- | --- | --- |
| 范围与规则 | 主执行者；Git root、规则及授权文件 | 只在允许范围新增/修改；材料和初始状态写入 `environment.md` | Blocked，保留现有工作 |
| 结构与命名 | 主执行者；全部新增Python文件 | 业务命名、无禁用架构词、无注释/docstring、AST通过；`static-review.md` | 修正后再测 |
| 依赖与状态 | 主执行者；solver、animation、operators | 单向依赖；solver无bpy/Retarget；状态归一次Job；`static-review.md` | Blocked |
| 公式与坐标 | 主执行者；step_chain、姿势转换 | 独立预期、米制、长度、父子/twist和退化规则通过；`contract.log` | 回到最小数值修复 |
| Action安全 | Job；输入Action/slot与新副本 | 输入曲线不变、非模拟通道不变；不支持输入预检拒绝；`animation.log` | 恢复入口 |
| 生命周期 | Job/操作器；预览、取消、提交、注册 | 创建/删除、启动/停止、注册/注销逐项对称；故障恢复；`lifecycle.log` | Blocked，不冒称取消成功 |
| 线程与时钟 | 操作器/Job；采样、模拟、写入 | 全部bpy主线程；60Hz与展示fps解耦；`contract.log`、`runtime.log` | 停止作业并修复 |
| 不争写 | 操作器；同骨架与场景 | 一次活动任务；输入变更取消；Retarget顺序使用；`coexistence.md` | 拒绝并提示停止当前任务 |
| 诊断清理 | 主执行者；本次临时项 | 用户核对后清理、再复验；`cleanup.md` | 未完成 |

上述证据文件均放在修改范围声明的证据目录，实际执行时创建。拥有者均为本插件主执行者及具体Job/操作器，不能转交给Retarget承担恢复。

## 验收标准

| 层级或硬门 | 必须达到的结果 | 当前状态 |
| --- | --- | --- |
| Static | 新包与Retarget同级、可独立注册；无双向依赖、重复数学实现或无关diff；规则/命名/编码门通过 | NotRun |
| Contract | selected>0的真实RED与GREEN；手算递推、零向量、反平行、球/胶囊/锥限、权重0/1、参考平移均覆盖 | NotRun |
| 数值精度 | 骨长误差<=max(1e-6米,长度*1e-5)；四元数范数误差<=1e-5；非冲突碰撞穿深<=1e-5米 | NotRun |
| 时钟一致 | 相同连续输入在24/30/60/30000/1001fps下，同物理tick的尾点差<=1e-5米、旋转差<=1e-4弧度；两次新作业一致 | NotRun |
| 动画回归 | 输入Action与非模拟通道逐项不变；新动作独立播放；slot、原旋转模式、Euler连续/近万向锁、切回原Action、根运动与混合父子正确 | NotRun |
| 生命周期 | 取消/错误/Stop/重建/Undo/加载/注销成对恢复；没有悬空会话、残留timer或误删Action | NotRun |
| Process | 自然退出0、正确工作区路径、真实选择数与成功标记；完整回归通过 | NotRun |
| Runtime | 三段链与8链裙摆可生成、停止、烘焙、保存重开；两插件单独及同时启用均符合顺序约定 | NotRun |
| Visual | 亲自检查裙网格和逐帧转身/深蹲/抬腿；记录难例和残余穿模；不能只交骨骼截图 | NotRun |
| 性能 | 固定样本实测预算，保留分阶段数据与最长阻塞；超预算先定位 | NotRun |
| 兼容 | 5.2.1实际功能通过；4.2未测不声明支持 | NotRun |
| Build与C/C++ | 无C/C++和生成管线；成员对齐、赋值对齐、namespace、三元参数、unique_ptr label、raw pointer门均不适用 | NotApplicable |
| Generated/RealTransport/Apply/Resim | 无代码生成、网络或引擎回滚目标，不以其替代Blender证据 | NotApplicable |
| 收尾与正式验收 | 目标结果经用户核对，临时诊断清理，清理后聚焦/回归/必要视觉与性能复验通过 | NotRun |

## 禁止事项

- 不修改Retarget求解、映射、片段切换、原Action、rest骨架、网格权重和用户代理体归属。
- 不把UE SpringBone或Goal软力积分当成本模型；不复制UE源码；如后续引入第三方代码，先核逐文件许可证并保留必要声明。
- 不引入bpy工作线程、实时姿势handler、跨插件通用锁、万能Manager、注册表或推测性求解后端。
- 不按名称批量删对象/Action，不清理全局孤儿；不执行Git暂存、提交、推送、回退或stash。
- 不把点碰撞称为布料自碰撞或保证无穿模；不把API探针、后台通过或文档交付称为视觉与正式完成。
