# OPS-2A：生产运维工具套件第一版（2026-07）

## 1. 任务边界

OPS-2A 落地生产运维工具套件第一版，用于“看清楚、备得住、校验过、能计划”。

本阶段实现：

- `ops-runner` 命令入口。
- `inventory` 只读盘点报告。
- `backup` 备份 manifest；显式 `--execute` 时复制备份文件。
- `check-data` 只读数据一致性报告。
- `validate-release` 离线发布包校验。
- `prepare-upgrade` 非执行型 upgrade-plan。
- OPS job 本地 JSONL 结构化日志。

本阶段不实现：

- 正式 `apply-upgrade`。
- 正式 `rollback`。
- PostgreSQL 实际迁移。
- 自动修复 owner map。
- 永久删除生产文件。
- 修改 frpc / frps / 1Panel 配置。
- Update Center 页面执行。

## 2. 命令入口

从项目根目录执行：

```powershell
python -m enterprise.ops.runner inventory
python -m enterprise.ops.runner check-data
python -m enterprise.ops.runner backup
python -m enterprise.ops.runner validate-release --release <release-dir-or-zip>
python -m enterprise.ops.runner prepare-upgrade --release <release-dir-or-zip> --backup-manifest <backup-manifest.json> --data-check-report <data-check.json>
```

