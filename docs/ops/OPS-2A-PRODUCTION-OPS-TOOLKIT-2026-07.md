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
- 文件级 SHA-256。
- `enterprise.env` 和 `API/.env` 的 key 名称。

实际备份复制到：

```text
<backup-root>/<backup-id>/app/
<backup-root>/<backup-id>/backup-manifest.json
```

备份会包含生产恢复需要的 env 文件本体，因此备份目录必须按敏感资产管理，不得提交 Git，不得公开上传。

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
