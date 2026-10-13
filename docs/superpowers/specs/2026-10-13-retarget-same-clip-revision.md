# 重定向烘焙后显示同一片段：第 3 轮修订

日期：2026-10-13。状态：修订规格，尚未实施。

```text
bake_retarget 入口时的来源 Action
  -> 查找其成功烘焙的目标 Action
  -> 未找到则使用第一对成功烘焙的 Action
  -> 来源与目标同时赋值
  -> 时间轴只显示该片段，并跳到起始帧
```

## 目标

烘焙全部可烘焙片段后，来源和目标显示同一逻辑片段。优先使用调用 `bake_retarget` 时来源骨架已经绑定的 Action；该 Action 未进入成功烘焙结果时，使用第一对成功烘焙的来源与目标 Action。

`scene.frame_start`、`scene.frame_end` 使用该片段的整数范围，`scene.frame_current` 跳到该片段起始帧。禁止使用全部片段的范围并集，也不保留烘焙循环的最后一帧。

本轮沿用用户已核验的事实，不重新测量：

- 当前来源停在最后收集的 `a050_305001`，目标显示第一段 `Bip01_a050_300000`。第 37 帧比较的是不同片段：`upperarm_l` 链 dot 为 0.518，夹角 58.8 度；`thigh_l` 为 0.933，夹角 21.1 度。这是视口不一致的原因。
- 静音 NLA 后求值方向差为 0。
- 两骨架显示同一片段时，`upperarm_l`、`forearm_l`、`thigh_l`、`spine` 在帧 1、20、37、52 均满足 `abs(dot - 1) < 1.5e-7`。
- 双手保持 identity。本轮不修改手部或 swing 数学。

## 修改范围

后续实施只需修改：

| 文件 | 职责 |
|---|---|
| `humanoid_retarget/retarget.py` | 在 `bake_retarget` 保存入口 Action/slot，记录来源与烘焙结果的对应关系，修改成功收尾 |
| `tests/run_retarget_test.py` | 新增合成双 Action 回归，并在 `main()` 中调用 |

本次评审只写本文件，不修改上述代码。

当前依赖为 `__init__.py -> pipeline.py -> retarget.py`。`load_target_and_retarget`、`retarget_existing`、`retarget_selected_meshes` 已调用同一个 `bake_retarget`，且返回后没有重新指定 Action 或时间轴。无需修改这些调用者或面板回调。

保留 `collect_actions` 的收集、去重、过滤和顺序；保留 `bake_retarget` 的参数、摘要和返回值。返回的 Action 列表仍按烘焙顺序排列，不把显示片段移到列表首位。

本规格替换旧响应性设计中“来源停在最后一段、目标选第一段、时间轴保持原规则”的要求，以及相关场景帧范围不变式。缓存、modal 和性能优化不属于本轮实施范围。当前源码没有 `RetargetBakeJob`，本轮不新增该类。

## 实施步骤

### 1. 保存入口选择并记录配对

在 `bake_retarget` 的来源、目标及同对象校验之后，且在任何 `_assign_action(src, action)` 之前保存：

```python
source_anim = src.animation_data
source_action = source_anim.action if source_anim else None
source_slot = getattr(source_anim, "action_slot", None) if source_anim else None
```

以 Action 数据块对象匹配，不读取下拉框文本，不从目标 Action 名称反推来源。Blender 自动添加名称后缀不会影响对应关系。

现有 `baked = []` 旁增加 `baked_sources = []`。保留 `baked` 的 `(target_action, start, end)` 结构。在每段所有帧成功写入后，紧接现有 `baked.append((target_action, start, end))` 执行 `baked_sources.append(action)`。两列表长度和索引必须对应。

循环内仍先调用 `_assign_action(src, action)`。若 `action == source_action` 且 `source_slot is not None`，立即执行 `src.animation_data.action_slot = source_slot`，然后才求值和采样。这样入口 Action 的有效 slot 与烘焙采样、最终显示一致；其他 Action 继续使用现有 slot 选择规则。

### 2. 替换成功收尾，严格遵守赋值顺序

将现有 `if baked:` 块替换为以下内容。`try/finally` 中恢复 `original_frame` 的现有行为保留；成功收尾随后设置最终片段和帧。

```python
if baked:
    selected_index = next(
        (index for index, action in enumerate(baked_sources) if action == source_action),
        0,
    )
    selected_source = baked_sources[selected_index]
    selected_target, start, end = baked[selected_index]
    _assign_action(src, selected_source)
    if selected_source == source_action and source_slot is not None:
        src.animation_data.action_slot = source_slot
    src.animation_data.use_nla = False
    _stash_nla(tgt, [
        action for index, (action, _start, _end) in enumerate(baked)
        if index != selected_index
    ])
    _assign_action(tgt, selected_target)
    scene.frame_start = start
    scene.frame_end = end
    scene.frame_set(start)
```

