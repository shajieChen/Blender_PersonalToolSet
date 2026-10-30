# 人形映射自动挂载实施档

```text
最终重定向映射 -> 角色骨骼记录 -> 一键装备 -> 原生动画跟随
保存证据 -> 用户核对 -> 清理本次临时诊断 -> 清理后复验 -> 最终报告
```

日期：2026-10-30。owner：本任务主执行者。状态：核心实施与首轮逻辑验证通过；按用户最新要求以逻辑验证为主，Visual、用户真实资产与正式验收待用户人工复核。

## 目标

已重定向角色不再手动选择实际骨骼。选择已登记握持根或其武器部件，点击“装备到当前部位”，自动创建或复用挂点并吸附。右手先闭环，再覆盖左手、背、腰、头、多角色、保存重开和失败恢复。

自动定位骨骼不等于掌心校准。新建挂点沿用骨骼原点并明确提示首次校准；已有角色挂点与武器握持根保存其校准。已校准角色和武器后续免选骨、免光标。未知武器首次通过现有光标工具创建握持根，不猜剑柄、不宣称自动握拳。

## 修改范围

仓库根为本文上三级目录，remote 已核对为 github.com/shajieChen/Blender_PersonalToolSet.git。本文路径相对本文目录；代码与命令的工作基准为仓库根。

- `../../../humanoid_retarget/mapping.py`：校验并序列化最终目标角色语义骨骼记录；成功后发布。
- `../../../humanoid_retarget/retarget.py:_bake_retarget`：在任何动画写入前复用相同记录校验，防止已完成烘焙后因非法映射报错。
- `../../../humanoid_retarget/pipeline.py:retarget_existing`：成功烘焙后发布；只作局部修改，保留本任务开始前已有的 FBX 修改。
- `../../../humanoid_mounts/bone_roles.py`：只读记录、部位解析和失效反馈。
- `../../../humanoid_mounts/weapons.py`：复用绑定能力，合并装备事务与失败恢复。
- `../../../humanoid_mounts/operators.py`、`panels.py`：读取目标、一键装备及折叠自定义操作。必要时局部调整 properties.py；不新增持续回调。
- `../../../tests/test_humanoid_mounts_automatic.py`、`run_humanoid_mounts_automatic.py`：合同、真实重定向链、重开和前台验证入口。
- 证据目录 `../evidence/2026-10-30-auto-mounts/`；夹具、备份和运行副本为 `../../../tests/out/auto_mounts/`。不覆盖用户 blend。

数据合同：目标 Armature Object 的 `hr_bone_roles` 保存 JSON `{schema:1, roles:{role:actualBoneName}}`，不保存来源对象或临时骨架。mapping.py 是写入 owner，挂载模块只读；只在真实烘焙成功后替换，不在预览、失败或面板绘制时写入。记录只用于新挂点，现有挂点的原生 parent/parent_bone/局部变换仍是真值。骨骼改名造成记录缺失时拒绝新建并提示重新重定向；已有原生挂点继续复用。

## 实施步骤

### 1 固定材料和基线

前置：规则完整读取；输入为当前源码与 Git 状态。已读本次方案、减枝准则、旧实施档/调研、挂载六文件、mapping.py、pipeline.py 的成功入口及现有 runner。未变化材料复用；具体将修改的函数亲自完整读取。上一轮两个只读探子已完成源码定位，本轮不重复派发；仅出现具体跨目录缺口时一次并发并等待收敛。

记录现有 dirty/untracked；将即将触及文件原字节备份到本次 tests/out 目录。实际可用环境已核对：Blender 5.1.2 与 5.2.1。先运行现有挂载整套，保留退出码和 selected 数。失败保留证据，区分既有失败，不改无关内容。

### 2 右手核心 RED 到 GREEN

输入为不同骨轴角色、已登记握持根和非原点握位。先新增可收集测试，在测试体内断言新入口存在，取得 selected>0 的目标 RED。实现成功烘焙后的角色记录、映射读取与装备事务，复用 create_mount、bind_weapon 和 ParentPose。真实调用 retarget_existing 后装备，验证发布的是 options.resolved_pairs。失败重定向不得覆盖旧记录；中间 metarig 不进入最终角色记录。已纠正的最终映射在 _bake_retarget 创建动画前完成 schema、骨名、重复与可写性校验；成功后记录写入仍使用同一序列化校验。新增重复目标骨骼 RED 必须证明 Action/slot/NLA/元数据/帧范围保持原状。

