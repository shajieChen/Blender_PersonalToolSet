# 胸部朝向复核：大方块绑定与躯干扭转
DO_NOT_PATCH

## 目标

```text
大方块网格 -> Head，非 chest
spine/chest/neck -> 链方向保留，来源扭转丢失
扩展同一 hips 公式 -> 躯干恢复；Head 误差增大 -> 不授权补丁
```

结论：第 36 帧确实存在与旧 hips 同类的躯干扭转缺失；但截图的大方块不是胸甲绑定。它由 `Head` 控制。不能把三处躯干的修复直接当作该方块的修复。唯一允许评估的现有公式扩展反而增加 Head 朝向误差，因此本修订不授权 PATCH，也不另造公式。

本次核对 HEAD 为 `e49a01b7279472477831585390e8afa63a78aeec`，插件版本 `(1, 7, 1)`。独立 Blender `5.1.2`，build `ec6e62d40fa9`。这不是已部署修复。

### 绑定证据

实际导入 `body.FBX` 后，目标 armature 为 `Bip01`；唯一网格为 `body00`，615 顶点。Armature modifier 指向 `Bip01`，`use_vertex_groups=True`，`use_bone_envelopes=False`。

上方大方块的 **141 顶点全部仅有 `Head` 权重 1.0**。这些顶点的导入 rest 世界包围盒：X `[-0.333681, 0.333670]`，Y `[-0.290343, 0.346165]`，Z `[1.052889, 1.699750]` 米。约 `0.667 × 0.637 × 0.647` 米的方块区域。`Bip01 Spine1` 权重区域最高 Z 为 `1.039582`，低于方块；方块没有 chest 或 neck 混合权重。骨名来自实际权重与 modifier，不来自外形猜测。

实际角色映射：`Spine -> spine.001 -> Bip01 Spine`；`Spine2 -> spine.003 -> Bip01 Spine1`；`Neck -> spine.004 -> Neck`；`Head -> spine.006 -> Head`。

保存的 PNG 显示帧 **18**，不是文字要求的 36；选中对象名也显示 `Armature`。本次按明确要求测帧 **36**，不把该旧图当作帧 36 的运行证据。站位 SIDE 只平移对象，求解/角度使用 armature 与 rest 身体坐标，平移不影响以下数字。

### 测量定义

完整烘焙唯一选中的 `a050_300000`，帧范围 `0..52`；主测 `RIGIFY_HUMAN_METARIG / REST / KEEP / foot_ik=False / hand_ik=False`，另测 DIRECT 对照。FBX 自动骨骼朝向关闭。测的是实际 baked Action 在 frame 36 的 pose。

链方向取 mapped bone head 到 mapped child head；分别转换到由 rest 几何建立的身体坐标，再求夹角。扭转取来源或目标自身的 `R_pose @ inverse(R_rest)`，按**各自 posed chain**提取与已交付 hips 相同的 signed swing-twist 标量；角度包装到 `[-180°,180°)`。不比较原始 bone +Y，不复制绝对矩阵，也不把整个 orientation 差当成 twist。

`Head` 无 mapped chain end：`_CHAIN_CHILD` 不含 head，且其实际 children 都不在映射中。因此 Head 的**出射求解链方向与扭转是 N/A**，不能伪造数值。为检查方块朝向，下面单独给出其入射 `Neck -> Head` 链方向，以及 Head 自身 rest-relative delta 绕该入射链的扭转。它不是 Head 的新增求解链。body-up yaw 与全旋转误差另列，不相互替代。

### frame 36 原版两跳

| role | 来源 -> 目标 | 链方向误差 ° | 来源扭转 ° | 目标扭转 ° | 来源减目标 ° |
|---|---|---:|---:|---:|---:|
| hips | Pelvis -> Bip01 Pelvis | 0.000015 | -39.261078 | -39.261071 | -0.000007 |
| spine | Spine -> Bip01 Spine | 0.000028 | -42.266775 | 0.000009 | -42.266783 |
| chest | Spine2 -> Bip01 Spine1 | 0.000082 | -51.992257 | 0.000000 | -51.992257 |
| neck | Neck -> Neck | 0.000085 | -38.787924 | -0.000016 | -38.787908 |

