# 自动挂载最终静态复核

日期：2026-10-30。范围仅本次改动；文件哈希见 source-manifest.json。源码路径以仓库根为基准，证据路径以本文目录为基准。

| 硬门 | 结果与依据 |
|---|---|
| 规则、范围与编码 | Passed。逐文件对 tests/out/auto_mounts/before 原字节核对 UTF-8/BOM、原 CRLF/LF、末尾状态；内存 compile 和 git diff --check 通过。pipeline.py 起始已有导入修复保留。 |
| 命名和局部结构 | Passed。新增 target_roles_record/save_target_roles/resolve_bone/grip_from_object/equip_weapon 均承担具体业务职责；未新建抽象层、注册表、Manager 或 Context。 |
| 禁止新增注释 | Passed。9 个 Python 文件逐文件 token/AST 检查；既有 comment/docstring 与起始备份完全一致，新文件为零。 |
| 依赖方向 | Passed。pipeline -> retarget/mapping，retarget -> mapping -> classify；挂载内部 operators -> weapons -> bone_roles/mounts -> properties。挂载生产代码不 import retarget 私有函数，无新增环。 |
| 数据所有权 | Passed。最终角色 Object 拥有 hr_bone_roles 字符串快照；mapping 为写入 owner；仅 pipeline 成功烘焙后发布。挂点父级/parent_bone/局部矩阵仍是唯一绑定真值。 |
| 失败行为 | Passed，限本次功能。_bake_retarget 在动画写入前复用 target_roles_record 拒绝无效/重复映射；新增行为 RED 曾确认旧实现改写 Action，GREEN 保持原 Action/slot/NLA/元数据/动作集合/时间范围。equip 的 ParentPose 恢复与新挂点删除由故障注入覆盖；原挂点及校准不删除。 |
| 生命周期、线程与持续开销 | Passed。沿用主线程 bpy 算子与原生父级；新算子随原 CLASSES 对称注册/注销；无新 timer、frame/depsgraph/load handler、线程或全局运行缓存。未知/失效记录不绑定，多挂点必须选择，不能静默绕过失效点。 |
| 公共 API 和兼容 | Passed，夹具与已列版本范围。新增接口保持具体参数，无第三方依赖；最终求值、Relative Parenting、roll、缩放、非原点握位与保存重开由 56 项挂载测试覆盖。 |
| 临时诊断 | Passed，源码层。生产新增项为无；预览 watch_equipment、轮询、自动截图及 Undo/Redo 调度已移除。正式测试、夹具和证据保留。最终人工收尾尚待用户核对。 |
| m_ 成员声明变量名对齐 | NotApplicable：无 C/C++ 修改。 |
| 连续赋值普通 = 对齐 | NotApplicable：无 C/C++ 修改。Python 保留项目局部风格。 |
| namespace Tab / 三元分组 | NotApplicable：无 C/C++ 修改。 |
| 工具链、项目容器、字符串和 allocator | NotApplicable：纯 Blender Python，无 C++ ABI 或工具链变更。 |
| unique_ptr label 门 | NotApplicable：无 owning unique_ptr。 |
| 生命周期对称门（C++） | NotApplicable：无 C++ 对象或注册入口；Python 算子注册见生命周期项。 |
| raw pointer 借用门 | NotApplicable：无 C/C++ raw pointer。 |
| 日志与诊断宏隔离 | NotApplicable：非 MiniGameCode/RainbowEngine C++；本次也未加生产诊断。 |

未把 Static、Contract 或后台 Runtime 当作 Visual。新增装备入口的真实 Undo/Redo、真实用户 Rig 和正式验收均 NotRun，由用户人工复核。
