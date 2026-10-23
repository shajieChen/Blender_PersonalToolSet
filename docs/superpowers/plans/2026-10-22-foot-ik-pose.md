# 脚 IK 弯曲方向与缩放修订

## 目标

来源膝盖给出的有效弯曲方向应优先于绑定姿势兜底；旋转求解不得改变输入局部缩放。禁止角色特例、固定补偿角或修改绑定骨架。上一批髋高修订已单独提交推送 main（9a1929b）；本批未获 Commit/Push 授权。

## 修改范围

- `humanoid_retarget/ik.py`：`_solve_chain`、`_aim_joint`、`_write_end_rotation`。
- `tests/test_ik_pose.py`：有效来源 pole、无来源兜底、旋转写入不改变缩放。
- Blender 5.1 安装版 `humanoid_retarget/ik.py`：同一局部差异，不覆盖现有接触修正、Datum 或用户修改。

## 实施步骤

1. 复用已读脚 IK 设计；主代理已读当前目标函数、安装版接触修正、MotionSpace，以及 UE `TwoBoneIK.cpp` 和 `LimbSolver.cpp:1-291`、`AnimNode_TwoBoneIK.cpp:135-163`。独立一批探子仅核验插件差异和 UE Limb 朝向机制，不重复读奠基文档。
2. 已保存 `tests/out/foot_ik_twist_20261022/scene_before.blend` 和两版 IK 原始字节。第 16 帧源/目标膝盖弯曲、骨骼矩阵、缩放与动画输入见 case.json。
3. 单变量实验：从单位缩放开始重复烘焙仍产生缩放漂移；可信来源 pole 被绑定侧修正覆盖，右膝平面与来源偏离。单帧保留来源 pole 后右膝平面更接近来源。不能把这些事实等同完整视觉修复。
4. RED selected=4，3 failed，日志 red.log；仅修复已归因的三个断言。来源 pole 缺失时保留绑定兜底；保存并恢复每次旋转写入前的局部 scale，不清零用户缩放。
5. 检查完整局部 diff、编码/末尾换行、无新增注释与实际 bpy API，再跑聚焦、既有 pole/fold/髋高与受影响回归；修改后必须重新验证。C++ 不修改，不运行 UE 构建。
6. 单帧及完整动作验证使用当前场景副本；只有结果闭合后安装局部补丁并提供新 Action 预览，原动画与输入场景保留。
7. 保存证据 → 与用户核对目标结果 → 清理本批临时诊断 → 清理后复验 → 最终报告。未完成的门保持 NotRun/Blocked。

## 强制约束

- 所有 bpy 调用属于当前主线程，运行实验采用独立后台进程；无产品 timer/handler、轮询、日志或新全局状态。
- 成员/方法命名、命名空间、MemLabel、ABI 等 C/C++ 专项门 NotApplicable；Python 业务命名、无新增注释、局部差异与依赖边界仍需核对。
- 无效/近直来源方向继续使用已有退化处理；本次不重写两骨余弦公式、Floor/Planting、脚底补偿和手部 FK。
- 不修改 `align_pole_to_bind_side` 的既有独立函数合同；只纠正明确有来源 pole 时的调用策略。
- 优先原理：UE Limb 使用当前动画弯曲方向，基础 TwoBoneIK 对 Rotation/Translation 分别写入；Blender FULL 父缩放可传播剪切，不能把完整矩阵回写后的 scale 漂移当动画曲线。
- 三个变化检查：不同骨轴/roll 使用关节点与来源 pole；不同对象统一缩放保留现有空间转换；无来源 pole 保留绑定兜底。不同动作与重烘焙须独立验证，不引入角色名分支。

## 验收标准

- `blender.exe --background --factory-startup --python-exit-code 1 --python tests/run_pose_channel_tests.py -- test_ik_pose.py`，selected>0 且退出 0。
- 既有 `test_ik_pole.py`、`test_limb_fold.py`、`test_pelvis_height.py` 和合适的真实动作回归分别报告。
- 数值：保存局部缩放、末端可达残差、来源与目标膝盖平面、相邻帧连续性、骨长、重复执行一致性；来源真实翻转不能简单记作目标失败。
- Visual：检查第 16 帧与相邻帧图像，由用户确认改善；不得仅靠数字或截图已保存宣称麻花消除。
- 诊断仅为进程内函数拦截、临时模式和 JSON/日志，没有产品入口。证据、正式测试、原始备份保留。若自动审批阻止清理，明确记录并保持收尾 Blocked，不变换手段绕过拒绝。
- 效率复盘：首批后台烘焙未清除来源 NLA，实际纳入 10 动作而非预期单片段；两个实验已自然结束（未终止用户 GUI）。后续先用单帧直接求解定位，仅在验收阶段运行全片段，按真实动作集合限制输入。

## 禁止事项

禁止对角色写死角度、换骨长/roll/parent、关闭用户骨骼缩放继承、删动画或忽略失败测试。禁止覆盖安装目录整包或清理其他 dirty/untracked 工作。本批不得自动 Commit/Push。
