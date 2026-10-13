# 骨盆偏航：唯一实施修订
PATCH

日期：2026-10-13。本文替代本文件旧版 DO_NOT_PATCH 与旧验收门；Cursor 只能按本文件实施。本文授权的是后续实施范围，本次审查没有修改插件或测试，也没有完成产品修复。

```text
REST hips 链方向 -> swing 保留方向、丢失绕链自由度
                + 来源 rest-relative twist 标量
                -> hips orient -> 原有子骨补偿 -> yaw 恢复
```

## 目标

**确定原因：** 当前 _apply_body_orientations 的 REST 分支（retarget.py:281-289）仅把 hips→spine 的单一方向变成 swing，再乘目标 rest orientation，没有读取来源 hips 的 rest-relative 旋转中绕 posed chain 的自由度；因此链方向几乎完全匹配时，骨盆仍丢失显著 body-up yaw。Epic 的 retarget-root 文档明确默认旋转跟随来源，retarget root 通常为 pelvis/hips；保留 target bind 骨轴不等于冻结来源的动画 yaw。采用这一生产重定向规则与用户要求，本问题是插件 REST hips 的旋转信息缺失，不是 same-clip 显示问题。已测公式 A 在本次完整烘焙的五个指定帧满足新门，不需要第三公式。该判断不声称所有 retargeter 都必须使用 A，也不声称它是 Epic 的内部公式。

### 原始规则与来源

以下页面于 2026-10-13 实时检索并打开。原文只证明产品旋转规则或 API 含义，不能单独证明跨 bind 公式。

1. **Epic：retarget root 是 pelvis/hips。**
   > Within both IK Rig Assets, you must define the root for each character, which is typically the pelvis or hip bone.
   URL：https://dev.epicgames.com/documentation/en-us/unreal-engine/retargeting-bipeds-with-ik-rig-in-unreal-engine
   这是角色定义；独自不足以决定 yaw。需和下一条明确旋转规则一起读。

2. **Epic Unreal 5.1：rotation_alpha 的 source-follow 规则。**
   > At 1 the root is rotated fully to match the source root rotation.
   URL：https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/TargetRootSettings?application_version=5.1
   页面把该参数的说明默认值写为 1；值为 0 是选择保留 retarget-pose 旋转，不是所有骨盆 yaw 必须留在 target bind 的规则。这里是 retargeted root rotation，不授权直接复制来源绝对骨轴。

3. **Epic Unreal 5.8：明确将 pelvis rotation 与 FK chains 分开。**
   > Blends the animation on the retarget pelvis between the retarget pose (0) and the incoming retarget source (1).
   URL：https://dev.epicgames.com/documentation/unreal-engine/retargeting-operation-stack-in-unreal-engine-5-8
   引文来自 Pelvis Rotation / Rotation Alpha。它确认来源旋转不是只有 hips→spine 的方向。这里只使用可读文档，不声称本机运行过 Unreal。

4. **Auto-Rig Pro：Root Bone 的旋转转移规则，作为交叉核对。**
   > Setting it as Root will retarget translation + rotation, while only rotation is used otherwise.
   URL：https://www.lucky3d.fr/auto-rig-pro/doc/remap_doc.html#root-bone
   同节把 root 定义为通常的 hips/pelvis。这是旋转转移规则，不是 A 的推导。该产品对对象归零、rest pose 的流程要求不迁入本补丁。

5. **Blender 5.1.2 官方 API 文档源码：单角提取。**
   > Split the rotation into a swing quaternion with the specified axis fixed at zero, and the remaining twist rotation angle.
   URL：https://github.com/blender/blender/blob/v5.1.2/source/blender/python/mathutils/mathutils_Quaternion.cc#L323-L334
   函数 Quaternion.to_swing_twist 接受 X/Y/Z，返回 swing 与 twist angle。官方 5.1 API 网页抓取为 402，以上同版本源码已实际打开核验。这里只用它提取角，不把 API 说明冒充产品重定向公式。

Blender Rigify/manual 页面已检索和尝试打开，但本主线程抓取为 402；不依赖它作因果证明。Mixamo 的已打开官方页只说映射 skeleton；Maya HumanIK 的已打开 character-structure 页只规定 hips rotation 存到哪个节点，均不足以决定 source-follow yaw。它们没有提供可替代上述 Epic 规则的 target-bind 必保留 yaw 规则。检索范围有限，不能以未找到文档证明不存在其他模式。

## 修改范围

