# 人形自动挂载逻辑验证结果

```text
最终映射 -> 自动选骨与建点 -> 一键装备 -> 原生动画跟随
逻辑验证通过 -> 用户人工复核 -> 必要清理和复验 -> 正式收尾
```

2026-10-30：逻辑实施已验证，待用户人工复核。按最新要求，本轮没有使用 Computer Use。实施档见 [自动挂载实施档](../../plans/2026-10-30-humanoid-automatic-mounts.md)。

## 已实现行为

- 成功重定向把最终 target 语义骨骼记录在角色 Object；来源/临时 metarig 不作为该记录的角色归属。
- “使用重定向目标”后，选择已校准的武器根或其部件，点击“装备到当前部位”，自动创建或复用右手、左手、背、腰、头挂点。已有偏移保持不变。
- 未校准资产仍需首次设置握持根与掌心偏移。失效记录、重复映射、多挂点歧义、其他角色已绑定武器均明确拒绝，不回落到原点或静默改绑。
- 重复骨骼在烘焙写入动画前拒绝；装备故障恢复根的父级/变换，只删除本次新建挂点。

## 分层证据

| 验证 | 结果 | 证据 |
|---|---|---|
| Static | Passed，9 个 Python 文件；编码/注释/依赖/生命周期专项检查 | [静态复核](static-review.md)、[源码哈希](source-manifest.json) |
| RED | selected=16 的缺实现失败；后续 selected=19、1 个行为失败证实重复映射会改写原 Action | [入口 RED](red-automatic.log)、[发布前置 RED](red-publication-preflight.log) |
| Contract/Process/后台 Runtime | Blender 5.1.2 56/56，退出0 | [5.1.2 结果](logic-verified-5_1.log) |
| Contract/Process/后台 Runtime | Blender 5.2.1 56/56，退出0；使用 --threads 1 | [5.2.1 结果](logic-verified-5_2.log) |
| 安装副本 | 5.1.2 自动挂载 22/22，退出0；独立进程重开核验真实安装路径 | [安装测试](logic-installed-final-5_1.log)、[安装重开](installed-reopen-5_1.log) |
| 相关回归 | Pose 13/13、FBX 25/25；Spring 两版本各147/147，均退出0 | [Pose](logic-pose-5_1.log)、[FBX](logic-fbx-5_1.log)、[Spring 5.1](spring-5_1.log)、[Spring 5.2](spring-5_2.log) |
| 重定向全量 | Concern：metarig 原地位移用例失败；任务起始副本复现同一断言，非全量 GREEN | [当前隔离副本](retarget-isolated-5_1.log)、[起始隔离副本](retarget-baseline-5_1.log) |
| Generate | Passed，仅测试场景生成，非代码生成 | [生成日志](manual-preview-generation.log) |
| Visual / 新装备入口真实 Undo/Redo / 用户真实 Rig | NotRun，交由用户人工复核 | 不以后台算子或夹具代替 |
| Build / RealTransport / Apply/Resim | NotApplicable，纯 Blender Python 挂载功能 | 无这些目标 |
| 正式验收 | 待用户人工复核和收尾复验 | 本结果不是最终验收完成声明 |

详细计数、退出码与日志哈希见 [validation.json](validation.json)。5.2.1 首次默认线程启动停滞，后续单线程探测和测试通过；未声称已定位或解决该启动原因。

## 安装和数据保护

安装基准为 Blender 5.1 的 user_resource('SCRIPTS')/addons，实际路径和 SHA256 见 [安装清单](install-manifest.json)。只改本次7个文件；pipeline.py 和 retarget.py 的安装版本与工作区原本不同，均只应用本次精确补丁，保留安装副本已有的前臂等能力。未把工作区旧差异整包覆盖到安装目录。

安装准备首次发现差异后中止，校正为先准备全部文件再写入；对应身份校验失败日志保留，随后完整 22 项安装测试通过。已有未保存 Blender 实例不会自动热加载新模块，人工验证应保存当前工作后重新启动。

没有 Git 暂存、提交、推送或清理。既有 dirty/untracked 保留。Spring 既有测试覆盖的两个起始 clean 证据 blend 已按精确文件恢复，恢复哈希见 [恢复记录](regression-output-restoration.json)。

## 人工复核入口

打开 [独立测试场景](../../../../tests/out/auto_mounts/automatic-mounts-preview.blend)，进入“人形挂载”，点击“装备到当前部位”。场景已预置角色/武器的一次性校准，实际骨骼字段为空；此校准只属于夹具，不能证明任意资产自动找到掌心。

在用户自己的旧角色文件中，先重新执行一次重定向以保存最终映射，再点“使用重定向目标”，选择已校准武器并装备。新角色或新武器缺少握位时，展开自定义区域首次校准。

人工重点检查：武器方向和掌心位置、播放/跳帧跟随、Undo/Redo、保存重开、换部位与多挂点选择。当前不支持自动手指闭合、双手 IK 或任意未知武器自动识别剑柄。

## 临时诊断与收尾

本次生产临时诊断为无。预览脚本的临时轮询、自动截图和自动 Undo/Redo 调度已删除；最新脚本仅生成场景或运行显式测试。必要测试、夹具、失败日志和证据保留。未继续控制先前的前台实例。

用户核对前保留必要证据；核对后确认本次临时项为零并检查差异，重跑适用聚焦/回归。Visual、人工核对或必要复验尚未通过时，不宣告正式完成。
