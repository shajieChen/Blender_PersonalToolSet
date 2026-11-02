# 三步装备实施与逻辑验证结果

```text
角色 + 装备 + 位置 -> 放置
缺握位 -> 首次设置 -> 保存或取消 -> 后续复用
逻辑验证通过 -> 用户人工核对 -> 必要清理与复验 -> 正式收尾
```

2026-10-30：逻辑实施及安装副本验证通过，待用户人工复核。未运行Computer Use，未宣告Visual或正式验收完成。

[设计档](../../specs/2026-10-30-humanoid-guided-equipment-design.md) / [实施档](../../plans/2026-10-30-humanoid-guided-equipment.md)

## 实际变化

- 主面板仅保留角色、装备、位置和一个主动作。高级设置默认关闭，旧子面板即使保存为展开也不会占据主界面。
- 当前状态实时计算，不显示旧的Pose Mode错误；跨部位不展示旧挂点，取下明确标明装备当前来源。
- 角色握位与装备拿法分别保存。首次设置通过原生视口工具移动/旋转，不要求使用3D光标。旧角色点保留偏移，只需确认一次。
- 多部件装备可固定为同一输入，角色设置时选择标记不会丢失装备。保存失败可重试，取消恢复进入设置前状态。
- 设置快照可随文件保存；新进程可以保存或取消。停用前先检查各场景，不能恢复时保留注册和恢复数据并明确报错。

## 验证证据

| 层级 | 结果 | 证据 |
|---|---|---|
| Static | 9个Python文件，编码/注释/依赖/生命周期专项通过 | [静态复核](static-review.md)、[源码哈希](source-manifest.json) |
| RED | selected=17，因缺少首次设置实现失败 | [RED](red.log) |
| Contract/Process/后台Runtime | Blender5.1.2 81/81、退出0 | [5.1.2最终结果](verified-final-5_1.log) |
| Contract/Process/后台Runtime | Blender5.2.1 81/81、退出0；--threads 1 | [5.2.1最终结果](verified-final-5_2.log) |
| 安装副本 | Blender5.1.2 首次设置25/25、退出0，真实安装路径核验 | [安装测试](installed-final.log)、[安装哈希](install-manifest.json) |
| 独立新进程重开 | 角色取消、装备多部件取消和保存均通过 | [角色取消](installed-role-reopen.log)、[装备取消](installed-equipment-cancel.log)、[装备保存](installed-equipment-save.log) |
| Generate | 人工复核场景生成，状态READY、高级区关闭、无设置会话、实际骨骼字段为空 | [生成结果](preview.log) |
| Visual / 实际Undo/Redo / 用户真实资产 | NotRun，等待用户人工复核 | 不由布局记录器或后台算子代替 |
| Build / 代码生成 / RealTransport / Apply/Resim | NotApplicable，纯Blender Python挂载功能 | 无这些目标 |
| 正式验收 | 尚待人工核对及收尾复验 | 不以逻辑GREEN替代 |

计数、实际退出码和日志SHA256见[validation.json](validation.json)。原挂载56项全部保留，新增首次设置25项；未重新运行未受影响的Spring/重定向全量，也未扩大修复旧metarig位移问题。

## 人工复核

保存当前工作并重启Blender后，打开[三步装备复核场景](../../../../tests/out/guided_mounts/automatic-mounts-preview.blend)。场景已预先明确校准，默认只需点“放到右手”；其校准不代表任意新角色或武器已自动适配。

自己的旧文件：选择角色，再选装备，点击“使用选中的物体”；选择位置。若提示首次设置，按主按钮移动标记或装备，保存即可；已有偏移不会被重置。测试取消、换部位、取下、实际Undo/Redo和保存重开。新装备为刚性部件；已有复杂层级、动画、约束等输入继续由高级工具处理或拒绝。

## 临时内容与收尾

本次生产临时日志、埋点、探针、轮询、计数、调试钩子及专用依赖均为无。主流程提示是正式交互；设置快照是正式可取消编辑数据，不能当作诊断删除。必要测试、夹具、故障注入和验收证据保留。

用户核对结果后，再确认本次临时项清单与差异，进行必要复验并提交最终完成报告。当前尚未到正式收尾。没有Git暂存、提交、推送或清理，无关dirty/untracked保持原样。
