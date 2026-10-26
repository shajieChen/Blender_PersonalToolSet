# 运行与验证收据

开始于 2026-10-23，持续至 2026-10-24；Blender 5.2.1 LTS，hash `9e2066aef7ef`。

| 证据 | 结果 |
|---|---|
| 基线 | Pose 13，Spring Bone 67；均退出 0 |
| 功能整套 | `suite-before-user-review.log`：selected 34，无 skip/expected failure，成功标记与退出 0 |
| 既有回归 | `regression-pose.log` 13，`regression-spring.log` 67；均退出 0 |
| runner 负控 | `runner-negative-filter.log`：selected 0，TEST_FAIL，退出 1；不计业务 RED |
| 跨进程重开 | 测试启动独立 Blender 加载 persistence.blend，核对五挂点、握持根和部件共七对象的关系/部位/schema/骨名/世界矩阵及人形指针；子进程退出 0 |
| Collection 复用 | 保存握持根及部件，无旧人形 parent；Append 后绑定第二个人形并保留第一把武器 |
| 前台 Undo/Redo | 原生 undo_push/undo/redo 核对挂点复制移除/恢复；随后删除副本，原武器保留 |
| 安装 | 源/目标六文件 SHA256 一致，实际模块路径位于 portable/scripts/addons/humanoid_mounts；独立启停及重开通过 |

用户核对前收据为 `installed-ui-user-review.log`；清理后最终前台收据为 `post-cleanup-ui.log`：实际安装目录加载，PID 51780，自然退出 0；16 个不同播放帧，包含 walk/run 两段输入，捕获第 19/37 帧，Undo/Redo 通过。手掌中心只按已知夹具几何校准，不属于插件的自动掌心识别。

前台进程全部由本任务启动，脚本通过 bpy.ops.wm.quit_blender 自然退出；未调用进程终止工具。早期默认退出收据写入 Blender 系统临时目录；后续前台的 TEMP/TMP 与 BLENDER_USER_CONFIG 已隔离到 tests/out/humanoid_mounts，不覆盖用户配置。

独立配置先在任务路径写入测试 userpref，关闭首次启动弹窗；前台不用会忽略该配置的 factory-startup。场景由独立 Scene 构建，不重置当前上下文。Undo 后显式重绘，再在 UI 区域上下文切换侧栏类别；截图前刷新 framebuffer。

保留了上下文失败、黑屏和弹窗遮挡的原始日志，均不作为 Visual 通过。最终截图须经过实际查看；机器输出“已保存截图”本身不证明画面有效。

产品没有每帧 Python 跟随；演示工具只有显式 --verify-ui 才创建测试 timer，驱动真实时间轴和截图，并随该进程自然退出。它是正式前台测试入口，不随插件加载。

清理后复验：transform 7、lifecycle 21、整套 34、Pose 13、Spring 68，均退出 0；安装新进程 REOPEN_OK 7 和 INSTALLED_OK。收据统一为 post-cleanup-*.log。Spring 相比原基线新增 1 项来自范围外同步工作，本任务未修改其源码和测试。原生后台 Undo 的 poll 不可用没有当作通过；前台已单独完成。
