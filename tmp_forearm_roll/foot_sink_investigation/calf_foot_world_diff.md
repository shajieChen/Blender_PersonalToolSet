# 本轮差异

未修改正式插件、正式场景、正式动作和正式烘焙。

副本 `tmp_forearm_roll/humanoid_retarget/ik.py`：

- `_CALF_ROLL_APPLY` 增加 `inherit` 与 `restore_foot`。
- 新增 `_quat_deg`、`_local_quaternion_for_pose_orient`、`_foot_pose_delta`。
- 新增 `FOOT_POSE_LOG`。
- `_calf_roll_final_now` 在这两个模式下只于写回阶段（高度计划已设置）去滚转。
- `_apply_calf_roll_final` 增加 `keep_foot`、`restore_foot`。补偿只设置脚骨局部四元数，并保留脚骨原有 `location`。不写小腿位置通道，不调用端点平移锁定。

新增：

- `calf_foot_world_scan.py`
- `calf_foot_world_frames.csv`
- `calf_foot_world_pose_log.csv`
- `calf_foot_world_scan.log`
- `calf_foot_world_compensation.md`
