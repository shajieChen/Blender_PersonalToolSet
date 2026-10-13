# Rigify human metarig 中间标准设计

```text
站位
  |
标准人形骨架: Rigify human metarig / 当前直接映射
  |
1. 动画来源 -> 2. 目标角色

直接模式: 来源 --------------------------> 目标
标准模式: 来源 -> human metarig 中间骨架 -> 目标
                 现有 swing 求解器逐跳转换
```

## 目标

增加一个中间标准选择。推荐使用完整 Human 的样本骨架定义，保留当前直接映射。

选择器选择中间标准，不选择动画来源，也不替换目标角色。此次只交付设计和计划；没有实现新模式，没有修改任何 `.py`。

### 事实与证据边界

- 当前插件为 `humanoid_retarget`，版本 `(1, 6, 6)`。
- 用户已核实 Blender `5.1.2` 的安装文件：`C:\Program Files\Blender Foundation\Blender 5.1\5.1\scripts\addons_core\rigify\metarigs\human.py`。
- `human.py` 由 `rigify.utils.write_metarig` 生成；`create(obj)` 创建 edit bones，并保存名称、head、tail、roll 和 parent。
- `metarigs\Basic\basic_human.py` 是另一个样本。此模式使用 `metarigs\human.py`，不能悄悄改用 Basic Human。
- Codex 当次没有重新打开手册。随后核对了 Blender 5.1 手册，结论与安装的 `human.py` 一致：Add 菜单里的 Human 是预置 meta-rig，Basic Human 不含脸和手指；Generate Rig 生成另一套 rig，变形骨在 DEF bone collection。骨链由 Connected 连接，链的第一根骨带 Rigify type，生成时才创建 controls 和 deform bones。手册：<https://docs.blender.org/manual/en/5.1/addons/rigging/rigify/basics.html>，<https://docs.blender.org/manual/en/5.1/addons/rigging/rigify/metarigs.html>。
- 当前插件入口已定位：`__init__.py` 的 `HRSettings`、`HR_PT_panel.draw`、`_options_from_settings`；`pipeline.py` 的三个重定向入口；`retarget.py` 的 `RetargetOptions` 与 `bake_retarget`。

### 已有失败不能改写

`REST` swing 传递相邻映射关节之间的肢体方向，不复制来源绝对骨轴。`hand_l`、`hand_r` 没有映射链子节点，因此其 FK 烘焙局部四元数保持 `(1, 0, 0, 0)`。hips 使用 hips-to-spine 方向，因此绕身体 up 的 yaw 被丢弃。

用户给定实测：`c0000_突刺_wp_a_0300.glb` 到 `body.FBX`，第 37 帧来源 pelvis yaw 约 `-42.7°`，烘焙目标约 `-0.7°`。wrist-delta 候选改善右手，却翻转左掌。以下两份修订均为 `DO_NOT_PATCH`，本设计不解除该结论：

- `docs/superpowers/specs/2026-10-13-retarget-hand-pretzel-revision.md`
- `docs/superpowers/specs/2026-10-13-retarget-pelvis-rotation-revision.md`

选中 metarig 不代表修复上述两项实测。骨名预设也不代表共享 rest 或局部轴。

## 修改范围

### UI 与设置

在 `HR_PT_panel.draw` 中，紧接 `layout.prop(settings, "stand_layout", text="站位")`，位于 `source_box = layout.box()` 和 `1. 动画来源` 之前，加入选择器。

设置字段为 `HRSettings.standard_skeleton: EnumProperty`，标签为 `标准人形骨架`。

| 枚举值 | 显示名称 | 含义 |
| --- | --- | --- |
| `RIGIFY_HUMAN_METARIG` | `Rigify human metarig` | 第一项；选择完整 Human 的样本骨架作为中间标准 |
| `DIRECT` | `当前直接映射` | 不创建中间骨架；保持现有来源到目标路径 |

默认值为 `DIRECT`，避免旧场景在加载后自动改变烘焙行为。第一项的显示顺序与默认值分别控制。仅切换枚举不立即创建骨架或烘焙，不修改站位和 same-clip 显示。

### 标准定义携带什么

携带身体链的实际骨名、原始 parent、head、tail、roll；它是 rest 几何与轴定义，不只是骨名对应表。另设语义 role 到 metarig 骨名的显式映射，不把映射结果当成原始定义。

首版范围为躯干、头颈、肩、双臂和双腿，保留这些骨骼所需的身体祖先。face、breast、ear 不要求；手指不进入首版求解链。不得为了过滤骨骼随意重设 parent、改 roll 或移动 head/tail；必要身体祖先缺失应拒绝该定义。

