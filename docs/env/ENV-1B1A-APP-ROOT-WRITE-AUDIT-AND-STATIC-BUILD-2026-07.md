# ENV-1B1A：APP_ROOT 写入审计与确定性 Static 构建

- 状态：已由 PR #81 完成并合并
- 审计日期：2026-07-20
- 起始代码基线：`main@be5573ae416b4ce81f8cc26ae282868a7efa7672`
- 决策依据：[ADR-ENV-003](../decisions/ADR-ENV-003-IMMUTABLE-RELEASE-STATIC-CACHE-2026-07.md)、[ADR-ENV-004](../decisions/ADR-ENV-004-PATH-ROOTS-AND-RELEASE-DIRECTORY-2026-07.md)、[ADR-ENV-005](../decisions/ADR-ENV-005-RUNTIME-ENTRYPOINT-SELF-CHECK-MODES-2026-07.md)
- `production_device_touched_by_project_owner=true`（项目负责人确认的既有事实）
- `production_device_touched_by_codex=false`
- `production_modified_by_this_PR=false`

## 1. 结论

本任务关闭一个明确 blocker：`main.py` 不再在 import、FastAPI startup 或 HTML 响应阶段按版本和 mtime 改写 `static/*.html`。静态缓存参数改由显式 Release staging builder 生成：本地叶子资源使用实际文件字节的完整小写 SHA-256，CSS 使用传递依赖处理后的 output SHA-256，HTML 引用 HTML 使用统一确定性 build ID；builder 只接受显式 source、全新 output 和 report 路径。

这不等于 APP_ROOT 已只读。审计识别出 40 个功能写入流；只有 static 自修改和新 builder 边界在 ENV-1B1A 内关闭，其余数据、配置、上传、生成结果、启动 migration、legacy update、重启脚本、OPS 默认路径、bytecode 等仍是 ENV-1B1B / ENV-1B1C 或后续阶段 blocker。正式不可变 Release、Release-bound Python 和 Production Baseline 均未形成。

## 2. 审计方法和可重复证据

审计以受 Git 管理的 Python、PowerShell、Batch 和 JavaScript 为输入，结合以下四层证据，不把单一关键词命中等同于真实写入：

1. Python AST 检查 write-mode `open` / `Path.open`、`write_text`、`write_bytes`、目录和删除/移动 API、`json.dump`、SQLite、临时文件、图片保存、解压、下载和日志构造。
2. PowerShell / Batch / JavaScript 受控文本检查 `Out-File`、content cmdlet、文件操作、transcript、下载目标、重定向和浏览器 local storage。
3. 从入口、caller、路径常量和触发条件追到实际目标；区分磁盘写入、内存序列化、浏览器客户端缓存和只读打开。
4. `enterprise.release.app_root_audit` 只接收 Git tracked 文件集，排除 test fixture 和浏览器静态页面后，对每个生产写入 site 记录相对文件、qualified symbol、operation 和规范化调用 SHA-256 fingerprint，再映射到 W01-W41。
5. 冻结 manifest digest 覆盖所有 site fingerprint 和 Wxx；在既有 symbol 或脚本中新增、删除或改变写入也会漂移。每个 Wxx 另有必须存在的文件/符号锚点；读取失败、Unicode decode error 和 Python `SyntaxError` 均 fail closed。

原始 ENV-1B1A 扫描的 40 个功能流是历史基线。当前 ENV-1B1B C1 重新扫描 Git tracked 输入后，83 个生产候选文件进入扫描、239 个文件被分类排除，检测到并映射 293 个 write site，parse failure、uncovered site 和 stale mapping 均为 0；冻结 site manifest SHA-256 为 `2220ebccfea0194d1bfe4c5720f6da134e30babc6a42d86259c0e665e888f0d0`。C1 新增 W41，将 current-release persistent-state primitive 从 W24 分离。ENV-1B2P 的 `runtime_provenance._atomic_write_report` 仍归入 W40，不表示 APP_ROOT 路径已迁移。该静态分析是可重复漂移门禁，不能证明绝对不存在动态或未知写入。

## 3. 写入流清单

“APP?” 表示当前默认目标是否位于版本目录。目标根严格使用 ADR-ENV-004 的集合。“已识别”只表示纳入清单，不表示已迁移。

