# 执行环境

日期：2026-10-23。工程：`H:\Blender_Plugin`；remote：`https://github.com/shajieChen/Blender_PersonalToolSet.git`。

已完整读取本任务实施档与调研。根目录/祖先及目标测试目录未找到额外 AGENTS.md/CLAUDE.md；遵守聊天中的全局规则。原有修改见 `initial-state.json`，不接管其他任务修改。

当前可执行文件：`H:\Blender\5.2.1\blender.exe`，`--version` 输出 Blender 5.2.1 LTS，hash `9e2066aef7ef`。

基线：Pose 13 项，退出 0；Spring Bone 67 项，退出 0。收据为 `baseline-pose.log`、`baseline-spring.log`。

Spring 生命周期测试会写其模块 EVIDENCE 指向的 blend。为保护原证据，通过同一测试入口和相同过滤器执行，仅把该模块的输出位置重定向到 `tests/out/humanoid_mounts/baseline_spring/`；未修改测试源码。日志已记录隔离路径。

本轮一次 rg 使用 Windows 不展开的路径通配符；已改为目录加 `-g`，不将失败检索作为无实现证据。基础文档单次输出超限时只补读缺失中段，后续不重复全文。