以下是用户已核实的样本值；不是本轮重新提取的数据：

| 骨名 | head | tail | roll | 已给定 parent |
| --- | --- | --- | --- | --- |
| `spine` | `(0, 0.0552, 1.0099)` | `(0, 0.0172, 1.1573)` | `0` | 未在输入中给定 |
| `thigh.L` | `(0.0980, 0.0124, 1.0720)` | `(0.0980, -0.0286, 0.5372)` | `0` | `spine` |
| `upper_arm.L` | 未在输入中给定 | 未在输入中给定 | `2.0724` | 未在输入中给定 |
| `forearm.L` | 未在输入中给定 | 未在输入中给定 | `2.1535` | 未在输入中给定 |
| `hand.L` | 未在输入中给定 | 未在输入中给定 | `2.2103` | 未在输入中给定 |

不得凭此表补造缺少的字段。后续实现应从安装的完整 Human 样本加载真实数据，并校验身体链。

### Metarig 与生成 rig 不同

```text
human.py -> 样本 metarig -> Generate Rig -> ORG / DEF / MCH / 控制骨
               ^
          本模式的中间标准
```

metarig 的 pose 设置包含：`spine` 为 `spines.basic_spine`、`QUATERNION`；`pelvis.L/R` 为 `basic.super_copy`、`YXZ`；`thigh.L/R` 为 `limbs.leg`；`spine.004` 为 `spines.super_head`；`upper_arm.L/R` 为 `limbs.arm`；`face` 为 `faces.super_face`。

`shin`、`foot`、`toe`、`forearm`、`hand` 的 `rigify_type` 为空，但它们属于 typed bones 的子链，不是无效骨骼。首版不需要调用 Rigify 生成器，也不需要 face 类型。运行时四元数烘焙设置与样本原始 rotation_mode 分开处理，不宣称所有样本骨骼原本都是 `QUATERNION`。

生成控制 rig 是另一个对象及另一套骨骼职责。此模式不匹配其控制骨，不把 ORG、DEF、MCH 骨名当作 metarig 标准。

## 实施步骤

### 1. 加载 metarig 定义

在新增 `humanoid_retarget/rigify_metarig.py` 的 `load_human_metarig_definition()` 中加载安装的 `rigify.metarigs.human`，调用其 `create(obj)` 创建任务自有临时样本。

从该样本读取身体骨骼的原始字段，保存为值数据。确认版本、左右链、父关系和非零骨长。加载失败必须给出错误，不自动退回直接映射，也不改用 `Basic.basic_human`。实际导入可用性属于后续实现的 Contract 验证，本轮未运行该 API。

使用两个生命周期分离的临时对象：定义提取样本在提取后清理；中间动画骨架在两跳转换结束后清理。它们都由当前重定向调用拥有，不绑定到目标网格，不写入来源或目标 rest。

### 2. 将来源校准到标准

建立 `source -> metarig` 的 role/bone 对应与身体坐标、高度比例、参考姿势数据。校准只计算转换数据和中间对象的姿势，不调整来源 rest，不复制来源绝对朝向。

hips、脊柱、肩臂、腿脚用显式语义角色；不要仅凭 `spine` 字符串猜 hips。完整 Human 的各段脊柱和必要祖先仍保留原始结构。左右角色分别验证，不借 wrist-delta 镜像修正。

### 3. 将目标校准到标准

建立 `target -> metarig` 的对应，得到同一标准到目标的反向查表与第二跳参考数据。来源与目标都对同一份 rest 定义校准，但各自 bind/rest 仍保持不同。

用户现有来源到目标映射可作为共同语义 role 的输入，不被中间骨名覆盖。`CURRENT` 参考必须在烘焙前、同一参考帧分别捕获两跳数据；不能把原 source-target 的 reference_data 原样用于两跳。

### 4. 经过中间骨架转换动画

由 `pipeline.py` 选择路径；标准模式调用现有 `bake_retarget` 两次：来源到 metarig，再从 metarig 到目标。中间骨架是真实 armature，承载第一跳 Action，不是只更换名称的预设。

每跳仍用现有 swing solver。`REST`、关闭最终 IK 的 FK 路径中，每跳的手末端 identity 与 pelvis yaw 丢失都保持现有行为。两跳不会补回第一跳丢掉的旋转；也不要求最终误差数值恰好等于直接模式。

保持原帧范围、采样时刻和来源 Action 对应。每个中间 Action 与最终 Action 都关联同一个原始来源 clip，最终显示仍是来源和目标的 same-clip，不显示临时中间 clip。

