# 动态骨骼复核与界面修订

```text
原设计 -> 当前实现与缺口
用户新增要求 -> Gizmos / 面板分类 / 场景角色选择
Retarget源码 -> 相对HEAD未改动；原有回归仍失败
```

日期：2026-10-23。本报告先于后续脚踝蒙皮调查；脚踝调查若需要修改Retarget，须另外记录修改范围，不能覆盖这里的时间边界。

## 结论

动态骨骼仍为同级独立插件，未耦合Retarget。当前实现存在明确数学与状态管理缺口，测试通过不能替代这些缺口的修复。此次按用户要求增加绘制、角色选择和面板分类；没有修改solver.py或animation.py，也没有通过改Retarget消除旧回归。

## 已核实的实现问题

| 级别与状态 | 位置 | 触发条件与影响 | 最小修订方向 |
| --- | --- | --- | --- |
| P2 ConfirmedStatic，MCP数值复现 | `spring_bone/solver.py:81-135` | 胶囊端盖内侧点的真实非零delta仍被投影到轴的垂面。胶囊(0,0,0)至(0,0,2)，半径0.2，点(0,0,2.1)，推出后距离仍为-0.058578645米 | 非零delta使用最近点到目标的方向；仅轴心退化时选备用径向。增加端盖推出测试，不仅测距离函数 |
| P2 ConfirmedStatic，MCP数值复现 | `solver.py:172-185`；`animation.py:604-615` | fps_base被取整。fps=24、base=1.001、范围1至25时最后grid帧24.976023976，endpoint=None，遗漏真实结束时刻 | 保留分数时间比例，统一tick计数与结束点判定；增加1.001样本 |
| P2 ConfirmedStatic | `animation.py:728-733`、`_step_runtimes` | 非整数tick结束点直接执行完整60Hz一步，再把该姿势标到较早的结束帧；未按设计插值 | 在相邻完整tick间插值端点输出，同时维持主状态不变；补姿势值断言 |
| P2 ConfirmedStatic | `operators.py:147-171`、`animation.py:1028-1055` | 完成预览后用户切到另一Action，停止或重启时cancel仍无条件恢复entry_action，覆盖用户新选择 | 只在目标仍挂本会话Action时恢复动画；单独恢复本会话拥有的资源。新增完成预览后的外部切换测试 |
| P2 ConfirmedStatic | `operators.py:173-196,468,558` | modal只传event.type，任何TIMER都推进当前任务，没有比较event.timer和会话timer | 传完整事件，仅处理自己的timer |
| P2 ConditionalGap | `operators.py:105-115,186`及操作器异常分支 | 只捕获SpringBoneError；RNA RuntimeError/ReferenceError等可逃出，清理前还先丢失_session引用 | 用finally保证timer/会话释放；保留能恢复的入口。补通用异常注入，不把当前自定义异常测试外推 |
| P2 ConfirmedStatic | `animation.py:_validate`的NLA检查 | use_nla=False但仍有静音轨道时，any(track.strips)仍拒绝，并提示关闭NLA；当前现场角色即有此情况 | 明确是否允许禁用NLA的单Action输入；若允许，按实际求值开关预检，保留轨道 |

前三项中的数值复现见 `mcp-probes.json`。未列为事实：父子骨断开、所有参数都可由正常UI输入NaN等探子疑点；现有预检或真实输入不变量尚需闭合，不能仅凭底层函数没有检查就判定产品缺陷。

碰撞推出后恢复骨长、再次锥限或部分混合造成残余穿深，是原设计已写明的单次投影限制；不能误报为“实现顺序偏离”。它仍限制裙摆质量，真实网格穿插不能靠尾点距离证明解决。

`publish_from_preview()`缺少finished内部前置检查属于API健壮性Concern；当前UI先调用preview_still_valid，未证明正常按钮会提交半成品。代理显示Empty缺少明确来源标记同为所有权Concern；后续删除或复用用户指针时应先核owner，不能扩大为已发生用户物件丢失。

## 本次实际修订

