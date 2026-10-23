# 本轮差异

未修改正式插件、正式场景、正式动作和正式烘焙。
未修改 `tmp_forearm_roll/humanoid_retarget/ik.py` 与 `retarget.py`。
Roll 的 Swing-Twist、写回和旋转关键帧保持原样。

新增：

- `calf_parent_location_scan.py`：在已烘焙姿态上临时给小腿父空间 `location` 的一个分量加 0.1，求值后丢弃。
- `calf_parent_location_frames.csv`
- `calf_parent_location_vertices.csv`
- `calf_parent_location_scan.log`
- `calf_parent_location_experiment.md`

变量只有一个：`Bip01 L Calf` 或 `Bip01 R Calf` 的 `location[0|1|2]`，父骨为同侧大腿。脚的 `location` 与 `rotation_quaternion` 不写。