| ID | 文件与符号 | 当前目标 / APP? | 触发阶段与模式 | 内容；持久事实；secret | 当前 caller | 目标根 | ENV-1B1A 状态 / 后续 | 风险与证据 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| W01 | `main.py:sync_static_html_versions`、`startup_event`（已移除） | `static/**/*.html`；是 | startup；upstream child | cache `v`；否；否 | FastAPI startup | `STAGING_ROOT` | 已关闭；builder 取代 | 原逻辑按 mtime 重写源码；import/startup/source-hash 测试 |
| W02 | `main.py` 模块级 `makedirs` | `assets/`、`output/`；是 | import；所有入口 | 上传/输出目录；目录含持久数据；可能 | Python import | `UPLOAD_ROOT` | 已识别；ENV-1B1B | import 仍写 APP_ROOT；AST inventory |
| W03 | `main.py` 模块级 `makedirs` | `static/`、`workflows/`；是 | import；所有入口 | Release 目录；是；否 | Python import | `APP_ROOT` | 已识别；ENV-1B1B | 只读 Release 中连 mkdir 也必须移除或验证；AST inventory |
| W04 | `main.py` 模块级 `makedirs` | `data/`、conversation、canvas；是 | import；所有入口 | 业务目录；是；可能 | Python import | `DATA_ROOT` | 已识别；ENV-1B1B | import 创建持久目录；AST inventory |
| W05 | `main.py:ensure_runtime_config_files` | `API/.env`、`data/`；是 | import；foreground/service-host/child | 配置实例；是；是 | 模块 import | `CONFIG_ROOT` | 已识别；ENV-1B1B | import 创建 secret 文件；定点源码核对 |
| W06 | `main.py:update_env_values` | `API/.env`；是 | admin；API request | provider key/config；是；是 | 设置 API | `CONFIG_ROOT` | 已识别；ENV-1B1B | secret 与 Release 混放；AST inventory |
| W07 | `main.py:save_to_history`、`delete_history`；`enterprise/interceptors.py:_write_history_records` | `history.json`；是 | normal business request | 历史业务事实；是；可能 | 生成、删除、隔离拦截 | `DATA_ROOT` | 已识别；ENV-1B1B | 双写入口和并发一致性；测试锚点 |
| W08 | `main.py:save_conversation`、`delete_conversation` | `data/conversations/*.json`；是 | normal business request | 对话；是；可能 | 对话 API | `DATA_ROOT` | 已识别；ENV-1B1B | 持久用户数据位于 APP_ROOT；AST inventory |
| W09 | `main.py:save_canvas`、`save_projects`、`update_canvas_meta`、`delete_project`、`purge_canvas`；`enterprise/db.py:set_canvas_project` | `data/canvases/*.json` 及 trash；是 | normal business request / admin | 画布和归属；是；可能 | 画布/项目 API | `DATA_ROOT` | 已识别；ENV-1B1B | 多入口 JSON 更新；AST inventory |
| W10 | `save_asset_library`、`save_prompt_libraries`、`shared_folders_save`、`save_runninghub_workflow_store` | `data/*.json`；是 | normal business request | 业务元数据；是；可能 | 素材、提示词、共享目录 API | `DATA_ROOT` | 已识别；ENV-1B1B | 多类持久 JSON 位于 APP_ROOT；AST inventory |
| W11 | `save_api_providers`、`update_env_values` | `data/api_providers.json`、`API/.env`；是 | admin | provider 配置/凭据；是；是 | 设置 API | `CONFIG_ROOT` | 已识别；ENV-1B1B | 配置与 secret 需限制读取者；源码核对 |
| W12 | `upload_workflow`、`save_workflow_config`、`delete_workflow`、workflow library helpers | `workflows/` 和 workflow JSON；是 | admin / normal business request | 用户工作流；是；可能 | workflow API | `DATA_ROOT` | 已识别；ENV-1B1B | 用户数据与上游 Release 模板混放；AST inventory |
| W13 | upload/import helpers | `assets/input`、`assets/uploads`；是 | upload | 用户上传；是；可能 | upload / local import API | `UPLOAD_ROOT` | 已识别；ENV-1B1B | 用户文件位于版本目录；AST inventory |
| W14 | asset library create/move/rename/delete/crop helpers | `assets/library`；是 | normal business request / admin | 素材文件和 caption；是；可能 | asset API | `UPLOAD_ROOT` | 已识别；ENV-1B1B | move/delete 与 owner 数据一致性；AST inventory |
| W15 | download/generate/store helpers | `output/`、`assets/output`；是 | upload / generation | 生成结果；是；可能 | Provider / Comfy / RunningHub | `UPLOAD_ROOT` | 已识别；ENV-1B1B | 下载、临时替换、失败清理分散；AST inventory |
| W16 | `media_preview._build_preview`、`image_jpeg._build` | `data/media_previews`；是 | normal business request | 可重建预览；否；可能 | media response | `CACHE_ROOT` | 已识别；ENV-1B1B | cache 当前混入 DATA/APP_ROOT；AST inventory |
| W17 | provider/CLI/media temporary helpers | 系统 temp、临时图片/视频；通常否 | foreground / generation | 可丢弃临时文件；否；可能 | Codex/Gemini/Jimeng/media adapters | `TEMP_ROOT` | 已识别；ENV-1B1B/B1C | 路径分散、失败清理依赖 caller；AST inventory |
| W18 | `enterprise/db.py:get_db` 及业务连接 | `data/enterprise.db` 与 WAL/SHM/journal；是 | normal business request | 企业数据库；是；是 | gateway/admin/interceptors | `DATA_ROOT` | 已识别；ENV-1B1B | SQLite sidecar 与数据库同目录；连接调用链核对 |
| W19 | `enterprise/migrations/*`、security bootstrap | caller 指定 SQLite 及 sidecars；当前默认可在 `data/` | admin | Schema/migration 事实；是；是 | 显式 migration/activation 工具 | `DATA_ROOT` | 已识别；ENV-1B1B；DATA-1 | 不在旧生产执行；AST 与 runner 核对 |
| W20 | `migrate_asset_library_into_dirs` | `assets/library` move/mkdir；是 | startup / child | 素材布局；是；可能 | `startup_event` | `UPLOAD_ROOT` | 已识别；ENV-1B1B | startup 仍会写持久素材；startup 回归证明调用保留 |
| W21 | `migrate_double_extension_uploads`、`migrate_mislabeled_image_extensions` | `assets/uploads` rename；是 | startup / child | 上传文件名；是；可能 | `startup_event` | `UPLOAD_ROOT` | 已识别；ENV-1B1B | startup rename 仍阻止只读 APP_ROOT；调用保留测试 |
| W22 | legacy update download helpers | `data/.update_staging` 等；是 | update | 下载和 staging；否；否 | legacy update endpoint | `STAGING_ROOT` | 已识别；ENV-1B1B/OPS-3B | 与 OPS-3A workspace 并存；源码核对 |
| W23 | `update_from_github`、`rollback_update` | 覆盖/删除 `main.py`、`static/` 等；是 | update | Release 文件；是；否 | legacy update endpoint | `APP_ROOT` | 已识别；OPS-3B 后续 | 原地更新违反不可变 Release；本任务不实现或调用 |
| W24 | `schedule_self_restart` | `_self_restart.bat` / `.sh`；是 | restart | 一次性控制脚本；否；可能含路径/PID | legacy update restart | `STATE_ROOT` | 已识别；ENV-1B1B/B1C | 生成脚本位于 APP_ROOT；脚本和 caller 核对 |
| W25 | `schedule_self_restart`、`_self_restart.bat` | `_self_restart.log`；是 | restart / crash handling | launcher 日志；否；可能 | legacy restart script | `LOG_ROOT` | 已识别；ENV-1B1B/B1C | APP_ROOT 日志且脚本含强制 taskkill；文本扫描 |
| W26 | `enterprise/runtime/state.py`、control/process/child | PID、lock、state、command、ACK、shutdown marker；默认否 | service-host / foreground / child / stop | runtime 控制状态；否；可能 | runtime CLI/controller/supervisor | `RUNTIME_ROOT` | 已在现有 runtime root；ENV-1B1C 接线仍待做 | 默认 `%LOCALAPPDATA%` 且拒绝 APP_ROOT；runtime 测试 |
| W27 | `enterprise/runtime/logging.py`、supervisor streams | launcher/upstream/gateway/health/crash logs；默认否 | service-host / child / crash handling | 脱敏日志；部分保留；可能 | supervisor/runtime host | `LOG_ROOT` | 当前实际位于 runtime root；ENV-1B1B | 正式 LOG_ROOT 尚未接线；runtime 测试 |
| W28 | host bootstrap failure、graceful request/marker | runtime control 目录；默认否 | crash handling / stop / child | 失败与关闭证据；否；可能 | host/process/child | `RUNTIME_ROOT` | 已识别；ENV-1B1C | 入口统一和 Release identity 尚未完成；AST inventory |
| W29 | `enterprise/ops/runner.py:write_json` | `ops_artifacts/` 默认相对 cwd；可为是 | admin | inventory/check/plan report；否；可能 | OPS CLI | `STAGING_ROOT` | 已识别；ENV-1B1B | 默认 cwd 可落 APP_ROOT 且旧报告可含绝对路径；AST/CLI defaults |
| W30 | `append_jsonl`、update job log | `logs/ops/jobs.jsonl` 或 workspace；可为是 | admin / update | job log；部分保留；可能 | OPS runner/update service | `LOG_ROOT` | 已识别；ENV-1B1B | runner 默认相对 cwd；redaction 测试存在 |
| W31 | OPS backup helpers | `ops_backups/` 默认相对 cwd；可为是 | backup | SQLite/JSON/assets backup；是；是 | OPS backup execute | `BACKUP_ROOT` | 已识别；ENV-1B1B | 默认路径仍可能在 APP_ROOT；备份测试 |
| W32 | `enterprise/ops/update/download.py`、jobs | 显式外部 workspace；否（校验要求） | update | archive part、job/report；否；可能 | OPS-3A service | `STAGING_ROOT` | 已实现 workspace 边界；正式根接线待 ENV-1B1B | 原子下载、redaction、containment 测试 |
| W33 | `enterprise/ops/update/staging.py` | 显式 workspace staging；否（校验要求） | update | 解压 Release Candidate；否；否 | OPS-3A prepare | `STAGING_ROOT` | 已实现 fresh staging；OPS-3B 未实施 | ZIP 安全和全新目录测试 |
| W34 | `enterprise/tests/**` fixtures | pytest / system temp；否 | test | 临时 DB、sidecar、日志、文件；否；测试 secret | test runner | `TEMP_ROOT` | 已隔离；持续验证 | scanner 将整个 tests 树分类为 test-only |
| W35 | `get-pip.py` | 临时目录和所选 Python site-packages；可能 | admin | installer/bootstrap；是；供应链敏感 | 人工安装脚本 | `PYTHON_RUNTIME` | 已识别；ENV-1B2P/B2 | 不由正式入口调用，本任务不执行/修改 Runtime |
| W36 | Jimeng install/login scripts | WSL temp、日志、API 辅助文件；部分是 | admin | CLI、login state、日志；是；是 | 人工 PowerShell/Batch | `TEMP_ROOT` | 已识别；ENV-1B1B/B1C | transcript/临时清理和凭据边界；脚本扫描 |
| W37 | OPS-2A/2B Windows wrappers | 显式 output、report、job log；可为是 | backup / admin | 盘点、备份、日志；部分持久；可能 | 人工 PowerShell | `STAGING_ROOT` | 已识别；ENV-1B1B | caller 必须显式选择外部根；脚本扫描 |
| W38 | shipped/browser tool JavaScript | browser `localStorage`、浏览器/UXP temp download；服务器 APP_ROOT 否 | foreground / normal business request | 客户端偏好和临时下载；否；可能 | browser/connector | `CACHE_ROOT` | 已分类；不是服务器 APP_ROOT blocker | 受控 JS 扫描；不得误计为 Python server 写入 |
| W39 | Python import machinery | `__pycache__` / `.pyc`；默认可在 APP_ROOT | import / child | bytecode cache；否；否 | Python interpreter | `CACHE_ROOT` | 已识别；ENV-1B1C/B2 | 正式入口尚未禁止 APP_ROOT bytecode；生命周期门禁待做 |
| W40 | `enterprise/release/static_build.py`、`enterprise/release/runtime_provenance.py` | 调用者显式全新 output + report；否（正式要求） | release-build / evidence verification | staging static、确定性构建报告与脱敏 provenance 报告；否；否 | 显式 build / verifier CLI | `STAGING_ROOT` | static 边界已关闭；provenance report 已识别，正式根仍待 ENV-1B1B | source/evidence 只读、原子 report、失败清理、确定性测试 |
| W41 | `enterprise/release/current_release.py:atomic_write_current_release` | `STATE_ROOT/current-release.json`；否 | test / validation state primitive | strict current-release pointer；是；否 | 当前仅测试/验证调用 | `STATE_ROOT` | C1 已实现状态原语；没有 activation call site | fixed `.new` exclusive create、owned-temp cleanup、atomic replace 测试 |

