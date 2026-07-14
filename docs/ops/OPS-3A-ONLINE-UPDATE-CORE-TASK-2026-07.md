# OPS-3A：在线更新核心实施任务（2026-07）

## 1. 任务目标

OPS-3A 直接实现企业版在线更新的安全核心，使 Windows 单机生产环境能够在**不执行正式升级、不停止服务、不替换生产文件**的前提下完成：

1. 查询受信任发布源的最新版本。
2. 比较当前版本与目标版本。
3. 下载 release manifest 与发布包。
4. 校验发布包来源、大小与 SHA256。
5. 安全解压到全新的 staging 目录。
6. 复用并增强现有 `validate-release` 校验。
7. 生成结构化在线升级计划和 JSONL job 日志。
8. 为 OPS-3B `apply-upgrade` / `rollback` 和 OPS-3C Update Center 提供稳定 API。

OPS-3A 结束时，开发机和生产副本应能完成：

```text
check update -> fetch manifest -> download archive -> verify -> stage -> prepare plan
```

## 2. 当前代码基线

当前 `enterprise/ops/runner.py` 已提供：

- `inventory`
- `check-data`
- `backup`
- `validate-release`
- `prepare-upgrade`
- JSON 报告
- JSONL OPS job 日志

已有 release 校验会拒绝 `data/`、`assets/`、`output/`、`history.json`、`enterprise.env`、`API/.env`、`python/`、日志、凭据名称和不安全 ZIP 路径。OPS-3A 必须复用这些规则，不得另建一套相互漂移的规则。

## 3. 强制安全边界

本 PR 严禁实现或触发：

- `apply-upgrade`
- `rollback`
- `restore`
- 服务停止、启动或重启
- 生产目录原地覆盖
- 数据库 migration apply
- `git pull`
- `git checkout`
- `git reset --hard`
- 任意 shell 执行
- 任意用户输入 URL 的网页透传
- 自动修复 owner map
- 删除生产数据或运行时文件
- 提交 `data/`、`assets/`、`output/`、`history.json`、`enterprise.db`、`enterprise.env`、`API/.env`、`python/`、日志、缓存、Token、Cookie 或用户上传文件

所有下载、解压和 staging 只能写入调用者明确提供的 OPS 工作目录；不得写入当前应用根目录。

## 4. 发布源模型

### 4.1 Provider 边界

新增可测试的发布源抽象，第一版至少支持：

- GitHub Releases provider。
- 本地 JSON fixture provider，用于离线测试和生产副本演练。

Provider 只返回规范化 metadata，不直接执行升级。

建议规范化字段：

```json
{
  "provider": "github-releases",
  "repository": "MEIS-DaCaiTou/Infinite-Canvas-Enterprise",
  "release_id": "...",
  "tag_name": "...",
  "version": "2026.07.6",
  "prerelease": false,
  "draft": false,
  "published_at": "...",
  "manifest_url": "https://...",
  "archive_url": "https://...",
  "release_notes": "..."
}
```

### 4.2 来源限制

- GitHub repository 必须是服务端或 CLI 明确配置值，不能来自未来 Update Center 的任意文本输入框。
- 只允许 HTTPS 网络地址。
- GitHub provider 仅接受 `api.github.com` 和经过验证的 GitHub release asset 下载地址。
- 重定向必须重新校验 scheme / host。
- 不得把 Authorization、Token、Cookie 或响应头写进报告和日志。
- 可选 GitHub Token 只能从进程环境读取；不得回显、持久化或写入 JSON。
- 网络超时、最大重定向次数、最大 metadata 大小和最大发布包大小必须有硬限制。

## 5. Release Manifest v1

新增严格 manifest schema，建议标识：

```text
ops-release-manifest-v1
```

最低字段：

