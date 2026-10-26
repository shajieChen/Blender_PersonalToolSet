# 人形挂点交付说明

状态：已完成。用户已确认效果，精确清理与清理后复验通过。最终事实见 final-report.md。

已安装：`H:\Blender\5.2.1\portable\scripts\addons\humanoid_mounts`。在插件偏好启用 Humanoid Mounts，N 侧栏选择“人形挂载”。测试未保存用户实际启用偏好。

预览：`H:\Blender_Plugin\tests\out\humanoid_mounts\humanoid-mounts-preview.blend`。原生关系和输入动画不依赖插件逐帧求值；面板需要启用插件。

操作顺序：

1. 明确选择人形，选择部位和实际骨骼，创建挂点。默认骨骼原点，需要校准掌心或装备位置。
2. 将 3D 光标位置/方向置于武器握位，选择刚性部件，创建握持根；或显式登记已有本地 Empty。
3. 选择当前人形所属挂点，以吸附或保持位置绑定。解除时保留当前世界姿势。
4. 偏移与显示折叠区可选择挂点/道具偏移，使用原生变换控件；校准时关闭自动关键帧。

证据：清理后新插件 34 项、Spring Bone 68 项、Pose 13 项均退出 0；五部位新进程重开、武器 Collection 复用、故障恢复和前台 Undo/Redo 已分别核验。

已核对源文件无范围外修改，初始已存在的四个 dirty 文件保持原哈希；无 Git 写操作。安装 BAT 仅多两行 ASCII。

边界：程序化人形夹具已测，用户具体模型、其他 Blender 版本未测；不含换手、双手 IK、自动握拳、衣甲蒙皮、碰撞或导出。

收尾全部通过；证据索引见 evidence-index.md，Goal 对照见 completion-audit.md。
