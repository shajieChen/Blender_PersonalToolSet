# 人形装备三步操作与首次设置实施档

```text
文档与基线 -> selected-positive RED -> 首次设置与三步主界面 -> GREEN/回归/安装
保存证据 -> 用户人工核对 -> 清理诊断 -> 必要复验 -> 正式收尾
```

日期：2026-10-30。owner：主执行者。状态：逻辑实施与安装副本验证通过，待用户人工复核及正式收尾。设计依据：[三步操作设计](../specs/2026-10-30-humanoid-guided-equipment-design.md)。本档路径以本文目录为基准，命令和源码清单以仓库根为基准。

## 目标

已校准装备日常只需角色、装备、位置和放置按钮。首次缺角色握位或装备拿法时，按单个下一步完成可保存、可取消设置。骨骼/挂点管理统一进入默认关闭的高级区；切部位和换角色不混显旧对象，不用长期显示旧错误。

## 修改范围

仅 humanoid_mounts/{__init__,properties,panels,operators,weapons,mounts}.py；新增 placement.py；新增 tests/test_humanoid_mounts_guided.py 与必要的独立重开测试路径。必要时局部更新正式预览脚本以生成新主流程夹具。证据为 ../evidence/2026-10-30-guided-mounts/，副本/备份为 tests/out/guided_mounts/。不修改重定向、Spring或旧证据。

Git root与remote已核对，当前HEAD a2c7ed4；上轮自动挂载已在当前源码中，不能以旧dirty状态或旧测试报告代替本次事实。现有mmb文档dirty/untracked原样保留，不进行Git写操作。

## 实施步骤

### 1 材料、基线与预检

输入：设计档、当前源码和Git状态。已完整读取本次减枝准则，主代理亲自读取将修改的具体源码；上轮已读取且未变的基础调研直接复用。首次读源码后不重复派发定位；核心GREEN后一次并发派发两个只读独立复核，分别检查设置生命周期和界面状态。等待两者终态后收敛，未委派实现。复核发现具体快照预检/取消回滚与只读输入校验缺口后才补局部验证。按实际小批读取，截断仅补缺失范围。

备份精确文件字节，记录编码/BOM/换行/末尾状态。用既有 run_humanoid_mounts_tests.py 跑56项基线；先核对RNA的Pointer/CollectionProperty、原生变换通道、Object可编辑性和选择限制。纯Python不编译C++。失败先保留日志再修，不重复失败命令。

### 2 行为RED与最小完整GREEN

前置：基线和静态环境通过。输入：普通rig、已登记握持根、未准备多部件装备和旧保存字段。先建立状态/设置/取消/布局合同测试，在测试体内检查缺失入口，取得selected>0 RED。再依次实现：只读状态与部位选择 -> 显式装备输入 -> 角色握位开始/保存/取消 -> 装备拿法开始/保存/取消 -> 主面板完整放置。

复用create_mount、ParentPose、prepare_grip_root、bind_weapon/equip_weapon。仅把已有部位选择与握持根查找拆为可读查询以避免重复逻辑。旧API继续接受已有输入；新主流程以明确选择的装备为准，不被后续选中标记覆盖。

开始设置前验证Object Mode、Auto Keying关闭、输入可编辑可选、无动画/约束等既有限制。快照由场景属性持有，Object指针和原父级指针配合JSON原生通道；不按名字恢复。取消删除的只能是本次创建的无外来附件挂点；原对象全部恢复。存储/绑定失败保持可恢复状态。改变角色/部位时禁止保存旧设置；取消仍按原owner恢复。

### 3 总高级区与即时状态

主面板默认只显示三项输入、当前步骤和对应动作。新增总开关show_advanced默认False，旧子面板展开也不能透出。部位用下拉框。只读状态不update depsgraph、不写场景、不创建点；已有挂点与已校准严格区分。正在设置时锁定其他入口；重置/换骨骼使角色握位确认失效。

失败处理：布局或状态合同不符先修，不能用视觉猜测。取消前检查全部快照，恢复出错保留入口编辑姿势；停用前先检查所有场景，避免一个坏场景导致其他场景提前取消。取消/停用/重开都验证对象和父子关系；部分注册仍按原机制回滚。新增属性类先注册、逆序注销；注销前取消未保存设置，失败时停止注销而不是丢失快照。

### 4 编码与格式复核

修改后、测试前以及再次修改后，复核实际API/import/头部注册顺序、业务命名、无新增注释/docstring、对象归属、失败恢复、无持续回调和原生矩阵语义。保留原编码/换行/末尾状态，无行尾空格或无关diff，内存compile并git diff --check。明确错误先修再跑。

### 5 构建与测试

前置：静态复核Passed。工作目录明确为仓库根。

```powershell
$blenderExe = 'C:/Program Files/Blender Foundation/Blender 5.1/blender.exe'
& $blenderExe --background --factory-startup --python-exit-code 1 --python ./tests/run_humanoid_mounts_tests.py -- test_humanoid_mounts_guided.py
& $blenderExe --background --factory-startup --python-exit-code 1 --python ./tests/run_humanoid_mounts_tests.py -- 'test_humanoid_mounts_*.py'
```

exe绝对路径是已核对的环境入口例外；5.2.1使用 H:/Blender/5.2.1/blender.exe 加 --threads 1。selected必须>0、无必需skip、退出0；两版本顺序跑，避免共享夹具文件冲突。首次设置、多部件、已登记根调整、失败注入、取消、角色/部位改变、旧展开字段、无绘制写入、保存新进程重开和停启为必要门。矩阵误差<=1e-5，原mesh/骨架/Action不改。只运行受影响回归，不因旧的metarig基线失败扩展修复。Spring既有runner会写历史证据，本次未改Spring，不重复执行。