```json
{
  "schema_version": "ops-release-manifest-v1",
  "release_version": "2026.07.6",
  "source_commit": "40-char lowercase sha",
  "source_tree": "40-char lowercase sha",
  "generated_at": "UTC ISO-8601",
  "archive": {
    "filename": "Infinite-Canvas-Enterprise-release-<commit>.zip",
    "size_bytes": 1,
    "sha256": "64-char lowercase sha256"
  },
  "package": {
    "file_count": 1,
    "root_prefix": "Infinite-Canvas-Enterprise-<commit>"
  },
  "compatibility": {
    "minimum_current_version": "",
    "maximum_current_version": "",
    "requires_database_migration": false,
    "migration_ids": []
  },
  "release_notes": ""
}
```

要求：

- 拒绝未知顶层安全关键字段或定义清晰的前向兼容策略。
- 严格验证类型，拒绝 bool/int 混淆。
- 版本、commit、tree、SHA256、文件名、大小、file_count 必须规范化。
- manifest URL、asset metadata 与 manifest 内容必须互相绑定。
- archive 文件名不得包含路径分隔符、绝对路径或 `..`。
- manifest 不得包含 secret。

## 6. 版本比较

实现项目专用版本解析，不依赖系统区域设置：

- 支持当前格式 `YYYY.MM.N`，每段必须是非负十进制整数。
- 拒绝空段、负数、前后空白和非数字段。
- 输出 `current_version`、`target_version`、`relation`：`newer` / `same` / `older` / `invalid`。
- prerelease 默认不作为可升级目标，除非调用者显式允许。
- downgrade 只报告，不作为普通在线升级候选。

## 7. 下载核心

新增标准库实现的原子下载器：

- 下载到同目录临时文件。
- 完成后校验实际字节数和 SHA256。
- 校验成功后使用原子 rename / replace 发布最终文件。
- 目标文件或 staging 目录已存在时默认拒绝覆盖。
- 下载中断时不得留下被误认为完整发布包的最终文件。
- 临时文件清理只能清理由当前 job 创建且严格匹配命名的临时文件。
- 响应体采用流式读取，不一次性加载整个 ZIP。
- 记录下载字节数和耗时，不记录请求凭据。

## 8. 安全 staging

新增 staging 核心：

- staging 目标目录必须不存在。
- 先执行 ZIP 中央目录只读检查。
- 拒绝绝对路径、盘符路径、UNC、`..`、空文件名、NUL、反斜杠绕过和路径规范化冲突。
- 拒绝符号链接、junction/reparse 风险条目或非普通文件类型。
- 限制单文件展开大小、总展开大小、文件数量和压缩比，防止 ZIP bomb。
- 解压时逐项写入，目标 resolved path 必须仍在 staging root 内。
- 解压完成后重新枚举文件并校验 manifest `file_count`。
- 调用增强后的 release validation；任何 critical finding 都使 staging 失败。
- staging 失败必须保留结构化报告；不得触碰应用根目录。
- 不得复制生产运行时目录进入 staging。

## 9. CLI / Python API

在保持现有命令兼容的基础上新增 OPS-3A 命令。命令名可在实现审查后微调，但至少覆盖：

```text
check-update
fetch-release
stage-release
prepare-online-update
```

建议职责：

- `check-update`：读取当前 `VERSION`，查询 provider，规范化 metadata，比较版本，写报告。
- `fetch-release`：获取并验证 manifest，下载 archive，校验 size/SHA256，写报告。
- `stage-release`：安全解压新目录，执行 manifest/file-count/release validation，写报告。
- `prepare-online-update`：组合已有 data-check、backup manifest、release validation 与 staging 结果，生成不执行升级的 plan。

Python 核心不得强依赖 argparse，以便 OPS-3C 后端白名单 API 直接调用同一 service 层。

建议模块边界：

```text
enterprise/ops/update/
  __init__.py
  models.py
  versions.py
  manifest.py
  providers.py
  download.py
  staging.py
  service.py
```

可以根据现有项目风格调整，但不得把全部逻辑继续堆进 `runner.py`。

## 10. Job 状态和报告

新增统一阶段状态：

```text
created
checking
metadata_ready
downloading
verifying
staging
staged
planned
failed
```

每个 job 至少记录：

