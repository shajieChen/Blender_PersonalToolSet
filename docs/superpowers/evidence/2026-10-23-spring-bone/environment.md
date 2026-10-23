# 动态骨骼执行环境

日期：2026-10-23。本轮按实施档写代码并测试，不安装、不提交。

| 项 | 值 |
| --- | --- |
| Git root | `H:/Blender_Plugin` |
| remote | `https://github.com/shajieChen/Blender_PersonalToolSet.git` |
| HEAD | `0ef80daea8ef0b657b63b1c6a6fa51856dbdd840` |
| branch | `main` 跟踪 `origin/main` |
| AGENTS.md / CLAUDE.md | 仓库内不存在 |
| Blender | `H:\Blender\5.2.1\blender.exe`，5.2.1 LTS，build hash `9e2066aef7ef` |
| 设计档 hash | `7efeef2df61a2b84b76a1a8c338840e38a71c64d` |
| 实施档 hash | `443d15a753f2ba9ddb40a0bc40f76b614dfda84e` |
| 公式证据 hash | `2e56c07f340fd7c1b17b65cbd7bd9dc39439e51c` |

hash 来自 `git hash-object` 对工作区文件内容。公式证据为既有未跟踪文件，本轮保留。

允许新增或修改：`spring_bone/` 包、`tests/test_spring_bone_solver.py`、`tests/test_spring_bone_animation.py`、`tests/test_spring_bone_lifecycle.py`、`tests/run_spring_bone_tests.py`、`tests/run_spring_bone_demo.py`、本证据目录，以及测试通过后的 `安装插件.bat`。

不修改 `humanoid_retarget` 源码，不运行安装 BAT，不覆盖安装目录，不暂存、提交、推送或清理无关未跟踪文件。

C/C++、namespace、赋值对齐和引擎内存规则对本纯 Python 插件为 NotApplicable。Blender 4.2 未运行，兼容性保持 NotRun。

API 探针：`tests/out/spring_bone_api_probe.py` 与 `api-probe.log`。5.2.1 的 Action 为单层单条 KEYFRAME、slot `OB{name}`、旋转曲线在 channelbag；`Bone.convert_local_to_pose(..., invert=True)` 在静立姿势下得到单位 basis；`Scene.frame_set(frame, subframe=0)` 可用。探针只证明接口存在，矩阵和槽行为以动画测试为准。