**本轮实际写入：** 本修订档与插件外 codex_sideways_cause.md。问题事实档不改；新测量未推翻其数值，只替换旧验收合同。旧事实档的 DO_NOT_PATCH / 非髋 quaternion 不变 / 世界 dot 门不再是实施指令。

**后续 Cursor PATCH 范围：**
- humanoid_retarget/retarget.py：新增 Quaternion 与 pi 必要导入；只在 REST hips orient 增加 A 的单角旋转。其它 role 的算法、CURRENT、平移、Action/slot 与 same-clip 行为不变。
- humanoid_retarget/__init__.py：仅把 bl_info version 从 (1, 7, 0) 改为 (1, 7, 1)。本轮不改版本。
- tests/run_retarget_test.py：后续新增 test_rest_hips_yaw_preserves_arm_chain，并在 main 中调用；本轮不修改测试。不得改动既有测试或测试过滤器来制造 GREEN。

依赖保持 pipeline.py -> retarget.py -> classify/mapping/ik；测量与测试依赖产品，不反向引入运行依赖。无需新策略、接口或配置。Blender 主线程持有 armatures、Action；本函数借用引用，只更新目标 PoseBone。无新注册/注销、线程、长期对象、公共 API 或外部依赖。

## 实施步骤

### 1. 复用本轮已读材料与源码定位

已完整读精确求解函数：_body_matrix:139、_chain_vector:220、_apply_body_orientations:246-308；已读原问题/修订档及公式 A 测量脚本；已核对现有 build_biped、test_swing_preserves_target_roll、test_metarig_swing_limits 和 main 的相关代码。未变化材料直接复用，只有源码变化或证据冲突时局部刷新。

本轮探子一批、两个独立只读任务：Blender/Rigify/Mixamo 与 Maya 官方规则；主线程负责 Epic/ARP、精确源码、公式与最终验证。探子不修改文件。后续若确实有跨目录缺口，才补派聚焦任务，不重复检索已闭合问题。

### 2. 精确公式 A，不得换为 B

保持现有 src_chain、tgt_chain、desired、swing、orient 计算顺序。src_chain 是 posed source hips→spine；tgt_chain 是 target rest hips→spine。身体轴只来自各自 rest head_local。骨骼局部 +Y 不是链轴；仅借 +Y 作为 Blender API 的计算坐标。

```text
src_chain = _chain_vector(src, src_roles, role, True)
tgt_chain = _chain_vector(tgt, tgt_roles, role, False)
desired = target_body @ normalize(source_body^-1 @ src_chain)
swing = rotation_difference(normalize(tgt_chain), normalize(desired))
orient = swing.to_matrix() @ target_rest_orientation
D = _rot3(source_pose.matrix) @ _rot3(source_rest.matrix_local)^-1
q = normalize(Quaternion(D)); choose q.w >= 0
F = rotation_difference(+Y, normalize(src_chain))
q_chain = F^-1 @ q @ F
theta = wrap(q_chain.to_swing_twist('Y')[1], [-pi, pi))
orient = Rot(normalize(desired), theta) @ orient
rest = _rot3(pose_bone.bone.matrix_local)
basis = rest^-1 @ parent_rest_rotation @ parent_pose_rotation^-1 @ orient
```

最后一行只适用于有 parent 的分支；无 parent 时保持 basis = rest^-1 @ orient。保留现有 target_rest_orientation 的原始 rest_orient 计算，不用 source rest 替换它。因为 Rot(desired, theta) 不改变 desired 自身，所以 A 不改变 hips 链方向。target bind 仍是乘法的最右侧基础；只转移 theta 一个标量。

**准确插入点：** 当前 REST 分支 orient = swing.to_matrix() @ rest_orient 之后、else CURRENT 分支之前，仍在原有父先子后循环内。新代码等价如下；需要 from math import pi 及现有 mathutils 导入增加 Quaternion：

```python
if role == "hips":
    source_rest = _rot3(src.data.bones[source_name].matrix_local)
    source_delta = _rot3(src.pose.bones[source_name].matrix) @ source_rest.inverted()
    source_rotation = source_delta.to_quaternion().normalized()
    if source_rotation.w < 0.0:
        source_rotation.negate()
    chain_frame = Vector((0.0, 1.0, 0.0)).rotation_difference(src_chain.normalized())
    chain_rotation = chain_frame.inverted() @ source_rotation @ chain_frame
    hips_twist = chain_rotation.to_swing_twist("Y")[1]
    hips_twist = (hips_twist + pi) % (2.0 * pi) - pi
    orient = Quaternion(desired.normalized(), hips_twist).to_matrix() @ orient
```

