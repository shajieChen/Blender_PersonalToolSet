# 重定向作业缓存与 modal 实施计划

> 执行者：Cursor。可使用 `executing-plans` 逐项执行；子代理仅做只读定位与核验，不承担代码修改。本计划不含提交步骤。

**Goal:** 缓存一次作业内稳定的分类、链末端和 rest 数据，主线程按约 16ms 切片，姿势及已交付 same-clip 结果不变。

**Architecture:** `__init__.py -> pipeline.py -> retarget.py`。`RetargetBakeJob` 拥有缓存、进度、临时 Action 与回滚状态；操作器拥有 TIMER 和界面状态。同步入口驱动同一个 Job，不注册计时器。

**Tech Stack:** Blender 5.1.2、Python、`bpy`、`mathutils`、`time.perf_counter`。版本目标 `(1, 6, 7)`。

设计依据：[本轮规格](../specs/2026-10-13-retarget-bake-cache-modal-design.md)。最终显示仍服从 [same-clip 修订](../specs/2026-10-13-retarget-same-clip-revision.md)。本计划取代旧 `2026-10-13-retarget-bake-responsiveness.md` 的实施任务；旧文件保留，里面的提交、更新删减、父矩阵递推和旧显示行为均不执行。

```text
RED 次数与基准 -> 最小缓存 GREEN -> 共用 Job -> modal/取消 -> 前台验收
                                                       -> 诊断清理后复验
```

## 目标

本轮实验已得到：全片段当前 bake 115.733s，仅缓存分类 8.467s；503 帧曲线完全一致。帧 1、20、37、52 的两侧角色图和 body columns 相同；独立全帧验证无角色、body 或 bake 内世界矩阵变化。实现必须保留一般输入的世界矩阵失效路径，不能因这份输入稳定就硬编码稳定。

剩余显式更新 5.722s，约占缓存实验剩余时间 68%。本计划仍保留原更新，因为总量已显著下降，父矩阵替代会扩大正确性风险。16ms 是帧边界检查预算，不是单帧硬上限；实验最大帧约 29.5ms。

## 修改范围

| 文件 | 唯一职责 |
|---|---|
| `H:\Blender_Plugin\humanoid_retarget\retarget.py` | `RetargetBakeCache`、`RetargetBakeJob`、缓存读写、帧步骤和成功/取消数据收尾 |
| `H:\Blender_Plugin\humanoid_retarget\pipeline.py` | 拆出同步导入/绑定准备，记录本次准备产生的对象和数据；保留同步包装的返回值 |
| `H:\Blender_Plugin\humanoid_retarget\__init__.py` | 三个操作器的 modal、进度、输入保护、Gizmo 开关与生命周期；版本号 |
| `H:\Blender_Plugin\humanoid_retarget\gizmos.py` | 仅在现有 `draw_bone_gizmos=False` 无法可靠短路时修改 |
| `H:\Blender_Plugin\tests\run_retarget_test.py` | 次数 RED/GREEN、float32 对照、同步/切片、取消与回归 |

不改 `classify.py`、`mapping.py`、`ik.py`、`autorig.py`；不新增仓库内 profile 脚本或基准文件。输入身份和复用结果放在作业内，不能借用 Gizmo 的跨绘制 `_ROLE_CACHE`。

## 实施步骤

### 1. 固定材料与验证入口

- [ ] 记录 Git 当前状态和上述五个文件的哈希，保留无关 dirty、deleted、untracked。不要暂存、回退或清理。
- [ ] 主执行者亲自读取本轮 spec、same-clip spec，以及即将改动的确切函数。已读未变化内容复用，只在证据冲突或代码变化时定向复读。
- [ ] 当前定位：`retarget.py:51` collect、`:87` 新 Action、`:135` body、`:197` chain end、`:233` anatomical、`:242` solve、`:443` bake、`:512` same-clip；`pipeline.py` 的三个 bake 包装；`__init__.py` 的三个重定向操作器；`gizmos.py` 的 `draw_callback`；测试的 `test_bake_displays_same_source_clip`、swing、split-parent 和 `main`。以执行时行号为准。
- [ ] 已有两项独立探子范围是旧探针定位与 live web 约束核验，均完成。实施时只有发现具体缺口才加探子；独立缺口一次并发派发，随后按适用规则等待收敛。禁止重派相同全仓检索。
- [ ] 检查实际 `Action.slots`、layer/strip/channelbag、`AnimData`、driver mute、modal TIMER 和 progress API。所有补丁先完成语法与 API 自查，再启动 Blender；遇到明确 API 错误先修正，保留日志，不重复运行未修正代码。