第一跳不执行 hand/foot IK，第二跳按原设置执行一次。root 位移使用两跳高度比例，避免重复应用最终比例；`IN_PLACE` 策略只在最终跳应用。`resolved_pairs` 回传最终来源到目标语义映射，不把临时骨名写回用户映射。

## 强制约束

### 依赖、所有权与失败行为

```text
__init__.py 设置/UI -> pipeline.py 路径选择 -> retarget.py 现有求解器
                                 |
                                 +-> rigify_metarig.py -> 安装的 human 样本
```

- 求解器不反向依赖 UI 或 Rigify；无依赖环，无通用注册器或全局单例。
- 仅标准模式加载 Rigify。直接模式不受 Rigify 是否安装影响。
- 所有 `bpy` 创建、模式切换、pose 计算、Action 操作和销毁均在 Blender 主线程。
- 创建/销毁、临时链接/解除链接、Action 创建/释放必须对称。仅移除本次调用拥有的数据，不按前缀批量清理。
- 在写目标前完成定义与映射校验。失败恢复目标原 Action/slot、姿势及活动对象、模式、帧和选择状态；只丢弃本次创建且未交付的 Action。成功保留正式目标输出和原 same-clip 行为。
- 只为任务自有临时骨架进入 Edit Mode。严禁在目标 Edit Mode 改 rest；现有自动绑定流程不因该模式扩展。
- 跨版本 Rigify 导入、身体骨集合及 `CURRENT` 两跳参考属于后续必须验证的 Concern，不以本轮文档作为 Runtime 通过证据。

### 后续可以改变什么

经另行授权可以增加设置枚举、UI 行、标准加载模块、两跳编排、校准值数据及对应测试。可按真实需求加入更多身体链角色，但先保证 solver 仍按现有链定义工作。

手末端旋转或 pelvis twist 的新求解方式必须作为独立问题设计、RED/GREEN 和真实动作验证；不能借此次模式接入夹带已否决补丁。

### 方案取舍与未来变化

推荐真实中间 armature 加两跳 swing：概念少，重用现有求解器，能验证原始 rest 定义。代价是一次额外烘焙、临时数据和两次投影的信息损失，不承诺质量改善。

不选仅骨名预设：没有共享 rest/head/tail/roll，也没有中间动画。不同骨轴不能靠名字解决。

不选生成控制 rig：引入生成器、控制约束及另一套骨名，超出样本骨架标准需求。不选绝对朝向复制：违反既有跨 bind 约束。

| 三种可能变化 | 局部扩展位置 | 核心与 API 边界 |
| --- | --- | --- |
| 新增另一个真实标准 | 新标准定义加载文件和选择分支 | 未有第二实现前不建抽象接口或注册器 |
| 增加手指能力 | 标准身体角色表和独立求解设计 | 不把手指加入链来暗改当前 hand identity |
| 替换 Rigify 数据来源 | `load_human_metarig_definition()` | 保持值字段与 pipeline 调用；显式标明定义版本，不能静默换标准 |

## 验收标准

- UI 位于 stand_layout 后、步骤 1 前；第一项为 `Rigify human metarig`，仍保留 `DIRECT`。
- 标准身体骨数据可追溯到安装 Human 样本；parent/head/tail/roll 完整，未取生成控制 rig。
- 定义加载、来源校准、目标校准、真实中间动画与第二跳均有测试，不能仅以枚举存在验收。
- 两跳逐跳验证 `REST` 手末端 identity 和 pelvis yaw 不保留的限制；关闭 IK，勿把限制测试包装成旋转修复。
- 直接模式、same-clip、参考姿势、root motion、IK 和失败清理保持现有合同。
- 新增测试先有可归因 `selected > 0` RED，再最小 GREEN；完整回归输出 `RETARGET_TEST_OK` 且进程退出码为 0。
- 后续实现清理临时诊断后再跑聚焦与完整回归；未清理、未复验不得宣布实施完成。

本轮仅文档 Static 交付。Generate、Build、Process、Runtime、Visual 和正式功能验收均为 NotRun。

## 禁止事项

不改任何 `.py`。不重读安装 Rigify 源码。不恢复 stash，不暂存、不提交、不推送，不派子代理。不实现 wrist-delta 或 pelvis yaw 补丁。不复制绝对来源骨轴。不改目标 rest。不把 `bpy` 放到 worker thread。不移除 same-clip 显示。不声称选中 metarig 已修复第 37 帧或左掌问题。