公共参数：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--app-root` | 当前目录 | 应用根目录。生产执行时应指向生产项目根目录。 |
| `--output-dir` | `ops_artifacts` | JSON 报告输出目录。 |
| `--log-file` | `logs/ops/jobs.jsonl` | OPS job 本地结构化日志。 |
| `--operator` | 空 | 可选操作人标识，只记录本地日志。 |
| `--job-id` | 自动生成 | 可选固定 job id。 |

## 3. 产物

默认产物：

```text
logs/ops/jobs.jsonl
ops_artifacts/inventory-<job>.json
ops_artifacts/data-check-<job>.json
ops_artifacts/backup-manifest-<job>.json
ops_artifacts/release-validation-<job>.json
ops_artifacts/upgrade-plan-<job>.json
ops_backups/<backup-id>/
```

这些目录均为本地运行产物，不提交 Git。

## 4. inventory

`inventory` 只读收集：

- 当前 `VERSION`。
- Git branch / commit / dirty 摘要。
- `data/`、`assets/`、`output/`、`history.json`、`enterprise.db`、env 文件存在性、文件数量和大小。
- `enterprise.env`、`API/.env` 的 key 名称。
- SQLite 表名与行数。
- `history.json` 数量和 type 分布。

报告只记录 env key 名称，不记录 env value、API Key、JWT secret、Token、Cookie 或管理员密码。

## 5. backup

`backup` 默认是 dry-run，只写 manifest，不复制文件：

```powershell
python -m enterprise.ops.runner backup
```

实际复制备份必须显式加 `--execute`：

```powershell
python -m enterprise.ops.runner backup --execute --backup-root D:\ic-backups
```

备份 manifest 记录：

- backup id / type / 时间。
- 当前版本和 Git 摘要。
- 备份对象存在性、文件数量、大小。
- 顶层文件项 SHA-256，以及目录项文件数量 / 大小汇总。
- `enterprise.env` 和 `API/.env` 的 key 名称。
- SQLite 备份方式、状态和目标路径：`sqlite_backup_method`、`sqlite_backup_status`、`sqlite_backup_path`。

实际备份复制到：

```text
<backup-root>/<backup-id>/app/
<backup-root>/<backup-id>/backup-manifest.json
```

备份会包含生产恢复需要的 env 文件本体，因此备份目录必须按敏感资产管理，不得提交 Git，不得公开上传。

`backup --execute` 不直接复制运行中的 `data/enterprise.db`、`enterprise.db-wal` 或 `enterprise.db-shm`。复制 `data/` 目录时会跳过这些 SQLite 运行态文件，然后使用 `sqlite3.Connection.backup()` 在备份目录生成一致性的 `app/data/enterprise.db`。如果 SQLite 备份失败，backup manifest 状态为 `fail`，命令返回非 0。

## 6. check-data

`check-data` 只读检查：

- `history.json` 是否可读。
- `history.json` 记录与 `user_history_map` 是否对齐。
- `data/canvases/*.json` 与 `user_canvas_map` 是否对齐。
- `data/conversations/*.json` 与 `user_conversation_map` 是否对齐。
- `user_resource_map.resource_url` 是否能映射到本地 `/assets/...` 或 `/output/...` 文件。

报告只指出差异、样例和风险，不写回数据库，不修复归属，不删除文件。

## 7. validate-release

`validate-release` 校验离线发布目录或 zip，禁止以下内容进入发布包：

- `assets/`
- `output/`
- `data/`
- `history.json`
- `enterprise.env`
- `API/.env`
- `python/`
- `logs/`
- `ops_artifacts/`
- `ops_backups/`
- Token / Cookie / auth 文件路径。

该命令只读扫描 release，不修改 release。

校验会识别任意顶层目录包裹下的运行时 / 敏感路径，例如 `Infinite-Canvas-Enterprise/data/enterprise.db`、`release-root/app/history.json` 或 `some-wrapper/API/.env`。

## 8. prepare-upgrade

`prepare-upgrade` 生成非执行型 upgrade-plan：

```powershell
python -m enterprise.ops.runner prepare-upgrade `
  --release D:\release\Infinite-Canvas-Enterprise-2026-07 `
  --backup-manifest D:\ic-backups\pre-upgrade-xxx\backup-manifest.json `
  --data-check-report ops_artifacts\data-check-xxx.json `
  --target-commit <target-commit> `
  --maintenance-window "03:00-05:00"
```

upgrade-plan 会列出：

- release validation 摘要。
- backup manifest 摘要。
- data-check 摘要。
- blockers。
- warnings。
- 人工维护窗口步骤。
- 回滚决策点。

该命令不会停止服务、不会替换文件、不会执行迁移、不会 rollback。

## 9. 生产执行建议

生产主机执行顺序建议：

1. `inventory`
2. `check-data`
3. `backup --execute`
4. `validate-release`
5. `prepare-upgrade`

执行输出和 JSON 报告需脱敏后回传主对话复核。只有 backup manifest、data-check、release validation 和 upgrade-plan 均可接受后，才能进入后续生产副本演练和维护窗口。

## 10. 2026-11-18 隔离 Windows 成套备份与恢复

以正式 2026.11.2 的 Windows 发行资产创建独立安装及合成业务数据。上文的旧工具按平铺目录取文件。此次按安装路径解析 `CONFIG_ROOT`、`DATA_ROOT`、`UPLOAD_ROOT` 和 `STATE_ROOT`，将业务数据、上传素材、配置、版本指针和安装身份纳入同一时点的清单。程序从同版发行资产恢复。

1. 在测试任务完成后停止隔离实例的网关与上游，等两个进程退出。使用现有数据库备份函数完成 SQLite 备份及校验，再复制配置、业务数据与稳定的安装状态文件。上传目录位于该安装的数据目录内，随数据一并复制。使用已校验的备份恢复主库，由 SQLite 在启动后管理 WAL 和 SHM。
2. 在源实例写入一个备份后的画布标记，再停机并保留源目录。在原测试路径下创建独立恢复副本，放回程序、固定入口与清单中的数据，再验证数据库和安装身份。整个演练使用回环地址、相同 Windows 用户及捆绑的 Python 运行网关和上游。
3. 重新登录一个管理员和两名普通成员，检查两类画布及保存、上传图片和生成原图、任务回执、历史与素材归属。另一个普通成员访问私有结果返回 404。SQLite `quick_check` 返回 `ok`，外键异常为 0，项目 Schema 元数据为 4。原任务关联的合成 DPAPI 凭据能在同一 Windows 用户下解密。

备份清单含 19 个文件，共 354,014 字节。北京时间 15:41:29.419 的画布写入可恢复，15:41:35.142 的备份后写入保留在源副本。取备份耗时 0.092 秒，恢复到两服务就绪耗时 9.949 秒，完成业务验收耗时 11.905 秒。时间只覆盖该合成数据集。真实试点数据量、NAS、换机与跨账号凭据恢复仍需按实际环境验证。