本项目没有 C++ 编译入口。目标验证命令是：

```powershell
& 'C:\Program Files\Blender Foundation\Blender 5.1\blender.exe' --background --factory-startup --python-exit-code 1 --python 'H:\Blender_Plugin\tests\run_retarget_test.py'
```

必须退出 0 且打印 `RETARGET_TEST_OK`。日志还要确认导入的是工作区插件；错误过滤器、selected=0、旧报告和脚本未到末尾都不算通过。

### 2. 先加入常数分类次数测试，得到 RED

仅改测试。在 `main()` 中调用下面测试一次，放在已有 same-clip 测试之后。它用显式 pairs，把自动映射准备的额外分类排除；patch **`retarget.classify_armature` 的调用绑定**，不能只 patch `classify.classify_armature` 后漏掉已导入的别名。

```python
def test_bake_classification_count_constant():
    import humanoid_retarget.retarget as retarget

    for end_frame in (10, 60):
        tag = "Classify" + str(end_frame)
        source_names = _role_names(tag + "S")
        target_names = _role_names(tag + "T")
        source = build_biped(tag + "Source", source_names)
        target = build_biped(tag + "Target", target_names, arm_roll=0.4)
        animate(source, source_names)
        if end_frame > 10:
            bone = source.pose.bones[source_names["upperarm_l"]]
            bone.keyframe_insert("rotation_euler", frame=end_frame)
        first = source.animation_data.action
        second = first.copy()
        second.name = tag + "Second"
        source["hr_actions"] = first.name + "\n" + second.name
        source.animation_data.use_nla = False
        actions = retarget.collect_actions(source)
        frames = sum(
            retarget._frame_range(action)[1] - retarget._frame_range(action)[0] + 1
            for action in actions
        )
        check(len(actions) == 2, tag + " selects two clips")
        check(frames == 2 * end_frame, tag + " selects the expected frames")
        pairs = [(role, source_names[role], target_names[role]) for role in source_names]
        original = retarget.classify_armature
        calls = []

        def counted(arm):
            calls.append(arm.as_pointer())
            return original(arm)

        retarget.classify_armature = counted
        try:
            _report, baked = retarget.bake_retarget(
                source, target, retarget.RetargetOptions(pairs=pairs)
            )
        finally:
            retarget.classify_armature = original
        print("CLASSIFY_COUNT", frames, len(calls), flush=True)
        check(len(baked) == 2, tag + " bakes both clips")
        check(
            calls.count(source.as_pointer()) == 1
            and calls.count(target.as_pointer()) == 1,
            "classification is constant per stable bake",
        )
    print("PASS bake classification count is constant")
```

- [ ] 运行命令，确认 20 帧 fixture 当前为 40 次，因最后的常数断言失败，而非构造或导入错误。第一 fixture 失败后第二 fixture 尚未执行，日志准确报告 selected=1，仍大于 0。
- [ ] GREEN 后两 fixture 都必须执行：20 与 120 帧各为 2 次。本轮外部探针已确认旧实现 20 帧=40 次，不能把实验 monkeypatch 称作插件已经 GREEN。
- [ ] 再加无显式 pairs 的测试。单独统计 `mapping.classify_armature` 的两次准备调用；稳定输入默认总分类不超过 4 次，并证明两个不同长度 fixture 不增长。`correct_deform_pairs` 的目标权重扫描仍为每 bake 一次，不纳入 classify 次数混淆。

### 3. 保存独立姿势基准，建立严格比较器

- [ ] 在改求解接入前，用固定名称、目标 roll=0.55 的双片段合成 fixture 保存原实现每帧、每根映射骨骼的 quaternion/location float32 原始位。片段 A 范围 1..5、B 范围 11..20，入口选择 B；动画角度沿用现有 same-clip 测试，B 不等于 A。基准生成脚本和完整输出仅放 TEMP；把固定预期值嵌入 `tests/run_retarget_test.py`，不要新增文件。
- [ ] 每行键为片段索引、帧、role，不把对象名称后缀或新 Action 名称当作数值差异。读取既有结果时绑定正确 Action 和 slot、关闭 NLA，再采样；读结果的函数不得重新 bake。
- [ ] 比较器采用下列转换。加入正例、一个分量改变的负例、四元数整体取反的负例。不得用 round 或方向点积代替。