装备顺序：验证武器与归属 -> 优先指定的当前部位挂点 -> 唯一既有挂点 -> 无挂点才解析骨骼并创建 -> SNAP。多个候选必须选择，不暗中认领普通 Empty。武器已有其他挂点时拒绝迁移；失败恢复根的父级和变换，只删除本次新建挂点。预期产物为红绿日志和右手运行场景。失败修复后重跑，不原样重复。

### 3 五部位和界面

在右手 GREEN 后复用相同入口：hand_r/hand_l 对应同名语义，back 优先 chest 后 spine，waist 对应 hips，head 对应 head。缺一部位只阻止该部位。角色可由“使用重定向目标”明确选定，选择武器不切换角色。没有角色记录的旧文件提示重新执行一次重定向；不把未经应用的面板编辑当成最终记录。

主面板保留角色、部位、映射/校准状态和装备按钮；实际骨骼、光标建根、登记、保持位置绑定收入“自定义骨骼与握持校准”。从选中部件沿父链定位唯一已登记握持根；没有则提示首次校准，不自动登记任意 Empty。复用挂点不改其位置或方向。

### 4 编码与格式复核

每次代码修改后先检查实际 API、import 方向、类型、schema、主线程写入、对象归属、父子循环、事务恢复与注册/注销。新代码无注释/docstring，既有注释保留。保留原编码、BOM、CRLF/LF 和末尾状态，局部替换，无行尾空格。无生产跨插件私有 import、逐帧 handler、timer 或全局缓存。通过后才运行测试。

### 5 构建与测试

本项目为 Python，无 C++ 构建；先内存 compile，再用既有 runner：

```powershell
$blenderExe = 'C:/Program Files/Blender Foundation/Blender 5.1/blender.exe'
& $blenderExe --background --factory-startup --python-exit-code 1 --python ./tests/run_humanoid_mounts_tests.py -- test_humanoid_mounts_automatic.py
& $blenderExe --background --factory-startup --python-exit-code 1 --python ./tests/run_humanoid_mounts_tests.py -- 'test_humanoid_mounts_*.py'
& $blenderExe --background --factory-startup --python-exit-code 1 --python ./tests/run_pose_channel_tests.py -- test_ik_pose.py
```

绝对 exe 路径是环境入口例外，脚本相对显式仓库工作目录。5.2.1 使用已核对的 `H:/Blender/5.2.1/blender.exe` 并加 `--threads 1` 复验。Spring 原 runner 会写历史证据目录，后续若确需重跑必须先隔离输出，不能直接重复覆盖。selected 必须 >0、无必需 skip、退出 0。既有 Retarget 全量入口会写预设，本次优先通过隔离 fixture 真实重定向覆盖受影响入口；FBX 回归用既有测试入口并保存输出。

覆盖重复装备、多个挂点、自定义校准保留、两角色不串绑、左右、缺骨/改名、未知 schema、坏 JSON、失败回滚、Relative Parenting、roll、缩放、最终约束姿势、保存新进程重开、独立启停及共存。支持的无剪切矩阵误差 <=1e-5。按用户最新要求不再执行 Computer Use 或自动前台交互；只生成无轮询的独立测试场景供用户人工核对。Visual 和新装备入口的真实 Undo/Redo 保持 NotRun，不以后台算子测试替代。安装时只分发本次两个包的确切文件并核对加载身份；备份已安装文件，不运行批量 BAT。

### 6 用户核对和临时诊断清理及复验

保存可观察场景、日志和身份后让用户核对目标结果。用户核对前保留所需诊断，不宣称正式完成。本次临时内容初始为无；实施中若增加临时探针、日志、采样、轮询或 UI 回调，逐项登记精确文件/入口/依赖。正式测试、测试夹具、验收证据和原生挂点显示保留。

核对后只清理本次临时项与配套注册/调用/依赖，重审 diff 并跑聚焦和适用回归；运行路径变化补运行复验。失败保留 WIP。没有临时项也记录无及差异复核，不跳过清理后复验。最后报告实际状态和证据。

## 强制约束

