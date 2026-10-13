# 重定向烘焙响应 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 点击「导入目标并重定向」时，烘焙阶段让出主线程并减少重复求值，烤出来的四元数和位移与现在逐位相同。

**Architecture:** `bake_retarget` 改成驱动 `RetargetBakeJob`。准备阶段缓存分类、链末端和 rest。帧循环先保持现有求解顺序。界面用计时器每次处理约 16 毫秒。重复的 `view_layer.update` 和父矩阵递推都要在逐位对比通过之后才成为默认路径。

**Tech Stack:** Blender 5.1 Python（`bpy`、`mathutils`），现有包 `humanoid_retarget`，测试用 `blender.exe --background --python H:\Blender_Plugin\tests\run_retarget_test.py`。

**设计:** `docs/superpowers/specs/2026-10-13-retarget-bake-responsiveness-design.md`

---

## 文件

- 修改 `humanoid_retarget/retarget.py`：Job、缓存、帧循环。`bake_retarget` 仍是同步入口。
- 修改 `humanoid_retarget/pipeline.py`：导入和烘焙拆开，同步包装保留。
- 修改 `humanoid_retarget/__init__.py`：三个重定向操作改成 modal，版本改为 `(1, 6, 7)`。
- 修改 `humanoid_retarget/gizmos.py`：烘焙期间短路绘制。
- 修改 `tests/run_retarget_test.py`：逐位比较器和缓存一致性测试。
- 新建 `tests/fixtures/bake_pose_baseline.json`：当前求解器的合成双片段基准。生成后纳入仓库。
- 新建 `tests/profile_bake.py`：只在实施时计时，最后删除，不提交。

写完 Python 后，把 `humanoid_retarget` 里改过的 `.py` 复制到这三个已启用目录，再跑后台测试。否则 Blender 会先导入 AppData 里的旧插件：

- `C:\Users\chenshajie1\AppData\Roaming\Blender Foundation\Blender\5.1\scripts\addons\humanoid_retarget`
- `C:\Users\chenshajie1\AppData\Roaming\Blender Foundation\Blender\5.2\scripts\addons\humanoid_retarget`
- `H:\Blender\5.2.1\portable\scripts\addons\humanoid_retarget`

复制用 Python `shutil.copy2`，不要用 PowerShell `Set-Content`。

## 任务 1：记下当前姿势基准

**Files:**
- 修改 `tests/run_retarget_test.py`
- 创建 `tests/fixtures/bake_pose_baseline.json`

- [ ] **Step 1: 加上比较器和双片段采样**

在 `tests/run_retarget_test.py` 末尾、`main` 之前加入：

```python
import struct


def quat_bits(quat):
    return tuple(struct.pack("<f", float(component)) for component in quat)


def quaternions_identical(left, right):
    return quat_bits(left) == quat_bits(right)


def test_quaternion_comparator():
    print("--- quaternion bits ---")
    check(quaternions_identical((1.0, 0.0, 0.0, 0.0), (1.0, 0.0, 0.0, 0.0)), "same quaternion matches bits")
    check(not quaternions_identical((1.0, 0.0, 0.0, 0.0), (-1.0, 0.0, 0.0, 0.0)), "negated quaternion is not identical")
    check(not quaternions_identical((1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0)), "different component is not identical")


def _sample_bake(source, target):
    from humanoid_retarget.retarget import RetargetOptions, bake_retarget

    options = RetargetOptions()
    _report, baked = bake_retarget(source, target, options)
    rows = []
    scene = bpy.context.scene
    for action in baked:
        source.animation_data.action = None
        target.animation_data.action = action
        if action.slots:
            target.animation_data.action_slot = action.slots[0]
        start = int(action.frame_range[0])
        end = int(round(action.frame_range[1]))
        for frame in range(start, end + 1):
            scene.frame_set(frame)
            for pose_bone in target.pose.bones:
                quat = tuple(round(component, 7) for component in pose_bone.rotation_quaternion)
                loc = tuple(round(component, 7) for component in pose_bone.location)
                rows.append({
                    "action": action.name.split("_", 1)[-1],
                    "frame": frame,
                    "bone": pose_bone.name,
                    "quat": list(quat),
                    "loc": list(loc),
                })
    return rows
```

