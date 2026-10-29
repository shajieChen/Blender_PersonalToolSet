# 中键 WASD 视口移动

插件已在当前Blender启用。鼠标放在3D视口，按住滚轮中键，再按W/S前后、A/D左右移动。观察中心与视点一起平移，不锁定目标。中键拖动仍旋转；松开中键停止，Esc或右键还原本次视图。

N侧栏“飞行”中的“导航模式”默认是“Blender 中键 WASD”。速度单位为Blender单位/秒，可在面板调整。需要旧操作时选“Unity兼容模式”。新模式不绑定全局WASD、右键飞行或QE，初始Shift/Ctrl/Alt中键仍走原生组合。

当前支持普通Turntable视口。相机、锁定视图、Trackball或已有编辑modal时不接管；例如G/R/S中的中键约束保留。按住中键后临时按修饰键会暂停移动和拖动，释放修饰键继续。

本功能不修改物体、场景相机或动画。正式使用不需要--enable-event-simulate；该选项只用于独立原生事件审计进程。

[实施档](superpowers/plans/2026-10-27-mmb-wasd-viewport-navigation.md)。
