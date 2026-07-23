# ENV-1B1B：PathRoots 与 Current Release 实施记录

- 状态：当前 Draft PR 实施中；尚未进入 `main`
- 基线：`main@240f6a2b93268a415cddc3c9af9951f334c8e4e1`
- `production_device_touched_by_project_owner=true`（项目负责人确认的既有事实）
- `production_device_touched_by_codex=false`
- `production_modified_by_this_PR=false`
- 依据：[ADR-ENV-004](../decisions/ADR-ENV-004-PATH-ROOTS-AND-RELEASE-DIRECTORY-2026-07.md)、[ADR-ENV-005](../decisions/ADR-ENV-005-RUNTIME-ENTRYPOINT-SELF-CHECK-MODES-2026-07.md)

## 1. 本 PR 已实施的边界

本 PR 新增纯 Python 标准库的 `enterprise.paths.PathRoots`。它以十四个固定根表达
ADR-ENV-004 的契约：`INSTALL_ROOT`、`RELEASE_ROOT`、`APP_ROOT`、`CONFIG_ROOT`、
`DATA_ROOT`、`UPLOAD_ROOT`、`LOG_ROOT`、`BACKUP_ROOT`、`STATE_ROOT`、`STAGING_ROOT`、
`RUNTIME_ROOT`、`CACHE_ROOT`、`TEMP_ROOT`、`PYTHON_RUNTIME`。根身份是由 schema、profile
和规范化根标签计算的稳定 SHA-256，不报告本机路径。

提供两个显式 profile：

- `development`：从代码位置而不是 cwd 得到兼容路径；不需要 `python/` 或
  `current-release.json`，且不能形成正式 Release 结论。
- `portable-release`：先仅推导安装拥有的根和 `STATE_ROOT`，读取严格的
  `STATE_ROOT/current-release.json`，再推导 `APP_ROOT` 与 `PYTHON_RUNTIME`。

两阶段 helper 只解析状态，不启动服务、不选择解释器、不切换 Release。运行时入口绑定、
PATH Python fail-closed 和启动自检仍是 ENV-1B1C。

未经 factory-derived capability 验证的 `PathRoots` 不能 install，也不能进入任何 prepare
写入能力；该私有 capability 不可由公开构造参数提供，也不会经 `dataclasses.replace` 继承。
release component 校验拒绝非 ASCII、分隔符、`..`、尾点/空格与 Windows
设备名（包括扩展名形式）。验证会拒绝空、相对、UNC、`\\?\\`、`\\.\\` 和 drive-relative
路径，使用组件语义 containment（不是字符串前缀），检查 portable 根的不预期重叠及
release/staging 同卷。目录能力只在显式调用时创建目标目录；
对既有路径以 `lstat` 拒绝 symlink/junction/reparse point。该 pre-use/post-create 检查不应
被描述为消除所有 Windows TOCTOU 竞态。

C2 correction pass 进一步补齐三项路径安全缺口：`DB_PATH` 解析返回前同时检查
`DATA_ROOT`、candidate parent 和已存在的 candidate 文件本身；`get_db()` 在创建父目录前后、
紧邻 `sqlite3.connect` 前以及连接建立后重复执行 reparse 检查，连接后发现 candidate 已变为
reparse 时立即关闭连接并 fail closed。OPS CLI 新增集中 operation-target validator：
portable-release 下 `--output-dir`/report 相对值锚定 `STAGING_ROOT/reports`，`--log-file`
锚定 `LOG_ROOT/ops`，`--backup-root` 锚定 `BACKUP_ROOT`，`--workspace` 锚定
`STAGING_ROOT/workspace`；显式安全外部本地目标可用，但 APP_ROOT、RELEASE_ROOT 内其它
release、UNC、device namespace、drive-relative、reparse escape、source/target overlap
和要求全新但已存在的目标均 fail closed。development compatibility 仍保留为兼容行为，不作为
portable Release 证据。

## 2. current-release 原语

`enterprise.release.current_release` 实现 schema
`env-1b1b-current-release-v1` 的严格 reader、resolver 和 writer。JSON 只接受固定字段、
UTF-8（无 BOM）、16 KiB 上限、无重复 key、规范 release ID、精确
`releases/<release_id>` 相对路径、小写 64 位 manifest SHA-256 与 UTC 秒级时间。reader
fail closed；writer 使用固定 `.new`、排他创建、flush/fsync 与 `os.replace`，不会在已有
residual `.new` 上覆盖。临时文件所有权以本次调用成功的排他创建状态和创建后记录的文件 identity
共同判断：外部残留无论长度或字节是否恰好等于 canonical payload 都不会删除；替换 pointer 前会重新
核对 identity；本次创建后 write、flush、fsync 或 replace 失败时，也只尽力清理 identity 仍匹配的
自有 `.new`，外部替换文件保持不动。