`spine`、`chest`、`neck` 全部满足 **扭转丢失 >5°，链方向误差 <1°**。hips 新公式仍工作，本次两跳 hips twist 残差约 `0.000007°`；这不是此前 body-up yaw 的度量。

### frame 36 原版直连

| role | 来源 -> 目标 | 链方向误差 ° | 来源扭转 ° | 目标扭转 ° | 来源减目标 ° |
|---|---|---:|---:|---:|---:|
| hips | Pelvis -> Bip01 Pelvis | 0.000012 | -39.261078 | -39.261071 | -0.000007 |
| spine | Spine -> Bip01 Spine | 0.000034 | -42.266775 | 0.000055 | -42.266830 |
| chest | Spine2 -> Bip01 Spine1 | 0.000089 | -51.992257 | -0.000040 | -51.992217 |
| neck | Neck -> Neck | 0.000097 | -38.787924 | 0.000002 | -38.787925 |

三处躯干直连也远大于 5°，所以不是“仅 metarig 两跳错误”。两跳中，第一次已经把三处扭转投影成接近零；第二次的输入已无可恢复信息。若第一跳保留，第二跳原有非 hips 分支同样仍会丢失。

| 跳 | role | 链方向误差 ° | 输入扭转 ° | 输出扭转 ° |
|---|---|---:|---:|---:|
| 1 | spine | 0.000015 | -42.266775 | 0.000002 |
| 1 | chest | 0.000038 | -51.992257 | 0.000012 |
| 1 | neck | 0.000043 | -38.787924 | -0.000003 |
| 2 | spine | 0.000013 | 0.000002 | 0.000009 |
| 2 | chest | 0.000044 | 0.000012 | 0.000000 |
| 2 | neck | 0.000045 | -0.000003 | -0.000016 |

### 方块实际绑定骨 Head

| 第 36 帧 | 原版两跳 | 原版直连 | 同公式扩三角色，两跳 |
|---|---:|---:|---:|
| Neck -> Head 链方向误差 ° | 0.000085 | 0.000097 | 0.000191 |
| 来源 Head 绕入射链扭转 ° | -6.566558 | -6.566558 | -6.566558 |
| 目标 Head 绕入射链扭转 ° | -0.000010 | 0.000001 | -38.787858 |
| Head 扭转差：来源减目标 ° | -6.566548 | -6.566559 | 32.221300 |
| 来源 Head body-up yaw ° | -5.199594 | -5.199594 | -5.199594 |
| 目标 Head body-up yaw ° | -0.234443 | -0.234450 | -35.837794 |
| Head body-up yaw 差 ° | -4.965152 | -4.965144 | 30.638200 |
| Head 身体坐标 rest-relative 旋转误差 ° | 9.213323 | 9.213408 | 33.205135 |

原版中，来源 torso/chest twist 为 `-51.992257°`，但来源 **Head 的 body-up yaw 仅 `-5.199594°`**。把来源胸甲与目标 Head 方块比较，不是同 role 验收。目标 Head yaw 为 `-0.234443°`，差 `-4.965152°`；绕入射链扭转差为 `-6.566548°`，身体坐标完整 rest-relative 旋转差为 `9.213323°`。这些量不能互换。

Head 在两侧都 parent 到 Neck。REST `_apply_body_orientations` 先清空 Head 局部 quaternion；因无链在 `retarget.py:285-286` 跳过 Head 求解，Head 继承目标 Neck 与自身 bind 的关系。来源 Head 含不同于 Neck 的独立旋转；把 Neck 扭转修好并不补回该独立旋转。这与“同一 bone 的出射链方向被保留，只遗漏绕该链的标量”不是相同的已闭合因果链。

## 修改范围

本轮只写本文件与 `C:\Users\chenshajie1\.cursor\projects\h-Blender-Plugin\addon_stage\codex_chest_orientation.md`。

**授权新增角色：无。** 不修改插件、测试、版本或 hips 公式。版本保持 `(1, 7, 1)`；不进入 `(1, 7, 2)` 实施。不添加测试；产品 RED/GREEN 与全量回归均 NotRun。

确认的静态缺口位于 `retarget.py:_apply_body_orientations:247` 的 REST 分支 `:288-303`：`spine/chest/neck` 只有方向 swing 与 target rest，不读取来源绕链扭转；`role == "hips"` 才读取该自由度。手和 Head 无 mapped end，走 `continue`。以上是现状，不是扩大手或 Head 求解范围的授权。