- `job_id`
- `job_type`
- `state`
- `started_at`
- `updated_at`
- `finished_at`
- `current_version`
- `target_version`
- `source_commit`
- `manifest_sha256`
- `archive_sha256`
- `archive_size_bytes`
- `staging_path`
- `report_paths`
- `failure_code`
- 脱敏 `failure_message`

要求：

- 状态只能按允许的状态机前进。
- 失败不能被后续普通事件覆盖成成功。
- JSONL 不写 secret、token、cookie、完整请求头或环境变量值。
- 错误信息需要稳定错误码，不把任意远端响应正文直接写入日志。

## 11. prepare-online-update plan

计划至少绑定：

- 当前版本和目标版本。
- 当前 app root 指纹摘要。
- source commit / tree。
- manifest 文件 SHA256。
- archive SHA256 / size。
- staging 目录与 staging file-count。
- release-validation report。
- data-check report。
- executed backup manifest。
- migration requirement 摘要。
- 维护窗口文本。
- blockers / warnings。
- 明确的 `not_executed` 列表。

计划必须明确：

```text
No production files were replaced.
No services were stopped or started.
No database migration was applied.
No version switch was performed.
No rollback was performed.
```

## 12. 测试要求

新增临时目录和本地 HTTP fixture 测试，不访问真实生产，不依赖真实 GitHub 网络。

最低覆盖：

1. 版本比较：newer / same / older / invalid。
2. draft / prerelease 默认排除。
3. manifest 类型、commit、tree、SHA256、size、filename 校验。
4. HTTP 非 HTTPS 拒绝（本地 fixture provider 可显式测试豁免，但生产 GitHub provider 不得豁免）。
5. redirect host/scheme 校验。
6. metadata 超限、archive 超限、timeout。
7. 下载中字节数不符。
8. 下载 SHA256 不符。
9. 已存在目标拒绝覆盖。
10. 临时文件不会被当作完成包。
11. ZIP traversal、绝对路径、Windows drive、UNC、混合斜杠。
12. symlink / reparse 风险条目。
13. duplicate normalized path。
14. ZIP bomb 文件数、总大小和压缩比限制。
15. release 内包含 runtime / secret 路径时失败。
16. manifest file_count 与实际不一致。
17. staging 目录已存在时失败。
18. staging 失败不修改 app root。
19. job 状态机合法/非法转换。
20. 日志和报告敏感字段扫描。
21. `prepare-online-update` 缺少 backup/data-check/staging 输入时 blocked。
22. 全部通过时生成 ready 或 ready-with-warnings plan。
23. 现有 `test_ops_runner.py` 和 `test_ops_windows_wrappers.py` 回归通过。

测试只能使用临时文件、临时 SQLite 和本地 fixture；不得写入仓库 runtime 路径。

## 13. 文档同步

本 PR 需要更新：

- `docs/ops/OPS-ROADMAP-2026-07.md`
- `docs/CURRENT_PROJECT_STATUS.md`
- `enterprise/tests/README.md`
- 新增 OPS-3A 实现与 CLI 文档

文档必须区分：

- 已实现并通过测试。
- 仅规划。
- OPS-3B 才会实现的 apply / rollback。
- OPS-3C 才会实现的网页 Update Center。
- 尚未进行的生产升级。

## 14. PR 验收标准

PR 必须保持 Draft，直到主对话完成代码审查。

验收需提供：

- changed-file 清单与职责。
- manifest schema 示例。
- 状态机说明。
- threat model / 安全失败场景。
- 完整测试命令和逐项结果。
- `git diff --check`。
- 变更文件 secret scan。
- 明确确认未触碰生产、未执行升级、未提交运行时数据。

## 15. 本阶段明确不实现

- 正式 `apply-upgrade`。
- 正式 `rollback` / `restore`。
- 服务生命周期控制。
- 当前版本指针切换。
- 数据库 migration apply。
- Update Center HTML/UI。
- 后端网页 OPS API。
- Step-up Authentication / Operation Token。
- Docker / 1Panel / PostgreSQL / Redis / 对象存储。
- 自动清理旧 release、backup 或 staging。

上述内容分别进入 OPS-3B、OPS-3C、SEC-1U 或后续阶段。