`os.replace` 成功后会尝试同步 `STATE_ROOT` 目录；在平台明确不支持目录 fsync 时返回稳定
`unsupported` 分类且不描述为 verified，非预期目录同步失败使用稳定
`CURRENT_RELEASE_DIRECTORY_SYNC_FAILED`。该失败发生时 pointer 可能已经替换，调用方必须
重新读取 `current-release.json` 作为权威状态；writer 不自动回滚 pointer，不引入 activation，也不
引入跨进程锁。

直接 reader 先将 `STATE_ROOT` 绝对化并拒绝相对、UNC、device namespace 与 drive-relative 形式；
它不会把调用进程 cwd 当作 state-root 锚点。

它是状态原语而不是 activation：没有 Release builder、manifest v2、版本切换、rollback 或
生产调用。pointer 的 `manifest_sha256` 只可与调用方显式传入的期望值比较；完整 manifest
真实性仍属于后续阶段。

writer 只使用进程内锁（`cross_process_lock=false`），不声称提供跨进程 activation lock 或
消除外部替换文件的全部 TOCTOU。本 PR 的生产源码搜索证据为
`current_release_writer_runtime_call_sites=0`、`current_release_reader_formal_runtime_call_sites=0`、
`Release_activation_call_sites=0`、`Release_activation_implemented=false`；当前调用者仅为测试和
两阶段 validation helper，不以易漂移的测试行数作为安全结论。

## 3. 已迁移的核心路径与兼容补丁

| 流 | 本 PR 行为 | 目标根 | 备注 |
| --- | --- | --- | --- |
| W02–W04 | 移除 `main.py` import 期目录创建；startup 才显式准备业务目录 | DATA / UPLOAD / CACHE / LOG / TEMP | `static`、shipped `workflows` 不再由 import 创建 |
| W07–W10、W18 | 上游 JSON、history、canvas/conversation 与企业 SQLite 常量改为 `DATA_ROOT` | DATA | 保持原 API 语义 |
| W11 | `enterprise.env` 与 provider 配置常量改为 `CONFIG_ROOT` | CONFIG | 未读取或生成真实凭据 |
| W12 | shipped workflows 留在 `APP_ROOT/workflows`；用户工作流 overlay 在 `DATA_ROOT/workflows` | APP / DATA | 编辑 shipped workflow 时先复制到用户树；shipped-only 删除拒绝 |
| W13–W15、W20–W21 | assets、uploads、output 常量改为 `UPLOAD_ROOT` | UPLOAD | 保留既有 startup migration 调用，但目标不再默认为 APP_ROOT |
| W16 | media preview 常量改为 `CACHE_ROOT` | CACHE | 可重建缓存 |
| W26–W28 | runtime control state 保持 `RUNTIME_ROOT`；仅 portable fixture 可显式注入 `LOG_ROOT/runtime` | RUNTIME / LOG | development 不迁回 `APP_ROOT/logs/runtime`；正式入口仍属 ENV-1B1C |
| W29–W33 | portable operation target 通过集中 validator 锚定 STAGING / BACKUP / LOG，并拒绝 APP_ROOT / RELEASE_ROOT / reparse / overlap；development compatibility 仍保留 | STAGING / BACKUP / LOG | 不是 Manifest v2 或 apply/switch |
| W40 | static builder 仅在显式 staging output 写入 | STAGING | ENV-1B1A 已实现，未接入 activation |

## 4. 可重复写入审计

`enterprise.release.app_root_audit` 只扫描 Git tracked 的生产候选文件；AST、受控脚本扫描、
site fingerprint、操作数、W01–W41 映射和每个 flow anchor 共同构成漂移门禁。当前本 PR
代码版本的结果是：scanned `83`、excluded `239`、detected/mapped `293`、parse failures
`0`、uncovered `0`、stale mappings `0`，site manifest SHA-256 为
`2220ebccfea0194d1bfe4c5720f6da134e30babc6a42d86259c0e665e888f0d0`。C2 重新运行
APP_ROOT audit 后统计和 digest 未变化。

这是“已知静态 site 发生漂移时提醒维护者更新审计”的证据，不证明运行时或动态路径绝对
不存在未知写入。

## 5. Deferred、formal Release blocker 与后续边界

### W01–W41 状态

