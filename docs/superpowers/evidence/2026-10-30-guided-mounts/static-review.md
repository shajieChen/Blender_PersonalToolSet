# 三步装备编码与生命周期复核

日期：2026-10-30。源码路径以仓库根为基准，证据链接相对本文目录。

检查文件：humanoid_mounts/{__init__,properties,operators,panels,weapons,mounts,placement}.py，tests/test_humanoid_mounts_guided.py，tests/run_humanoid_mounts_automatic.py。具体SHA256见[source-manifest.json](source-manifest.json)。

| 门 | 结果与依据 |
|---|---|
| 规则、范围与编码 | Passed。Git root/remote已核对；起始备份逐字节比对原UTF-8/BOM、CRLF/LF和末尾换行状态；内存compile及git diff --check通过；无关mmb修改保留。 |
| 命名与局部结构 | Passed。placement管理装备步骤和设置，weapons/mounts仍管理原生关系；没有Manager/Context、通用工作流框架或重复识别器。 |
| 禁止新增注释 | Passed。9个Python文件token/AST检查，无comment/docstring新增；本包源文件原本也没有注释。 |
| 依赖方向 | Passed。panels/operators -> placement -> weapons/mounts -> properties；不反向import，不接入重定向私有函数。EquipmentStatus为4字段只读结果；EquipmentObject为明确对象引用记录。 |
| 所有权与生命周期 | Passed。Scene.hm_settings拥有输入和快照；Object/parent用指针保存，恢复不按名字查找。只删除fitting_created且归属明确、无外来附件的新点。开始/保存/取消/停用成对；停用前全场景预检；重开后多部件保存/取消验证。 |
| 失败与回滚 | Passed。错误角色/位置/装备变化拒绝保存；保存故障保留编辑入口姿势及原快照；取消先验证全部记录，恢复故障回到取消入口状态。损坏快照不静默注销或丢失恢复数据。 |
| 输入和即时反馈 | Passed。主流程使用显式装备，不被选中标记覆盖；当前位置与放置目标分别表述；取下按钮使用明确装备并显示来源。多个点按当前角色/部位选择。主要按钮错误即时report，过期status只在高级区标明上次操作。 |
| 线程、依赖图与持续开销 | Passed。仅主线程bpy算子，无timer/worker/frame/depsgraph/load handler新增；完整draw与状态查询禁止world_matrix依赖图更新的合同测试通过。 |
| API、兼容和矩阵 | Passed，夹具范围。保留旧算子入口；角色握位采用可选hm_grip_fitted确认标记，旧点不重置但需确认一次；重置/换骨骼使确认失效。变换继续由原生父级求值，<=1e-5合同通过。 |
| 回滚和安装边界 | Passed。安装前核对全部本包文件与起始副本，备份到tests/out/guided_mounts/installed-before，7文件变更、8文件核验。回退前应先保存或取消当前设置，再按精确文件恢复；不整包覆盖其他插件。 |
| m_成员声明变量名对齐 | NotApplicable：无C/C++修改。 |
| 连续赋值普通=及逗号对齐 | NotApplicable：无C/C++修改。Python保留既有局部风格。 |
| namespace Tab与形参/实参三元分组 | NotApplicable：无C/C++修改。 |
| C++14、项目容器/字符串/allocator及ABI | NotApplicable：纯Python，无C++工具链或ABI变更。 |
| unique_ptr label门 | NotApplicable：无owning unique_ptr。 |
| C++生命周期对称与raw pointer借用门 | NotApplicable：无C++对象或裸指针；Python/Blender生命周期另列。 |
| 日志与诊断宏隔离 | NotApplicable：非指定引擎C++；本次没有生产诊断代码。 |
| 临时诊断与证据分层 | Passed，源码层。生产临时项为无；设置快照是正式取消功能数据，测试/故障注入/独立重开脚本为必要测试，均保留。Visual、实际Undo/Redo与正式验收不由后台合同替代。 |

复核后两版本各81项通过、安装副本25项通过。真实视口交互和用户资产仍NotRun。
