# 插件内动态骨骼预设验证

日期：2026-10-26。状态：用户已确认符合预期，清理及清理后复验通过，实施完成。用户随后授权发布到origin/main。

## 来源与实现

[VRM官方SpringBone规范](https://github.com/vrm-c/vrm-specification/blob/master/specification/VRMC_springBone-1.0/README.md)提供链/关节参数与球胶囊局部定义；[VRChat官方PhysBones](https://creators.vrchat.com/common-components/physbones/)提供用途/身体区域划分、根与忽略子树思路。采用配置结构原则，不照搬其他求解器数值。本地四种链系数来自本solver的编辑起点，三种身体模板按关节/骨长比例换算，仍可手调。

新增presets.py和preset_operators.py，JSON保存在插件preset_data。复用原_selected_chain、validate_parameters及只读人形名称分类；不修改solver、动画公式、权重或Retarget源码。原不互相导入边界在设计第13节明确扩展为可选只读人形识别，未偷偷引入求解依赖。

## 量化结果

- 预设聚焦24项；完整Spring5.2工作区147项、5.1正式安装147项，进程退出0，未跳过。
- 动态Enum默认值RED、几何识别/控制骨/短标记RED均保存；修复后完整回归通过。
- 实际场景：目标骨架8条四节裙链、32节，7个下身代理体；根名和所有绑定见live-match.json。初始错误几何方案仅匹配检查，未应用，保存在live-match-initial.json。
- 当前角色19个身体角色明确对应真实身体骨；不再把head/刘海/耳朵认作骨盆或腿。另一源骨架控制裙骨由12条候选降为6条真实候选。
- 四个腿部胶囊8个轴端与Rest关节间距公式最大误差5.960873736104565e-8米。
- body、clothing、clothing.001、hair、hair.001、head.001六个网格/权重哈希、Rest、输入Action曲线保持；时间/选择保持。
- 重复匹配链和碰撞体均0新增。用户预设user/ChibiSkirt.json可保存/回读8链7体；源目录包含4链模板、3人形模板。头发/尾巴另有9/4条候选，本轮未添加。
- gizmo骨骼3904个线顶点、碰撞体1344个线顶点；正式绘制handler保持，不通过截图评估。
- 13个Python文件与builtin.json从正式安装位置逐项SHA一致；独立新进程自动启用Spring/Mounts，预设面板及已保存JSON可用。Mounts正式安装回归34项通过。

## 生命周期与风险

匹配计划为操作器拥有的JSON值，用户对象仅借用；无跨帧模拟缓存。目标/Rest/单位/缩放/配置快照改变则拒绝，全部预检后才写，异常回滚新增集合及旧参数。Session存在时禁止写入。确认框显示候选并逐项选择。文件独占创建、同名拒绝、禁止路径穿越，加载不执行代码。

没有新增持久诊断、计数、采样、timer或回调。既有正式绘制资源与用户配置是功能，不删除。单次同步MCP审计无持续调度。测试/日志/JSON与用户偏好本地备份是必要证据/回滚项，保留；偏好原始二进制不放仓库。C++/unique_ptr/raw pointer/ABI门NotApplicable，Python值/借用与失败回滚Passed。

当前代理碰撞初始尺寸不是完整网格拟合，也未执行本轮完整裙面防穿/FBX零穿插验收；这些为NotRun。人形识别可选依赖Retarget包存在，不要求其运行；未知名称明确缺失，不猜。

## 收尾

源材料、正式代码、数据和安装均已复核。用户确认“符合预期，可以收尾”后，核对临时namespace和已知探针回调无残留，额外临时文件/handler/timer均为空，无需删除正式功能。随后双版本清理后再次各147项通过；14个安装文件哈希一致，8链32节7体及用户预设回读仍有效，重复匹配0新增。用户已开启实时，按其选择保留，正式统计关闭。生成的两个生命周期fixture恢复HEAD字节，其他来源修改未触碰。本轮未提交/推送，其他来源修改保留。


最终证据：cleanup-result.json、post-cleanup-5_2.log、post-cleanup-installed-5_1.log、fresh-startup.json。Static/Contract/Process/Runtime与用户核对通过；正式安装和独立新进程自动加载通过。完整裙面防穿/本轮FBX新输出仍NotRun，不以代理匹配替代该验收。


## 发布记录

用户在验收收尾后明确要求推送远端main。代码提交`d46a7af5831896aa022a130c81f31737061b4ac9`，文档与量化证据单独[Docs]提交，随后推送origin/main并核对远端HEAD。本次不纳入humanoid_retarget/pipeline.py及tests/test_fbx_pipeline.py中的其他来源工作区修改。
