# 第六阶段：前臂 Roll 连续性

修订只在 `tmp_forearm_roll/humanoid_retarget/retarget.py`。正式插件 SHA256 仍是 `A018034B2D24F8FF99473BF00DE4E0DCD41480C47E9899301212DCF3920D245A`。正式场景、`final_bake.blend`、`acceptance_bake.blend`、`BASELINE.txt` 未改。

## 根因

旧连续状态在 `options._forearm_roll_memory`。它不在场景、Action 或关键帧里。`_bake_retarget` 每次烘焙前清空它。若 `previous["frame"] != frame - 1`，函数直接返回逐帧最短摆动 P0。倒序、跳帧和单独求值因此失去连续姿态。

退出同时要求链与静止方向夹角 `< 150°` 且相对 P0 的扭转 `<= 8°`。进入后只做“搬运上一姿态 + 绝对 Twist 标量差”，没有把偏差拉回 P0。本片段第 33 帧进入（夹角 166.252°）。第 39 帧 P0 跳约 129°，连续输出只走 5.910°，偏差变成 141.195°。第 52 帧夹角已是 76.699°，偏差仍是 167.247°，退出条件到不了。这是状态机和目标构造的问题，不是记忆被写坏。

相邻帧绝对 Twist 标量相减也不是相对旋转的扭转。第 18→19 帧来源局部旋转 26.916°，绝对标量差 +160.076°，相对四元数绕当前链的扭转是 +47.668°。把标量差写进目标姿态会在奇异点附近注入不存在的滚转。

固定 8 帧把约 150° 摊回去已被否定：B 最大步 35.579°、肘部 0.0507 米；C 最大步 58.346°、肘部 0.0756 米。本阶段没有采用。

## 求解

坐标空间：

1. 来源静止相对旋转在来源骨架空间：`pose.matrix @ rest.matrix_local.inv`，`w >= 0`。
2. 目标链方向 Desired 在目标骨架空间：`target_body @ (source_body.inv @ source_chain)`。链是本骨头部到下一映射关节头部。
3. P0 是静止朝向经最短摆动对准 Desired，再绕 Desired 加上来源绝对链扭转。它只作为区间第一帧的初值。
4. 之后每一帧：用上一 Desired 到当前 Desired 的最短旋转搬运已解姿态，再加上来源相对四元数 `q_t @ q_{t-1}.inv`（`w >= 0`）绕当前来源链的扭转。该扭转施加在目标当前 Desired 上。
5. 返回的是缓存里的骨架空间朝向本身。不把这个滚转再钉回当帧 P0。钉回 P0 会在第 39 帧把步长抬到 28.401°，34–40 帧窗口最大 80.801°。
6. `forearm_roll_cyclic` 默认关闭。打开时，用末帧相对首帧、绕末帧 Desired 的接缝扭转，按帧序号比例分到整个区间。本片段接缝已是 0°，开关结果相同。

必须满足的是当前链方向，以及来源相对旋转绕链的那一维。P0 的滚转不是每帧硬约束。时间连续性来自整段积分，不来自“上一帧恰好被求值过”。

缓存签名是 `(start, end, cyclic)`。烘焙前按该区间建一次。实时求值若签名相同则复用；缺失时从区间起点重建。同一区间内正序、倒序、单帧和随机跳帧读同一张表。区间外的帧没有记录，退回 P0。

## 实测

脚本：`exit_root_cause/verify_roll_cache.py`、`print_steps.py`。无保存。左前臂局部基旋转：

| 量 | 结果 |
| --- | --- |
| 38→39 | 4.246° |
| 39→40 | 4.784° |
| 34–40 最大步 | 9.601°（第 35 帧） |
| 第 39 帧方向误差 | 0° |
| 第 39 帧肘部相对 P0 的位移 | 0.005 米 |
| 第 39 帧相对 P0 的姿态差 | 64.233° |
| 第 52 帧相对第 0 帧 | 0° |
| 正序重复、倒序第 39 帧、单帧 19/39、随机路径第二次到 19 | 0° |
| 右前臂与双上臂的重复差 | 0° |
| 循环开关下 34–40 与肘部 | 与默认相同 |

已验收窗口没有退回 129° 跳变，肘部优于旧锁存的 0.0084 米。第 19 帧局部步长仍是 165.997°。上臂仍是逐帧最短摆动，父骨变化会进入前臂局部基。这一项继续单独开放，整段不能标成连续性通过。区间开头也有大步：第 1 帧 88.371°、第 2 帧 82.492°、第 3 帧 142.000°。

## 来源与限度

- Blender Dependency Graph（https://developer.blender.org/docs/features/core/depsgraph/）：求值按变化的数据块进行，不保证调用方按帧号顺序执行。它说明不能把“上一帧内存”当动画状态。它不证明本插件的扭转公式。
- Bake Action（https://docs.blender.org/manual/en/3.6/editors/nla/editing.html）：烘焙逐帧求值最终运动并写入关键帧。回放关键帧与求值顺序无关；重新求解只有在结果是片段的函数时才与顺序无关。
- FCurve.evaluate（https://docs.blender.org/api/current/bpy.types.FCurve.html）：单通道按帧求值，外推为常数或线性。它不给出骨骼矩阵。
- Hanson、Ma，Parallel Transport Approach to Curve Framing，1995（https://scholarworks.iu.edu/dspace/bitstreams/23d6fd59-b151-4064-88a7-f7e058b2cc69/download）：平行搬运避免曲率为零时的 Frenet 翻转；闭合曲线的标架一般不回到起点，完整角是挠率积分。他们按弧长比例加切向自旋使标架闭合。这证明按比例分配接缝自旋是一种闭合几何标架的做法。它不证明把 150° 压进 8 帧合理，也不证明本片段必须闭合。默认因此关闭循环；打开时按帧序号而不是弧长，因为接缝是时间循环。
- Wang 等，Computing Rotation Minimizing Frames using Quaternions，CAD 9(5)，2012（https://www.cad-journal.net/files/vol_9/CAD_9(5)_2012_679-690.pdf）：四元数旋转最小标架。不解决重定向扭转标量。
- Allen Chou，Swing-Twist Interpolation（https://allenchou.net/2018/05/game-math-swing-twist-interpolation-sterp/）：摆动与扭转分解，以及 180° 奇异。证明分解，不证明逐帧独立最短摆动在时间上连续。
- chomnr MathQ（https://sbox.game/notpointless/chomnr_humanoid_retargeter/source?file=Code%2FHumanoidRetargeter%2FCore%2FMaths%2FMathQ.cs）与 chadmv/cmt `swingtwist.py`（https://github.com/chadmv/cmt/blob/master/scripts/cmt/rig/swingtwist.py）：单姿态的摆动扭转。没有时间轴随机访问，也没有循环接缝。

没有找到同时满足这两点的公开 Blender 重定向实现：用相对旋转的链扭转替换逐帧最短摆动的滚转，并且在随机帧访问和循环闭合下结果确定。