| 文件 | 内容 |
| --- | --- |
| `spring_bone/gizmos.py` | 原样骨骼线框、关节标记、球和完整胶囊端盖；青色链、黄色当前链、粉色代理体。穿透模型，线宽与透明度不变，远处按视空间深度混入灰色。关闭后在骨架求值、几何生成和GPU工作前返回 |
| `spring_bone/properties.py` | 每个角色自己的show_gizmos，默认关闭 |
| `spring_bone/targets.py` | 场景骨架选择、当前骨架回退及网格绑定骨架查找；拒绝其他场景的对象 |
| `spring_bone/panels.py` | 目标骨架字段；骨骼链、碰撞体、预览与烘焙、结果信息四个子面板；列表切换链/代理体 |
| `spring_bone/operators.py` | 所有操作按选定目标路由；添加链/代理体仍要求在目标姿态模式选择；已有A角色预览时拒绝把它提升给B角色 |
| `spring_bone/__init__.py` | 当前版本1.0.4；注册/注销绘制和场景指针；加载清理handler加persistent，修正跨文件加载后handler丢失的原缺口 |
| `tests/test_spring_bone_gizmos.py` | 16项几何、单位、开关、资源配对、角色隔离、网格回退、灰度/穿透及按蒙皮修正末端合同 |

后续用户明确“脚踝处”指裙摆下摆，追加蒙皮核验与链尾修订，见[裙摆末端蒙皮检查](skirt-tip-binding.md)。8条无权重`.003`只移出模拟配置，骨骼、权重和当前Action均保留；不修改原积分或重定向。

依赖为UI/操作器至目标解析与动画作业、动画至solver；gizmos使用目标解析和求值数据，不写姿势。handler和shader由gizmos模块持有并在unregister释放；数据不跨帧缓存。Scene只持目标引用，各角色配置仍在Object.sb_settings。未创建或删除现场角色、网格、动作或权重，未保存用户未保存的blend，未运行安装BAT。

## 对原始设计与实施档的偏差核对

依据：[设计档](../../../specs/2026-10-23-spring-bone-design.md)、[实施档](../../../plans/2026-10-23-spring-bone-implementation.md)。

| 项 | 判定 |
| --- | --- |
| 同级插件、无Retarget导入、尾点递推、米制、固定60Hz、生成预览后播放、新Action、保留旋转模式 | 方向一致 |
| 结束子帧插值、1.001帧率、只处理自己的TIMER、外部切换Action后不覆盖选择 | 实现未满足，见上表 |
| 碰撞分组 | 原设计有组的描述，当前字段和求解将全局colliders用于全部链，未实现分组选择；属于未交付范围，不应写为已完成 |
| 灰度Gizmos、Checkbox、折叠分类、场景角色选择 | 本轮用户明确追加的需求，不是原设计偷偷扩展 |
| 接受非统一祖先缩放或放宽骨长容差 | 没有写入磁盘；原设计仍拒绝。现场角色超出支持条件属于能力限制，不能以临时放宽冒充正式支持 |
| 输入/结果保存 | 正式发布设置fake user；基础Action由source_action指针持有。预览不设fake user是会话清理策略，不能据此认定正式结果不保存 |
| 安装器 | 仍未修改；受原Retarget回归门阻塞，不冒充安装交付 |
| 原实现RED | 交接记录为ModuleNotFoundError，未达到实施档要求的业务断言RED；此次新增特性的RED为已收集测试中的显式断言失败 |
| 正式验收、原临时诊断清理 | 仍未完成，不能因界面可见或64项测试通过而关闭 |

原设计本身需保留的风险：单次有序点碰撞不能保证非冲突场景总满足1e-5米；混合会重新穿入；关键帧间插值不保证碰撞；当前角色含设计拒绝的NLA/缩放条件。后续要消除这些限制须明确修订设计，不能无界加迭代或改公式。

## 联网调研与推荐