## 实施步骤

### 已完成的唯一公式核验

独立进程内仅把现有 `if role == "hips"` 临时换为角色集合 `{"hips", "spine", "chest", "neck"}`，**其余公式逐字保持**；未写入产品文件。即继续使用交付公式的来源 rest-relative twist，围绕 desired chain 左乘，并把 target bind 留在最右侧。没有第二公式，没有 source absolute orientation copy。

```text
D = R_source_pose @ inverse(R_source_rest)
theta = 原 hips 块的 canonical/wrapped swing-twist(D, posed source chain)
orient = Rot(desired chain, theta) @ swing @ R_target_rest
```

这是已交付公式的测量说明，不是新的实施公式。子骨按原有 parent-relative basis 顺序重新求解，允许局部 quaternion 补偿，未冻结子骨。

| role | 来源 -> 目标 | 链方向误差 ° | 来源扭转 ° | 目标扭转 ° | 来源减目标 ° |
|---|---|---:|---:|---:|---:|
| hips | Pelvis -> Bip01 Pelvis | 0.000005 | -39.261078 | -39.261071 | -0.000007 |
| spine | Spine -> Bip01 Spine | 0.000087 | -42.266775 | -42.266792 | 0.000017 |
| chest | Spine2 -> Bip01 Spine1 | 0.000104 | -51.992257 | -51.992206 | -0.000051 |
| neck | Neck -> Neck | 0.000191 | -38.787924 | -38.787866 | -0.000058 |

三处躯干候选残差小于 `0.000059°`，链方向仍小于 `0.000191°`。然而 Head 绕入射链误差从 `6.566548°` 增至 `32.221300°`，完整 rest-relative 旋转误差从 `9.213323°` 增至 `33.205135°`。**否决它作为方块修复**。DIRECT 候选同样为 `32.221292° / 33.205135°`，不是特定中间骨架独有的退化。

其它角色也有被单方向投影舍弃的自由度：两跳基线肩 L/R `+27.773192° / -30.108456°`，上臂 L/R `+67.395887° / -36.111168°`，前臂 L/R `+77.240407° / -44.048174°`，大腿 L/R `+16.813901° / +33.110480°`，小腿 L/R `+13.561782° / +45.452496°`；方向误差均 <`0.000307°`。这是信息缺失测量，不等于授权把同公式扩到全部 limb。两侧 hands 局部 quaternion 仍 identity，无末端链扭转度量。脚/趾缺少对应链末端，也不据此推广。

### 官方规则：本日实时检索并打开

