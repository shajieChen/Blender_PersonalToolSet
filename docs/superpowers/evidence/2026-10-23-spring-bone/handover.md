# 动态骨骼交接

日期：2026-10-23。状态：已验证的半成品，不是最终完成。用户尚未核对裙摆验收静帧，临时诊断未清理，清理后复验未做。不要把本文件当成验收通过。

## 现在能用什么

独立插件在 `H:\Blender_Plugin\spring_bone`，与 `humanoid_retarget` 同级，两边不互相导入。版本 **1.0.1**，`bl_info` 最低 Blender 为 `(5, 2, 0)`。侧栏分类是「动态骨骼」，标题不显示版本号。配置写在骨架物体的 `sb_settings`，`schema_version` 仍是 1。

面向已经有骨骼和权重的裙摆、发束、饰物。可以生成预览、停止并恢复入口、烘焙一份新的 Action。预览名带 `_SpringPreview`，正式结果带 `_Spring`，并写 `sb_generated=1`。同一条结果动作还记下 `sb_frame_start`、`sb_frame_end` 和 `sb_penetration_m`。侧栏在结果下面显示残余穿深（米）。下一次生成会改掉侧栏上的数字，已经烘焙的动作仍保留自己的范围和穿深。带 `sb_generated` 标记的动作不能再当作下一次输入。

求解是插件自己的 VRM 风格尾点递推，`dt` 只出现一次。固定 60 Hz。世界空间米制，骨长冻结，父到子，保留基础 twist。不要改成 UE 刚度/阻尼或 Goal 软力，也不要复制 UE 源码。

验收只用 `H:\Blender\5.2.1\blender.exe`，5.2.1 LTS，hash `9e2066aef7ef`。工作区加载路径是 `H:\Blender_Plugin\spring_bone\__init__.py`。Blender 4.2 没跑过，不声明支持。本机另有 Blender 5.1.2，下面「现场预览」是用户要求看效果时做的，不是兼容性验收，也没有安装进 5.1 的插件目录。

## 已通过的证据

证据目录：`docs/superpowers/evidence/2026-10-23-spring-bone/`。

当前完整结果以这一次全套为准。`animation.log`（当时 7 项）、`lifecycle.log`（当时 22 项）、`lifecycle-ui.log`（当时 13 项）是更早的分文件运行，不能拿它们的选择数当作现在的总数。

| 命令 | 结果 | 日志 |
| --- | --- | --- |
| `run_spring_bone_tests.py -- test_spring_bone_solver.py` | 退出码 0，`SPRING_BONE_SELECTED 16`，`SPRING_BONE_TEST_OK` | `contract.log` |
| `run_spring_bone_tests.py -- test_spring_bone_*.py` | 退出码 0，`SPRING_BONE_SELECTED 51`，`SPRING_BONE_TEST_OK` | `spring-all.log` |
| `run_pose_channel_tests.py -- test_*repulsion.py` | 退出码 0，`POSE_CHANNEL_SELECTED 7`，`POSE_CHANNEL_TEST_OK` | `pose-channel.log` |
| `run_retarget_test.py` | 退出码 1，`RETARGET_TEST_FAIL` | `retarget.log` |

缺模块时的 RED 在 `contract-red.log`：15 项都是 `ModuleNotFoundError: spring_bone`，有选择数，没有成功标记。该文件是 UTF-16。其余日志是 UTF-8。

51 项覆盖手算尾点、球/胶囊、锥限、反平行、权重 0/1、父子参考、24/30/60 与 30000/1001 的同一物理 tick、Euler 连续、原 Action 切回、故障取消、保存重开，以及和 `humanoid_retarget` 一起注册再注销。禁用插件再启用后，链名称、骨骼名和显示空物体都还在。参数超出范围、重力方向无效、镜像缩放和负的帧跨度会给出中文错误。添加链会拒绝空选择、断链、分支和重复占用。多条链如果子链写在父链前面，求解前会改成祖先链先算。动态骨不能当成碰撞骨。指向动态骨的 IK 极向目标、骨架约束目标、会走到动态骨的 IK/样条 IK，以及数据路径里引用动态骨的驱动，都会拒绝。链长只含那根非模拟骨时仍然允许。

