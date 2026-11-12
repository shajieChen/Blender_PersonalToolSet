# 源码与交付复核

2026-11-12。源码、脚本和 tests/out 路径以仓库根为基准；本页证据链接以本文目录为基准。

| 项目 | 结果与边界 |
|---|---|
| 规则与改动范围 | 独立新插件四文件、新增测试、两份任务文档、正式插件清单及安装 BAT 的新增入口；无关九个掌心 JSON 保留，无 Git 写操作 |
| 依赖方向 | __init__ → locomotion → playback/library；playback → library；库不反向依赖 UI 或会话，无重定向插件私有 import |
| 状态与线程 | 角色配置归 Object、目标归 Scene、目录偏好归插件；活动会话是唯一显式运行引用；bpy 与 timer 均在主线程 |
| 所有权与失败 | 会话 owns timer/player；播放器 owns Action copies、snapshot 和两条轨道；临时库对象 owns 参考骨架副本；按精确对象移除，原 Action 只读；失败恢复原动作、轨道、姿势和对象变换 |
| 接口与命名 | 具体角色/片段/播放职责；无新 Manager、Context、Adapter 或通用注册表；新增类和文件未使用禁用架构名词 |
| 源码硬门 | 内存 compile、AST 元数据、注释/docstring 为零、无行尾空格；主标题由版本生成；原安装 BAT 编码保留，只插入 ASCII 新入口 |
| 生成物与安装 | 只打包四个正式源码；安装副本与源文件 SHA-256 一致；详见 source-manifest.json 与 installed-green.log |
| C++ 专项 | 修改 C/C++ 文件为零；m_ 变量对齐、赋值对齐、namespace Tab、三元参数、unique_ptr label、raw pointer、USE_TEST_UNIT 全部 NotApplicable |
| 测试分层 | 23 项聚焦、真实 FBX/重定向/库链、原生事件、保存重开通过；默认面板截图已目视；完整 Visual、用户真实角色与正式验收未闭合 |
| Concern | 上游重定向整套回归及独立失败收据保留；多尺寸 UI 自动化缺原生 action zone 上下文，不记 GREEN |
| 诊断与收尾 | 正式运行路径无临时诊断开销；测试探针与核对场景暂保留，用户确认后精确清理并复验 |

1.0.1 增量复核：`locomotion.validate_character` 读取已加载动态骨骼模块的公共任务入口，在同一 armature 的活动任务存在时拒绝启动。该检查仅入口执行；无额外持续轮询、反向 import 或自动注销其他插件。真实 SpringBone 集成 RED 11 项选中 1 项失败，GREEN 24/24；安装副本和 Blender 5.2.1 同样 24/24。版本元数据、ZIP 与源码见 source-manifest-1.0.1.json。现场冲突、恢复与边界见 mcp-current-session.json、mcp-final-logic.json，不把发生过的恢复失败改写为通过。

后续禁止 Computer Use；MCP 逻辑与实际骨骼/网格采样可作为各自范围证据，不作为人工界面验收。当前仍缺正式三槽配置、完整 Visual、用户正式验收与清理后复验。

默认页面截图：[main-panel.png](main-panel.png)。实际结果汇总与命令入口以实施档为唯一进度维护位置。
