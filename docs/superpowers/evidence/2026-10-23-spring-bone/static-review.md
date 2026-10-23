# 动态骨骼静态复核

日期：2026-10-23。对象：`spring_bone/*.py`。用内存 `ast.parse` 与 `tokenize` 检查，未写 pycache。

| 文件 | 行尾 | docstring | 注释 | 导入 |
| --- | --- | --- | --- | --- |
| `__init__.py` | LF | 无 | 无 | `bpy` |
| `properties.py` | LF | 无 | 无 | `bpy`、`bpy.props`、`bpy.types` |
| `panels.py` | LF | 无 | 无 | `bpy`、`bpy.types`、`operators` |
| `operators.py` | LF | 无 | 无 | `animation`、`bpy`、`bpy.props`、`bpy.types`、`mathutils.Matrix`、`solver`、`time` |
| `animation.py` | LF | 无 | 无 | `bpy`、`dataclasses`、`mathutils`、`solver`、`time` |
| `solver.py` | LF | 无 | 无 | `dataclasses`、`math`、`mathutils` |

`solver.py` 不导入 `bpy` 或 `humanoid_retarget`。`spring_bone` 包内没有 `humanoid_retarget`、`frame_change`、`depsgraph_update`、`threading`、`hr_actions`、注释或 docstring。统一缩放预检写入 `animation.py` 之后又做了一次内存 `ast.parse`，六个文件都是 LF，编译通过。活动任务是操作器模块里的一次会话，不是通用注册表。

`bl_info` 最低版本为 `(5, 2, 0)`。Blender 4.2 未运行，兼容性为 NotRun。C/C++ 与构建门为 NotApplicable。
