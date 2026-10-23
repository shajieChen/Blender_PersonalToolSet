# Blender 人形挂点与武器挂载参考调研

```text
人形角色骨骼 -> 挂点 Empty -> 武器握持根 -> 刚性道具
                 |
          局部偏移 + 可读名称
                 |
          后续参考 UE Socket 导出
```

调研日期：2026-10-23。状态：参考调研、界面与武器设置复核、仅人形范围专项两轮复核完成；插件实施与运行验收未开始。

## 结论与适用范围

有可借鉴方案。优先参考 **Blender For Unreal Engine 的挂点制作与导出**、**Dynamic Parent 的动画绑定切换**，以及本地 **UE5.7.4 的 Socket 数据与编辑流程**。

当前范围仅为人形角色。建议用 Blender 原生 Empty、骨骼父子关系实现人形挂点；需要动画切换时再使用约束。跟随计算交给 Blender，不另写逐帧追踪器。UE 作为行为参考，不作为 Blender 插件的运行依赖。

这里的“挂点”指人形骨骼上的具名附件位置，例如手持武器、背部装备、腰包和头饰。武器自身的枪口等挂点只保留为后续参考。以下三件事应分开：

| 职责 | 含义 | 例子 |
|---|---|---|
| 挂点定义 | 所属人形骨架、实际骨骼、名称、局部变换 | `WeaponGrip` 相对右手骨骼的位置 |
| 附件绑定 | 哪个物体跟随挂点、使用什么偏移 | 剑吸附到 `WeaponGrip` |
| 动画切换 | 何时绑定、解除、换手，是否保持世界姿势 | 右手把剑交给左手 |

布料、软体、弹簧骨、蒙皮和节点编辑器的输入输出 Socket 不属于本次挂点范围。

界面采用“人形角色 → 部位 → 挂点 → 武器/道具”的顺序。下面的界面草图与人形流程属于建议方案，尚未实现。

### 现阶段人形范围

| 范围 | 当前判定 |
|---|---|
| 挂点归属 | 只挂在人形角色的实际骨骼上；右手、左手、背部、腰部、头部可分别映射 |
| 附件 | 刚性武器、盾牌、背包、腰包、头饰；武器 Mesh 或 Empty 根可作为附件对象 |
| 基本操作 | 创建/复制/重命名/删除挂点，编辑偏移，吸附或保持位置绑定，解除，动画跟随预览与保存重开 |
| 资产复用 | 每把武器保存握持根和部件；换武器时复用角色挂点 |
| 后续人形能力 | 动画换手、双手 IK、自动手指握持、衣甲蒙皮、武器自身动画、镜像与引擎导出，均不作为当前首批完成条件 |
| 不纳入当前工具 | 非人形骨架、任意物体的通用挂点、静态网格 Socket 编辑；不为这些能力预建扩展框架 |

限制的是挂点的角色归属，并非要求武器也有骨架。下文静态网格和通用对象资料只保留作对照，不构成当前功能需求。

### 仅人形专项两轮复核

| 轮次 | 实际检索与核对 | 结论 |
|---|---|---|
| 第一轮 | `Bone Parent Relative Parenting`；`Rigify Deform Controls generated rig`；`Skeletal Mesh Sockets Bone Name` | 用人形实际骨骼承载挂点；需要区分 Rigify 的 metarig、控制骨与实际输出骨；固定骨骼名不能作为通用契约 |
| 第二轮 | `humanoid character weapon attachment hand bone socket two bone IK`；`rigify metarig generated rig deform bones`；`Child Of changing parents animated inverse` | 当前收敛为刚性附件跟随；手握姿势、双手贴合和换手属于另一个动画职责；不扩展为通用 Socket 系统 |