```python
def pose_component_bits(values):
    import struct

    return tuple(struct.pack("<f", float(value)) for value in values)
```

- [ ] 保留原始基准，之后不得由新实现自动重写预期值。新同步入口和分帧 Job 两者都与这个独立基准比较。
- [ ] 继续执行既有 same-clip 四 fixture、hand identity、swing roll、split-parent、CURRENT/root/IK 测试。手的四元数和 `matrix_basis` identity 要直接检查，不能只测链方向。

### 4. 最小接入 `RetargetBakeCache`，得到 GREEN

缓存对象私有于一次调用，字段和读写点固定如下：

| API / 字段 | 填充位置 | 读取位置 |
|---|---|---|
| `RetargetBakeCache(src, tgt, pairs, options)` | 原胸部/蒙皮修正完成后 | 每帧 solve |
| `pairs`, `source_roles`, `target_roles` | 构造时；使用修正后 pairs | 清零、链起点、髋与插帧 |
| `source_chain_ends`, `target_chain_ends` | 构造时，逐 role 调用原 `_chain_end`，保留 None | posed 链每帧只读取 head 差；rest 链读取缓存 |
| `ordered_pairs` | 构造时，原目标 depth 与 `_BODY_ROLE_ORDER` 排序，保留稳定排序 | 原求解循环 |
| `target_rest_chains`, `target_rest_orientations`, `target_rest_rotations`, `parent_rest_rotations` | 构造时，沿用原转换和 None/小向量判断 | 原 swing 和 basis 算式 |
| `references` | 构造时，逐 pair 调原 `_reference_for`；拷贝存储值 | 每帧髋位移；CURRENT 的参考保持固定 |
| `source_anatomical_roles`, `target_anatomical_roles`, `source_body`, `target_body` | 首次实际 `frame_set` + 原更新后 | `_apply_body_orientations` |
| `source_world`, `target_world` | 同次分类后复制 | 每帧相等检查与分类失效 |
| `refresh_body_frames(src, tgt)` | 每帧原 `frame_set`/update 之后、solve 之前 | 仅首次或对应侧矩阵变化才调用原 `_anatomical_roles` 与 `_body_matrix` |
| `validate_input_identity(src, tgt, pairs)` | 保存入口身份，每个 slice 起始检查 | 身份变更抛 `RetargetError`，进入取消，不继续混合数据 |

- [ ] 给 `_apply_body_orientations` 增加私有可选 `cache=None`。无缓存分支保留当前公式，供测试对照；有缓存分支只替换准备结果和链末端查找，不改变四元数求解。
- [ ] `_chain_vector` 的 posed 路径仍在当前帧读 `src.pose.bones` 的起点/末端 head，并做原相减和长度判断。不要缓存 posed vector。
- [ ] 保留清零的 pair 顺序、父优先排序、全部更新、髋位移、IK 和逐骨两次 `keyframe_insert`。不要重排矩阵乘法或预先合并矩阵。CURRENT 每帧源 pose 矩阵和目标父矩阵仍现场读取。
- [ ] 身高比例及 KEEP/IN_PLACE 按原 prepare 位置计算一次；`_hips_translation` 仍每帧读实际 `matrix_world`。只把原先每帧重复的固定参考数据改为缓存读取。
- [ ] 初次 body 分类必须在目标原动画隔离、第一帧求值之后。不能在未求值的 invoke 中冻结角色图。
- [ ] 跑次数测试和 float32/既有回归；先完成最小缓存 GREEN，再拆调度。

失效边界：两侧对象/data 身份、骨骼名称/层级/rest、绑定 mesh 及 data 身份、顶点组、weights、mapping 改变均使旧缓存无效。普通 UI 编辑在作业期间被阻止；身份检查不能证明原地权重没被外部脚本修改，不每帧扫描 133825 顶点来“验证缓存”。禁止并发外部写输入。新调用永远重新构造缓存。世界矩阵动画则刷新对应 body 分类，允许分类次数随这些真实变化增加；次数测试只约束稳定 fixture。