安装到实际5.1 user_resource('SCRIPTS')/addons 的本包确切文件；先全部准备并核对安装文件与起始源码的差异，再写入。保留安装副本其他能力，不运行批量BAT。安装副本跑新合同并记录真实加载路径和hash。准备独立人工检查场景，不运行Computer Use或自动前台交互。

### 6 临时诊断清理及复验与完成报告

登记本次临时内容：计划生产诊断、日志、探针、采样、轮询、调试钩子及专用依赖均为无；若新增必须精确登记。正式设置快照、必要测试、夹具和证据保留。

保存证据并交付用户人工核对。核对前不宣告正式完成；核对后清理本次非正式依赖的临时内容，重审diff并重跑必要聚焦/回归；运行路径改变补运行验证。报告逻辑实施、安装、Visual和正式验收的独立状态。无临时内容也记录无与差异检查。

## 强制约束

| 门 | owner/动作与通过标准 | 证据/失败处理 |
|---|---|---|
| 范围与编码 | 主执行者核对root/remote/确切文件与起始字节，保留无关dirty、编码和布局 | static-review；失败先修，不做无关清理 |
| 职责与依赖 | placement管步骤，weapons/mounts管原生关系，面板只读；无反向import/重复算法 | 源码与diff；失败Blocked |
| 无新增注释与语义命名 | 本次Python token/AST新增comment/docstring为0，无泛化框架 | static-review；违规先修 |
| 所有权与失败 | Scene拥有输入与设置快照；指针恢复；创建/保存/取消/注销成对，故障无误删 | 聚焦测试；未闭合Blocked |
| 线程与开销 | 仅bpy主线程；不新增timer/handler/worker/depsgraph写入 | 状态只读测试和静态检查 |
| API与矩阵 | 真实RNA、原生求值、无剪切合同<=1e-5；不改原点/顶点/角色动画 | 版本日志；不满足拒绝输入 |
| 测试 | selected-positive RED、最小GREEN、全挂载回归、独立重开与安装身份 | 日志/退出码；非0不算GREEN |
| C++专门门 | 无C/C++修改；m_对齐、普通=对齐、namespace Tab、三元分组、allocator/unique_ptr/raw pointer/宏隔离均NotApplicable | 完成报告明确列出 |
| 诊断与证据 | 无生产诊断；用户核对后精确清理/复验，低等级证据不替代Visual | 临时清单及result；未核对不得正式完成 |

## 验收标准

| 项目 | 实际结果与证据 | 状态 |
|---|---|---|
| 主流程 | 默认总高级门、三项输入、唯一下一步；只读draw不重复旧错误；角色固定、旧部位不混显 | Contract Passed |
| 首次设置 | 角色/装备分别保存，已有偏移不重置，多部件与已登记根调整均通过 | Passed |
| 恢复与生命周期 | 取消恢复、保存失败保持可重试、取消中途恢复到入口、跨场景停用预检、独立重开保存/取消通过 | Passed |
| RED/GREEN | selected=17缺入口RED；随后聚焦GREEN扩展到25项 | Passed |
| Process/后台Runtime | Blender5.1.2与5.2.1各81/81，退出0；5.2.1使用--threads 1 | Passed，夹具范围 |
| 安装 | 5.1本包7项实际变更、8文件哈希核验；安装副本25/25和独立重开通过 | Passed |
| Static | 9个Python文件语法、编码/换行、零新增注释、局部依赖与生命周期复核通过 | Passed |
| Generate | 新主流程人工场景已生成，状态READY、默认高级关闭，无自动轮询 | Passed，仅夹具 |
| Visual/真实Undo/Redo/用户资产/正式验收 | 未运行Computer Use，交由用户人工复核 | NotRun |
| 临时诊断与收尾 | 生产新增临时诊断为无；必要测试/快照/证据保留，正式收尾待用户核对 | 源码清理Passed；收尾待核对 |
| Build/代码生成/RealTransport/Apply/Resim | 纯Python，无这些目标 | NotApplicable |

详细索引见[实施结果](../evidence/2026-10-30-guided-mounts/result.md)。人工核对后，再确认临时项清单并执行必要复验，不把后台通过称为正式验收。

DP-01 Passed：步骤2/3与验收覆盖三步和首次设置。DP-02 Passed：仅必要状态和可取消编辑。DP-03 Passed：复用原有骨骼/握持根/父级实现。DP-04 Passed：先完整核心再高级整理。DP-05 Passed：失败、生命周期、测试及用户后清理明确。DP-06 Passed：六段结构、前置/动作/产物/失败边界齐全。

执行效率记录：首次组合读取输出截断，仅补齐确切缺失范围。首轮新测试未显式固定part且在tearDown删除对象后才注销，导致状态串用和取消指针失效；已隔离默认部位并调整为先注销再删除夹具。探子仅一次独立复核批次。双版本首次提前启动第二进程存在共享产物风险，未采用为最终凭据；改为同一shell顺序执行并等待终态，两版本均81项通过。后续仅因末次反馈改动重跑必要套件，最终安装25项通过。没有C++构建或可避免的编译失败。

## 禁止事项

不执行Git暂存/提交/推送/回退/清理。不改其他插件或旧证据。不猜测任意资产握柄、不自动握拳、不复制绑定算法。不在draw里写数据或增加轮询；不按名称认领/删除对象。不把后台布局合同当作Visual，不跳过人工复核收尾。