| 流 | 状态 | 说明 |
| --- | --- | --- |
| W01 | migrated | ENV-1B1A static build-time boundary。 |
| W02–W04 | migrated | import 期 mkdir 移除，业务目录由 capability 准备。 |
| W05–W16 | migrated | config/data/upload/cache/workflow core constants 已指向 PathRoots。 |
| W17 | deferred | 第三方/provider 临时目录局部不可控；归属 ENV-1B1C/后续，非 formal Release blocker。 |
| W18 | migrated | enterprise SQLite 默认 DATA_ROOT。 |
| W19 | partially_migrated | caller 指定 migration SQLite 路径仍属 DATA-1/显式工具边界。 |
| W20–W21 | migrated | startup migration 调用保留，路径改为 UPLOAD_ROOT。 |
| W22–W23 | deferred | legacy update staging/原地覆盖；归属 OPS-3B，formal Release blocker。 |
| W24 | deferred | 仅 legacy `schedule_self_restart` / self-restart state/script 生命周期；仍属 ENV-1B1C/OPS-3B，formal Release blocker。 |
| W25 | deferred | legacy self-restart log；归属 ENV-1B1C 或 OPS-3B，formal Release blocker。 |
| W26 | partially_migrated | control state 继续在 RUNTIME_ROOT；正式入口统一属 ENV-1B1C。 |
| W27 | partially_migrated | development 继续使用外部 `RUNTIME_ROOT` 日志；portable fixture 可显式使用 `LOG_ROOT/runtime`，正式入口接线仍属 ENV-1B1C。 |
| W28 | partially_migrated | host/control state 保持 RUNTIME_ROOT，正式 host/child context 属 ENV-1B1C。 |
| W29–W31 | partially_migrated | portable operation targets 已具备外部根锚定和 fail-closed 测试；development compatibility 仍保留旧相对路径语义，因此不提升为完整 migrated。 |
| W32–W33 | partially_migrated | 现有 OPS-3A 保持显式外部 workspace；完整 Release staging/activation 不在本 PR。 |
| W34 | migrated | test-only 临时写入。 |
| W35–W37 | deferred | installer、人工辅助/Windows OPS wrapper；不改变 Runtime 或脚本。 |
| W38 | deferred | 浏览器客户端本地存储，不属于服务器 APP_ROOT。 |
| W39 | deferred | bytecode/PYTHONDONTWRITEBYTECODE 正式门禁属 ENV-1B1C，formal Release blocker。 |
| W40 | migrated | 显式 static/evidence staging output。 |
| W41 | migrated_state_primitive | `atomic_write_current_release` 是独立 `STATE_ROOT` persistent-state primitive；包含 owned-temp cleanup、atomic replace 和目录同步尝试；没有 activation call site。 |

| 类别 | 本 PR 结论 |
| --- | --- |
| 普通 deferred | W17、W35–W38 共 5 项，均有明确后续归属且未以范围扩张处理。 |
| formal Release blocker | W22–W25、W39 共 5 项；此外正式 runtime entrypoint/self-check 与可信 Python 尚未接线。完整 APP_ROOT read-only 因此未成立。 |
| ENV-1B1C | 未开始：只负责正式入口、解释器绑定和 fail-closed 自检，不应在本 PR 偷渡实现。 |
| ENV-1B2 / Manifest v2 | 未开始；不重建 Runtime、不生成 lock/wheelhouse、不建立 Release manifest。 |
| 其它 | Fresh Install Bootstrap、DATA-1、OPS-3B/3C、Release activation、生产部署均未实现。 |

因此，本 PR 若合并也只能说明路径契约和核心迁移进入仓库；
`ENV_1B1B_initial_implementation_present=true`、`ENV_1B1B_completion_classification=partial`、
`ENV_1B1B_acceptance_passed=false`、`ready_to_mark_ready=false`、`ready_for_merge=false`、
`merge_recommended=false`、`formal_release_blocking_deferred_count=5`、
`non_blocking_deferred_count=5`、`full APP_ROOT immutable=false`、`formal Release created=false`、
`Production Baseline approved=false`。

## 6. 验证范围

新增测试覆盖 profile、deterministic identity、无隐式目录创建、portable layout、Windows
特殊路径拒绝、capability trust boundary、component containment、DB_PATH data-root containment、
DB 文件级/父目录/连接后 reparse fail-closed、current-release malformed/duplicate/residual `.new`、
临时所有权故障注入、replace 后目录同步 verified/unsupported/unexpected failure 分支、两阶段解析、
portable OPS operation-target 外部根锚定和 APP_ROOT / reparse / overlap 拒绝，以及 FastAPI
startup、canvas/conversation/history/SQLite/upload/preview/OPS fixture/runtime log 的隔离路径验证。
测试只使用临时目录和开发解释器；不访问临时业务设备、生产、网络、Provider API 或真实数据。
`codex_reported_local_tests=true`；没有对应成功的 GitHub workflow，因此
`github_ci_verified=false`。
