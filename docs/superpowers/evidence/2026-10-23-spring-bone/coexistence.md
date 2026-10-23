# 动态骨骼共存与回归

日期：2026-10-23。执行文件 `H:\Blender\5.2.1\blender.exe`，版本 5.2.1 LTS，hash `9e2066aef7ef`。工作区 `__file__` 为 `H:\Blender_Plugin\spring_bone\__init__.py`。命令均带 `--background --factory-startup --python-exit-code 1`。

| 命令 | 退出码 | 标记 |
| --- | --- | --- |
| `run_spring_bone_tests.py -- test_spring_bone_solver.py` | 0 | `SPRING_BONE_SELECTED 16`，`SPRING_BONE_TEST_OK`，日志 `contract.log` |
| `run_spring_bone_tests.py -- test_spring_bone_*.py` | 0 | `SPRING_BONE_SELECTED 51`，`SPRING_BONE_TEST_OK`，日志 `spring-all.log` |
| `run_pose_channel_tests.py -- test_*repulsion.py` | 0 | `POSE_CHANNEL_SELECTED 7`，`POSE_CHANNEL_TEST_OK`，日志 `pose-channel.log` |
| `run_retarget_test.py` | 1 | `RETARGET_TEST_FAIL`，日志 `retarget.log` |

缺模块时的可归因 RED 在 `contract-red.log`：15 项均因 `ModuleNotFoundError: spring_bone` 失败，`SPRING_BONE_SELECTED 15`，无 `SPRING_BONE_TEST_OK`。该日志由 PowerShell 重定向写成 UTF-16。其后日志为 UTF-8。

Retarget 失败点是 `tests/run_retarget_test.py:1775`，`test_metarig_root_reference_and_ik`：`AssertionError: the final hop removes horizontal root travel`。该测试导入 `humanoid_retarget`，不导入 `spring_bone`。本轮 `git diff --name-only -- humanoid_retarget` 为空，也未改 `tests/run_retarget_test.py`。失败发生在第二次 hop 的原地根运动，髋骨第 10 帧相对第 1 帧的水平位移超过 1e-3 米。按实施档，此回归未通过前不修改 `安装插件.bat`，也不改 Retarget 源码去压掉断言。

`lifecycle.log` 在同一进程里注册 `spring_bone` 与 `humanoid_retarget`，再注销 Retarget，`sb_settings` 仍在，活动会话为空。两包没有互相导入。

`安装插件.bat` 仍只安装 `humanoid_retarget` 与 `shortcut_hint`。未运行该 BAT，未覆盖安装目录。
