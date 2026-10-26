# 动态骨骼实时预览复核

日期：2026-10-26。状态：用户确认手部正常，诊断清理及清理后复验通过，实时预览已完成并在用户Blender保持开启。没有提交或推送。

## 交付行为

动态骨骼主面板新增“实时预览”复选框。播放时由原生frame_change事件驱动；暂停时仍可调整重力、方向、刚度、拖曳和混合。八条四节链的32节均经过重力、惯性及球/胶囊代理体碰撞求解，包括末节。

临时隐藏骨架读取基础Action的副本，避免上帧模拟结果反馈。实时路径只对配置链修正四元数符号，非模拟骨骼曲线原样复制。仅写临时Pose，不插关键帧，不改原Action、Rest、网格或权重。停止恢复进入前Action，保留当前时间与选择。若进入前为插件生成动作，按其输入元数据或基础动作指针找到原动作，停止时仍恢复原选中结果。

完整裙面防穿保持离线功能，实时代理体碰撞不声明裙面零交叉。实时开启期间不能并行运行离线预览、烘焙或防穿。FBX仍使用离线烘焙结果；本次未增加实时记录/导出按钮，也未放宽旧离线缩放/骨长限制。

## 实现和根因闭环

- 新`realtime.py`持有采样对象、Action副本、固定步状态和临时Pose写入。
- `animation.py`提取现有初始链状态、碰撞坐标转换、排序和单链求解；实时与离线共享solver，不复制重力公式。修复禁用NLA时仍因轨道存在而拒绝的误判，活动NLA仍拒绝。
- `operators.py`复用唯一Session和停止入口。帧回调不调用frame_set采样，暂停timer不在播放期间重复积分。倒放、循环和大跳帧重置，每次最多16步。
- 新增24/60FPS移动锚点对照，找到采样时刻偏差，RED为0.000860521米差；修正为真实固定tick时刻后GREEN小于1e-5米。
- `__init__.py`注册不保存状态的WindowManager开关；load/undo/save/render/unregister统一停止。没有增加Retarget导入或第二套全局会话。

## 本次数值结果

| 层级 | 结果与证据 |
| --- | --- |
| Static | AST/局部diff/UTF-8与CRLF/无新增代码注释通过；依赖单向，无bpy工作线程 |
| RED/GREEN | 初始9项selected-positive RED → GREEN；随后21项跨帧率RED包含1个明确失败 → GREEN。最终实时24项及完整Spring121项通过 |
| Contract/Process | Blender5.1.2、5.2.1各121项，进程退出0；球和胶囊、0混合、重复帧无反馈、模式/Action切换、删除目标、多角色与卸载覆盖 |
| Runtime逐节重力 | 真实5.1.2角色，32/32节对正反重力方向压力对照有角度变化；同一预览Action持续复用 |
| Runtime蒙皮 | 手部修复后压力对照中主裙面8021个顶点、第二裙面1007个顶点移动；身体手部372点、衣服手部441点位移均为0；实时运行不改源曲线、Rest、静态网格或权重 |
| 原生播放 | 约2.2秒，52个不同真实播放帧事件，143个模拟步，包含循环；会话正常，结束恢复时间 |
| 原生暂停调参 | 同一帧约0.46秒内，原生timer推进28步；当前链四节均响应方向改变，未生成新Action，用户参数恢复 |
| 全段帧事件 | 用户当前0–52帧53点，每帧均求解32节，恢复原时间；这是实时求解事件检查，不是完整裙面防穿验收 |
| 实际保存/加载 | 两版本独立后台进程执行真正save_as_mainfile/open_mainfile，均无临时对象/动作残留，开关不自动开启 |
| 停止恢复 | 真实用户场景原Action/当前帧/选择恢复，隐藏骨架、临时Action、帧回调和暂停timer删除；可再次启动 |
| 用户核对 | 用户确认“手部正常，可以清理并收尾”；量化通过独立记录，未以截图替代 |
| FBX/Retarget | 共享求解提取后的既有FBX回归在121项内通过；本次未改Retarget，未新增实时FBX记录能力 |
| C++/Build/Generated/ABI/unique_ptr/raw pointer | NotApplicable，无对应代码或工具链变化 |

