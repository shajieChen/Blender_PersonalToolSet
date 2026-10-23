# IK 坐标空间修复报告（独立副本，未合并正式插件）

## 修改清单

采用方案 B：给 `MotionSpace` 增加明确的世界入口，只改传错的调用点。骨架空间入口 `position()` 和已正确传骨架坐标的姿势通道调用点没有动。

| 文件 | 修改 | 原因 |
| --- | --- | --- |
| `motion_space.py` | 新增 `world_position(world)`：先用 `object_matrix.inverted()` 回到骨架空间，再走 `position()`；新增 `world_rotation(world_matrix)` 同理 | 世界到骨架的转换只在入口执行一次 |
| `ik.py` `apply_contact_ik` | 来源/目标关节头、末端旋转改走 `world_position` / `world_rotation`（原传 `matrix_world @ head`） | 输入是世界坐标，接口要求骨架坐标 |
| `ik.py` `transfer_source_fold_pole` | 来源三关节、目标根和静止三关节改走 `world_position` | 同上 |
| `ik.py` `_solve_chain`、`_apply_two_bone_aim`、`_fold_opposes_bind` | 根、静止参考、末端复核、膝位置改走 `world_position` | 同上，求解器内部全程同一空间 |
| `retarget.py` `_prepare_retarget_geometry` | `head_world`、`rest_head_world` 的非通道分支改走 `world_position`；末端旋转改走 `world_rotation` | 静止链长和 `height_offset` 的来源 |
| `retarget.py` `_hips_translation_with_floor`、`_sample_foot_motion` | 非通道分支改走 `world_position` | 骨盆当前高度和脚速采样 |
| `retarget.py` `_solve_pose_channel_chain` | 根和静止参考改走 `world_position` | 通道路径的求解入口传的是世界坐标 |

没有改：`position()` 本身、姿势通道中传 `pose.head` 的调用（本来就是骨架坐标）、FK 路径 `_apply_body_orientations`、`_hips_translation`、前臂 Roll。

副本哈希（修复后）：`motion_space.py` 4DA6582C…773DFE，`ik.py` CD46E8E7…39EEE，`retarget.py` B11C1711…03B11。正式插件 `retarget.py` 仍为 5D679723…80AC06F，未改。

## 验证结果（已实测）

第 24 帧：腿长恢复 0.2542/0.1907，`height_offset` -0.0149，求解末端误差 0，烘焙与求解一致，网格最低 -0.0022 米。详见 `coordinate_fix_frame24.md`。

四帧与全范围（0–52，共 53 帧，动作 `a050_300000`，逐帧依赖图网格扫描，见 `coordinate_fix_frames.csv`、`full_frame_ground_scan.csv`）：

- FK 基准：53 帧网格最低点全部低于 -0.01 米，最差 -0.2856（第 18 帧）。
- 坐标修复后脚 IK：43/53 帧不低于 -0.01 米。仍穿地的 10 帧：第 4 帧 -0.0107；第 16–19 帧 -0.0556、-0.0733、-0.0895、-0.0336；第 28–32 帧约 -0.016。
- 求解器末端误差全范围 0.0000（目标在踝，求解器确实到达目标）。
- 大腿、小腿长度全范围保持 0.2542/0.1907。
- 膝角相对 FK 最大变化：左 22.4°（第 17 帧），右 12.8°（第 16 帧），方向没有翻转。
- 骨盆相对 FK 最大抬高 0.180 米（第 17 帧），第 24 帧抬高 0.106 米。
- 左前臂局部四元数在 FK 与 IK 两组逐帧字符串相同，上半身没有被脚 IK 改动。

## 判定

坐标空间错误已修复（目标、长度、求解、烘焙四层一致）。现有脚 IK 仍不能满足全范围防穿地：第 16–19 帧穿地 0.034–0.090 米，属于情况 B。原因不在坐标：这几帧来源动作本身脚部位置低、骨盆下沉深，现有约束只把踝目标按来源踝高衰减，没有脚掌接触概念，骨盆又被抬高，脚掌最低点仍能穿过地面。

下一步应先提交脚掌接触机制的设计（接触参考点、支撑期检测、脚掌目标、有限骨盆补偿的优先级），再在独立副本实验。不要继续调踝目标偏移。
