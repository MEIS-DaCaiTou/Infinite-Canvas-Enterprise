# ADR-ENV-004：路径根与版本目录

- 状态：Accepted
- 决策日期：2026-07-16
- 事实基线：`main@240f6a2b93268a415cddc3c9af9951f334c8e4e1`
- 实施状态：契约已冻结；ENV-1B1B 实现当前仅在 Draft PR，尚未进入 `main`

## 决策

所有路径必须由集中配置对象解析，不允许业务模块自行依赖 `Path.cwd()`、`os.getcwd()` 或本机绝对路径。

Linux 默认值是未来 `server` adapter 的契约，不表示当前已实现 Linux 部署。

| 根 | 定义 | Windows portable-release 默认 | Linux server 契约默认 | 可覆盖 | 持久 / 备份 | 随版本切换 | 可在 APP_ROOT | 权限与上游兼容 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `INSTALL_ROOT` | 一个安装实例的外层目录 | 用户选择的安装目录 | `/opt/infinite-canvas-enterprise` | 安装时 | 是 / 否 | 否 | 不适用 | 管理员安装、运行账号只读；不改变上游相对布局 |
| `RELEASE_ROOT` | 不可变版本集合 | `INSTALL_ROOT/releases` | `/opt/infinite-canvas-enterprise/releases` | 是 | 可重建 / 否 | 否 | 否 | 激活后运行账号只读；保留完整上游树 |
| `APP_ROOT` | 当前版本应用目录 | `RELEASE_ROOT/<release_id>` | `RELEASE_ROOT/<release_id>` | 仅由激活状态选择 | Release / 否 | 是 | 自身 | 全树只读；`main.py`、`static`、`workflows`、`API` 和 `VERSION` 相对位置不变 |
| `CONFIG_ROOT` | 实例配置 | `INSTALL_ROOT/config` | `/etc/infinite-canvas-enterprise` | 是 | 是 / 是 | 否 | 否 | 运行账号最小读取；secret 文件限制读取者 |
| `DATA_ROOT` | 数据库和业务元数据 | `INSTALL_ROOT/data` | `/var/lib/infinite-canvas-enterprise` | 是 | 是 / 是 | 否 | 否 | 运行账号读写；通过 adapter 保持上游数据路径语义 |
| `UPLOAD_ROOT` | 用户上传和生成输入 | `DATA_ROOT/uploads` | `/var/lib/infinite-canvas-enterprise/uploads` | 是 | 是 / 是 | 否 | 否 | 运行账号读写；不得回落到 Release 内上传目录 |
| `LOG_ROOT` | runtime / app / OPS 日志 | `INSTALL_ROOT/logs` | `/var/log/infinite-canvas-enterprise` | 是 | 是 / 选择性 | 否 | 否 | 运行账号写、运维读；不含 secret |
| `BACKUP_ROOT` | 正式备份 | `INSTALL_ROOT/backups` | `/var/backups/infinite-canvas-enterprise` | 是 | 是 / 单独保留 | 否 | 否 | 受限写入和读取；不能与源数据库同一事实混淆 |
| `STATE_ROOT` | 版本指针和安装状态 | `INSTALL_ROOT/state` | `/var/lib/infinite-canvas-enterprise/state` | 是 | 主机持久 / 否 | 否 | 否 | 运行账号原子写；不迁移 PID、lock 或旧命令 |
| `STAGING_ROOT` | 新版本解压与验证 | `INSTALL_ROOT/staging` | `/var/lib/infinite-canvas-enterprise/staging` | 是 | 临时 / 否 | 否 | 否 | 与目标 Release 同卷、不可覆盖已有目录 |
| `RUNTIME_ROOT` | PID、lock、command / ACK | `%LOCALAPPDATA%\InfiniteCanvasEnterprise\runtime` | `/run/infinite-canvas-enterprise` | 是 | 否 / 否 | 否 | 否 | 当前账号私有；重启可重建，不随设备迁移 |
| `CACHE_ROOT` | 可重建缓存 | `%LOCALAPPDATA%/Infinite-Canvas-Enterprise/cache` | `/var/cache/infinite-canvas-enterprise` | 是 | 否 / 否 | 否 | 否 | 运行账号读写；删除不损失业务事实 |
| `TEMP_ROOT` | 同卷临时文件 | `%LOCALAPPDATA%/Infinite-Canvas-Enterprise/temp` | `/var/tmp/infinite-canvas-enterprise` | 是 | 否 / 否 | 否 | 否 | 运行账号私有；原子发布时必须满足同卷约束 |
| `PYTHON_RUNTIME` | 当前 Release 解释器 | `APP_ROOT/python` | `APP_ROOT/runtime/python` 或镜像内固定 venv | 由 manifest 绑定 | Release / 否 | 是 | 是 | 正式入口只读执行；ABI、lock 和 manifest 必须匹配 |