`round(..., 7)` 只用于基准文件可读。真正的守门测试在任务 3 里对内存中的 float32 位做比较，不读这份四舍五入的 JSON 来判断通过。JSON 用来发现「求解器输出变了」时人工查看。

- [ ] **Step 2: 用两段合成动画生成基准**

```python
def test_record_two_clip_baseline():
    print("--- two clip baseline ---")
    roles = _role_names("Base")
    source = build_biped("BaseSource", roles)
    target = build_biped("BaseTarget", roles, arm_roll=0.4)
    animate(source, roles)
    first = source.animation_data.action
    first.name = "ClipA"
    second = first.copy()
    second.name = "ClipB"
    track = source.animation_data.nla_tracks.new()
    track.strips.new(second.name, 1, second)
    rows = _sample_bake(source, target)
    folder = os.path.join(os.path.dirname(__file__), "fixtures")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "bake_pose_baseline.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(rows, handle, indent=2)
    check(len(rows) > 0, "baseline has sampled keys")
    names = {row["action"] for row in rows}
    check("ClipA" in names and "ClipB" in names, "baseline covers both clips")
```

在 `main()` 里现有测试之前调用 `test_quaternion_comparator` 和 `test_record_two_clip_baseline`。文件头补上 `import json`，如果还没有。

- [ ] **Step 3: 跑测试并确认基准文件出现**

Run: `"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe" --background --python H:\Blender_Plugin\tests\run_retarget_test.py`

Expected: 输出里有 `PASS same quaternion matches bits`、`PASS baseline covers both clips`，以及最后的 `RETARGET_TEST_OK`。`tests/fixtures/bake_pose_baseline.json` 存在且包含 `ClipA` 和 `ClipB`。

- [ ] **Step 4: Commit**

```powershell
git add -- tests/run_retarget_test.py tests/fixtures/bake_pose_baseline.json
git commit -m @"
Record the current retarget bake as a pose baseline.

Later bake scheduling changes have to match these sampled keys.
"@
```

## 任务 2：准备阶段缓存，帧循环仍走原求解

**Files:**
- 修改 `humanoid_retarget/retarget.py`

- [ ] **Step 1: 写失败测试，要求第二次分类不再扫描顶点**

在 `tests/run_retarget_test.py` 增加：

```python
def test_bake_classifies_once():
    print("--- classify once ---")
    roles = _role_names("Once")
    source = build_biped("OnceSource", roles)
    target = build_biped("OnceTarget", roles)
    animate(source, roles)
    import humanoid_retarget.classify as classify
    calls = {"n": 0}
    original = classify.skinned_bone_names

    def counting(arm_obj):
        calls["n"] += 1
        return original(arm_obj)

    classify.skinned_bone_names = counting
    try:
        from humanoid_retarget.retarget import bake_retarget
        bake_retarget(source, target)
    finally:
        classify.skinned_bone_names = original
    print("SKIN SCANS", calls["n"])
    check(calls["n"] <= 8, "bake scans skin weights a bounded number of times")
```

`8` 的来源：准备阶段来源和目标各一次名称分类，加上 `correct_deform_pairs` 对目标的一次。几何分类不扫权重。留一点余量给准备阶段的重复调用，但不能按帧增长。两段动画、每段多于 1 帧时，旧代码会远大于 8。

- [ ] **Step 2: 跑测试，确认它失败**

Run: 同上 blender 命令。

Expected: `FAIL bake scans skin weights a bounded number of times`，并且 `SKIN SCANS` 大于 8。

- [ ] **Step 3: 在 `retarget.py` 增加缓存和 Job**