1. [Wiggle 2作者仓库](https://github.com/shteeve3d/blender-wiggle-2)：先选Armature，再启用骨骼的头/尾动态，不是自动判断头发、裙摆、尾巴。其[当前源码build_list](https://raw.githubusercontent.com/shteeve3d/blender-wiggle-2/main/wiggle_2.py)按scene中的Armature分别组织对象与骨骼列表。这支持本插件按角色保存配置，而不是把所有链混在Scene全局。
2. [VRChat PhysBones官方说明](https://creators.vrchat.com/common-components/physbones/)：指定Root Transform后按后代层级处理，并提供排除列表；主体人形骨不应直接当动态根。这能借鉴根节点、后代和排除规则，不能证明存在可靠的自动语义识别。
3. [Hair Bone Generator作者仓库](https://github.com/morimoristudio3D/hair-bone-generator)：从用户选定发梢区域生成骨链，可补发根标记；不创建权重。这属于网格辅助建骨，与给现有骨链添加动力学不同。
4. 面板采用Blender原生Panel父子结构、UIList和默认折叠。参考[Panel API](https://docs.blender.org/api/3.3/bpy.types.Panel.html)的bl_parent_id与DEFAULT_CLOSED；实际注册和界面以本机5.1.2/5.2.1验证为准，不以旧版网页证明新版本兼容。

推荐下一批自动配置：已有骨链优先，名称词表（Hair/Skirt/Tail及项目命名）+父子拓扑+蒙皮关联，排除身体主骨、约束控制骨和已占用骨，输出候选根与完整链供确认后批量加入。分叉拆链，不能擅取第一个子骨。碰撞体先依据明确身体骨及用户尺寸生成候选；不能只按名称自动改权重。此方案是本项目建议，本轮只调研，未实现自动识别或自动建骨。

## 本轮证据

| 层级 | 实际结果 |
| --- | --- |
| Static | 9个插件/新增测试文件AST、无新增注释/docstring、空白与依赖检查；C/C++与Build为NotApplicable |
| RED | 初始Gizmos selected=7，缺功能断言失败；目标选择RED selected=11、4失败；深度/穿透/灰色语义修订均有选中测试断言失败，日志在本目录 |
| Contract/Process | 最终spring-all.log：selected=67，退出0，SPRING_BONE_TEST_OK。通过的是测试集合，不代表上表已知缺陷消失 |
| Regression | pose-channel.log：7项、退出0；retarget.log：退出1，原有test_metarig_root_reference_and_ik第1775行水平根位移断言失败 |
| Retarget改动核对 | git diff HEAD -- humanoid_retarget tests/run_retarget_test.py 安装插件.bat 无输出；本次未修改这些文件 |
| MCP现场 | 本机BlenderMCP通道连接5.1.2。8裙链、4代理体；重载前后Action、帧、链和代理数量、隐藏状态一致。第8/36帧线段位置不同，跟随实际求值。见mcp-ui.json |
| Visual | gizmos-screen.png为实际窗口截图，已检查原绘制与分类；gizmos-gray-viewport.png为MCP中当前视口+正式GPU绘制函数的受控捕获，已检查灰度、不遮挡与胶囊端盖。它不代替完整自由旋转/长期性能验收 |
| 兼容 | 5.2.1后台合同与回归；5.1.2为用户现场UI验证，不改最低版本声明，不宣称4.2支持 |

截图尝试中的纯黑窗口捕获gizmos-depth.png不作为证据；插件原生MCP offscreen截图不包含draw handler，gizmos-enabled.png也不能证明绘制已出现。最终灰度验证使用正式绘制函数写入受控GPU视口，而非修图。

## 清理与未完成项

本轮没有向插件加入临时日志、计时器、轨迹采样或探针开关。MCP一次性数值/截图脚本未持久注册，截图临时Image和GPUOffScreen在finally释放。正式绘制handler和Checkbox为用户要求的长期功能，默认关闭，保留测试与证据。原cleanup.md列出的历史临时项未动，等待用户核对。

本轮UI增量的静态、测试与受控绘制已验证；自由旋转体验待用户核对。原动力学缺陷、Retarget旧回归、安装、历史诊断清理及正式验收仍未关闭。此处只报告可审查WIP，不宣告原实施任务最终完成。

## 后续观察到的并行改动

上述Retarget无差异核对完成后，工作树出现本轮工具调用未写入的`humanoid_retarget/__init__.py`与`pipeline.py`修改，内容涉及FBX导出和骨骼平移；另有`docs/design/research_attachment_points.md`新增。均保持原状，未回退、暂存或覆盖。当前整棵工作树因此不能再描述为Retarget无差异；准确结论是本次动态骨骼工作未写Retarget。

retarget.log对应这些后续改动之前的运行，不能作为并行改动后源码的最新验证；后续源码状态为NotRun，需由对应工作继续验证。此前原地根位移断言失败仍是旧收据事实，不归因于本轮Gizmos或链尾修订。

## 用户后续确认的权重方案

在此前报告交付后，用户选择保留四节模拟并重分配末端权重。现已恢复四节配置，保留原数据备份，仅在clothing的独立Mesh副本调整下摆权重。此前三节方案是历史状态，不应继续当作当前配置。新修订的范围、53帧检查及8个末骨验证见[四节权重修订结果](four-joint-weights/result.md)。本轮仍未写Retarget源码。
