# 独立复核建议核验

调用收据确认gpt-6.1-sol、high、read-only，退出0，有新鲜报告。主代理回查ui-5_1-errors.log，确认两处Area集合包含检查均触发TypeError。

采用：用逐项RNA对象相等比较替换集合对象in；新增拒绝对象包含查询的集合测试；原生trace记录进入/异常及自有Timer计数。未采用推测的改键优先级、隐藏窗口或调度重写，因为merged keymap中新入口在首位，原生invoke已实际进入。

修复只影响区域有效性与清理，不改移动、相机、固定LookAt或其他插件。验证见rna-area-red及后续GREEN/UI结果；Review本身不是Runtime通过证据。