更新代理体显示时，空物体挂在骨骼尾端，所以会先把米制偏移换算到骨头局部坐标，再减去骨长。场景单位不是 1 时也按这个换算。形状从胶囊改回球时，末端空物体会去掉。生成进行中，编辑事件被模态吃掉；中键等视图事件仍然放过。Esc 和右键取消。面板上的链、代理体、更新显示、生成预览和烘焙会锁住。停止预览仍可点。窗口里已有别的模态操作时，预览和烘焙会提示「请先结束其他操作」。骨架 rest 被改、换场景、帧率或单位变化，会以「输入已变化」停掉。骨架被删掉会提示「目标已失效」，取消可以再调一次。原地改关键帧的内容检测不到。每个采样点会先把姿势恢复到入口 basis，再 `frame_set`。链上或祖先姿势缩放如果三轴相差超过 1e-5，生成前会拒绝并提示「缩放不是统一缩放」。磁盘上的骨长门槛仍是 `max(1e-6 米, 骨长×1e-5)`，没有放宽。

裙摆性能样本在 `runtime.log`：24 骨、5 个代理体、帧 1–301 @ 30 fps。当前这次总生成 **2.035 秒**，没有 `SPRING_BONE_DEMO_CONCERN`。分阶段是准备 0.001、采样 0.693、求解 0.766、写入 0.562、提交 0.003 秒。95% 切片 0.017 秒。最长一块 0.086 秒。切片数 119。尾点最大穿深 0.002084090591978033 米。分段穿深是行走 0.000003、转身 0.000481、深蹲 0.000434、抬腿 0，骨长误差都是 0。四帧坐标：行走 40 骨盆 (0, 0.32, 0.9)、大腿 (0.09, 0.53, 0.5572)、裙摆 (0.2741, 0.3092, 0.3477)；转身 110 (0, 0.6, 0.9)、(0.3895, 0.6993, 0.99)、(0.557, 0.6, 0.9927)；深蹲 190 (0, 0.6, 0.64)、(-0.09, 0.9815, 0.7669)、(-0.3979, 0.6, 1.1463)；抬腿 250 (0, 0.6, 0.9)、(-0.09, 1.0018, 0.8884)、(-0.3986, 0.6, 1.4059)。动作是 `SkirtArmAction` 和 `SkirtArmAction_Spring`。这份日志是在入口 basis 恢复、直接写曲线和统一缩放预检之后重跑的，四张静帧一起重渲了。早先 8.329 秒和 12.9 秒的样本包着 `tracemalloc`，不作为当前预算。

## 验收裙摆怎么看

场景 `skirt_demo.blend`。静帧由 `tests/run_spring_bone_demo.py` 在 2.035 秒那次烘焙之后重渲。

| 文件 | 帧 | 看到的情况 |
| --- | --- | --- |
| `skirt_walk.png` | 40 | 裙摆下垂成锥，左右摆幅不完全对称，左侧有一条灰腿穿过粉条 |
| `skirt_turn.png` | 110 | 条带甩向一侧，腿条横穿裙带 |
| `skirt_squat.png` | 190 | 骨盆下降，双腿前折，裙带被顶开并上翻 |
| `skirt_raise.png` | 250 | 一条腿向上穿过裙摆 |

尾点到代理体的采样穿深：行走 3e-6 米，转身 4.81e-4 米，深蹲 4.34e-4 米，抬腿采样为 0。全程最大 2.084e-3 米。网格条带上的穿模比尾点距离更明显，不承诺无穿模。重新打开 `skirt_demo.blend` 后，`SkirtArmAction` 和 `SkirtArmAction_Spring` 都在。结果动作上是 `sb_generated=1`、`sb_frame_start=1`、`sb_frame_end=301`、`sb_penetration_m=0.002084090591978033`。`SkirtArm.sb_settings.source_action` 是 `SkirtArmAction`。插件不加 fake user；演示脚本给基础动作加了 fake user，所以保存后基础动作还在。