### 3.1 要求覆盖但当前无仓库写入器的项目

- `global_config.json`：当前受 Git 管理的 Python 只读取，未发现明确 writer；未来若成为实例配置，必须位于 `CONFIG_ROOT`。
- `enterprise.env`：当前只读取；真实实例文件含 secret，必须位于 `CONFIG_ROOT` 且不得提交。
- Release package：当前 OPS-3A 只下载并 staging 已存在 archive；正式 Release package 生成、Manifest v2 和激活未实现，后续仍归 `STAGING_ROOT` / `APP_ROOT` 的新目录发布协议。

## 4. 分类统计

历史 40 个功能写入流按主要触发阶段计数；C1 的 W41 是独立 state primitive，未倒灌改写该历史分类表：

| 主要阶段 | 数量 |
| --- | ---: |
| import | 5 |
| startup | 2 |
| foreground / 客户端 | 2 |
| service-host / child / stop | 2 |
| restart | 2 |
| crash handling | 1 |
| normal business request | 7 |
| upload | 1 |
| generation | 1 |
| admin | 8 |
| update | 4 |
| backup | 2 |
| release-build | 2 |
| test | 1 |
| **总计** | **40** |

按计划目标根计数：

| ADR-ENV-004 根 | 数量 |
| --- | ---: |
| `APP_ROOT` | 2 |
| `CONFIG_ROOT` | 3 |
| `DATA_ROOT` | 8 |
| `UPLOAD_ROOT` | 6 |
| `LOG_ROOT` | 3 |
| `BACKUP_ROOT` | 1 |
| `STATE_ROOT` | 1 |
| `STAGING_ROOT` | 7 |
| `RUNTIME_ROOT` | 2 |
| `CACHE_ROOT` | 3 |
| `TEMP_ROOT` | 3 |
| `PYTHON_RUNTIME` | 1 |
| **总计** | **40** |