顺序固定为：选择配对 → 来源 Action/slot → 来源 `use_nla = False` → 保存目标其余片段的 NLA → 目标 Action/slot → 单片段范围 → `scene.frame_set(start)`。最终帧求值发生在两个骨架都绑定正确片段之后。

范围来自该段烘焙时调用 `_frame_range(action)` 得到的 `start/end`，整数截取、末帧取整和最小一帧规则均不变。此处不调用 `preview_action`，因为它会在目标完成赋值之前设置帧，并重新选择来源 slot。`preview_action` 本身保持不变。

`_stash_nla` 函数保持不变；只修改传入的列表。当前显示片段使用活动 Action，其余每个烘焙片段保留一条 NLA strip，顺序沿用烘焙顺序。选择第二段时，第一段必须进入 NLA，不能继续传入固定的 `baked[1:]`。

保留 `_new_target_action` 的 `use_fake_user = True`、目标 slot 创建规则和命名规则；保留 `_stash_nla` 的 strip slot 赋值和目标 `use_nla = False`。`tgt["hr_actions"]` 仍包含全部烘焙 Action，顺序不变；`hr_retarget_from` 和返回值不变。

### 3. 加入合成回归，先失败再通过

在 `tests/run_retarget_test.py` 新增 `test_bake_displays_same_source_clip()`，放在 `test_source_clip_picker()` 之前定义，并在 `main()` 中调用一次。测试内部逐一执行下表四个独立 fixture；每个 fixture 只创建两个来源 Action，不导入大 glTF。

复用 `_role_names`、`build_biped`、`check`，在测试函数内从 `humanoid_retarget.retarget` 导入 `collect_actions`。来源 roll 为 0，目标 roll 为 0.55，scale 均为 1。构建后切回 OBJECT 模式，用 `pairs = [(role, source_names[role], target_names[role]) for role in source_names]` 构造 `RetargetOptions(pairs=pairs)`，IK 保持关闭。

创建 `SameClip_A`、`SameClip_B`，每个 Action 创建一个 OBJECT slot，名称为来源对象名；沿用 `_new_target_action` 的两种 `slots.new` 调用兼容写法。分别将 Action 和 slot 绑定到来源后插帧，并设 `use_fake_user = True`。

非空 A 在帧 1、5 插帧；非空 B 在帧 11、20 插帧。每帧为 `upperarm_l`、`forearm_l`、`thigh_l`、`spine` 写入 `rotation_euler`，模式为 XYZ。A 的角度依次为 `(0.2, 0, 0)`、`(0.1, 0, 0)`、`(0.15, 0, 0)`、`(0.1, 0, 0)`；B 依次为 `(-0.6, 0, 0)`、`(-0.3, 0, 0)`、`(-0.35, 0, 0)`、`(-0.2, 0, 0)`。两端使用相同值，避免插值影响。髋位移为零；不向双手插入来源动画。

每次令 `source["hr_actions"] = A.name + "\n" + B.name`，显式设置入口 Action 和 slot，关闭来源 NLA，并将场景设为范围 0..100、当前帧 99，再调用 `bake_retarget`。

| fixture | 两个 Action | 入口来源 Action | 成功后显示 | 预期场景 `(start, end, current)` |
|---|---|---|---|---|
| A 当前选中 | A、B 均非空 | A | 来源 A、目标 `baked[0]` | `(1, 5, 1)` |
| B 当前选中 | A、B 均非空 | B | 来源 B、目标 `baked[1]` | `(11, 20, 11)` |
| 当前选择不可烘焙 | A 非空、B 空 | B | 来源 A、目标 `baked[0]` | `(1, 5, 1)` |
| 当前没有活动 Action | A、B 均非空 | `None` | 来源 A、目标 `baked[0]` | `(1, 5, 1)` |

空 B 只创建 Action/slot，不插入任何曲线，并用 `check(B.is_empty, "fallback fixture B is empty")` 确认 fixture。入口为 `None` 时，创建动画数据后将 `animation_data.action = None`。收集仍通过 `hr_actions` 找到 A、B。

每个 fixture 必须检查：