不把这段放到 CURRENT 或全 role 公共出口。保留 rest、parent-relative basis、rotation_quaternion 写入及紧接的 bpy.context.view_layer.update()，让子骨看见新的父旋转，再按现有算法重求解。原有缺失/退化链 continue 不改；不新增事后 hips keyframe 修饰器。

**子骨局部 quaternion 变化是必要父级补偿，明确允许。** spine、thigh_l、thigh_r 继续按自身 target bind 与来源方向求解，用新的局部旋转抵消父级变化。它们没有新增 source roll 迁移公式。禁止冻结它们的旧局部 quaternion；旧实测冻结后手臂方向大幅失配。

### 3. 合成 RED -> 最小 GREEN -> 回归

新增测试名：**test_rest_hips_yaw_preserves_arm_chain**，文件 tests/run_retarget_test.py。不得加载 GLB/FBX 或使用用户绝对资源路径。

- 用现有 build_biped 创建两个全新 synthetic armatures；包含 hips、spine、chest、头、双肩、upperarm_l -> forearm_l -> hand_l 及身体轴需要的右臂，不能只建 hips/spine。可使用不同 arm_roll 保证仍保留 target arm bind roll。建立 fixture 之外不得进入 Edit Mode 改目标 rest。
- 用来源自身 rest 旋转把 +40° body-up armature-space delta 换算为来源 hips 局部 quaternion，再制作 Action。不是复制来源 quaternion 到目标。对象为 identity、同一身体轴；目标先记 rest，不加手部关键帧、不启用 IK。
- 使用 REST / KEEP / foot_ik=False / hand_ik=False 经正常 bake 路径，并在实际 baked Action 上采样。
- yaw 用本文件的 rest-body-left 度量，断言 abs(wrap(source yaw - target yaw)) < 2°。
- 上臂 chain 用 pose head 的 upperarm_l -> forearm_l，归一化后在 armature space 比较，断言 abs(dot - 1) < 1.5e-3；不得使用 bone tail 或 matrix_world。补充 forearm_l -> hand_l 同门，双手 quaternion identity-angle < 1e-4 rad。
- 在未补丁版本选中此测试，selected > 0，确认失败来自 lost yaw，不是导入错误；随后只加 A，重跑同一测试 GREEN，再跑相关与全量回归。不允许 monkeypatch 在正式产品测试中掩盖缺陷。

**现有回归合同冲突已发现：** test_metarig_swing_limits:1412-1413 明确要求第一跳 yaw < 20°、第二跳 < 5°，是在测试旧版丢 yaw。REST hips 新规则同样作用于两跳，不能偷偷跳过 metarig 来保住这两条旧断言。本修订不授权删除、skip、松门或改动既有测试；在用户单独批准更新旧行为预期之前，全量回归合同为 **Blocked**。可以实施精确补丁与新增测试，但不得宣布全回归 GREEN 或正式完成。双手 identity、链方向、CURRENT、same-clip 与 rest 未变这些旧门继续保留。

### 4. 编译前检查与执行入口

Python 插件无 C++ 构建项。先核对 Blender 5.1.2、Quaternion.to_swing_twist('Y')、Quaternion(axis, angle)、pi 导入、真实 role 名与 parent basis 顺序；用 compile 源码检查语法，避免 py_compile 在受保护目录写缓存。明确错误先修复，保留日志，不重复跑未修正版本。

正式 headless 回归入口：
```powershell
& 'C:\Program Files\Blender Foundation\Blender 5.1\blender.exe' --background --factory-startup --python-exit-code 1 --python 'H:\Blender_Plugin\tests\run_retarget_test.py'
```

聚焦测试使用项目现有加载/调用方式，确保真实函数被调用、selected > 0；不改 main 的既有测试列表来躲失败。处理上述回归合同冲突后再跑全量，不以退出码非零充当通过。

### 5. 手动真实资源验收与临时诊断清理

GLB/FBX 仍是手动集成检查，不是 unit test。完整 bake 0..52 后采样 1/20/31/37/52：
- source：H:\SErsiko_ExtactedTool\output\c0000_突刺_wp_a_0300.glb；target：C:\Users\chenshajie1\Downloads\body.FBX。
- a050_300000；REST、KEEP、两种 IK 关闭。实际链 Pelvis -> Spine 与 Bip01 Pelvis -> Bip01 Spine。
- CURRENT 另外确认保持原 _desired_orientation 路径与行为。保留已交付 same-clip 规则，不能重新自动挑别的 Action。