## 5. Static staging builder 契约

实现位置：

- `enterprise/release/static_build.py`：核心 builder。
- `enterprise/release/runtime_provenance.py`：ENV-1B2P 只读证据验证与调用者显式报告写入；不接线正式 Release 入口。
- `tools/build_release_static.py`：薄 CLI，只解析三个必填路径并返回稳定错误分类。

构建规则：

1. source、output、report 都必须显式提供；output 必须不存在，不能等于 source 或位于 source 内，report 不能位于 source/output 内。
2. source tree 的 symlink 和 Windows reparse point fail closed；引用解析绝对化后必须仍在 source root。
3. 先逐字节复制到全新 staging；递归扫描全部 CSS 的 `url(...)`、`@import url(...)`、`@import "..."` 和 `@import '...'`，按 CSS 所在目录或 `/static/` 根解析引用，生成稳定依赖图并以 dependency-first 顺序处理。
4. CSS import cycle、缺失资源、路径逃逸和 reparse/symlink 均 fail closed；本地图片、字体、SVG 等叶子资源使用 source 文件实际 SHA-256，被 import 的 CSS 使用转换后 output SHA-256，因此字体变化会传递到 CSS 以及引用该 CSS 的 HTML。
5. 随后递归处理所有 HTML；`src`、`data-src`、`href`、`poster` 和内联 CSS `url()` 中的本地 JS/CSS/HTML/图片/字体纳入版本处理。HTML 引用 HTML 不使用源 HTML 单文件哈希，而统一使用 `SHA-256(builder_version + NUL + source_tree_digest)`；HTML 相互引用不形成依赖循环。
6. HTTP(S)、`data:`、`blob:`、`mailto:`、`javascript:` 和协议相对 URL 不修改；应用绝对路由也不当作 static 文件。
7. 已有所有 `v` 参数被移除后规范追加一个 `v=<64-char-sha256>`；其它 query 和 fragment 原样保留。
8. tree digest 只由稳定排序后的相对路径和文件字节构成；HTML build ID 只由固定 builder version 和 source tree digest 构成；不使用时钟、mtime、ctime、随机数或本机路径。
9. report schema 为 `env-1b1a-static-build-report-v2`，builder version 为 `env-1b1a-static-builder-v2`；字段稳定排序、UTF-8、无绝对路径和时间戳。
10. 明确本地资源缺失、CSS import cycle、路径逃逸、reparse、非 UTF-8 HTML/CSS、已存在 output/report 都 fail closed。失败不留下成功 report，并清理本次新建的 output。