```python
class BakeCache:
    def __init__(self, src, tgt, pairs):
        self.pairs = list(pairs)
        self.src_roles = {role: name for role, name, _target_name in pairs}
        self.tgt_roles = {role: name for role, _source_name, name in pairs}
        self.src_body_roles = _anatomical_roles(src, self.src_roles)
        self.tgt_body_roles = _anatomical_roles(tgt, self.tgt_roles)
        self.source_body = _body_matrix(src, self.src_body_roles)
        self.target_body = _body_matrix(tgt, self.tgt_body_roles)
        self.src_world = src.matrix_world.copy()
        self.tgt_world = tgt.matrix_world.copy()
        self.chain_end = {}
        for arm, roles in ((src, self.src_roles), (tgt, self.tgt_roles)):
            for role, _source_name, _target_name in pairs:
                self.chain_end[(arm.name, role)] = _chain_end(arm, roles, role)
        order = {role: index for index, role in enumerate(_BODY_ROLE_ORDER)}

        def depth(bone_name):
            bone = tgt.data.bones.get(bone_name)
            seen = set()
            count = 0
            while bone is not None and bone.name not in seen and bone.parent is not None:
                seen.add(bone.name)
                count += 1
                bone = bone.parent
            return count

        self.ordered = sorted(self.pairs, key=lambda pair: (depth(pair[2]), order.get(pair[0], 100)))

    def refresh_if_moved(self, src, tgt):
        if src.matrix_world != self.src_world or tgt.matrix_world != self.tgt_world:
            self.src_world = src.matrix_world.copy()
            self.tgt_world = tgt.matrix_world.copy()
            self.src_body_roles = _anatomical_roles(src, self.src_roles)
            self.tgt_body_roles = _anatomical_roles(tgt, self.tgt_roles)
            self.source_body = _body_matrix(src, self.src_body_roles)
            self.target_body = _body_matrix(tgt, self.tgt_body_roles)
```

给 `_apply_body_orientations` 增加可选参数 `cache=None`。`cache` 为空时保持现在的函数体。`cache` 有值时：

- 调用 `cache.refresh_if_moved(src, tgt)`
- 使用 `cache.source_body`、`cache.target_body`、`cache.ordered`
- `_chain_vector` 改为接受已经算好的 `end_name`，或者在缓存命中时跳过 `_chain_end`

清零、swing、逐骨 `view_layer.update` 和四元数写入保持原样。

`bake_retarget` 在解析 pairs 之后构造一个 `BakeCache`，帧循环把这个对象传进去。`collect_actions` 的范围不要改。

- [ ] **Step 4: 跑分类次数测试和整套测试**

Expected: `PASS bake scans skin weights a bounded number of times`，最后 `RETARGET_TEST_OK`。

- [ ] **Step 5: Commit**

```powershell
git add -- humanoid_retarget/retarget.py tests/run_retarget_test.py
git commit -m @"
Cache retarget classification for the duration of one bake.

The pose math and per-bone updates stay on the existing path.
"@
```

## 任务 3：同步 Job，供测试和 modal 共用

**Files:**
- 修改 `humanoid_retarget/retarget.py`
- 修改 `tests/run_retarget_test.py`

- [ ] **Step 1: 写内存位比较测试**

```python
def _live_pose_rows(source, target):
    from humanoid_retarget.retarget import bake_retarget

    _report, baked = bake_retarget(source, target)
    rows = []
    scene = bpy.context.scene
    for action in baked:
        target.animation_data.action = action
        if action.slots:
            target.animation_data.action_slot = action.slots[0]
        start = int(action.frame_range[0])
        end = int(round(action.frame_range[1]))
        for frame in range(start, end + 1):
            scene.frame_set(frame)
            for pose_bone in target.pose.bones:
                rows.append((
                    action.name,
                    frame,
                    pose_bone.name,
                    quat_bits(pose_bone.rotation_quaternion),
                    quat_bits(pose_bone.location),
                ))
    return rows


def test_job_matches_direct_bake():
    print("--- job matches direct bake ---")
    roles = _role_names("Job")
    source = build_biped("JobSource", roles)
    target = build_biped("JobTarget", roles, arm_roll=0.4)
    animate(source, roles)
    direct = _live_pose_rows(source, target)
    # 第二次在副本上走 RetargetBakeJob.prepare + step(None)
    source_b = build_biped("JobSourceB", roles)
    target_b = build_biped("JobTargetB", roles, arm_roll=0.4)
    animate(source_b, roles)
    from humanoid_retarget.retarget import RetargetBakeJob, RetargetOptions
    job = RetargetBakeJob(source_b, target_b, RetargetOptions())
    job.prepare()
    while not job.step(budget_s=None):
        pass
    job.finish()
    stepped = _live_pose_rows_from_existing(target_b)
    check(direct == stepped, "modal job pose bits match the direct bake")
```