1. [Epic FK Chain Retarget / Interpolated](https://dev.epicgames.com/documentation/unreal-engine/retargeting-operation-stack-in-unreal-engine-5-8)：
   > each target bone rotation is generated by finding the rotation at the same normalized distance on the source chain

   页面明确在 FK rotation 模式转移来源旋转；选择 None 才让目标保持 reference pose。推断：其规则不是“沿 child 对齐方向以后，所有来源扭转都必须留在 target bind”。它支持传递躯干动画旋转，但没有给出本插件的跨 bind 数学公式。同页的 Pole Vector Alignment 允许 limb 依据来源 pole 进行链扭转；也没有要求每根 limb 都用 hips 公式。

2. [Autodesk HumanIK / HIKReachActorChestRotationId](https://help.autodesk.com/cloudhelp/2016/ENU/HumanIK-SDK-Help/files/GUID-16CA9EA7-4684-4FD5-B95C-7091193FA562.htm)：
   > matching the final rotation of the target character’s chest to the original rotation of the source character’s chest

   它是来源 chest 旋转匹配优先级，范围 0..1，默认 0；不是每种模式强制完整匹配，更不是直接复制绝对骨轴的许可。它证明 chest 来源旋转是独立目标，不能把 head mesh 当作 chest 匹配证据。

3. [Blender 官方 Rigify basic_spine.py](https://raw.githubusercontent.com/blender/blender-addons/main/rigify/rigs/spines/basic_spine.py)：
   > self.make_constraint(mch, 'COPY_TRANSFORMS', control,
   >                              space='LOCAL', influence=1 / chain_len)

   `rig_mch_bone` 把 hips/chest 控制变换分配到生成 spine 机制链。它是 Rigify 内部控制 rig 的机制，不是跨 skeleton retarget 的 source-follow 规则。本插件只使用 human **metarig** 样本，没有运行生成 rig，不能借这段源码证明当前中间骨架自动保留 twist。该官方归档源码也不冒充本机 5.1.2 运行版本。

官方资料没有提出“所有 spine/limb 动画扭转必须无条件保留 target bind”的统一规则。本次 DO_NOT_PATCH 的依据是**方块绑定和候选实测不闭合**，不是该假定。文档支持的旋转能力不能替代实际 pair 的成功验收。

### 材料与执行效率

已读 hips 修订、metarig 设计、实际 solver 及相关 pipeline/role 定义。已定位 `correct_chest_pairs`；它纠正 chest 到 Neck 父骨，不改变网格权重。探子一批两项：数据入口、官方规则；收敛后主线程读精确源码并负责测量和决策，未派修改任务。

输出截断后仅补读缺失段。首个测量发现方块绑定 Head，追加一次仅导入/rest 数据与已保存 pose delta 的 Head 核验，不重复完整 bake；为避免 bone +Y 跨 bind 误判，再补入射链诊断。未出现编译错误；无未经修正的重复失败运行。每次 import 禁止写 bytecode，避免触碰保护目录。

## 强制约束

- Head 的 outgoing mapped chain 为 N/A，不用 head tail 或脸/头发骨拼造求解链。对骨骼原始 +Y 的差异不作补丁依据；不能复制 `matrix_basis` 或来源绝对朝向消除 rest-axis 差。
- hips 已交付公式、CURRENT、hand identity、目标 rest、IK、same-clip 和 Git stash 全部保持。本轮没有进入目标 Edit Mode；创建 Rigify 自有临时样本不等于编辑目标。
- 依赖仍为 UI -> pipeline -> retarget，pipeline -> rigify_metarig；无新增 API、注册项、全局长期状态或运行依赖。
- Blender 主线程拥有本次进程的数据；测量函数借用 armatures。pipeline 在 finally 销毁自有中间骨架；内存候选在结束前恢复，进程自然退出。失败不应发布候选结果。本轮没有产品修改回滚需求；不执行任何 Git 回退或写入。
- 单独验证 torso 规则不等于 Head 旋转/Visual 通过。Head 独立旋转如何在当前无末端链合同下传递仍 **Unproven**；不得为此增加第二公式。

## 验收标准

本次已完成 Static、实际网格绑定 Contract、Process 退出 0、完整实际 pair 的原版与内存候选 Runtime 测量。主测两跳与 DIRECT 各原版/候选一次，共六次 53 帧单跳 bake；每次只选中一个真实 Action。Head 二次诊断复用这些 frame 36 pose delta，不另改 Action。

证据：`H:\tmp\chest_orientation_20261013\measurement.json`、`head_measurement.json`、`probe.log`、`head_probe.log` 与两份外部脚本。`retarget.py` SHA256 为 `ddc0696d33d0c260751dfde5bdce283eae9a2eea626942d5f87d1ac644450b50`。测量前后整个 `humanoid_retarget` 与 `tests` 文件内容 SHA256 集合一致，目标各骨 matrix_local 前后一致。双手四元数每次仍为 identity。

临时产品诊断清单：无。外部独立脚本、JSON 和日志保留为本次验收证据，不安装到插件，不注册、不轮询，进程结束后无运行开销。未改产品或测试，因此没有可宣称的产品 RED/GREEN；全量回归、修复后 Visual、正式修复验收均 **NotRun**。图像仅检查了所给 PNG 的内容与帧号；没有 frame 36 的匹配视角渲染或用户会话验证。

本修订完成的只是诊断与 DO_NOT_PATCH 文档交付。对 source 胸甲/target Head 的视觉类比不作产品失败结论；对于实际三处躯干 twist 的缺失，保留确证数据，待能够同时处理 Head 语义与真实视觉目标的独立授权方案再审。

## 禁止事项

不修改 `humanoid_retarget` 或 tests；不改 hips 公式、target rest、CURRENT、hands；不做绝对 source orientation copy、matrix_basis copy、子骨冻结、stash pop、暂存、提交或推送。不把躯干候选接近零的数值当作大方块已修复，也不把本文件当作 `(1, 7, 2)` 实施授权。