5.2.1 窗口里的进度和 Esc 记在 `skirt-ui.log`。进度到过采样约 47%。窗口获得焦点后送入 Esc，消息是「预览已取消」，动作回到 `SkirtArmAction`。同一次里马上再开始时，`ed.undo.poll()` 为假。更早一轮预览形成撤销步之后，一次 Undo 能执行，骨架和 8 条链还在。打开该 blend 时不会自动开始模拟。

## 用户角色上的现场预览

这不是验收。用户在已经打开的 Blender 5.1.2 里要求看裙摆效果。进程是 `C:\Program Files\Blender Foundation\Blender 5.1\blender.exe`。插件从工作区 `register()` 进了这个进程，没有复制到 5.1 的插件目录，重启后面板会消失。结果动作是普通 Action，保存文件后仍可播放。本次没有代用户保存文件。

可见的身体、衣服和头发挂在物体「骨架」上（146 骨，位置约 x=0.771）。侧栏当时选中的是另一具 `Armature`（479 骨，位置约 x=-2.065，网格 `model`）。那具骨架上没有动态骨，所以「动态骨骼」面板是空的。衣服的骨架修改器指向「骨架」。

「骨架」上有 8 条链，每条 4 节：`Q_QunZi.L`、`H_QunZi.L`、`QunZi.L`、`Q_QunZi.R`、`H_QunZi.R`、`QunZi.R`、`Z_QunZi`、`Z_HouQunZi`，以及 `.001` 到 `.003`。胶囊代理体：`upper_leg.L` / `upper_leg.R` 半径 0.03 米，`lower_leg.L` / `lower_leg.R` 半径 0.022 米。现场参数：刚度 6，拖曳 0.45，重力 2.2，方向 (0, 0, -1)，碰撞半径 0.012 米，混合 1，锥角 70°，预热 0.25 秒。

该骨架 `use_nla` 为假，但有 9 条带片段的 NLA 轨道。磁盘上的操作器会因此拒绝并提示「请关闭NLA」。现场烘焙先收起这 9 条轨道，烘焙完再按名称、动作、起止、缩放、重复、混合、影响和静音建回去，并把 `use_nla` 留在假。第二次烘焙尝试写回片段的 `action_slot`，输出里没有 `SLOT_SKIP`。播放用的是活动动作，不是 NLA。

髋的姿势缩放不是严格统一，裙骨世界长度会抖大约 0.002 毫米，超过磁盘上的 1e-6 米门槛。5.1 进程里把这次采样的骨长容差放宽到 `max(1e-4, 骨长×1e-4)`，只存在于当时执行出来的函数，不在磁盘文件里，重启即消失。磁盘上的预检会在生成前拒绝，并提示「缩放不是统一缩放」。所以在这具角色上点侧栏「生成预览」，加载的是磁盘代码时仍会失败。

两次结果都在第 0 到 52 帧。原动作都还在。

| 结果动作 | 基础动作 | 尾点最大穿深 | 裙摆末端相对基础动作的位移 |
| --- | --- | --- | --- |
| `骨架_a050_302011.002_Spring` | `骨架_a050_302011.002` | 0.007782 米 | 第 8/20/36/48 帧约 0.07–0.10、0.08、0.03、0.05 米 |
| `骨架_a050_302010.002_Spring` | `骨架_a050_302010.002` | 0.012717 米 | 第 8/20/36/48 帧最大 0.0868、0.0868、0.0285、0.0547 米 |

离开现场时，活动动作是 `骨架_a050_302010.002_Spring`，帧在 20。「骨架」物体已重新隐藏，避免骨骼线盖住脸。网格仍由它驱动。要看链列表，活动物体必须是「骨架」，不能是 `Armature`。

## 还没关的门