`_live_pose_rows` 自己会再烤一次，所以不能对同一个已经烤过的目标调用它来代表 Job 的结果。`stepped` 必须读取 Job 刚刚写下的 Action，不要再调用 `bake_retarget`。把读取循环抽成 `_read_baked_pose(target, baked_actions)`，两条路径都用它。

- [ ] **Step 2: 跑测试，确认失败**

Expected: `ImportError` 或 `cannot import name 'RetargetBakeJob'`。

- [ ] **Step 3: 实现 Job**

```python
class RetargetBakeJob:
    def __init__(self, src, tgt, options=None):
        self.src = src
        self.tgt = tgt
        self.options = options or RetargetOptions()
        self.cache = None
        self.actions = []
        self.action_index = 0
        self.frame = None
        self.frame_end = None
        self.created = []
        self.baked = []
        self.original_frame = None
        self.source_action = None
        self.source_slot = None
        self.summary = ""

    def prepare(self):
        src, tgt, options = self.src, self.tgt, self.options
        if src is None or src.type != "ARMATURE":
            raise RetargetError("请先导入带骨架和动画的来源模型。")
        if tgt is None or tgt.type != "ARMATURE":
            raise RetargetError("目标不是骨架。没有骨架的网格会走自动绑定。")
        if src == tgt:
            raise RetargetError("来源和目标是同一个骨架。")
        if options.reference == "CURRENT" and not options.reference_data:
            raise RetargetError("已选当前姿势作为起点，但是没有捕获参考姿势。")
        pairs = correct_deform_pairs(src, tgt, correct_chest_pairs(src, tgt, _pairs_from_options(src, tgt, options)))
        options.resolved_pairs = pairs
        self.cache = BakeCache(src, tgt, pairs)
        self.actions = collect_actions(src)
        if not self.actions:
            raise RetargetError("来源骨架上没有可烘焙的动画。")
        anim = src.animation_data
        self.source_action = anim.action if anim else None
        self.source_slot = anim.action_slot if anim and getattr(anim, "action_slot", None) else None
        self.original_frame = bpy.context.scene.frame_current
        if tgt.animation_data:
            tgt.animation_data_clear()
        self._begin_action()
        return self

    def step(self, budget_s=0.016):
        """Bake until the time budget is spent. budget_s None runs everything. Returns True when finished."""
        started = None if budget_s is None else __import__("time").perf_counter()
        while self.action_index < len(self.actions):
            self._bake_frame()
            self.frame += 1
            if self.frame > self.frame_end:
                self.baked.append((self.created[-1], self.frame_start, self.frame_end))
                self.action_index += 1
                if self.action_index < len(self.actions):
                    self._begin_action()
            if started is not None and __import__("time").perf_counter() - started >= budget_s:
                return False
        return True

    def progress(self):
        total = 0
        done = 0
        for index, action in enumerate(self.actions):
            start, end = _frame_range(action)
            count = end - start + 1
            total += count
            if index < self.action_index:
                done += count
            elif index == self.action_index and self.frame is not None:
                done += max(0, self.frame - start)
        return done, total, self.action_index + 1, len(self.actions), self.frame, self.frame_end

    def finish(self):
        # 把现有 bake_retarget 末尾的 NLA、帧范围、hr_actions 和摘要搬到这里
        ...
        return self.summary, [action for action, _start, _end in self.baked]

    def abort(self):
        for action, _start, _end in self.baked:
            bpy.data.actions.remove(action)
        for action in self.created:
            if action.users == 0:
                bpy.data.actions.remove(action)
        if self.src.animation_data and self.source_action is not None:
            _assign_action(self.src, self.source_action)
            if self.source_slot is not None:
                self.src.animation_data.action_slot = self.source_slot
        if self.original_frame is not None:
            bpy.context.scene.frame_set(self.original_frame)
```

