# 视觉核验

已实际查看两帧最终安装版画面：人形右手剑、左手盾，以及手/背/腰/头五部位的挂点标记；侧栏具有折叠分组、人形选择、实际骨骼、管理与两种绑定动作。

| 文件 | 观察 |
|---|---|
| tests/out/humanoid_mounts/humanoid-mounts-ui-1.png | 第 19 帧，walk 输入：剑保持已校准的手掌握持位置，五部位标记与当前角色面板可见 |
| tests/out/humanoid_mounts/humanoid-mounts-ui-2.png | 第 37 帧，run 输入：剑随手腕及身体运动，无关系跳位；盾保持左手绑定；无启动弹窗遮挡 |

对应最终复验进程 PID 51780，退出 0，实际包来自 `H:\Blender\5.2.1\portable\scripts\addons\humanoid_mounts\__init__.py`；16 个不同播放帧，Undo/Redo 通过。最终收据：`post-cleanup-ui.log`；核对前收据保留为 `installed-ui-user-review.log`、输出目录中的 `humanoid-mounts-ui-result.json`。

以上是程序化人形夹具，不是用户具体角色兼容证明。没有自动握拳、碰撞避穿插或双手 IK；剑柄位置需要用户校准。

早期黑屏及 Quick Setup 遮挡画面已排除。用户于 2026-10-24 明确回复“符合目标，继续清理复验”。核对后未更改产品代码；最终两张截图已重新实际查看。