本次新增临时产品埋点、注册项、轮询、开关、依赖：无。只有插件外独立进程的内存 monkeypatch；已恢复原函数、进程自然结束。保留 H:\tmp\pelvis_sideways_cause_20261013 的测量 JSON、日志与重现脚本作为证据。后续 Cursor 若加临时诊断，先逐项登记，再仅移除本次新增且正式功能不依赖的调用点/注册/配置，清理后重跑聚焦、回归与真实 pair；不得批量清理用户文件。

效率记录：旧档读取输出被截断时只补读缺失范围；Windows apply_patch 包装器两次未正确传入多行参数，改为原生执行器参数后成功。首个 Blender 启动因脚本不存在退出 1，不是 RED；最终有效测量退出 0。未改公式重试；后续直接复用成功入口。

## 强制约束

- REST only；CURRENT 不加 yaw。仅 role == 'hips' 得到新增 theta；其余骨的算法不改，允许它们自动补偿父级。
- 禁止 B：绕 body_up 左乘会改变 hips 链方位；旧实测 frame 20 为 26.703212689°，不是 PASS。
- 不复制 matrix_basis、matrix_local 或来源绝对 orientation 到目标。不把 matrix_world 乘进 align。
- 不编辑现有目标 rest；不清 hand scale，不改手求解，不以两跳/骨名预设替代 yaw 修复。
- foot IK / hand IK 默认仍关闭。公共 API、配置、IK 和参考模式不扩大。
- 不执行 stash pop、宽泛 Git 回退、暂存、提交或推送；保留用户所有既有改动。
- 对缺失链沿用 continue；A 不证明所有姿势/180°退化分解的普适正确性。新 fixture 若暴露不满足门的情况，报告 Concern/Blocked，不发明第三公式。

## 验收标准

本次 fresh Runtime 证据：H:\tmp\pelvis_sideways_cause_20261013\measurement.json 与 probe.log；Blender 5.1.2 / ec6e62d40fa9；完整两次 bake，每次 53 帧，采样共 10 行；选中真实 Action 1 个。当前源码 retarget.py SHA256：d8d7eacdb2407ea4ccb6136d73865fdc8bc21343784fda3ca407285a24dd3d0b。本次插件仍为 1.7.0。

| 帧 | 基线 lost yaw ° | A lost yaw ° | A 髋链方向误差 ° | 四链相对基线最大变化 ° | 手 identity-angle rad | 新门 |
|---|---|---|---|---|---|---|
| 1 | -36.349079593 | -0.377490289 | 0.000016083 | 0.000077541 | 0 | PASS |
| 20 | -42.134817830 | -0.841489540 | 0.000016042 | 0.000111078 | 0 | PASS |
| 31 | -41.996057057 | -0.515359868 | 0.000012073 | 0.000062674 | 0 | PASS |
| 37 | -37.959831937 | -0.431008993 | 0.000012050 | 0.000140078 | 0 | PASS |
| 52 | -6.711136037 | -0.089974404 | 0.000017522 | 0.000062828 | 0 | PASS |

五帧全部要求：abs(lost yaw) < 2°；髋链在各自身体坐标中的 source-target 方向误差 < 0.05°；upperarm_l、forearm_l、thigh_l、spine 相对 unmodified bake 的 target 身体坐标方向变化均 < 0.05°；hand_l/hand_r quaternion identity-angle < 1e-4 rad。

A 最大 yaw 残差 0.841489540°，髋链方向误差最大 0.000017522°，四链相对基线最大变化 0.000140078°；双手始终 (1,0,0,0)。子骨局部 quaternion 变化 > 1e-4 不是失败。世界 dot < 1.5e-7 与 hand matrix_basis < 1e-7 不是本验收门：两者在未改基线已经失败，不能归咎 A。

证据分层：Static 已核对；Contract 依据官方规则明确；Process 退出 0；Runtime 是独立测量进程的 A 候选 PASS，非已部署产品；Build 不适用；正式产品 synthetic RED/GREEN、CURRENT/regression 与 Visual 均 NotRun；旧 metarig 回归合同 Blocked。只有后续磁盘补丁、版本 1.7.1、必要测试/合同解决、手动 pair 与清理后复验全部闭合，才能报告产品完成。

## 禁止事项

不得恢复旧版“只有 hips 局部 quaternion 能变”的门。不得将公式 A 换成 B、另造第三公式、事后修改已烘焙 hips、改世界轴或归零手 scale。不得修改手部或 limb source-roll 规则。不得删除旧回归、绕过冲突或把候选 Runtime PASS 写成产品修复完成。不得修改本轮受保护插件/测试；Cursor 后续实施按本文件明确范围进行，旧测试预期另需授权。