`_begin_action` 做现在循环开头的 `_assign_action`、`_frame_range`、`_new_target_action`。`_bake_frame` 做现在循环体的一帧，包括插帧。把 `bake_retarget` 改成：

```python
def bake_retarget(src, tgt, options=None):
    job = RetargetBakeJob(src, tgt, options)
    job.prepare()
    while not job.step(budget_s=None):
        pass
    return job.finish()
```

`finish` 里的摘要文字和现在的六行保持一致，测试若比较摘要字符串才不会破。现有测试不比较摘要全文，但仍不要改措辞。

- [ ] **Step 4: 跑整套测试**

Expected: `PASS modal job pose bits match the direct bake` 和 `RETARGET_TEST_OK`。

- [ ] **Step 5: Commit**

```powershell
git add -- humanoid_retarget/retarget.py tests/run_retarget_test.py
git commit -m @"
Step the retarget bake through one shared job.

The synchronous bake used by tests runs that job to completion.
"@
```

## 任务 4：界面按时间片烘焙

**Files:**
- 修改 `humanoid_retarget/pipeline.py`
- 修改 `humanoid_retarget/__init__.py`
- 修改 `humanoid_retarget/gizmos.py`

- [ ] **Step 1: 拆开导入**

`pipeline.py` 增加：

```python
def prepare_target_import(path, source):
    if source is None or source.type != "ARMATURE":
        raise PipelineError("请先导入带来源动画的模型。")
    objects, _actions = import_model(path)
    meshes = [obj for obj in objects if obj.type == "MESH"]
    armature = pick_armature(objects)
    auto = False
    if _usable_armature(armature, meshes):
        note = "目标自带骨架，已直接映射"
    else:
        if not meshes:
            raise PipelineError("目标文件里没有网格，也没有可识别的蒙皮骨架。")
        try:
            armature, weight_mode, _landmarks = auto_rig_meshes(meshes)
        except AutoRigError as exc:
            raise PipelineError(str(exc)) from exc
        objects = list(objects) + [armature]
        auto = True
        note = f"目标没有可用骨架，已按 T/A Pose 自动绑定（{weight_mode}）"
    move_to_collection(objects, "HR_Target")
    return armature, objects, note, auto


def load_target_and_retarget(path, source, options=None):
    armature, _objects, note, auto = prepare_target_import(path, source)
    report, baked = retarget_existing(source, armature, options)
    return armature, note + "\n" + report, baked, auto
```

同步包装留给测试。不要改 `retarget_existing` 的对外结果。

- [ ] **Step 2: Gizmo 短路**

`gizmos.py`：

```python
_SUSPENDED = False


def set_draw_suspended(suspended):
    global _SUSPENDED
    _SUSPENDED = bool(suspended)


def draw_callback():
    if _SUSPENDED:
        return
    # 其余保持原样
```

- [ ] **Step 3: modal 操作**

在 `__init__.py` 放一个模块级 `_ACTIVE_BAKE = None`。`unregister` 时如果它不是 `None`，调用 `abort`、`set_draw_suspended(False)`，并尝试 `event_timer_remove`。

`HR_OT_import_target.execute` 改为：

```python
def execute(self, context):
    if _ACTIVE_BAKE is not None:
        self.report({"WARNING"}, "正在重定向，请等待结束或按 Esc 取消")
        return {"CANCELLED"}
    settings = context.scene.hr_settings
    _set_status(context, "正在导入目标")
    options = _options_from_settings(settings, use_mapping=False)
    try:
        armature, objects, note, auto = prepare_target_import(self.filepath, settings.source)
    except PipelineError as exc:
        self.report({"ERROR"}, str(exc))
        _set_status(context, str(exc))
        return {"CANCELLED"}
    job = RetargetBakeJob(settings.source, armature, options)
    try:
        job.prepare()
    except RetargetError as exc:
        self.report({"ERROR"}, str(exc))
        return {"CANCELLED"}
    self._armature_name = armature.name
    self._imported_names = [obj.name for obj in objects]
    self._note = note
    self._remember = self.filepath
    set_draw_suspended(True)
    wm = context.window_manager
    self._timer = wm.event_timer_add(0.01, window=context.window)
    wm.modal_handler_add(self)
    wm.progress_begin(0, 100)
    global _ACTIVE_BAKE
    _ACTIVE_BAKE = self
    return {"RUNNING_MODAL"}
```