已读取 [Blender 5.2 Rigify 生成说明](https://docs.blender.org/manual/en/5.2/addons/rigify/basics.html)、[metarig 机制](https://docs.blender.org/manual/en/5.2/addons/rigify/metarigs.html)，并复核 [UE5.7 骨骼挂点](https://dev.epicgames.com/documentation/en-us/unreal-engine/skeletal-mesh-sockets-in-unreal-engine?application_version=5.7) 与 [Two Bone IK](https://dev.epicgames.com/documentation/en-us/unreal-engine/animation-blueprint-two-bone-ik-in-unreal-engine?application_version=5.7)。这些资料支持职责区分，不证明本机已兼容任意人形 Rig。

当前工程 `classify_armature` 会合并名称与几何识别结果，校验骨名存在并去重；它不是已验证的人形资产准入判定器。角色由用户明确选择，映射结果用于辅助，最终按当前模型校准。Mixamo、UE 和 Rigify 命名均为识别参考，运行兼容性保持 `NotRun`。

## Blender 武器挂载设置流程

### 推荐的场景关系

先给角色准备稳定挂点，再给每把武器准备握持根对象。后续更换武器时只换武器根对象，不反复修改角色手骨或模型原点。

```text
HeroRig
  + 右手骨骼 -> Mount_Hand_R
  |                + GripRoot_Sword
  |                     + SwordMesh
  |                     + SwordDecoration
  + 左手骨骼 -> Mount_Hand_L
  + 胸部骨骼 -> Mount_Back
  + 骨盆骨骼 -> Mount_Waist
  + 头部骨骼 -> Mount_Head
```

箭头包含骨骼父级关系。`Mount_*` 是角色上的 Empty；`GripRoot_Sword` 是位于剑柄握持处的 Empty，统一带动武器部件。Collection 负责组织，不代替父子关系。

这属于基于原生能力的推荐流程，不是 Blender 内置的 Socket 数据类型。Empty 可作为父对象、约束目标和变换控制点，本身不会渲染。[Blender 5.2 Empty 手册](https://docs.blender.org/manual/en/5.2/modeling/empties.html)

### 第一步 给角色设置挂点

1. 保存工作副本，选定便于校准的静止帧，关闭 Auto Keying。保持现有骨架、Action、单位和 rest pose，不为挂载执行 Apply Pose 或批量 Apply Transform。
2. 在 Object Mode 添加 Empty，命名为 `Mount_Hand_R`。显示类型用 Arrows 或 Plain Axes；调 Display Size 改变标记显示大小，不用 Scale 改标记大小。
3. 先选择 Empty，再 Shift 选择角色骨架。进入 Pose Mode，选择实际右手骨骼。骨骼名以当前模型为准，`hand_r` 只是示例。
4. 按 `Ctrl+P` 设置骨骼父级。已有角色先检查该骨骼的 Relative Parenting，选择与原设置一致的 Bone 或 Bone Relative；不要为了新增挂点切换所有子物体的行为。
5. 回到 Object Mode，只移动和旋转挂点 Empty，让它位于掌心握持位置。统一其局部轴约定，并在其他动画帧确认跟随的是手掌最终姿势。
6. 同法准备左手、背部、腰部和头部挂点。没有对应骨骼时由用户指定；不要从名称猜测并静默绑定。

这是官方骨骼父级操作的应用。`Bone Relative` 主要区分修改骨骼 Edit Mode 后对子物体的处理，不等于“自动保持世界位置”或“自动对齐掌心”。该开关属于骨骼，影响其全部子物体。[Blender 5.2 父子关系手册](https://docs.blender.org/manual/en/5.2/scene_layout/object/editing/parent.html#bone-parent)

挂点的数值位置为零，不一定对应想要的掌心位置。不要仅靠清空变换推断挂点已对齐。带复杂控制 Rig 的角色，先确认用于跟随的输出骨骼，保持既有 IK 控制结构。

### 第二步 给武器设置握持根对象

1. 先用无动画的刚性武器校准。导入后检查实际尺寸、方向和已有父级；已绑定骨架的武器不按这套刚性流程批量重设父级。
2. 在剑柄应落入掌心的位置添加 Empty，命名为 `GripRoot_Sword`。它的方向应与角色挂点约定一致。例如可约定本地 +Y 沿剑身指向剑尖、+Z 朝指定正面；这是项目约定，不是 Blender 或 UE 的通用武器方向。
3. 选择武器所有刚性部件，最后选择握持根 Empty，使它为 active object。`Ctrl+P` 选择 Object，并启用 Keep Transform，让模型保持外观位置。
4. 此时移动握持根，确认整把武器一起移动。根对象保持单位缩放、无动画、无驱动和额外跟随约束；用 Empty 的显示大小调标记尺寸。

该方式把握持位置保存为父子关系，不需要改变原 Mesh 的原点或顶点。它是上文握持矩阵方案的手动实现：模型相对握持根的关系承担握点补偿，不再额外叠一次 `Grip_Main` 的逆变换。若已有 `Grip_Main`，用它定位握持根即可，不必再建同职责标记。

### 第三步 挂到手上或保持当前位置

以下“吸附”只针对上一步新建、无动画、Delta 变换为默认值的握持根；不要对用户已有的动画根对象直接清空通道。

| 目标 | 操作 | 预期 |
|---|---|---|
| 吸附到右手挂点 | 先选 `GripRoot_Sword`，最后选 `Mount_Hand_R`；执行 Object > Parent > Make Parent without Inverse，并关闭 Keep Transform；再把握持根局部位置、旋转设为 0，缩放设为 1 | 握持根与挂点对齐；模型保留相对握持根的剑柄校准 |
| 当前位置正确，只建立跟随 | 先将武器摆好，再选握持根和挂点，使用 Object 父级并启用 Keep Transform | 建立关系时保留当前世界姿势，保留额外偏移 |
| 解除但留在当前位置 | 只选择握持根，`Alt+P` 使用 Clear and Keep Transformation | 解除父级后保持当前世界姿势；含剪切时不能保证完全等价 |

无逆矩阵父级操作只保证重设父逆矩阵与局部位置，不会自动把原有旋转和缩放归零。因此吸附流程必须明确处理这两个通道；单独 `Alt+G` 或把位置写成零，不足以消除隐藏父逆矩阵。[父级与解除说明](https://docs.blender.org/manual/en/5.2/scene_layout/object/editing/parent.html#make-parent-without-inverse)

如果剑尖方向不对，先检查挂点与握持根轴向。角色通用握持方向不对时改角色挂点；只有这把武器需要修正时改武器校准或其局部偏移。不要给角色骨骼强加补偿旋转，也不要用负缩放制作另一只手的版本。

### 约束方式何时使用

| 方式 | 合适场景 | 设置边界 |
|---|---|---|
| 原生父级 | 长期固定手持、背部收纳 | 首选；关系直接，依赖最少 |
| Copy Transforms | 需要根对象完全匹配挂点，又不采用普通父级 | 目标设为挂点，双方空间用 World，Mix 用 Replace，Influence 为 1；会覆盖该根对象原有变换，不提供 Keep World 式逆矩阵补偿 |
| Child Of | 已摆好道具并保持偏移，或后续做拿起、放下、换手 | 目标设为挂点；初次校准时根据启用前后结果使用 Set Inverse；动画分段按上文换手方案处理 |

同一根对象选择一条明确的跟随路径，避免父级与另一套约束同时承担相同职责。Copy Transforms 的替换与空间、Child Of 的逆矩阵与 Influence 已读取 [5.2 Copy Transforms 正文](https://docs.blender.org/manual/en/5.2/animation/constraints/transform/copy_transforms.html) 和 [5.2 Child Of 正文](https://docs.blender.org/manual/en/5.2/animation/constraints/relationship/child_of.html)。上述组合设置仍需本机验证。

### 保存成后续可复用资产

- 角色文件保存已校准的 `Mount_Hand_R`、`Mount_Hand_L`、`Mount_Back` 等挂点。
- 每把武器另存 `.blend`，用一个 Collection 包含握持根和全部部件。武器库中的根对象不引用某个角色的挂点、骨架或约束目标，避免引入旧角色依赖。
- 后续通过 File > Append 选择武器 Collection；关闭 Instance Collections，得到可直接选择的本地对象，再把握持根绑定到目标角色挂点。不要只 Append 一个 Empty 并假定所有子部件都会随之带入。
- 已有同名 linked 数据时，Append 的结果可能仍保留链接；检查可编辑性。首批优先独立本地副本，跨文件同步的 Link 与 Library Override 留待实际需要。

Append 会复制数据，Link 保持外部引用且初始存在编辑限制；这也是武器试装优先使用本地副本的原因。[Blender 5.2 Link 与 Append](https://docs.blender.org/manual/en/5.2/files/linked_libraries/link_append.html)

Blender 内的挂点名称不必全加 `SOCKET_`。需要导出时再按选定管线转换。骨骼挂点仍应遵守 BFU 的专门导出流程，不能把本地父子关系当作 UE 自动建 Socket 的证明。

### 常见问题与最小自查

| 现象 | 优先检查 |
|---|---|
| 绑定后跳位 | 用错保持姿势/吸附流程、父逆矩阵、根对象原有 Delta 或动画 |
| 位置正确但方向错误 | 角色挂点和武器握持根的轴向是否采用同一约定 |
| 挂载后尺寸变化或出现剪切 | 单位、父链缩放、骨骼缩放；不能靠给已有骨架 Apply Scale 一次性修复 |
| 编辑挂点时只有标记变大 | Display Size 只改变 Empty 显示；实际武器大小在武器资产上校准 |
| 武器不随手或跟随错误部位 | 是否真是骨骼父级、实际骨骼是否正确、是否有额外约束覆盖 |
| 换一把武器就需要重调手骨 | 武器握持根尚未标准化，或把每武器偏移写到了角色骨骼上 |

官方提醒：给 Armature Apply Transform 不会同步修正 pose、动画曲线和约束，宜在绑定与动画前处理。因此本流程保留现有角色骨架变换，而非要求所有导入角色强制归一。[Blender 5.2 Apply](https://docs.blender.org/manual/en/5.2/scene_layout/object/editing/apply.html)

手动设置后至少检查：旋转手腕、播放一段动作、整体移动角色、测试角色统一缩放、保存重开、换另一把标准化武器。负缩放和非均匀缩放另测；双手握持与手指姿势不由这条挂点链自动生成。本次未操作 Blender 场景，上述步骤为源码与官方手册支持的待实机验证流程。

### 武器设置专项三轮搜索记录

| 轮次 | 本次实际检索 | 结论与收敛 |
|---|---|---|
| 第一轮 | `Bone Parent Relative Parenting`；`Child Of Constraint Set Inverse`；`Create Sockets Empty` | 确认骨骼父级与约束是基础；需继续区分握点和物体原点 |
| 第二轮 | `parent inverse keep transform`；`Empty Plain Axes Arrows`；`apply transforms armature pose animation scale` | 确认显示大小、父逆矩阵和现有骨架缩放的处理边界 |
| 第三轮 | `Copy Transforms Replace World Space`；`Clear Parent Inverse Keep Transform`；`Apply armatures before rigging`；`Sockets Skeletal copy/paste` | 采用固定父级主流程，约束作为明确替代；导出单独验证 |

搜索后直接读取 Blender 5.2 的 Parenting、Empties、Copy Transforms、Child Of、Apply 和 Link & Append 官方网页正文。网页工具抓取受限时使用只读 HTTP 获取正文；没有安装插件、启动 Blender 或更改资产。

## Blender 可参考插件

### Blender For Unreal Engine

优先级最高。作者提供静态与骨骼挂点制作、Empty 转换、自定义导出名称和骨骼挂点复制粘贴流程。[作者说明](https://github.com/xavier150/Blender-For-UnrealEngine-Addons/wiki/Sockets)

- 可借鉴：可视化 Empty、资产归属校验、制作名称与导出名称分开、导出时集中换算坐标。
- 重要边界：作者文档要求骨骼挂点通过复制粘贴导入 UE。不能据此承诺“骨骼 FBX 自动带入所有挂点”。
- 作者提供 FBX 的 X 轴旋转补偿选项。这是特定导出流程的处理，不能无条件用于 Blender 内部挂点。

已核对 `release` 提交 `780d9217fc8271f946f358559dbbb2ebbf989175` 的挂点模块：

| 源码入口 | 参考点 |
|---|---|
| [bfu_socket_operator.py](https://github.com/xavier150/Blender-For-UnrealEngine-Addons/blob/780d9217fc8271f946f358559dbbb2ebbf989175/blender_for_unrealengine/bfu_socket/bfu_socket_operator.py) | 静态与骨骼 Empty 转换、骨骼挂点剪贴板输出 |
| [bfu_socket_utils.py](https://github.com/xavier150/Blender-For-UnrealEngine-Addons/blob/780d9217fc8271f946f358559dbbb2ebbf989175/blender_for_unrealengine/bfu_socket/bfu_socket_utils.py) | `get_skeletal_mesh_socket_data`、`convert_to_unrealengine_socket`、`get_import_skeletal_mesh_socket_script_command` |
| [bfu_socket_props.py](https://github.com/xavier150/Blender-For-UnrealEngine-Addons/blob/780d9217fc8271f946f358559dbbb2ebbf989175/blender_for_unrealengine/bfu_socket/bfu_socket_props.py) | 自定义导出名称与属性注册、注销 |

`get_skeletal_mesh_socket_data` 会重置骨架姿势。借鉴变换计算时应审计完整调用链的姿势恢复，避免调研函数直接改变当前动画状态。该项目源码声明 GPL 许可证；本次未复制实现。

### Dynamic Parent

适合拾取、放下、换手。它通过 `Child Of` 约束和 Influence 关键帧切换关系，提供烘焙后清理功能。[作者仓库](https://github.com/romanvolodin/dynamic_parent)

已阅读 [Python 实现](https://github.com/romanvolodin/dynamic_parent/blob/master/__init__.py)：创建入口为 `dp_create_dynamic_parent_obj` / `dp_create_dynamic_parent_pbone`；`disable_constraint` 保存求值后的变换、关闭约束、恢复变换并打关键帧。

可借鉴“切换前保存姿势，切换后补偿”。作者说明每段重新绑定需要新约束，不能简单反复启用同一个约束。当前 manifest 为 **2.1.0，最低 Blender 5.0**；这是作者声明，未在本机试装。[版本清单](https://github.com/romanvolodin/dynamic_parent/blob/master/blender_manifest.toml)

### Send to Unreal

仅保留静态导出资料对照，不纳入当前人形工具的实施范围。

适合参考静态网格挂点管线。官方文档说明 `SOCKET_` 前缀与导入时去前缀的行为。[静态网格文档](https://epicgames.github.io/BlenderTools/send2ue/asset-types/static-mesh.html#sockets)

文档使用“child mesh”措辞；当前 [get_asset_sockets 实现](https://github.com/EpicGames/BlenderTools/blob/main/send2ue/core/export.py) 实际筛选直接子级 `EMPTY`，然后提取局部变换并转换坐标。实现时应以选定版本源码为准。

可借鉴命名与静态导出，不把这段静态流程推定为骨骼 Socket 支持。Blender 5.2 与 UE5.7.4 的实际互通兼容性仍需验证。

### Rigify 的父空间切换

属于源码参考，不是独立挂点插件。其 [switch_parent.py](https://github.com/blender/blender-addons/blob/main/rigify/utils/switch_parent.py) 使用 Armature 约束与目标权重；切换操作保存变换、更新依赖图，再恢复变换，也提供区间烘焙。

适合参考已有 Rigify 控制骨骼的空间切换。只做物体挂点时，引入整套 Rigify 生成机制会扩大依赖，暂不推荐。

## Blender 原生能力

| 原生能力 | 合适用途 | 必须核对 |
|---|---|---|
| Empty | 可见、可选、可命名的挂点 | 业务身份不能只靠名称前缀；附件不是挂点本身 |
| Bone parenting | 长期跟随骨骼的挂点 | 骨骼端点、Relative Parenting、父逆矩阵与 rest/pose 空间 |
| Object parenting | 武器握持根跟随人形骨骼上的挂点 Empty | 保持世界变换与吸附的行为必须分开 |
| Child Of | 动画中的绑定与解除 | Influence、Set Inverse、约束栈与关键帧插值 |
| 原生变换控件与 Undo | 编辑偏移、撤销恢复 | 删除、重命名和重复操作后引用保持一致 |

Blender 5.2 官方 `Child Of` 说明支持可动画的 Influence；Set Inverse 用于修正启用约束产生的非预期变换。[官方手册](https://docs.blender.org/manual/en/5.2/animation/constraints/relationship/child_of.html)

本次已取得上述 5.2 手册正文。原生机制与本机复杂 Rig 的运行行为仍须分别验证。

坐标关系建议先固定为：

```text
Blender 列向量约定
挂点世界矩阵 = 骨架世界矩阵 @ 骨骼 pose 矩阵 @ 挂点局部矩阵
附件世界矩阵 = 挂点世界矩阵 @ 附件局部矩阵
```

这是目标数学关系，不是直接设置 `matrix_local` 的配方。Bone parenting 的实际父空间还涉及骨骼端点、Relative Parenting 和父逆矩阵，应通过 Blender 求值结果核对。非均匀缩放与旋转可能产生剪切，不能假定 TRS 分解后完全等价。

## UE5.7.4 源码依据

本次读取 `C:\UE5.7.4\Engine\Build\Build.version`，版本确认为 **5.7.4**。Git HEAD 为 `260bb2e1c5610b31c63a36206eedd289409c5f11`；下表依据当前工作树源码，HEAD 不代表文件均无本地修改。

### 数据和运行时变换

| 当前源码 | 已确认行为 | 对 Blender 的启发 |
|---|---|---|
| [SkeletalMeshSocket.h:25](C:/UE5.7.4/Engine/Source/Runtime/Engine/Classes/Engine/SkeletalMeshSocket.h:25) | `SocketName`、`BoneName`、局部位置/旋转/缩放；`bForceAlwaysAnimated` 默认 true | 挂点核心数据很小，不必改骨架拓扑 |
| [StaticMeshSocket.h:27](C:/UE5.7.4/Engine/Source/Runtime/Engine/Classes/Engine/StaticMeshSocket.h:27) | 静态挂点归属于 StaticMesh，包含局部变换及编辑器预览数据 | 范围外对照，不增加通用物体挂点入口 |
| [SkeletalMesh.cpp:6911](C:/UE5.7.4/Engine/Source/Runtime/Engine/Private/SkeletalMesh.cpp:6911) | `GetSocketMatrix` 组合挂点局部矩阵与骨骼矩阵，骨骼缺失返回 false | 变换计算与失败检查集中在一个入口 |
| [StaticMesh.cpp:10570](C:/UE5.7.4/Engine/Source/Runtime/Engine/Private/StaticMesh.cpp:10570) | 静态挂点局部变换乘组件变换 | 两类挂点主要差异是父空间来源 |
| [SkinnedMeshComponent.cpp:3258](C:/UE5.7.4/Engine/Source/Runtime/Engine/Private/Components/SkinnedMeshComponent.cpp:3258) | 先按 Socket 查找，再尝试骨骼名；默认结果从组件变换开始，支持世界/组件等空间 | 缺失挂点不能仅靠“返回了矩阵”判断成功 |
| [SkinnedMeshComponent.cpp:5625](C:/UE5.7.4/Engine/Source/Runtime/Engine/Private/Components/SkinnedMeshComponent.cpp:5625) | 强制动画的挂点骨骼加入所需骨骼集合 | 后续接引擎时需要评估 LOD 裁骨影响 |
| [EngineTypes.h:60](C:/UE5.7.4/Engine/Source/Runtime/Engine/Classes/Engine/EngineTypes.h:60) | 绑定区分 KeepRelative、KeepWorld、SnapToTarget；缩放有独立规则，解除也有 KeepWorld | UI 应明确“保持位置”和“吸附挂点”，不要让用户猜测 |

UE 源码采用 `Local * Parent` 的组合表达；不能把乘法顺序原样搬入 Blender 的 `mathutils`。

### 编辑与资产归属

| 当前源码 | 已确认行为 | 可借鉴点 |
|---|---|---|
| [EditableSkeleton.cpp:542](C:/UE5.7.4/Engine/Source/Editor/SkeletonEditor/Private/EditableSkeleton.cpp:542) | `HandleAddSocket` 在 Skeleton 创建对象、生成唯一名称、加入 Sockets，使用事务 | 一键从当前骨骼创建、撤销、唯一性检查 |
| [EditableSkeleton.cpp:579](C:/UE5.7.4/Engine/Source/Editor/SkeletonEditor/Private/EditableSkeleton.cpp:579) | `HandleCustomizeSocket` 在 SkeletalMesh 创建同名 Socket，复制局部变换 | 共享骨架定义与特定模型偏移可以分开 |
| [SkeletalMesh.cpp:4993](C:/UE5.7.4/Engine/Source/Runtime/Engine/Private/SkeletalMesh.cpp:4993) | 编辑器分支先查 Mesh Socket，再查 Skeleton Socket | 同名覆盖必须有明确作用域与优先级；非编辑器缓存路径本次未追完 |
| [EditableSkeleton.cpp:384](C:/UE5.7.4/Engine/Source/Editor/SkeletonEditor/Private/EditableSkeleton.cpp:384) | `RenameSocket` 同步调整预览附件引用 | 重命名要维护关系，不能只改显示文本 |
| [EditableSkeleton.cpp:729](C:/UE5.7.4/Engine/Source/Editor/SkeletonEditor/Private/EditableSkeleton.cpp:729) | `HandleAttachAssets` 将预览附件记录到 Skeleton 或 SkeletalMesh 的容器 | 预览附件和运行时生成附件应分别处理 |
| [SSocketManager.cpp:535](C:/UE5.7.4/Engine/Source/Editor/UnrealEd/Private/SSocketManager.cpp:535) | 静态挂点支持创建、唯一命名、属性变更通知和资产脏标记 | 参考操作流程即可，无需移植 Slate UI |
| [FbxStaticMeshImport.cpp:2524](C:/UE5.7.4/Engine/Source/Editor/UnrealEd/Private/Fbx/FbxStaticMeshImport.cpp:2524) | 传统静态 FBX 路径识别 `SOCKET_` 的 Null/Skeleton 节点 | Empty 到静态挂点存在明确参考链；不推及所有导入器 |
| [FbxStaticMeshImport.cpp:2615](C:/UE5.7.4/Engine/Source/Editor/UnrealEd/Private/Fbx/FbxStaticMeshImport.cpp:2615) | 此清理分支跳过非导入创建的 Socket | 重导入应区分外部生成和手工编辑的数据 |

Epic 的 [5.7 骨骼挂点说明](https://dev.epicgames.com/documentation/en-us/unreal-engine/skeletal-mesh-sockets-in-unreal-engine?application_version=5.7) 与这些主要行为一致。本次未启动 UE 编辑器，源码入口不等于运行验收。

## 本工程现状

检索范围：`humanoid_retarget`、`spring_bone`、`shortcut_hint`、`wasd_fly_camera`、`tests` 和 `docs/design`；排除临时副本 `tmp_forearm_roll`。在这些范围内，未找到独立的 Socket 管理、附件换手或挂点导出工具。

- [spring_bone/operators.py:326](H:/Blender_Plugin/spring_bone/operators.py:326) 的 `_sync_empty` 已创建骨骼父级 Empty，并使用骨长补偿、父逆矩阵和前置显示。职责是碰撞体显示，不应直接改造成通用附件入口。它说明原生方案已有本工程使用先例，不能证明任意挂点偏移均正确。
- [humanoid_retarget/pipeline.py:200](H:/Blender_Plugin/humanoid_retarget/pipeline.py:200) 会收集骨架关联的 Mesh。后续挂入武器后，应检查其是否被重定向或显示处理误当作角色网格。
- 当前插件版本声明不同：重定向插件最低 Blender 4.2，弹簧骨插件最低 5.2。不能由单个插件声明推断整套工具或本机运行版本。

## 界面与人形联网复核记录

本次复核分三轮。第二轮根据第一轮的缺口检索；第三轮只补查控件和约束语义。各轮均以作者源码或官方说明收敛，不用论坛结论替代实现依据。

| 轮次 | 实际检索方向与关键词 | 核实结果 |
|---|---|---|
| 第一轮 | `Blender-For-UnrealEngine-Addons socket UI skeletal bone pose mode`；`skeletal mesh sockets preview assets mesh sockets`；`bone parenting Child Of armature attachment props`；`dynamic_parent panel create disable bone` | BFU 按选择状态提示操作并禁用按钮；UE 采用骨骼树、挂点详情和视口变换。缺口是人形部位映射、双手与衣甲边界 |
| 第二轮 | `rigify parent switching hand IK props`；`two bone ik weapon left hand socket`；`working with modular characters leader pose socket`；`auto rig pro child of constraint switch parent weapon` | 副手贴合需要 IK；换手需要姿势补偿；模块化蒙皮部件需要骨骼姿势机制，不能统一成单骨骼挂点 |
| 第三轮 | `IK constraints after all constraints`；`Child Of Set Inverse Influence`；`ChildOf Switcher`；`UIList filter template_list` | 确认约束切换与原生列表参考；IK 求值顺序未取得足够依据，保留为实施验证项 |

### 界面依据

- [BFU 界面源码](https://github.com/xavier150/Blender-For-UnrealEngine-Addons/blob/780d9217fc8271f946f358559dbbb2ebbf989175/blender_for_unrealengine/bfu_socket/bfu_socket_ui.py) 的 `draw_convert_skeletal_socket` 提示 Empty、骨架、Pose Mode 和目标骨骼；按钮跟随就绪状态。可借鉴逐步提示，减少对隐含选择顺序的依赖。
- [Auto-Rig Pro 作者说明](https://www.lucky3d.fr/auto-rig-pro/doc/rig_behaviour_doc.html#user-interface-controllers) 提供骨骼 Picker，缓解视口拥挤；[ChildOf Switcher](https://www.lucky3d.fr/auto-rig-pro/doc/rig_behaviour_doc.html#childof-switcher) 在切换时保持骨骼坐标并支持打关键帧。它们是控制骨骼工具，不能直接等同于道具挂载面板。
- [UE5.7 挂点说明](https://dev.epicgames.com/documentation/en-us/unreal-engine/skeletal-mesh-sockets-in-unreal-engine?application_version=5.7) 支持树或视口选择、局部变换、复制，以及保持世界姿势和吸附等规则。复用其“选择后编辑”的思路。
- 本工程 [HR_UL_mappings](H:/Blender_Plugin/humanoid_retarget/__init__.py:419) 已采用 `UIList` 与骨骼 `prop_search`。可复用交互方式，无须先造自定义绘制框架。

界面复核结合官方说明与 Rigify 源码；武器设置专项已补读相关 Blender 5.2 正文。Auto-Rig Pro 本次只读作者说明，未检查其商业插件实现。草图是方案示意，不是实机截图。

## 界面设计建议

### 主面板布局

入口建议为 `3D Viewport > N 面板 > 人形挂载`，复用 Blender 原生控件。角色字段限定为明确选定的人形 Armature，不提供通用物体/非人形模式。首批用部位按钮与挂点列表；可点击的人形轮廓留作后续增强，避免先投入复杂 Picker。

```text
+ 人形挂载
| 人形角色   [HeroRig         v] [使用当前骨架]
| 部位       [右手] [左手] [背部] [腰部] [头部]
|            左右以角色自身为准
|
| 挂点列表   名称         部位    状态
|            WeaponGrip   右手    已绑定 Sword
|            BackCarry    背部    空闲
|            HatMount     头部    空闲
|            [+ 创建] [复制] [删除]
|
| 当前挂点   WeaponGrip
| 实际骨骼   [hand_r          v] [取当前骨骼]
| 编辑对象   [挂点偏移] [道具偏移]
| 位置       X [ ] Y [ ] Z [ ]
| 旋转       X [ ] Y [ ] Z [ ]
| 缩放       X [ ] Y [ ] Z [ ]
|            [选中挂点] [重置当前偏移]
|
| 武器根     [GripRoot_Sword  v] [取当前物体]
| 握位       [显示握持根局部轴]
| 绑定方式   [吸附到挂点] / [保持世界姿势]
|            [绑定到挂点] [解除并保持位置]
|
| 显示       [挂点] [名称] [局部轴] [关系线]
| 动画       [使用 Blender 时间轴播放]
| 后续能力   动画换手 / 双手 IK / 导出
+ 状态       Hero / 右手 / hand_r / Sword
```

这是同一侧栏的折叠布局，不要求所有内容同时展开。数值默认显示当前编辑对象相对父级的变换；单位沿用场景设置。使用原生变换控件编辑选中的 Empty，不另设第二套变换数据。后续能力只是范围提示，首批不放置看似可用的功能按钮。

### 操作和反馈

| 用户动作或状态 | 建议反馈 |
|---|---|
| 选择角色 | 挂点列表限定为该角色；后续选择道具时仍保留角色，不随 active object 跳走 |
| 点击右手等部位 | 筛选相应挂点；没有挂点时显示“从已映射骨骼创建”，不暗中创建或重绑 |
| 没有有效骨骼 | 禁用创建与绑定，显示“右手未映射，请选择实际骨骼” |
| 视口选择插件挂点 | 面板跟随到该挂点；普通 Empty 不自动认领 |
| 编辑挂点偏移 | 所有绑定在此点的道具一起移动；列表明确提示影响对象 |
| 编辑道具偏移 | 只调整选中道具的握持关系，不改变同角色其他装备 |
| 道具已有父级、约束或驱动 | 显示现有关系；需要迁移时显式提供“替换绑定”动作，不静默叠加两套跟随 |
| 普通绑定与动画换手 | 普通绑定不自动打关键帧；换手入口明确显示帧号和写入的动画 |
| 删除挂点 | 告知受影响附件；默认保留附件并解除；不按名称批量删除物体 |

“播放预览”使用当前 Blender 场景关系和原生时间轴，不暗建道具副本；也不表示 UE 运行时已经挂载成功。颜色只辅助识别，空闲、绑定、失效均有文字状态。镜像和批量操作先不进入首批，避免左右骨轴差异被简单取负掩盖。

## 人形挂载的实现与表现

### 部位映射到真实骨骼

```text
当前角色
   -> 语义部位 hand_r / hand_l / chest / hips / head
   -> 经用户确认的实际骨骼
   -> 可编辑挂点 Empty
   -> 道具根对象
```

| 界面部位 | 可用语义角色 | 挂载例子 | 边界 |
|---|---|---|---|
| 右手、左手 | `hand_r`、`hand_l` | 剑、盾、工具 | 明确实际输出手骨；不把 metarig、IK 控制器或骨骼显示形状当作最终手部姿势 |
| 背部 | `chest`，或用户指定的 `spine` | 背剑、背包 | 背部是挂点用途，不是假定所有骨架都有的骨骼名 |
| 腰部 | `hips` 或自定义骨骼 | 刀鞘、腰包 | 左右腰可有多个点；不能只靠骨名判断位置 |
| 头部 | `head` | 帽子、头饰 | 刚性跟随；不自动完成尺寸适配、避穿插或头发模拟 |

本工程 [classify.py:13](H:/Blender_Plugin/humanoid_retarget/classify.py:13) 已定义这些角色，[classify_armature](H:/Blender_Plugin/humanoid_retarget/classify.py:115) 可返回角色与骨骼名，已有命名与几何识别。不得另写一套同职责识别器。

若读取重定向映射，必须明确选中的角色对应来源还是目标，不能混用 `source_bone` 与 `target_bone`。已有 [HRMapItem](H:/Blender_Plugin/humanoid_retarget/__init__.py:413) 与 [预设载入](H:/Blender_Plugin/humanoid_retarget/mapping.py:66) 可供复用；它们当前服务重定向，并不是已存在的挂载 API。

首批允许人工指定骨骼，保证插件可独立使用。可选“读取现有人形映射”应获取并验证快照，不强依赖重定向面板或自动复制其识别逻辑。部位映射缺失时只阻止该部位，不因缺脚骨而禁止头部挂载；重新识别不得覆盖已确认映射。映射预设只复用骨骼角色，握持偏移仍需逐角色、逐道具校准。

人形不等于统一骨架。普通导入人形可直接跟随其实际手骨；Rigify 等控制 Rig 应选择生成后、实际驱动可见手掌的骨骼。骨名带 `DEF` 或 Deform 勾选只能作为线索，不能单独证明它就是正确输出。为添加挂点不得重新生成 Rig、修改 rest pose，或覆盖已有动画。

### 单手道具对齐

1. 确认当前角色与右手骨骼，创建 `WeaponGrip`。挂点随最终求值的骨骼姿势运动。
2. 在剑柄处设置 `Grip_Main`；没有标记时允许使用道具原点，但提示可能需要较大偏移。
3. 选择“按握持标记对齐”，让剑柄对准挂点。调整道具偏移，使剑柄落在掌心；不修改源 Mesh 顶点、物体原点或 Apply Transform。
4. 播放走、跑、挥手动画，检查手腕旋转和全局缩放。挂点跟随不等于手指自动握紧，手指姿势仍由动画或既有控制 Rig 负责。

刚性道具的对齐关系建议为：

```text
S = 当前挂点的世界矩阵
G = 握持标记相对道具根对象的局部矩阵
O = 用户设置的额外握持修正，初始为单位矩阵
道具根对象世界矩阵 = S @ O @ inverse(G)
```

这是建议的对齐数学关系。它补足“只把道具原点吸到手上”的不足；实际 parent inverse、约束与缩放需另行验证。首批只接受稳定的刚性握持标记；道具自身骨骼驱动或动画化的握持标记属于扩展场景。矩阵不可逆时失败并保留原关系。

### 不同挂载场景

下表只有刚性附件长期跟随属于当前首批。拿取换手、双手、蒙皮和独立动画保留为后续人形能力对照。

| 场景 | 实现方向 | 应有表现 |
|---|---|---|
| 帽子、腰包、单手武器 | 一条骨骼挂点跟随链 | 动画中保持局部偏移；不承诺自动适配与避穿插 |
| 背部收剑再拿到右手 | 同一道具在两个挂点之间切换绑定区间 | 切换时可保持世界姿势，后续帧由拿取动画把手和武器对齐 |
| 两人传递或左右换手 | 指定下一角色、挂点与切换帧，保存求值姿势并补偿 | 边界帧不跳变；前后区间、倒放和任意跳帧一致 |
| 双手持枪或长柄武器 | 主手确定武器，武器副握点提供副手 IK 目标 | 两手贴合来自 IK 与手指姿势，不能把物体同时设成两只手的普通子级 |
| 衣服、软甲、跨关节护甲 | 蒙皮、权重和兼容骨骼姿势 | 随多个骨骼变形；单个胸部挂点不能产生这种形变 |
| 带独立骨架的枪械或背包 | 整体根对象挂载，内部动画单独处理 | 跟随角色同时保留内部动画；首批不自动改它的骨架或权重 |

双手方案依据：Epic [Two Bone IK](https://dev.epicgames.com/documentation/en-us/unreal-engine/animation-blueprint-two-bone-ik-in-unreal-engine?application_version=5.7) 明确支持用交互对象的 Socket 位置驱动末端，并用 Joint Target 控制中间关节。本方案据此推导“主手挂载、副手配合”，并非官方保证 Blender 任意 Rig 都可直接套用。

骨骼层面的目标依赖应保持“主手 → 武器位置 → 副握点 → 副手 IK”，不能再让主手反向依赖副手。Blender 中同一 Armature 经外部道具回接 IK，仍可能涉及对象级求值循环，必须用实际 Rig 验证；不能仅凭图上无环判定安全。优先接已有 Rig 的空间切换与 IK 控制入口，控制器或求值顺序未确认时禁用“双手贴合”，不要自动插入另一套 IK。

衣甲边界依据：Epic [模块化角色说明](https://dev.epicgames.com/documentation/en-us/unreal-engine/working-with-modular-characters-in-unreal-engine?application_version=5.7) 分别讨论 Leader Pose、Copy Pose 和骨骼网格合并。这说明模块化蒙皮需要姿势机制；它不是 Blender 中已有同名功能的证据。刚性肩甲仍可按单骨挂点处理，是否需要蒙皮取决于资产形变需求。

### 动画换手的界面边界

“动画换手”折叠区建议只显示：道具、当前挂点、下一角色/挂点、当前帧、保持姿势、`在当前帧切换`、`解除到世界`、`烘焙所选区间`。普通挂点编辑不进入动画写入路径。

离散换手默认使用离散的绑定权重，不把两个完整父变换随意叠加。每个绑定区间保存各自的逆变换；反复修改同一约束的 Set Inverse 可能改变较早区间。参考 [Dynamic Parent](https://github.com/romanvolodin/dynamic_parent) 的分段约束和 [Rigify 切换实现](https://github.com/blender/blender-addons/blob/main/rigify/utils/switch_parent.py)，但不照搬其清理逻辑。

必须明确当前 Action、slot 与 NLA 归属，保留用户原有动画和约束。保持世界姿势只保证切换瞬间位置连续，不会自动生成拿取动作、运动速度连续性或自然手指接触。平滑过渡、自动抓握和双手 IK 放在后续批次。

## 建议与取舍

首批只做一个可观察的完整闭环：**选人形角色与部位 → 确认实际骨骼 → 创建挂点 → 调偏移 → 绑定刚性道具 → 播放跟随 → 解除与撤销 → 保存重开**。这是后续方向，本次没有实施。

| 决策 | 推荐与原因 | 暂不采用 |
|---|---|---|
| 挂点载体 | 原生 Empty，使用现成选择与变换工具 | 默认新增挂点骨骼，会改变骨架与导出内容 |
| 跟随 | 原生父子关系；需要动画切换时才加 Child Of | 每帧 Python 更新，容易重复求值并增加维护负担 |
| 功能归属 | 独立挂点插件，单向使用 `bpy` / `mathutils` | 把它塞进重定向或弹簧骨求解器，扩大职责 |
| 业务身份 | 为挂点记录明确标识；对象引用与导出名称分开 | 仅靠 `SOCKET_`、全局对象名或选择顺序认定所有权 |
| UE 互通 | 确有需要时接 BFU 或提供明确的导出动作 | 首批自建完整 FBX/UE 导入框架 |

后续三个变化可局部增加：换手增加绑定区间；另一导出目标增加对应转换；不同角色体型增加各自挂点偏移。当前不预建通用注册表或多层框架。

挂点对象保存自身局部变换，附件保留独立偏移。默认删除挂点时保留附件，并按明确规则解除绑定；失效骨骼、奇异矩阵和依赖环应提示失败，避免静默回退到原点。启停插件只注册或注销自身功能，不删除用户已有物体。以上失败与生命周期规则需要在实施阶段验证。

## 验证边界与后续验收

| 证据层 | 本次结果 |
|---|---|
| Static | 已核对上述插件源码入口、作者文档与本地 UE5.7.4 源码 |
| Build | NotRun，本次未修改代码，无适用构建 |
| Process / Runtime | NotRun，未安装插件、未启动 Blender 或 UE |
| Export / Import | NotRun，未进行 FBX、glTF 或剪贴板往返 |
| Visual / 正式验收 | NotRun，仅完成参考调研 |

当前人形首批验收至少覆盖：

1. rest/pose 下创建，非零骨长，骨架有平移、旋转和缩放；动画中保持正确偏移。
2. 吸附、保持世界姿势、保留附件偏移三种操作；解除与重复绑定不产生意外跳变。
3. 重命名、骨骼缺失、删除、复制角色、Undo/Redo、保存重开，以及插件停用后原生关系。
4. 固定挂载随角色动画逐帧、倒放和跳帧结果一致；不删除用户原有约束与关键帧。
5. 武器切换测试只验证另一把标准化武器复用人形挂点，不要求动画换手或 UE 导出。
6. 与重定向、IK、弹簧骨共存；只操作明确属于本插件的内容。

本轮新增的界面与人形验收项：

| 检查 | 通过条件 |
|---|---|
| 仅人形范围 | 角色入口与骨骼归属均限定人形；通用物体、非人形和静态网格 Socket 没有实施入口 |
| 首次使用与错误反馈 | 从选角色到单手绑定可完成；缺骨骼时说明原因；按钮禁用原因可见 |
| 多角色与左右部位 | 道具选择不使当前角色跳变；A 角色映射不指向 B；镜头转向不改变左右语义 |
| 偏移与握持标记 | 道具原点远离剑柄仍能对齐；挂点偏移和道具偏移互不混淆；未改源资产原点 |
| 部位识别 | 缺映射不误绑；人工修改不会被刷新覆盖；控制骨、变形骨和 rest/pose 不混用 |
| 后续动画换手验收 | 当前不执行；将来实现时验证连续多次拿起/放下、倒放、跳帧与重新打开，早期区间无回写破坏 |
| 后续双手能力验收 | 当前不执行；将来先证实原 Rig 的 IK 入口、空间和无求值循环，再启用双手贴合 |
| 首批范围 | 完成人形刚性挂点闭环；动画换手、衣甲蒙皮、自动手指握持、双手 IK、镜像和导出均不冒充已支持 |
| 手动设置与资产复用 | 两把使用同一轴约定的武器经各自握持根对齐；无须改角色骨骼；Append Collection 后部件完整且无旧角色引用 |
| 原关系与变换 | 不改变已有 Relative Parenting；保持姿势和吸附结果分别通过；Scale、Delta 和父逆矩阵均检查 |

以上均为待执行的验收条件，当前 Runtime 与 Visual 仍为 `NotRun`。

本次新增内容只有本文档，无临时埋点、诊断脚本或运行依赖。后续实施仍须执行“保存证据 → 用户核对 → 清理临时诊断 → 清理后复验 → 最终报告”。

## 来源索引

所有在线来源于调研当日检索；未固定提交的 `master` / `main` / Wiki 内容可能继续变化。

- BFU：上文作者 Wiki、固定提交中的 `bfu_socket` 三个源码文件。
- Dynamic Parent：作者 README、`__init__.py`、`blender_manifest.toml`。
- Epic BlenderTools：静态网格官方文档、`send2ue/core/export.py`。
- Blender：官方 Child Of 手册；官方 `blender/blender-addons` 的 Rigify 父空间切换源码。
- Epic：指定 `application_version=5.7` 的骨骼挂点说明；本地当前源码路径与行号见上表。
- 本轮新增：BFU `bfu_socket_ui.py`；Auto-Rig Pro 的 Picker 与 ChildOf Switcher 作者说明；Epic 5.7 Two Bone IK 与模块化角色说明；本工程 `classify.py`、`mapping.py`、`HRMapItem` 和 `HR_UL_mappings`。
- 武器设置专项新增：Blender 5.2 Parenting Objects、Empties、Copy Transforms、Child Of、Apply、Link & Append 正文；链接分别位于设置步骤旁。
- 仅人形两轮复核新增：Blender 5.2 Rigify Basic Usage 与 Creating Meta-rigs 正文；再次核对本地 `classify_armature` 与 UE5.7 Skeletal Mesh Sockets / Two Bone IK 官方说明。
- 工程身份：`H:\Blender_Plugin`，remote 为 `https://github.com/shajieChen/Blender_PersonalToolSet.git`。本次仅新增本文档，保留原有未提交内容，无 Commit 或 Push。
