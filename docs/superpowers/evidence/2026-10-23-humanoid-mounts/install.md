# 单包安装核验

目标：`H:\Blender\5.2.1\portable\scripts\addons\humanoid_mounts`。

安装前该目录不存在，因此旧包备份为 NotApplicable；未覆盖其他插件。六个 Python 源文件逐文件复制并核对 SHA256，当前值见 `install-manifest.json`。

`安装插件.bat` 仅新增本包安装 call 与名称提示，共两行 ASCII。保留全部旧字节，原 BAT 的备份字节在 manifest 的 installerBefore 字段；没有执行会分发所有旧插件/多个版本的 BAT。

`installed-before-user-review.log` 及最终 `post-cleanup-installed.log` 从目标目录加载，完成真实 blend 重开、原生关系核对、停用保留关系、重新启用。没有保存用户实际启用偏好；测试启用为当前进程内状态。后续使用可在 Blender 插件偏好中启用 Humanoid Mounts，入口为 N 侧栏的人形挂载。

工作区路径通过不代表安装通过；本次已分别保存两层收据。测试用用户配置与临时目录均属于本任务输出目录。