`modal`：

```python
def modal(self, context, event):
    if event.type == "ESC":
        self._cancel(context)
        return {"CANCELLED"}
    if event.type != "TIMER":
        return {"PASS_THROUGH"}
    job = self._job
    try:
        finished = job.step(budget_s=0.016)
    except Exception as exc:
        self._cancel(context)
        self.report({"ERROR"}, str(exc))
        return {"CANCELLED"}
    done, total, action_i, action_n, frame, frame_end = job.progress()
    if total:
        context.window_manager.progress_update(int(done * 100 / total))
    if finished:
        summary, _baked = job.finish()
        self._close_ui(context)
        settings = context.scene.hr_settings
        settings.target = bpy.data.objects[self._armature_name]
        settings.show_bones = False
        set_armature_bones_visible(settings.target, False)
        _remember_filepath(context, "last_target_path", self._remember)
        if job.options.resolved_pairs:
            _fill_mapping(settings, job.options.resolved_pairs)
        _set_status(context, self._note + "\n" + summary)
        self.report({"INFO"}, "重定向完成")
        return {"FINISHED"}
    return {"RUNNING_MODAL"}
```

`_cancel` 调用 `job.abort()`，删除 `self._imported_names` 里仍存在的对象，然后 `_close_ui`。`_close_ui` 去掉计时器、`progress_end`、`set_draw_suspended(False)`，并把 `_ACTIVE_BAKE` 设为 `None`。

`HR_OT_retarget_existing` 和 `HR_OT_retarget_selected_mesh` 用同一个 modal 收尾。选中网格的自动绑定留在 `execute` 的同步部分，绑定完成后再 `prepare` Job。

状态行每 0.25 秒写一次「动作 {action_i}/{action_n}，帧 {frame}/{frame_end}」，不要每拍都写。

版本号改为 `(1, 6, 7)`。

- [ ] **Step 4: 后台测试**

Expected: `RETARGET_TEST_OK`。后台没有窗口区域，Gizmo 回调本来就会返回；新增的短路不能让 `test_bone_gizmos` 失败。该测试测的是 `gizmo_links`，不经过 `draw_callback`。

- [ ] **Step 5: Commit**

```powershell
git add -- humanoid_retarget/__init__.py humanoid_retarget/pipeline.py humanoid_retarget/gizmos.py humanoid_retarget/retarget.py
git commit -m @"
Bake retarget clips in short main-thread slices.

Import stays synchronous, and the pose job can still run to completion in tests.
"@
```

## 任务 5：去掉已证明多余的场景更新

**Files:**
- 修改 `humanoid_retarget/retarget.py`
- 修改 `tests/run_retarget_test.py`

一次只删一处，删完就跑 `test_job_matches_direct_bake` 的同类比较。比较对象是任务 1 生成基准之前的行为。实施时在删更新之前，把「逐骨更新都保留」的内存位结果存进测试里的 `expected`。删完一处后必须和 `expected` 相等。失败就恢复那一处。

候选顺序：

1. `bake` 帧循环里 `scene.frame_set(frame)` 紧后面的 `bpy.context.view_layer.update()`。
2. `_apply_body_orientations` 返回后的那次更新。
3. `apply_contact_ik` 之后的更新，仅当 `not options.foot_ik and not options.hand_ik`。

髋位移之后的那次更新先留着。IK 打开时，IK 之后的更新留着。

每通过一处就提交一次，信息写明去掉的是哪一次更新。三次都失败也可以，把结果写进测试注释里的失败原因，不要为了变快留下会改姿势的删除。

额外加一个 IK 打开的短测试：`RetargetOptions(foot_ik=True)` 烤两帧，确认删除第 3 项之后这条路径仍调用更新，并且现有 `test_mapping_root_reference_and_ik` 通过。

