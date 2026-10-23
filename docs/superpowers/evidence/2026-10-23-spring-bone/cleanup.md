# 动态骨骼临时项

日期：2026-10-23。用户核对前不删除。正式测试、功能 TIMER、裙摆场景和验收日志保留。

| 项 | 用途 | 清理 |
| --- | --- | --- |
| `animation-snip.txt`、`animation-out.txt`、`frame-probe.txt` | 解码日志时的摘录 | 待用户核对后删除 |
| `lifecycle-ui.log` | 一次失败的前台 Undo 尝试：脚本创建的对象与操作器 Undo 落在同一步，骨架被撤掉 | 待核对后删除；不能当作 GREEN |
| `api-probe.log` | 5.2.1 Action/slot/`convert_local_to_pose` 探针 | 保留到环境说明不再引用它 |
| `tests/out/spring_bone_skirt_ui_probe.py`、`tests/out/_list_actions.py`、`skirt-ui.log` | 5.2.1 窗口里对裙摆做进度、Esc 和一次 Undo；列出 blend 内 Action | 待核对后删除脚本；日志按结果决定保留 |
| `undo_fixture.blend`、`undo_fixture.blend1` | 一次 Undo 的前台夹具；结论在 `undo-probe.log` | blend1 可删；blend 在核对前保留 |
| `lifecycle_reopen.blend1`、`skirt_demo.blend1` | Blender 保存备份 | 待核对后删除 |
| `skirt_demo.blend`、四张 `skirt_*.png`、`runtime.log` | 裙摆验收 | 保留 |
| `contract-red.log`、`contract.log`、`animation.log`、`lifecycle.log`、`spring-all.log`、`pose-channel.log`、`retarget.log`、`undo-probe.log`、`lifecycle_reopen.blend` | 命令与恢复证据 | 保留 |

插件代码没有临时轨迹开关、故障注入默认开启、跨会话缓存或额外轮询 handler。故障点只在测试里传入 `SpringBoneBakeJob.fault_point`。

本文件写完时尚未清理，也尚未做清理后复验。