### 5. 抽出共同的 `RetargetBakeJob`

只在 `retarget.py` 增加具体作业，不引入接口、工厂、注册表或 catch-all Context。

| 方法 | 明确行为 |
|---|---|
| `__init__(src, tgt, options=None)` | 记录借用对象引用和 options；初始化 actions/created_actions/baked/baked_sources 为空、action_index/completed_frames 为 0、frame/cache/入口快照为 None、终态标记为 False；不修改场景，不建 Action |
| `prepare()` | 原参数/参考校验、保存入口状态、修正 pairs、收集全部 actions、范围及总帧数、比例、创建缓存；无动画即原错误 |
| `_begin_action()` | 原来源 Action/slot 规则；入口 Action 使用保存的入口 slot；创建并立即记录目标 Action |
| `_bake_frame()` | 原完整帧体：frame_set、更新、缓存刷新、朝向、更新、髋、更新、IK、更新、原 keyframe_insert |
| `step(budget_s=0.016)` | 处理完整帧直到预算用完；完成所有片段返回 True；`None` 表示同步耗尽；空预算仍至少处理一帧 |
| `finish()` | 只允许所有帧成功后调用；暂存既有 same-clip tail、NLA、slots、元数据、摘要与返回值；提交前仍可取消 |
| `accept_result()` | 成功结果与调用方尾部均完成后，删除已隔离的旧目标 tracks/drivers，释放入口备份与缓存，标记已交付；同步调用，不能 yield |
| `cancel()` | 未成功提交时撤销本次改动，删除本次 Action 并恢复入口；可重复调用，不复用已移除 RNA 引用 |

作业保存 `created_actions`、`baked`、`baked_sources` 三者区别。`created_actions` 包括当前半成品；完成一段后才同时 append 到后两列表。修改 `_new_target_action` 的私有调用，使 Action 在 `bpy.data.actions.new` 后、创建 slot 前立即登记；slot 创建失败也能清理。

在模块顶部添加 `import time`。时间片循环的边界固定为：

```python
def step(self, budget_s=0.016):
    started = time.perf_counter()
    while self.action_index < len(self.actions):
        self._bake_frame()
        self.completed_frames += 1
        self.frame += 1
        if self.frame > self.frame_end:
            self.baked.append((self.target_action, self.frame_start, self.frame_end))
            self.baked_sources.append(self.actions[self.action_index])
            self.action_index += 1
            if self.action_index == len(self.actions):
                return True
            if budget_s is not None and time.perf_counter() - started >= budget_s:
                self.frame = None
                return False
            self._begin_action()
        if budget_s is not None and time.perf_counter() - started >= budget_s:
            return False
    return True
```

`_bake_frame()` 在 `self.frame is None` 时先执行 `_begin_action()`。这样预算在片段末尾耗尽时不会提前修改下一片段。最后一帧返回 True，不额外产生一拍。

同步入口必须覆盖 prepare、step 和 finish 的异常，清理后重新抛原异常：

```python
def bake_retarget(src, tgt, options=None):
    job = RetargetBakeJob(src, tgt, options)
    try:
        job.prepare()
        while not job.step(budget_s=None):
            pass
        result = job.finish()
        job.accept_result()
        return result
    except Exception:
        job.cancel()
        raise
```

- [ ] 在成功 `finish` 中搬运当前 `bake_retarget` 的 same-clip 尾部，保留 `selected_index` 的入口对象匹配、兜底 0、来源 slot、排除显示片段的 NLA 列表、单段时间轴与起始帧求值的赋值顺序。不要复用旧计划的第一段/最后一段尾部。
- [ ] 测试 Job 每次 `step(0.0)` 只完成一帧，完整跑完与同步及独立原基准相同；用 0.016 再测一次。不要从插帧中间 yield。
- [ ] 同步包装的 summary 和 Action 列表顺序不变，三条 pipeline 原返回值不变。

### 6. 做可取消的数据事务，再接 UI

入口快照在任何修改前保存：来源/目标是否原有 AnimData、活动 Action、slot、`use_nla`、目标 Action 混合/外推/影响值、driver mute、原 NLA track 状态、所有会改的 pose basis/rotation mode；scene 的 start/end/current/subframe；原 `hr_actions`、`hr_retarget_from` 等属性是否存在和值；options 原 `resolved_pairs`。Action 引用是借用，不能删除旧 Action。