## 任务 6：父矩阵递推

**Files:**
- 修改 `humanoid_retarget/retarget.py`
- 修改 `tests/run_retarget_test.py`

- [ ] **Step 1: 写退回条件测试**

```python
def test_algebra_skips_constrained_bones():
    from humanoid_retarget.retarget import pose_needs_evaluated_parent
    roles = _role_names("Alg")
    target = build_biped("AlgTarget", roles)
    bone = target.pose.bones[roles["upperarm_l"]]
    check(pose_needs_evaluated_parent(bone) is False, "plain bone can use the algebraic parent matrix")
    bone.constraints.new("COPY_ROTATION")
    check(pose_needs_evaluated_parent(bone) is True, "a constraint keeps the evaluated parent matrix")
    bone.constraints.remove(bone.constraints[0])
    target.data.bones[roles["upperarm_l"]].inherit_scale = "NONE"
    check(pose_needs_evaluated_parent(bone) is True, "non-full inherit scale keeps the evaluated update")
```

- [ ] **Step 2: 跑测试，确认失败**

Expected: `cannot import name 'pose_needs_evaluated_parent'`。

- [ ] **Step 3: 实现递推**

```python
def pose_needs_evaluated_parent(pose_bone):
    bone = pose_bone.bone
    if pose_bone.constraints:
        return True
    return getattr(bone, "inherit_scale", "FULL") != "FULL"


def _posed_armature_matrix(pose_bone, parent_matrix):
    local = pose_bone.bone.matrix_local
    basis = pose_bone.matrix_basis
    if parent_matrix is None:
        return local @ basis
    parent_local = pose_bone.parent.bone.matrix_local
    return parent_matrix @ parent_local.inverted() @ local @ basis
```

在 `_apply_body_orientations` 的骨骼循环里，若当前骨骼及其父骨骼都不需要求值父矩阵，则用字典里上一根的递推矩阵代替 `parent.matrix`，本根写完四元数后不要 `view_layer.update`。只要有一根需要求值，整帧退回现在的逐骨更新。循环结束后做一次 `view_layer.update`，让髋位移读到网格和骨骼的求值结果。

用 `test_job_matches_direct_bake` 同一套位比较。普通合成骨架必须一致。若不一致，默认关闭递推，只保留 `pose_needs_evaluated_parent` 和测试，不把递推放进默认烘焙。提交信息里写明它是默认开启还是被对比退回。

## 任务 7：计时并收尾

**Files:**
- 临时 `tests/profile_bake.py`，跑完删除
- 修改过的插件文件复制到三个插件目录

- [ ] **Step 1: 计时脚本**

`tests/profile_bake.py` 在后台加载插件，对合成骨架打出三段时间：导入准备、`prepare`、全部 `step`。若本机存在 `H:\SErsiko_ExtactedTool\output\c0000_突刺_wp_a_0300.glb` 和 `c:\Users\chenshajie1\Downloads\body.FBX`，再打出这对文件的导入时间和烘焙时间。不要把渲染或截图放进脚本。

- [ ] **Step 2: 跑计时和整套测试**

Expected: `RETARGET_TEST_OK`。把两段时间写进实施说明，不要写进插件界面。

- [ ] **Step 3: 删除计时脚本，确认工作区只剩应提交的文件**

- [ ] **Step 4: Commit**

只在任务 5 或 6 还有未提交的通过改动时提交。计时脚本不提交。

界面验收由用户做：完全退出并重新打开 Blender，点「导入目标并重定向」，确认状态行出现动作和帧进度，Esc 能取消且不留下半套目标，成功后一次撤销去掉这次导入。后台测试不能代替这一步。

## 自检

- 设计里的缓存、modal、取消、Gizmo 短路、重复更新、父矩阵递推，分别落在任务 2、4、4、4、5、6。
- 全部片段仍由 `collect_actions` 决定，没有任务把它改成当前下拉片段。
- `keyframe_insert` 没有被批量写曲线替换。
- 递推失败时的退回写在任务 6，不留成「以后再看」。
- 比较器用 float32 位，不用点积阈值代替。
