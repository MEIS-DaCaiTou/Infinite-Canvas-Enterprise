# OPS-2B：Windows OPS-2A 运维封装脚本（2026-07）

## 1. 定位

OPS-2B 只是 Windows 运维封装，不是新升级系统。

OPS-2A 已经提供 `inventory`、`check-data`、`backup`、`validate-release`、`prepare-upgrade`。生产侧试运行发现 Windows 生产机没有系统 `python` 命令，且 bundled Python 需要直接执行工具目录中的 `enterprise/ops/runner.py`。OPS-2B 因此新增两个 PowerShell wrapper，用于减少生产侧复制粘贴和多行反引号错误。

Codex 不能访问生产主机。项目负责人仍需在生产机本地执行脚本，并将脱敏后的输出、报告路径和关键结果回传主对话复核。

## 2. 脚本

| 脚本 | 用途 |
| --- | --- |
| `tools/ops/windows/run-ops2a-prod-dryrun.ps1` | 依次执行 `inventory`、`check-data`、`backup` dry-run。 |
| `tools/ops/windows/run-ops2a-backup-execute.ps1` | 只执行一次已确认的正式备份。 |

两个脚本都通过以下方式调用 OPS runner：

```powershell
& <AppRoot>\python\python.exe <ToolsRoot>\enterprise\ops\runner.py ...
```

它们不依赖系统 `python`，也不依赖 `python -m enterprise.ops.runner`。

## 3. 生产侧使用示例

### 3.1 dry-run

dry-run 脚本只做 inventory / check-data / backup dry-run。

```powershell
.\tools\ops\windows\run-ops2a-prod-dryrun.ps1 `
  -AppRoot "C:\Infinite-Canvas-Enterprise项目\production-app" `
  -ToolsRoot "D:\ops-tools\Infinite-Canvas-Enterprise" `
  -OutputRoot "D:\ops-output\ops2a-dryrun"
```

输出会打印：

- `inventory-*.json`
- `data-check-*.json`
- `backup-manifest-*.json`
- `jobs.jsonl`

### 3.2 backup execute

backup execute 脚本只做正式备份，不做升级。

必须显式传入 `-ConfirmProductionBackup`：

```powershell
.\tools\ops\windows\run-ops2a-backup-execute.ps1 `
  -AppRoot "C:\Infinite-Canvas-Enterprise项目\production-app" `
  -ToolsRoot "D:\ops-tools\Infinite-Canvas-Enterprise" `
  -OutputRoot "D:\ops-output\ops2a-backup" `
  -BackupRoot "E:\ic-backups" `
  -ConfirmProductionBackup
```

输出会打印：

- backup manifest 路径。
- backup 目录路径。
- `sqlite_backup_status`。
- `dry_run` 是否为 `false`。

backup --execute 需要单独确认，不应由 dry-run 阶段顺手触发。

## 4. 后置事项

validate-release / prepare-upgrade 后置，需要 release 包、已确认的 backup manifest、data-check report 等前置输入。

apply-upgrade / rollback 未实现。

Docker / 1Panel / PostgreSQL 未实现。

## 5. 禁止事项

OPS-2B 不做：

- 不升级生产。
- 不停止或启动服务。
- 不执行生产目录更新。
- 不执行直接覆盖升级。
- 不执行数据修复。
- 不删除生产数据。
- 不修改 frpc / frps / 1Panel 配置。
- 不接入 Update Center UI。

不得复制生产 enterprise.env、API/.env、enterprise.db、history.json、assets/output 到 Codex 开发环境。

含密钥、数据库、历史记录、上传和输出图片的生产资产只能留在生产主机或项目负责人指定的安全备份位置。