- [ ] 不在作业准备时不可逆 `target.animation_data_clear()`。保留旧 AnimData、NLA 和 driver 数据至成功；采样时替换活动 Action、关闭旧 NLA 求值、暂时 mute 原 driver，并设置与原新建 AnimData 相同的活动 Action 混合默认值。保存每个被改值，以便取消原地恢复。目标已有 NLA tweak mode 时准备前报错，不能在作业中切换 tweak mode。
- [ ] 成功尾部先建立本次其余 Action 的新 NLA tracks 并登记身份，完成 Action/slot、timeline、元数据和摘要。旧 tracks 此时保留但隔离，尚未交付。同步包装或 UI 尾部成功后调用 `accept_result()`，才删除旧 tracks/drivers，使最终结果等价于原先 clear 后的状态。提交前的异常可移除新 tracks、恢复旧动画。不要先删旧 tracks，再尝试构造新 strips。
- [ ] 补测有旧 Action/NLA/driver 的目标：缓存前原实现基准与新成功结果一致；取消必须保留旧数据块身份、旧轨道和 driver 配置。显式验证 mute 隔离不会改变原清除语义；此测试不过不能用较弱的默认 fixture 宣告通过。
- [ ] `cancel` 先解除新 Action/strip 引用，再仅按 `created_actions` 中仍存在的身份删除一次，含 fake user；不能用 `users==0` 跳过半成品，也不能两次 remove 同一引用。恢复入口 Action/slots、临时改动值和 pose，恢复 scene 范围/帧，清空缓存和本次列表。
- [ ] 保存开始时的选择、active object、模式、集合关联。`pipeline.py` 拆出 `prepare_target_import(path, source)` 和 `prepare_selected_meshes(source, meshes)`，保持当前导入/可用骨架/自动绑定逻辑和 note 文本。各准备记录同时列出返回目标、auto 标记、创建对象/数据块和恢复所需状态；同步包装仍完成 bake 并返回原元组。
- [ ] 导入前记录各类数据块身份差集；导入异常也收集本次已创建对象、Action、mesh、armature、collection/material 等。取消只清理本次新增且未被原对象依赖的记录，不能全局清孤儿或按名称匹配。来源导入的原 Action 不属于本次目标作业。
- [ ] 选中网格自动绑定前保存原 parent、parent inverse、world transform、集合、顶点组顺序/锁定和 modifier 状态。保存原 mesh data，绑定在其作业副本上进行；取消重新挂原 data 并恢复原组索引/绑定，删除仅本次副本与骨架；成功释放仅作业所有的备份。共享 mesh data 和已有绑定也必须覆盖，不能删除用户原网格或权重。
- [ ] 注入第一段中途、第二段中途、slot 创建失败和 finish 提交前异常，检查 Actions 集合及所有保存值恢复。再验证 cancel 调两次安全、成功后 cancel 不删除已交付结果。prepare 失败同样清理，不依赖 CANCELLED 自动撤回。

这部分是 modal 取消必需的生命周期工作，不扩展姿势数学。无法完整恢复的情形标为 Blocked，并保留失败收据，不能吞异常后返回 CANCELLED 冒充恢复成功。

### 7. 三个操作器进入 modal

`HR_OT_import_target`、`HR_OT_retarget_existing`、`HR_OT_retarget_selected_mesh` 继续是各自的一步 `REGISTER/UNDO` 操作；使用少量业务 free functions 复用开始、推进和 UI 释放，不新增多层基类。

