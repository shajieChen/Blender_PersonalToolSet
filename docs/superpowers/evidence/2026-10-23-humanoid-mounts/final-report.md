# 人形挂点插件完成报告

```text
实际骨骼 -> 挂点 Empty -> 握持根 Empty -> 刚性武器/道具
用户确认 -> 精确清理 -> 清理后复验通过
```

2026-10-24：实施完成，已单包安装至 Blender 5.2.1 LTS。用户已明确确认“符合目标，继续清理复验”。随后清理与必要复验均通过。

## 交付与使用

六个产品文件位于 H:\Blender_Plugin\humanoid_mounts：__init__.py、properties.py、mounts.py、weapons.py、operators.py、panels.py。另新增三个聚焦测试、测试 runner 和演示入口；安装插件.bat 仅新增两行本包安装项。实施档和本证据目录已更新。

安装位置：H:\Blender\5.2.1\portable\scripts\addons\humanoid_mounts。插件偏好中启用 Humanoid Mounts，在 N 侧栏进入“人形挂载”；本任务未保存用户启用偏好。

1. 选择人形与实际骨骼，选择右手/左手/背部/腰部/头部，创建挂点。
2. 放置并校准 3D 光标到武器握位，选择刚性部件创建握持根；也可登记已有本地 Empty。
3. 选择挂点，吸附绑定或保持世界位置绑定；在折叠区编辑偏移。掌心/装备位置需要手动校准。
4. 解除保持当前世界位置；删除挂点保留附件。复制、改名、换骨骼、原生 Undo/Redo 和保存重开已测。

预览：[humanoid-mounts-preview.blend](../../../../tests/out/humanoid_mounts/humanoid-mounts-preview.blend)。使用说明：[handover.md](handover.md)。

## 验证与硬门

| 门 | 结果与证据 |
|---|---|
| Static、命名、依赖、零注释 | Passed；11 文件 AST/compile/tokenize、依赖无环、无生产跨插件导入；final-static-audit.json |
| Contract | Passed；整套 34，矩阵误差门 1e-5；可归因 RED/GREEN 和零选择负控分别保留 |
| 聚焦与回归 | Passed；transform 7、lifecycle 21、整套 34、Pose 13、Spring 68，selected>0、成功标记、退出 0；post-cleanup-*.log |
| 生命周期与错误恢复 | Passed；部分注册失败、重复启停、创建/重绑/删除失败恢复、循环拒绝及两人形隔离 |
| Process / Runtime | Passed；5.2.1 LTS hash 9e2066aef7ef，原生骨骼跟随、Collection Append、新进程重开七对象，前台 Undo/Redo |
| Visual | Passed；亲自查看第 19/37 帧五部位及剑盾，PID 51780，16 个不同播放帧，自然退出 0，无错误；visual.md |
| 安装 | Passed；六文件源/目标哈希一致，实际安装目录加载，独立启停；post-cleanup-installed.log |
| 数据与范围保护 | Passed；初始四个 dirty 文件哈希保持。其他工作更新的 Spring 求解器与测试原样保留，本任务未修改。BAT 原字节加两行，无 Git 写操作 |
| 用户确认、临时诊断、清理后复验 | Passed；cleanup.md、cleanup-files.json。无产品临时调度或诊断依赖，正式测试默认不运行 |
| C/C++ 编码/成员对齐/赋值对齐/namespace/三元分组 | NotApplicable；没有 C/C++ 文件变更 |
| unique_ptr label / raw pointer / C++ allocator / API与ABI | NotApplicable；纯 Python 原生 bpy 对象关系 |
| Build / Generated / RealTransport / Apply/Resim | NotApplicable；没有编译、代码生成、网络预测目标 |
| 正式验收 | Passed；限定本次五个人形部位与刚性附件；completion-audit.md |

原始 Spring 基线为 67；最终复验时另一项工作增加测试并更新求解器，当前 68 项全过。其变化不归于本插件。Pose 基线已有模块名提示，回归仍通过；后台 Undo poll 不可用的记录由实际前台 Undo/Redo 覆盖，未冒充后台通过。

## 限制与恢复

仅验证本次 Blender 5.2.1 和程序化人形夹具。用户具体 Rig、其他版本保持 NotRun。不含自动握拳、动画换手、双手 IK、衣甲蒙皮、碰撞或导出。不支持的链接数据、动画根、奇异矩阵/不可保持剪切等预检拒绝。

无需逐帧 Python 跟随，注销保留原生对象和绑定。若需停用，在偏好中关闭本插件；需要解除时先用插件解除保持位置。卸载包不能代替场景解绑。只安装本包，未执行全量 BAT 或推送。

完整收据：[evidence-index.md](evidence-index.md)。
