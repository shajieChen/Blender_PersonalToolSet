# 自适应髋部竖直位移修订

## 目标

修复 FK 路径把髋到头顶比例用于竖直位移的问题。每组骨架按参考髋部到足部支撑面的高度自动计算比例；保持水平位移和身体旋转算法。此修订不承诺 FK 能消除全部脚底穿地。

## 修改范围

- `humanoid_retarget/retarget.py`：支撑高度、参考髋高比、FK 竖直分量。
- `tests/test_pelvis_height.py`：独立身体比例、对象缩放与位置、参考姿势、根运动、绑定网格和异常输入。
- 当前 Blender 5.1 已安装的 `humanoid_retarget/retarget.py`：只应用同一局部修改，保留其独有的 Datum、脚底接触和其他用户改动。
- 本档记录依据和执行证据。不得整包覆盖已安装插件。

## 实施步骤

1. 已读 `docs/design/design_foot_ik.md`、UE 5.7.4 `PelvisMotionOp.cpp`、当前与安装版 FK 局部代码；同任务未变化材料复用。UE 初始化使用目标/来源参考髋高；Rokoko 固定提交 `b031e5a001b3d87e62359d18159c4e4ab479c732` 使用映射 root 到最低映射骨头的高度比。
2. 一批并发探子分别核验 Rokoko 与现有测试入口；均已收敛，不重复派发。UE 参考实现由主代理完整阅读。
3. 先新增聚焦用例并运行 RED；再在作业准备阶段计算比例，帧循环仅缩放世界 Z。足部绑定网格优先，无网格时使用映射足骨及后代的参考端点。缺足映射时使用显式配置地面；无有效正参考髋高时明确失败。
4. 复核编码、换行、无新增注释、实际 bpy API、私有调用点及无关 diff；运行 Blender 5.1.2 聚焦与适用回归。失败保留日志，先定位再重跑。
5. 保存当前场景副本；在副本上应用同一局部算法验证真实动作。确认效果、保留原 Action 后，再提供当前动作预览。
6. 保存证据 → 与用户核对目标结果 → 清理本次临时诊断脚本 → 清理后聚焦与回归复验 → 最终报告。

## 强制约束

- 禁止角色名、文件名、动作名分支或硬编码骨架比例。通用长腿、短腿和同构骨架都须通过。
- owner 为一次烘焙调用；支撑高度只采样一次，无全局缓存、handler、timer、线程或公共选项扩张。
- 参数由 `RetargetOptions` 和实际映射进入；参考数据用 REST 或已捕获 CURRENT，物体平移不参与身材比例。
- 只改变 FK 髋部竖直位移；保持原 XY、IN_PLACE 和脚 IK 路径。无网格的足骨基准是近似支撑面，不冒充真实脚底。
- 保存修改前字节和安装版备份；局部替换前核对唯一命中与文件未变化。失败回退仅本次字节，不触及用户其他工作。
- 三种后续变化：换角色由参考数据适配；换比例由几何适配；换地面/站位由支撑基准适配。坡面、非骨骼变形修改器和动态对象变换不扩展实现。
- 不执行 Git 暂存、提交、推送、清理或广泛回退。C/C++ 格式、ABI、MemLabel 门不适用：本次只改 Python。

## 验收标准

- RED：`tests/out/pelvis_height_red.log`，selected=6，5 个错误比例用例失败，同构比例通过。
- GREEN：`tests/out/pelvis_height_green.log`，selected=6，全部通过；后续扩展用例按实际日志记录。
- 命令：Blender 5.1.2 `--background --factory-startup --python-exit-code 1 --python tests/run_pose_channel_tests.py -- test_pelvis_height.py`。
- 回归入口 `tests/run_retarget_test.py`；已有 unrelated 失败必须与修改前同版本比较，不能改断言掩盖失败。
- 实际动作区分髋高修正与脚底不穿地；验证第 18 帧、全片段和相邻帧，单独记录 Runtime/Visual，未执行保持 NotRun。
- 当前与安装版原始字节备份：`tests/out/pelvis_height_20261022/`。报告所有修改文件和剩余限制。
- 临时诊断：仅一次性背景验证/预览脚本及输出；无产品运行埋点、计数、轮询或新依赖。自动测试、必要证据和原始回退备份保留。

## 禁止事项

不整角色抬高，不改骨长、rest、蒙皮或来源动画，不把脚底检测替换成踝点检测后宣称网格验收通过，不移植 UE C++，不重写已有 IK，不安装第三方商业插件。

## 执行结果与收尾

- 用户已确认：髋部修订符合预期，继续收尾。
- 新增 11 项自适应用例通过；安装版同一局部补丁 11 项通过。初次 RED selected=6、5 failed；CURRENT 缺矩阵补充 RED selected=11、1 failed，修订后全部通过。
- 既有根运动/参考/同片段/站位/旋转聚焦回归 selected=8，通过。真实 pose-scale 脚本 selected=1、POSE_SCALE_OK。
- 完整回归 Blocked：`ik stays off unless enabled`，修改前 baseline 同样失败，未更改旧断言或用户 UI 默认值。
- 当前真实场景副本 10 动作、502 帧：第 18 帧髋高 0.1141808→0.2901098m，脚底 -0.2856419→-0.1097133m。XY 最大误差 1.2e-7m，旋转分量最大误差 1.5e-7。
- 当前仅应用已确认的一个动作副本 `Bip01_PelvisHeight_a050_300000`，保留原 Action；其余旧烘焙动作未覆盖。插件补丁已安装，后续重定向需重启 Blender 加载新代码。
- 用户原场景仍为未命名状态，已另存 `tests/out/pelvis_height_20261022/scene_pelvis_height.blend`，原状态备份 `scene_before.blend`。
- 临时诊断清理 Blocked：自动审批先拒绝递归删除，再拒绝逐文件删除，均只返回 blocked by policy。未执行删除；`baseline/`、`installed_candidate/`、`verify_scene.py` 尚存。它们仅在证据目录，不被产品运行依赖。不得宣告最终完成；清理后复验 NotRun。
- 正式自动测试、日志、数字报告、输入/输出关键帧、原始代码备份和两个场景副本保留为必要证据与回滚资料。无新增产品日志、timer、handler、轮询、计数或诊断开关。
- 效率复盘：独立复核批次发现 CURRENT 缺矩阵边界，取得 RED 后补齐。pose-scale 脚本首次误走 unittest 得到 selected=0，不计通过；改用其实际 main 入口后 selected=1、POSE_SCALE_OK。
- Static/Contract Passed；Python Process/Runtime（公式与真实动作）Passed；Visual 已由用户确认髋部效果。脚底完全不穿地没有完成证明。C/C++、Generate、ABI、MemLabel、RealTransport、Apply/Resim 均 NotApplicable。
- 参考：UE 5.7.4 `PelvisMotionOp.cpp:193-225,284-339`；Rokoko `operators/retargeting.py:330-362`，固定提交 b031e5a001b3d87e62359d18159c4e4ab479c732。本插件采用参考髋到支撑面高度比，仅修正 Z，保留现有 XY，不声称完整移植任一参考实现。
