# 裙面碰撞量化方法

## 用途与入口

用于动态骨骼、裙摆、腿脚的量化复核。无需截图，不在播放路径运行。正式工具：`tests/run_spring_bone_contact_audit.py`。在 BlenderMCP 主线程调用；会恢复活动 Action、Slot、帧和基础姿势，不修改源曲线或权重。

```python
import sys
sys.path.insert(0, "H:/Blender_Plugin/tests")
from run_spring_bone_contact_audit import audit_contacts
audit_contacts(
    "H:/Blender_Plugin/docs/superpowers/evidence/my-contact-audit",
    action_names=[bpy.context.scene.sb_target_armature.animation_data.action.name],
    step=.125,
    label="round-2",
)
```

前置：目标骨架已设置 `Scene.sb_target_armature`，有动态链及身体碰撞骨；`contact_garment` 与 `contact_body` 指向同角色的线性蒙皮网格。先停止播放与插件作业。第二个裙面可用 `garment_name="clothing.001"` 单独审计。所有相关裙面都要执行，不能只检查主对象。`repair_quaternions=True` 在临时副本中检查修复反号键后的姿势，源动作不变。

## 指标和判断

| 指标 | 含义 | 不能替代什么 |
| --- | --- | --- |
| `legacy_pairs` | 历史 5%/多数顶点过滤的交叉数，仅作对照 | 不能作为验收 |
| `hits[].pairs` | 完整裙面与身体指定部位的真实三角面交叉对数 | 不是穿透顶点数，也不是体积 |
| `part=foot` | 足/趾骨权重三角面，用于区分脚部和大腿 | 不能把正常外露的脚鞋判为穿模 |
| 独立截线 `maximum_segment` | 两个非共面三角面交线的最大长度，乘场景单位得到米 | 不是最大穿透深度 |
| `point_inside_votes` | 三个非轴向射线奇偶结果与最近表面距离 | 开放或非流形网格中只作证据，不能独立证明体积内外 |
| `geometry_unchanged/actions_unchanged/entry_restored` | 身份与数据恢复检查 | 不证明未采样时刻无碰撞 |

裙面：所选网格全部三角面，包括动态权重为零的固定接缝。关联裙面由同一骨架和动态链权重识别。身体：碰撞骨及其后代，三角面任一顶点有大于 `1e-8` 的归一化权重即纳入。不得使用“至少两顶点”“至少 5%”删除边界三角面。额外脚鞋若在其他网格，必须单列审计，不能默认一个 body 对象完整。

`depth_sum_m` 是局部平面两侧距离的累计启发值，只供搜索和定位，不能当作真实穿深。对象名相同不等于同一输入，必须保存动作、范围、单位、网格与曲线哈希。

## 至少两轮复核

先确认部位语义：一个名为clothing的对象可能同时包含裙摆、袖子和手套。袖子与腿交叉不等于裙摆穿模；零裙骨权重也可能是正确的手部绑定。必须先确认裙摆区域，并将非目标手部/上身位移不变列为保护门。几何交叉数下降不能代替人物蒙皮正确。

1. 第一轮整帧：记录当前实际 Action，分别比较原动作、旧结果；清点全部蒙皮对象、动态与脚部顶点数。
2. 第二轮：至少把时间网格减半，检查关键帧之间；单独审计其他裙面。不能只重复第一轮相同过滤。
3. 对失败帧调用 `independent_intersections(points, triangles, body_points, body_triangles)`。它使用三角面平面截线和线性区间重叠，独立于生产的边穿三角面算法。记录三角面索引及最大交线长度。
4. 保存失败帧的世界坐标、三角面索引、动态权重、动作/帧、单位到 JSON/NPZ。局部修复先复跑该样本，再整段，避免反复盲跑完整动画。
5. 零动态权重顶点不能被裙骨移动。涉及配重前须备份并获得授权。`tests/run_spring_bone_seam_weights.py` 提供精确顶点配重与恢复函数，禁止按整个网格自动改权重。

配重工具现在只允许自动调整原动态链合计权重已经超过50%的顶点；非动态主导或零动态顶点直接拒绝，不能因其出现在交叉面就自动提高到0.65。其他情况需人工确认区域与绑定职责，不作自动修补。2026-10-25的一次错误示范及其回退已明确保留，不能继续沿用其旧成品。

## 修复与 FBX 门

作业不只检查求解快照：写出候选 Action 后必须重新实际求值。当前作业复核步长为 `min(生成步长/4, 0.0625)` 帧；发现交叉就补该帧关键帧，最多三次加密，仍失败则恢复输入并删除候选。元数据记录 `sb_contact_validation_step`、范围与覆盖网格。

正式 FBX 复核入口：

```powershell
& 'H:\Blender\5.2.1\blender.exe' --background --factory-startup --python-exit-code 1 --python tests/run_spring_bone_contact_fbx.py -- <含corrected-character.blend的目录> <最终FBX> <可选实际场景NPZ>
```

NPZ 字段 `frames`、`cloth`；后者按 `garment_meshes()` 的对象顺序拼接世界坐标。FBX 回导按片段相对时间对齐；所有裙面、全部复核时刻都检查，源候选和回导任一有交叉均失败，最大位置误差必须小于 `2e-5` 米。进程非零、采样为空、只打印 JSON 都不算通过。

## 方法边界与来源

有限采样不是连续碰撞证明。快速运动或接近零间隙时继续细化并复核；共面重叠、完全包围、薄层厚度与布料自碰撞须另外定义指标。

- [VRM SpringBone 规范](https://github.com/vrm-c/vrm-specification/blob/master/specification/VRMC_springBone-1.0/README.md)：尾点球与球/胶囊碰撞，不能推导为裙面不穿模。
- [VRChat PhysBones](https://creators.vrchat.com/common-components/physbones/)：骨骼碰撞半径和明确碰撞体列表；角度限制也能减少进入身体的风险。这属于骨骼代理体方法。
- [Bridson 等，SIGGRAPH 2002](https://www.graphics.stanford.edu/papers/cloth-sig02/)：几何碰撞处理、厚度与接触，以及考虑碰撞的细分后处理。
- [IPC Toolkit 官方仓库](https://github.com/ipc-sim/ipc-toolkit)：支持线性与非线性轨迹的连续碰撞检测。当前插件未接入该库，不能声明具有其保证。

本次采用保持骨骼 Action/FBX 的局部补齐；没有把布料求解器或新的 C++ 依赖塞入插件。

实时重力预览的逐节方向、蒙皮响应、原生播放及暂停timer量化，另见[实时预览量化方法](spring-bone-realtime-preview.md)。完整表面交叉审计仍按本文，执行前先停止实时会话；不能把骨骼实时移动作为裙面防穿通过。