| 门 | 状态 |
| --- | --- |
| Static、Contract、精度、时钟、动画、生命周期 | 已通过。静态复核见 `static-review.md`。当前全套是 `spring-all.log` 的 51 项 |
| Process | Retarget 退出码 1，未通过 |
| 安装 BAT | 未改，也未运行 |
| 性能 | 2.035 秒，在 10 秒内；95% 切片 0.017 秒；最长一块 0.086 秒 |
| 兼容 4.2 | 未运行 |
| 5.1.2 现场预览 | 用户要求下看过裙摆，不是最低版本声明 |
| 正式验收 | 未完成：待核对静帧、清理、清理后复验 |

Retarget 失败点是 `tests/run_retarget_test.py:1775`，`test_metarig_root_reference_and_ik`：`the final hop removes horizontal root travel`。该测试不导入 `spring_bone`。`humanoid_retarget`、`tests/run_retarget_test.py` 和 `安装插件.bat` 相对 HEAD 没有改动。第二次 hop 的 `root_motion` 是 `IN_PLACE`，前面的断言已经通过。最终 hop 开了脚 IK，髋位置走 `foot_ik.py` 的 `retarget_pelvis_position`：`in_place` 时把骨盆 x/y 钉在参考点（约 266–268 行）。钉住之后同一帧还会调用 `apply_contact_ik`（`retarget.py` 约 1761 行）。实测 `RootTarget` 的 `Tgt_hips`：第 1 帧世界头 (0, -0.003594, 1.659593)，第 10 帧 (0, 0, 1.457391)。差值 x 为 0，y 为 0.003594 米，超过 1 毫米门槛；z 是竖直方向，不在这条断言里。四条命令都退出 0 之后才改 `安装插件.bat`。现在 BAT 仍只安装 `humanoid_retarget` 和 `shortcut_hint`。不要为了这条断言去改 Retarget，除非单独授权。

默认 `use_nla=True` 且没有片段时允许通过；有 NLA 片段会拒绝。暂停预览期间不要重定向同一骨架，这是使用约定，没有跨插件锁。

## 接手时不要做的事

- 不要提交、推送、暂存、回退或清理无关的 dirty / untracked。
- 不要运行 `安装插件.bat`，不要覆盖已安装目录。已安装的 `humanoid_retarget` 缺少 `foot_ik`，不要把文件抄进去补。
- 不要改 `humanoid_retarget` 源码来压掉回归。
- 不要把磁盘上的骨长门槛改成 1e-4。现场放宽只为了让这具角色能看效果。
- 不要删 `cleanup.md` 里列出的探针、摘录和 `.blend1`，除非用户确认可以清理。正式测试、`skirt_demo.blend`、四张静帧和验收日志留下。
- 不要把用户正在用的 5.1.2 进程关掉，也不要往里面打开 `skirt_demo.blend`。
- 清理之后要重跑聚焦测试和受影响的回归，再写完成结论。

## 代码从哪读

| 文件 | 职责 |
| --- | --- |
| `spring_bone/solver.py` | 纯 mathutils。无 bpy，无 Retarget |
| `spring_bone/animation.py` | 采样、60 Hz 求解、Action 副本、取消、提交、统一缩放预检 |
| `spring_bone/operators.py` | 一次会话、预览/停止/烘焙、Esc 与 TIMER、代理体空物体 |
| `spring_bone/properties.py` | `sb_settings` |
| `spring_bone/panels.py` | 侧栏 |
| `spring_bone/__init__.py` | 注册、`load_pre` / `undo_pre` 停会话 |
| `tests/run_spring_bone_tests.py` | 测试入口 |
| `tests/run_spring_bone_demo.py` | 裙摆场景、计时和静帧 |

设计、实施和公式依据：

- `docs/superpowers/specs/2026-10-23-spring-bone-design.md`
- `docs/superpowers/plans/2026-10-23-spring-bone-implementation.md`
- `docs/superpowers/plans/2026-10-23-spring-bone-formula-evidence.md`

Git 仓库 `H:/Blender_Plugin`，remote `https://github.com/shajieChen/Blender_PersonalToolSet.git`，HEAD `0ef80daea8ef0b657b63b1c6a6fa51856dbdd840`，分支 `main`。本轮没有新的提交。