报告字段包括 schema/builder version、source/output tree digest、HTML/CSS 数量、`html_version_policy`、`html_build_id`、CSS dependency order/import edges、modified HTML/CSS、每个资源相对路径、source SHA-256、实际版本 SHA-256 与 version policy、unresolved references、skipped external URL 数量、result 和 warnings。真实仓库验收固定覆盖 `index.html -> vendor/css/fonts.css -> vendor/fonts/*.ttf`，10 个 TTF 均进入 resources。

## 6. `main.py` 最小上游覆盖补丁

本任务仅做 ADR-ENV-003 必需的兼容补丁：

- 从 `startup_event` 删除 `sync_static_html_versions()` 调用。
- 删除 `versioned_static_html` 和 `sync_static_html_versions`。
- `static_html_response` 返回 staging 已构建的 HTML 原文，不再按本机 mtime 动态改写。
- 三项既有 asset/upload startup migration 保持调用顺序和异常边界不变；API、Provider、Canvas、History、Asset Library、WebSocket、登录、企业隔离和 update 行为未重构。

上游同步必须把这三点作为企业版不可变 Release patch 保留；若上游仍依赖启动时 static 自修改，应优先向上游提交“build-time content hash / runtime source immutability” issue 或 PR。回滚仅需恢复上述两个 helper、startup 调用和 response 包装，但回滚会重新引入已确认的 APP_ROOT/static blocker，因此不能用于正式不可变 Release。