- [ ] `invoke` 启动同一作业入口。导入目标的 invoke 无可用路径时仍走现有文件选择器；确认后的 execute 同步准备目标，然后进入 `_begin_bake(operator, context, job)`。已有目标与选中网格的 invoke 直接准备并进入它。背景 execute 驱动同步 Job，不注册 TIMER；前台 execute 使用同一 modal 启动函数。
- [ ] `_begin_bake` 保存 owner scene/window/window_manager、`draw_bone_gizmos` 原值和所有 UI 恢复状态；设 False；把 Job 存入 `operator._job`；注册 `event_timer_add(0.016, window=context.window)`、`modal_handler_add`、`progress_begin(0,total_frames)`。启动任一环节失败，都取消已准备数据并释放已取得资源。
- [ ] 用一个明确命名的 `_active_bake_operator` 借用活动操作器引用，仅负责防重入和注销清理。它不保存分类数据，不成为通用作业注册表；在所有终态清空。需要 global 的函数在第一次引用前声明，避免旧草案的 Python 语法错误。
- [ ] modal 的 Esc/PRESS 先走 `_cancel_bake` 再返回 CANCELLED；只响应 `event.type == 'TIMER' and event.timer == self._timer`；每拍调用 `job.step(0.016)`，按实际 completed/total 更新 progress。每 0.25s 写一次动作/帧状态并 tag_redraw。
- [ ] 不相关 TIMER 不推进作业。其他事件仅允许视图导航和重绘通过；编辑、播放、帧跳转、导入、导出、参考捕获、mapping/preset、对象或权重改变、第二次 bake 均被阻止。面板禁用输入区；相应 operator poll/execute 及 settings update 回调也检查活动作业，不能只靠按钮变灰。
- [ ] 用户拖动 frame/source_action/stand layout 等不能在 slice 之间改变求解输入。外部 Python 并发原地编辑不在支持范围；轻量身份检测触发时取消并提示重启。scene/window 切换或对象丢失同样取消。
- [ ] 所有 step、finish 和现有 UI 成功尾部均置于异常处理范围内。finish 先暂存既有 same-clip 数据尾部；成功恢复 Gizmo，再按原三个操作器分别执行 filepath、target pointer、show_bones、mapping、status 和 report 尾部。事先保存这些 settings 与原两侧 world transform，尾部失败也恢复；完成后才 `job.accept_result()` 并返回 FINISHED。提交前核验旧 tracks/drivers 仍属可编辑目标且删除引用有效；提交过程不 yield。若不可逆提交异常无法恢复，明确报告 Blocked，不声称 CANCELLED 已完成回滚。
- [ ] 注意 `settings.target` 回调会改变站位；只在全部烘焙完成后调用它，与当前顺序一致。活动操作器进入成功收尾阶段时允许自己的这些更新；恢复入口快照时暂时抑制回调，并最后恢复 world transform。不得在该回调中重新指定动作、timeline 或提前预览。
- [ ] `_close_bake` 只移除本操作器 TIMER、结束其 progress、恢复保存的 Gizmo 值、清空活动引用，并可重复调用。不能无条件恢复 Gizmo=True。
- [ ] 在 `unregister` 及加载新文件前取消活动操作器，再清理 draw handler/属性。新增生命周期 handler 必须配对注册/移除、避免重复注册，不把这些 handler 留成临时探针。
- [ ] 当前 `draw_callback` 已在求值读取之前检查 `settings.draw_bone_gizmos`，因此优先保持 `gizmos.py` 无 diff。只有无法保证暂停时才加明确暂停入口及配对恢复测试。
- [ ] 版本改为 `(1, 6, 7)`。

成功保留一个 undo step：只保留操作器 `REGISTER/UNDO`，不逐帧 `undo_push`，不禁用 global undo。导入和自动绑定的嵌套 operator 可能影响撤销栈，必须用前台单次 Ctrl+Z 核验并修正嵌套 undo 行为；不能只从 bl_options 推断通过。

### 8. 验证、效率复盘和清理

- [ ] 先做 Python 语法/API 自查和缓存计数聚焦，再跑一次整套后台回归。新差异、失败或未闭合风险才触发重复，不无目的多轮完整运行。
- [ ] 全输入重新测 import、prepare/cache fill、frame loop、finish，确认 10 段/503 帧/19 pairs。把稳定分类次数、矩阵刷新次数、slice/单帧最大值、总耗时记入外部收据。不要渲染或截图混入 bake 计时。
- [ ] 重新比较所有片段、每帧 quaternion/location 原始位及 Action slots/NLA，检查双手 identity 和既有 same-clip。当前显示片段必须是入口对，不使用全片段范围并集。
- [ ] Blender 前台测试三个按钮：进度可见，烘焙能重绘；Esc 在第一段半帧序列、跨片段后、最后一帧前都不留下新 Action；成功一次 Ctrl+Z 恢复点击前。Gizmo 原开/关分别测试；注销、异常、场景切换和连续两次作业不残留 timer 或缓存。
- [ ] 临时诊断清单：TEMP 的计时脚本、计数 wrapper、矩阵/role 采样、异常注入、slice 统计及任何诊断开关/注册/调用。保存必要日志/JSON后，仅移除本次临时代码和依赖；正式测试 monkeypatch 保留并用 finally 恢复。正式 modal TIMER 与 progress 是功能，不当作临时轮询删除。
- [ ] 清理后核对差异、语法、聚焦和全套回归；前台运行路径若清理有变，重做响应/Esc/Undo。未清理或未复验不得宣告实施完成。
- [ ] 若重复读取、追加探子批次或出现可避免 API 错误，在实施进度简记原因及避免措施。不能以提效跳过 RED/GREEN、源码阅读或前台验收。