| 门 | owner 与动作 | 通过标准、证据与失败处理 |
|---|---|---|
| 范围/编码 | 主执行者；精确 diff 对起始备份 | 无无关修改；保留原字节格式；static-review.md；不符先修 |
| 唯一职责/依赖 | mapping 写记录，挂载读记录并复用原生绑定 | 无循环/私有跨插件 import/重复识别器；static-review.md；不符 Blocked |
| 合同/失败 | mapping 发布与 equip 入口 | 成功才写，失败旧记录不变；新建挂点和父级事务回滚；focused 日志；失败先修 |
| 生命周期 | operator/注册入口 | Undo/Redo、停启/重开无误删；无新回调；runtime 收据；未验证保持 NotRun |
| 用户数据 | 角色、根和部件 | 不改 pose/rest/Action/权重/顶点/原点/已有校准；失败不留空挂点；测试日志 |
| 线程/开销 | bpy 主线程操作 | 无轮询/逐帧 Python、无持续诊断；静态与运行分别记录 |
| 注释/命名 | 本次全部 Python 新增行 | 新增注释/docstring 为零；业务语义命名，无无关重排；static-review.md |
| API/测试 | 主执行者；真实 Blender 5.1.2/5.2.1 | selected-positive RED/GREEN、零退出、独立重开、加载路径一致；日志缺失不算通过 |
| C/C++ 特有门 | 本次无 C/C++ | namespace、m_、三元分组、allocator、unique_ptr、raw pointer、宏隔离均 NotApplicable |
| 诊断清理 | 主执行者；临时项登记和用户确认 | 用户核对后清理并复验；未闭合不得最终完成 |

不增加通用框架。三个变化边界已检查：换武器复用角色挂点；换角色仅换角色记录和校准；新增自定义挂点复用现有管理入口。均不需新注册表。

## 验收标准

| 项目 | 当前结果与边界 | 状态 |
|---|---|---|
| Static | 9 个 Python 文件内存 compile、注释/格式/依赖/生命周期与差异检查通过；见 static-review.md | Passed |
| Contract/Process/后台 Runtime | 5.1.2 与 5.2.1 各56/56，退出0；5.2.1 使用单线程 | Passed，夹具范围 |
| RED/GREEN | selected=16 缺入口 RED；selected=19 中1个重复映射行为 RED；最小修复后全部通过 | Passed |
| 安装 | 5.1.2 安装副本22/22，独立进程重开与7文件哈希核验；两个有既有差异的文件只应用本次补丁 | Passed |
| 回归 | Pose13、FBX25、Spring两版本各147通过；重定向全量的metarig原地位移断言在起始副本同样失败 | Passed / 既有Concern分别记录 |
| Generate | 已生成无自动轮询的独立人工复核场景；无代码生成 | Passed，仅夹具 |
| Visual / 新装备入口真实Undo/Redo / 用户真实资产 | 按用户最新要求由用户人工复核，不运行Computer Use | NotRun |
| 临时诊断 | 生产新增为无；预览临时自动化已移除，保留正式测试与证据 | 源码清理Passed；正式收尾待核对 |
| Build / RealTransport / Apply/Resim | 无C++、网络或引擎预测目标 | NotApplicable |
| 正式验收 | 用户核对后确认清理并执行必要复验 | NotRun |

执行进度和证据索引见 [逻辑验证结果](../evidence/2026-10-30-auto-mounts/result.md)。逻辑实施已验证，尚未宣告正式验收完成。新预览脚本不注册timer，不自动截图或执行Undo/Redo。

DP-01 Passed：目标与步骤2/3、验收逐项对应。DP-02 Passed：只保留映射接入与装备所需机制。DP-03 Passed：复用原挂点/握持根/绑定，无新识别器。DP-04 Passed：步骤2首先完成右手核心闭环。DP-05 Passed：步骤4至6保留失败、生命周期、测试、核对与清理。DP-06 Passed：六段结构、合同、责任和停止条件完整。

效率记录：组合读取输出截断后已定向补齐；后续小批输出。首轮前台脚本误写只读 active_panel_category，保留失败日志后移除；用户随后停止 Computer Use，并改为逻辑验证。两位探子仅独立审查发布失败边界与装备逻辑，发现发布后置校验缺口才追加针对性修复，不重复全仓探索。Spring 既有 runner 曾覆盖两个起始 clean 的证据 blend，本次只恢复这两个精确产物并保存恢复哈希；后续必要重跑先将该测试输出重定向到 tests/out。5.2.1 默认线程启动停滞，单线程探测成功后用 --threads 1 完成验证，根因仍未确认。安装准备曾在首个文件更新后发现另一文件漂移，导致一次身份校验失败；已改为先准备并校验全部文件再写入，保留安装副本既有差异后22项复验通过。

## 禁止事项

不执行 git add/checkout/reset/stash/clean/commit/push。不覆盖既有 dirty/untracked。不新增骨骼识别器、修改 rig/rest pose、自动猜握柄、逐帧追踪或重复握点。多个挂点不静默选取，失效不回落原点。不实现双手 IK、自动握拳、导出或衣甲蒙皮。不把夹具通过、安装或方案完成当成用户真实资产验收。