1. `collect_actions(source)` 的顺序与有效片段数量符合 fixture，排除测试未覆盖双片段的假通过。
2. `baked` 长度正确；返回顺序和 `target["hr_actions"]` 顺序一致。
3. 返回后立即检查来源活动 Action、目标对应活动 Action、目标 `action_slot == selected_target.slots[0]`，以及三个场景帧值。显示入口 Action 时，来源 slot 必须等于入口保存的 slot；兜底到 A 时，必须等于 `A.slots[0]`，不能恢复空 B 的 slot。采样前不能主动修正 Action 或范围。
4. 双方 `animation_data.use_nla` 均为 False；每个烘焙 Action 的 fake user 为 True。其余片段恰好各有一条目标 strip，`strip.action` 与返回 Action 对象一致，`strip.action_slot == strip.action.slots[0]`；当前显示片段不重复加入 strip。
5. 在显示片段的起始帧和末帧调用 `scene.frame_set`、`view_layer.update`，比较四条链方向，要求 `abs(dot - 1) < 1.5e-7`。链方向使用世界空间的关节 head 差：upperarm→forearm、forearm→hand、thigh→shin、spine→chest；不使用 `bone_dir` 的 head→tail 代替链末端。
6. 两个目标 hand 的 `matrix_basis` 与 identity 的逐元素最大误差小于 `1e-7`。采样完回到显示片段起始帧，再核对三个场景帧值。

RED：先只加测试，运行未修改的烘焙实现。A fixture 应因来源仍绑定 B 失败；B fixture 应因目标绑定 `baked[0]`、范围为 1..20 失败。失败必须归因到这些断言，不能以导入错误或 fixture 错误代替。

GREEN：实施本规格的最小修改，再运行全部 fixture 和现有回归。新增测试打印 `PASS bake displays the same source clip`，整套脚本最后打印 `RETARGET_TEST_OK`，进程退出码为 0。

执行命令：

```powershell
& 'C:\Program Files\Blender Foundation\Blender 5.1\blender.exe' --background --python 'H:\Blender_Plugin\tests\run_retarget_test.py'
```

## 强制约束

- swing 数学、链末端选择规则和 hand identity 全部不变。不得修改 `_apply_body_orientations`、`_chain_end`、`_chain_vector`、`_desired_orientation` 或手部求解。
- 不修改参考姿势、髋位移、根运动、IK、插帧、插值、rest、逐骨求值或烘焙范围；仍烘焙全部收集到的有效 Action。
- 本地 `source_action`、`source_slot`、`baked_sources` 只在本次调用存活，借用 Blender 数据块引用，不新增全局状态、注册项或公共 API。
- 当前空 Action 被 `collect_actions` 过滤，因此采用第一对成功结果。实际烘焙异常仍向外传播；不吞异常、不跳过失败 Action、不把部分结果宣告成功。没有任何有效来源时保留现有 `RetargetError`。
- 不扩展失败回滚；保留现有 `finally` 的场景帧恢复路径。单片段显示收尾只用于成功路径。

推荐直接修改当前函数收尾。只恢复来源 Action 会留下目标与时间轴错误；强制双方显示第一段会丢失入口选择；按名称猜配对会受重命名影响。因此均不采用。

未来增加第三段、改变目标命名、调整片段收集顺序时，只影响输入或命名，不需增加公共接口。对象配对和“入口优先、第一成功段兜底”规则保持稳定。

## 验收标准

- 四个合成 fixture 全部执行，非空双片段 fixture 必须得到两个烘焙结果；RED 可归因，GREEN 退出码为 0。
- 两骨架显示入口片段或第一成功片段，三个场景帧值只跟随该片段。
- 其余目标 Action 的 NLA、fake user、slots、列表顺序均满足上述断言。
- 现有 `test_swing_preserves_target_roll`、`test_split_parent_orientation`、`test_mapping_root_reference_and_ik` 和 `test_source_clip_picker` 全部通过；整套测试打印 `RETARGET_TEST_OK`。
- 修改前已读材料：`retarget.py` 的收集、赋值、slot、NLA、范围和烘焙函数；测试的骨架构建、片段切换、swing 和 `main()`；`pipeline.py` 与操作器的调用收尾；旧响应性规格的相关约束。当前源码优先，同任务未变化内容直接复用。
- 本轮无需探子批次；读取范围已知且局部。后续实施先核对 Blender 5.1 的 Action/slot 类型和插帧入口，再运行上述后台命令；这是 Python 插件，无 C++ 编译入口。遇到明确 API 错误先修正，不重复运行未修正代码。
- 本轮计划新增的临时日志、探针、统计、轮询、开关、脚本及依赖：无。新增回归是正式测试，保留。若实施时加入临时诊断，保存必要证据后逐项移除调用点和依赖，核对差异，再重跑整套回归；清理及复验未完成不得宣告实施完成。
- 本次交付仅为文档。Static：已核对当前收尾及调用位置；Contract：本规格已明确；Runtime、Visual、RED/GREEN 和正式功能验收：NotRun。用户提供的方向测量是既有验证事实，不记作本轮实测。

## 禁止事项

不重新测量已核验的大 glTF，不修改 hand 或 swing，不增加调度、缓存、性能优化或名称解析方案。不改动无关 dirty/untracked 工作。不执行暂存、提交、推送、清理或回退。本轮写完本文件即停止，不进入实现。