环境变量或受限 CLI 可以覆盖默认值，但解析后必须进行绝对化、containment、权限、同卷和路径长度检查；最终状态与报告不得泄露敏感本机路径。

### Windows runtime 路径兼容决定

ENV-1 首阶段保持当前代码已经使用的 `%LOCALAPPDATA%\InfiniteCanvasEnterprise\runtime`，不改名为带连字符的目录。这样不会制造两个并存的 supervisor 根，也不需要迁移活动 PID、lock、state、command / ACK 或 crash evidence。

本 ADR 不定义 legacy-to-new migration，因为首阶段没有目录重命名。若未来决定采用 `%LOCALAPPDATA%\Infinite-Canvas-Enterprise\runtime`，必须另行评审完整迁移协议，包括双路径检查、旧 supervisor identity、lock/state/control 检查、双根并存 fail closed、历史日志策略，以及 stop/status 在迁移窗口的兼容；不得只替换字符串。

## 当前版本权威指针

Windows 当前 Release 的唯一权威事实为：

```text
STATE_ROOT/current-release.json
```

最低内容包括 schema version、release ID、APP_ROOT 相对定位、manifest SHA-256、activated_at 和 previous release ID。状态使用同目录固定短临时文件、flush / fsync 和 `os.replace` 原子更新。

Junction 或快捷目录可以作为便利入口，但不是权威状态；junction 丢失或指向与 JSON 不一致时必须 fail closed。

## 生命周期边界

- APP_ROOT、PYTHON_RUNTIME 随 Release 切换。
- CONFIG_ROOT、DATA_ROOT、UPLOAD_ROOT、LOG_ROOT、BACKUP_ROOT 位于版本目录外。
- RUNTIME_ROOT、CACHE_ROOT、TEMP_ROOT 不随设备迁移。
- 新版本只能解压到全新 staging 目录，不能覆盖现有 APP_ROOT。
- APP_ROOT 不得反向包含任何持久根或 runtime 根。

## Server 模式

`server` 只预留同名路径契约；Linux `/opt`、`/etc`、`/var/lib`、`/run` 和 `/var/log` adapter 不在当前 Windows ENV-1 阶段实施。

## 后果

- 版本切换不再与数据和配置覆盖绑定。
- OPS-3B 可以基于 manifest 与权威状态文件执行明确切换。
- 旧代码中的隐式 cwd、APP_ROOT 写入和绝对路径必须在 ENV-1B1A / B1B 中逐项迁移。

## ENV-1B1B Draft 实施事实

当前 Draft PR 提供 `PathRoots` 十四根模型、development/portable-release 显式 profile、两阶段
portable 推导、containment/同卷/Windows 特殊路径/reparse 检查，以及按 application、runtime、
OPS、install-state 分开的 directory prepare capability。它也提供 `STATE_ROOT/current-release.json`
的严格 reader/writer/resolver（schema、固定字段、canonical JSON、residual `.new` 拒绝、fsync +
`os.replace`）。这些实现不等于 activation、不选择解释器、不接线 launcher，且 legacy update、
restart、bytecode 和其它 deferred 写入仍阻止完整只读 APP_ROOT。