证据：[逐节/蒙皮](live-gravity-audit.json)、[原生播放](live-playback.json)、[暂停timer](live-paused-timer.json)、[全段事件](live-frame-sweep.json)、[实际停止](live-stop.json)、[5.1回归](spring-final-5_1.log)、[5.2回归](spring-final-5_2.log)、[24/60FPS RED](clock-red.log)、[5.1文件生命周期](file-lifecycle-1.json)、[5.2文件生命周期](file-lifecycle-2.json)。

手部反馈前的8618点移动统计只反映当时错误配重，不作为当前数据验收。当前压力对照的模拟参数为重力20、正反方向，用来验证各节及蒙皮响应，不是用户默认参数或外观建议。结束已恢复用户原参数。不同帧和系统负载的耗时会不同；最新60次记录更新中位约3.6ms、P95约4.3ms、最大约5.1ms；先前部分记录最大20–27ms。全场景frame_set中位约9.2ms。偶发更新超过16ms，保留性能Concern；初次复制/预热约92ms，不归入稳态帧预算。

## 用户反馈：手部蒙皮错乱及修复

用户拒绝首次核对，指出手部蒙皮错乱，本轮因此未收尾。量化发现：非模拟骨矩阵相对基础采样完全一致，身体网格停止前后无有效位移；但上次防穿配重把肩、臂、手部衣服也当成裙摆提高权重，实时重力暴露了该错误。这是先前修订的范围错误，不归咎于用户调参。

已按2026-10-25的原始逐顶点备份撤销全部1088点误配重，哈希从`3c95e3e1...`精确恢复到`d2a72a31...`；未新增其他蒙皮改动。主导手骨的151个衣服顶点首先验证位移0，随后扩大到所有有手骨权重的顶点：身体372点、衣服441点，共813点，正反重力压力对照位移仍为0。32节裙骨正常响应，两个裙面继续有实际运动。

另有独立实现缺口：实时Action副本原先会修复所有骨骼四元数插值，可能改变非裙骨中间姿势。新增selected=24 RED，手骨矩阵偏差0.932；现只修复配置链，非裙骨曲线原样保持，GREEN通过。离线防穿的显式全动作修复语义未改变。

配重工具新增保护门：原动态链合计不超过50%的顶点拒绝自动改成裙骨权重，先验证全部计划再写备份/数据，不能仅因出现几何交叉便扩大动态蒙皮。新增手部保护RED/GREEN。旧防穿Action按数据变化标记失效，面板不再显示其历史0穿插；失效结果不能直接作为防穿输入。

[首次定位](hand-issue-initial.json)、[精确权重回退](seam-weight-rollback.json)、[回退后对照](hand-after-rollback.json)、[失效旧动作](invalidated-contact-actions.json)、[当前角色数据](after-hand-rollback.blend)、[非裙骨曲线RED](non-simulated-rotation-red.log)、[配重保护RED](hand-protection-red.log)。旧2026-10-25 FBX/Blend仅保留为历史错误证据，不能继续当作当前合格成品。

## 生命周期和边界

Owner为`RealtimeSpringPreview`，用户Scene、目标骨架、Armature data与原Action是借用；临时Object和Action副本由作业拥有，停止/失败对称删除。实时frame_change_post和暂停timer由既有Session管理，load/undo/save/render/unregister移除。共享Armature data只读，不建立新骨架绑定。

外部切换Action时不覆盖新选择；目标/场景变化、编辑模式、约束驱动变化、不支持的缩放/剪切或源曲线编辑使会话停止。源曲线/Rest完整性定期检查，不能声称在任意外部脚本原地改写瞬间具有全局锁。单槽单层完整替换动作；拒绝活动NLA、骨架约束和驱动。

停止实时后旧离线生成路径仍有独立输入硬门，不能把实时通过宣称为任意输入都可离线重新烘焙。完整裙面、连续碰撞、体积和自碰撞不在此实时功能保证内。

## 沉淀与收尾

[使用及量化文档](../../../spring-bone-realtime-preview.md)、[实施档](../../plans/2026-10-26-spring-bone-realtime-preview.md)。正式测试及审计脚本按需保留，用户先前明确要求沉淀量化方法。统计标记`diagnostics_enabled`默认False，审计临时开启并恢复；关闭时不计数、采样或写日志。

两次短时播放帧计数探针及一次暂停参数探针已运行结束，frame回调已移除、一次性timer自然退出，统计标记恢复关闭。临时采样骨架/Action和核心timer属于实时功能资源，开启时必须保留，关闭时必须释放，不能误作诊断清理。