## 强制约束

- 稳定 cache 的 owner 是 Job；TIMER、progress、Gizmo 和活动引用的 owner 是操作器；均只在主线程使用。依赖不得反向。
- `_chain_end`、swing、手 identity、root/reference/IK 的语义不变；复用固定值不能改变运算顺序或四元数符号。
- 不删原 update，不替换 `keyframe_insert` 为 `foreach_set`，不加父矩阵递推。
- 不把 bpy 搬到线程。依据是本轮重开的 [5.1.2 threading 文档](https://raw.githubusercontent.com/blender/blender/v5.1.2/doc/python_api/rst/info_gotchas_threading.rst)；modal 使用 [5.1.2 官方模板](https://raw.githubusercontent.com/blender/blender/v5.1.2/scripts/templates_py/operator_modal_timer.py) 的事件路径，solve 仍在主线程。
- CANCELLED 没有自动 undo，必须先完成本作业回滚。旧目标动画状态与新建半成品 Action 不能遗漏。
- 不改源码注释、不新增生成代码的任何注释；解释放在文档。最小语义差异，保留原布局和名称。

未来变化检查：增加第三片段只改变 actions 输入；增加世界变换动画只触发 body 缓存刷新；增加后台批处理仍使用同步 Job。三种变化都不需要新接口或 UI 依赖进入求解模块。

## 验收标准

| 门槛 | 必须得到的证据 |
|---|---|
| 次数 RED | selected > 0，20 帧旧实现 40 次，明确常数断言失败 |
| 缓存 GREEN | 20/120 帧显式 pairs 均 2 次；自动映射准备额外调用分开记录 |
| 数值 | 独立旧基准与新同步、切片逐位一致；所有片段、hand identity、slots/NLA、same-clip 通过 |
| 回归 | 全脚本退出 0，`RETARGET_TEST_OK`，新增测试确实执行 |
| Process/Runtime | Blender 5.1.2、工作区路径、真实输入、自然退出、缓存填充和循环分段收据 |
| UI/Visual | 前台重绘和进度；Esc 恢复原状态；一次 undo；原 Gizmo 开关恢复 |
| 生命周期 | 准备/中途/finish 前错误、连续作业、注销/加载、半成品 Action 清理通过 |
| 收尾 | 临时诊断清单清零，保留正式测试与收据，清理后复验通过 |

本轮已验证的是旧实现和实验缓存的后台对照；实施代码、modal、前台 Undo/Esc、完整新增回归仍 **NotRun**。不能把设计交付记成插件已完成。

## 禁止事项

不执行任何 commit、push、暂存、回退、stash 或宽泛清理。保留旧文档和已交付 same-clip。不新增全局缓存、线程、进程、foreach_set、父矩阵替代或无关重构。不把背景测量替代前台验收。

仅给实施者的安装提示：代码和验证完成后，将**本次实际修改的 addon 文件**按字节复制到以下三个现有目录；不复制 tests/docs，不覆盖未改文件。记录目标版本及来源哈希，再重启对应 Blender 验证加载路径。**本轮不执行复制。**

- `C:\Users\chenshajie1\AppData\Roaming\Blender Foundation\Blender\5.1\scripts\addons\humanoid_retarget`
- `C:\Users\chenshajie1\AppData\Roaming\Blender Foundation\Blender\5.2\scripts\addons\humanoid_retarget`
- `H:\Blender\5.2.1\portable\scripts\addons\humanoid_retarget`