## 7. 阶段边界和剩余 blocker

### ENV-1B1A 已关闭

- 启动和 HTML response 不再生成 static `v` 参数。
- static build 在显式 staging 中完成，source 不变且输出/报告确定。
- 写入 inventory、Git tracked fingerprint manifest、W01-W41 锚点和 fail-closed 漂移测试形成；这仍不是对未知写入绝对不存在的证明。

### ENV-1B1B 当前 Draft PR

- 集中 PathRoots、current-release pointer 和 W02–W16、W18、W20–W21、W27、W29–W31 的核心默认路径迁移正在当前 Draft PR 实施；详见 [ENV-1B1B 实施记录](./ENV-1B1B-PATH-ROOTS-AND-CURRENT-RELEASE-IMPLEMENTATION-2026-07.md)。
- legacy update W22/W23、self-restart W24/W25、第三方/installer/辅助脚本 W17/W35–W37 和 bytecode W39 仍未关闭；不能因此宣称完整 APP_ROOT 只读。
- startup asset/upload migration 调用保留，但目标由 PathRoots 指向外部 UPLOAD_ROOT；此语义只在当前 Draft PR 中待审查。

### ENV-1B1C 尚未开始

- 正式入口、supervisor/host/child/process 尚未绑定集中路径根和显式模式。
- `__pycache__` / bytecode 尚未在 portable-release 中 fail closed 或迁到 `CACHE_ROOT`。
- `_self_restart.*` legacy 路径和正式入口替代尚未处理。

### ENV-1B2P 已合并 / 完整 ENV-1B2 尚未开始

- `get-pip.py`、系统 Python 和 `sys.executable` 不是正式 Runtime 证据。
- ENV-1B2P 已由 PR #82 合并；结论为 core `true`、dependency `false`、archive `false`、`production_approved=false`；它没有下载、安装、重建或修改 Python Runtime、lock、wheelhouse、SBOM 或 archive。
- 分层证据详见 [ENV-1B2P 实施与证据文档](./ENV-1B2P-WINDOWS-RUNTIME-PROVENANCE-EVIDENCE-2026-07.md)；完整 ENV-1B2 仍未开始。

### 其它后续

- legacy 原地 update/apply/rollback 与不可变 Release 冲突，需在 OPS-3B 的全新 Release 切换协议中处理；OPS-3B 当前未实现。
- Manifest v2、Release 激活、Fresh Install Bootstrap、DATA-1、正式 backup/restore rehearsal 均未实施；`current-release.json` 原语只在 ENV-1B1B Draft PR 中，尚未进入 main 或接线 activation。

因此当前 `full APP_ROOT immutable=false`、`formal Release created=false`、`Production Baseline=false`。