当前没有落盘的一次性诊断脚本或废弃候选需要删除。`before-realtime.blend`只作错误配重回归fixture；当前正确角色为`after-hand-rollback.blend`。JSON/log及正式测试作为证据保留，不按后缀批量删除。用户核对、清理及清理后复验已依次完成。


## 最终清理及复验

用户确认“手部正常，可以清理并收尾”后，检查本次临时帧探针已移除、一次性timer已退出、统计默认关闭。没有需要删除的临时文件。停止实时后，源Action恢复，采样Object、Action副本、功能帧回调和timer全部释放；再开启成功，按用户现状保持实时开启。

清理后BlenderMCP对0–52帧逐帧复验，共53帧，每帧32节；手部骨矩阵相对基础采样的最大偏差为0。身体372点、衣服441点的手部关联顶点裙骨权重均为0，衣服权重哈希仍为原始`d2a72a310e2fa421bbb6cd83ceec8bfe6f6949b173809b7fa487fd3e4dbc6602`。当前帧和选择保持。

清理后Blender5.1.2、5.2.1各121项测试通过，退出0；两版本再次真正保存/加载均无功能资源残留。测试生成的两个既有lifecycle_reopen文件已精确恢复HEAD字节，未触碰用户资产。11个Python文件AST、注释保持、UTF-8无BOM、CRLF及git diff --check通过。无C/C++改动，专项命名/格式/unique_ptr label/raw pointer/ABI硬门NotApplicable；Python启动/停止、注册/注销与失败恢复Passed。

[清理清单](cleanup-result.json)、[清理后53帧](post-cleanup-live.json)、[5.1清理后回归](post-cleanup-spring-5_1.log)、[5.2清理后回归](post-cleanup-spring-5_2.log)、[5.1保存加载](post-cleanup-file-lifecycle-5_1.log)、[5.2保存加载](post-cleanup-file-lifecycle-5_2.log)、[最终摘要](summary.json)。

边界保持：本次交付实时骨骼代理体碰撞与手部隔离；撤销误配重后未重新声明完整裙面无穿模或旧FBX有效。偶发更新超过16ms仍为性能Concern。没有自动提交或推送。


## 后续补齐：实时预览同时绘制动态骨骼

状态：用户确认显示正常，清理后复验通过，本项完成。之前“完成”记录指手部修复和实时求解闭环，本节为新增绘制需求。

根因：gizmos.py的几何和标签入口都在job_running时返回，实时Session也被视为忙碌任务而隐藏。两处判断只对非实时任务隐藏，复用原绘制器；show_gizmos开关、青/黄/粉配色、穿透模型、距离混灰和GPU状态恢复均保持。新增实际Session下几何跟随、暂停调重力、碰撞体线及标签回归，selected=26 RED中两个失败，修复后GREEN；双版本完整各123项通过、退出0。

当前场景首链Q_QunZi.L为FOLLOW_TRANSLATION且ancestor_name为空，启动被既有输入门拒绝。将此空值补为实际直接父骨spine后启动成功；未修改其他链参数、Action、权重或Rest。实时与显示两开关均已开启。

真实视口POST_VIEW回调完成18次有效线绘制，POST_PIXEL完成16次文字绘制（8个链名含阴影）。32节骨骼共3904个线顶点，碰撞体800个线顶点；当前链根段绘制端点与实际求值Pose误差0。额外审计只绘制一次后移除两个临时handler，一次性timer退出，namespace释放，正式统计关闭；正式绘制handler保留。未使用截图替代数值。

证据：overlay-red.log、overlay-green.log、overlay-full-5_1.log、overlay-full-5_2.log、overlay-live.json。测试生成的两个lifecycle_reopen资产按HEAD原字节恢复，代码AST/无新增注释/编码与git diff --check通过。无新增依赖或Retarget改动，无提交推送。用户确认“显示正常，可以收尾”后已检查临时namespace及帧探针均不存在、正式绘制资源保留、统计关闭。两版本清理后再次各123项通过，实时32节、骨骼3904及碰撞体800个线顶点仍有效，新增绘制需求已最终收尾。


## 最终发布

用户最新明确要求推送远端main，本次授权覆盖此前不自动推送的限制。代码已提交`51066b8199b1b8913e72dfaec38df7f33101a342`，文档与证据单独[Docs]提交后推送origin/main，最终以Git远端核验为准。提交前本地main与origin/main相同，无其他任务文件纳入。
