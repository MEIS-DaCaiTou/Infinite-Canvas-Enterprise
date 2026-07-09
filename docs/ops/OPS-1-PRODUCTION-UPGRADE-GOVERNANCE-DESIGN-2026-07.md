# OPS-1：生产升级治理设计（2026-07）

## 1. 任务边界

OPS-1 是生产升级治理设计，只沉淀后续生产备份、离线发布包、升级演练、回滚、数据库迁移与数据治理的方案边界。

本阶段只做文档设计：

- 不写任何脚本。
- 不修改任何业务代码。
- 不访问生产主机。
- 不停止生产服务。
- 不升级生产。
- 不迁移数据库。
- 不清理生产数据。
- 不删除生产文件。
- 不生成可直接执行生产变更的脚本。
- 不修改 `main.py`、`enterprise/`、`enterprise-static/`、`static/`、`API/`、`workflows/`、`python/`、`VERSION`、测试或依赖文件。

OPS-1 的结果用于指导后续 OPS-2 / OPS-3 / OPS-4，不直接改变生产环境。

## 2. OPS-0 生产现状摘要

OPS-0 / OPS-0A 已完成生产环境只读盘点和文档化，关键结论如下：

- 生产主机与开发电脑 / Codex 环境不是同一台设备。
- 生产主机与开发电脑 / Codex 不在同一个局域网。
- Codex 不直接连接生产主机。
- 生产当前分支：`task/3g-4a-upload-isolation-impl`
- 生产 commit：`deb22620f792e68d8c2ccd86218510420733be97`
- 生产 VERSION：`2026.06.23`
- 当前开发仓库 `main / origin/main`：`c357b89e9601ea65b2c67d8611922069d93facfb`
- 生产已有真实用户和真实业务数据。
- 当前没有每日备份。
- 生产使用 Windows + bat + bundled python。
- `8000` 是 `enterprise.gateway:app` 对外入口。
- `3001` 是 `main:app` 本机入口。
- `data/`、`assets/`、`output/`、`history.json`、`data/enterprise.db`、`enterprise.env`、`API/.env` 均为生产关键资产。

生产目录不得被视为普通开发工作区。后续升级必须以备份、离线发布包、副本演练和维护窗口为前提。

## 3. 生产强制安全规则

生产升级前必须遵守以下强制规则：

- 生产目录不得直接执行 `git pull`。
- 生产目录不得直接 `checkout main`。
- 生产目录不得执行 `reset --hard`。
- 生产目录不得直接用开发仓库文件覆盖。
- 不得覆盖 `data/`、`assets/`、`output/`、`history.json`、`data/enterprise.db`、`enterprise.env`、`API/.env`。
- 不得在未完成完整备份和副本演练前执行升级。
- 不得在白天用户使用时执行升级。
- 不得在没有回滚方案时进入生产维护窗口。
- 不得让 Codex 直接远程操作生产主机。

任何生产变更必须由项目负责人在生产主机本机执行，并将脱敏后的命令输出和日志回传主对话复核。

## 4. 备份治理设计

OPS-1 只设计备份策略，不开发备份脚本。

### 升级前强制备份对象

升级前完整备份至少覆盖：

- 项目代码目录。
- `data/`
- `assets/`
- `output/`
- `history.json`
- `data/enterprise.db`
- `enterprise.env`
- `API/.env`
- 启动脚本。
- 当前 commit / branch / VERSION。
- frpc / frps / 1Panel / 反代配置摘要。
- 生产端口、进程与访问链路摘要。

### 备份层级

建议建立以下备份层级：

- 升级前强制完整备份：每次生产升级前必须执行。
- 每日增量或快照备份：覆盖业务数据变化，尤其是 `data/`、`assets/`、`output/`、`history.json`、`enterprise.db`。
- 每周完整备份：可用于跨周恢复。
- 每月归档备份：用于长期保留和审计。
- 重大升级前人工确认备份：必须由项目负责人确认备份路径、大小、清单和恢复可用性。

建议保留周期：

- 每日备份保留 7-14 天。
- 每周完整备份保留 4-8 周。
- 每月归档备份保留 6-12 个月。
- 重大升级前备份至少保留到下一个稳定版本通过验收后。

### 命名、清单与校验

备份命名建议包含：

- 环境：production。
- 备份类型：full / incremental / snapshot / pre-upgrade。
- 生产当前 commit。
- VERSION。
- 时间戳。

备份 manifest 至少记录：

- 备份时间。
- 生产路径。
- 当前 branch / commit / VERSION。
- 备份对象列表。
- 排除项列表。
- 文件数量和总大小摘要。
- 校验方式与校验结果。
- 负责人。
- 恢复演练状态。

备份完整性校验至少包括：

- 备份文件可读取。
- 备份大小符合预期。
- 关键文件存在：`history.json`、`data/enterprise.db`、`enterprise.env`、`API/.env`。
- 关键目录存在：`data/`、`assets/`、`output/`。
- SQLite 数据库可只读打开。
- 备份可在演练目录恢复出可启动副本。

### 敏感配置处理

`enterprise.env` 和 `API/.env` 必须备份，但不得提交到 Git。

含密钥的备份应离线保存或加密保存。文档只允许记录 env key 名称，不记录 value。不得记录 API Key、JWT secret 具体值、管理员密码、FRP 凭据、浏览器会话凭据、令牌值或云服务器登录信息。

## 5. 离线发布包设计

由于生产主机与开发 / Codex 环境隔离，生产机不直接拉 GitHub。后续升级应采用离线发布机制：

- 发布包由开发环境生成。
- 发布包经人工传输到生产主机。
- 生产主机本地解压、校验、演练、切换。
- 执行日志回传主对话复核。
- Codex 只能生成发布包结构设计和后续脚本草案，不能直接操作生产。

建议发布包结构如下，仅作为 OPS-1 设计示例，本阶段不新增这些目录或脚本：

```text
release/
  app/
  docs/
  manifest/
  scripts/
  README-UPGRADE.md
  CHECKSUMS.txt
```

发布包 manifest 至少包含：

- release version。
- source commit。
- generated time。
- included files。
- excluded runtime paths。
- checksum。
- required manual steps。
- rollback reference。
- compatibility notes。

发布包不得包含：

- `assets/`
- `output/`
- `history.json`
- `data/`
- `data/enterprise.db`
- `enterprise.env`
- `API/.env`
- `python/`
- 本地日志
- 令牌值
- 浏览器会话凭据
- API Key
- 上传文件
- 缓存文件

发布包只应包含目标版本代码、文档、manifest、校验清单和经审阅的升级说明。

## 6. 升级演练设计

生产升级必须先副本演练，后生产切换。建议流程：

1. 保留生产原目录不动。
2. 制作生产完整备份。
3. 新建升级演练目录。
4. 将生产数据副本复制到演练目录。
5. 将目标版本代码放入演练目录。
6. 在演练目录执行只读校验。
7. 在演练目录执行数据库迁移 dry-run。
8. 在演练目录检查 history / owner map / assets 引用。
9. 在演练目录进行浏览器登录验证。
10. 验证用户隔离、历史、画布、素材、生成输出。
11. 验证无误后再安排维护窗口。
12. 维护窗口内执行正式切换。
13. 切换后执行验收。
14. 验收失败触发回滚。

演练目录失败不能影响生产原目录。演练过程中产生的日志和报告应脱敏后回传主对话复核。

## 7. 回滚治理设计

升级失败时优先恢复升级前完整快照，不建议在半升级状态的原目录中继续硬修。

回滚必须覆盖：

- 代码。
- 数据库。
- `history.json`
- `assets/`
- `output/`
- env 文件。
- 启动脚本。
- 反代配置。

回滚后必须重新验证：

- 本机入口。
- 局域网入口。
- 公网入口。
- HTTPS。
- WebSocket。
- 登录。
- 管理后台。
- 普通用户隔离。
- 历史记录。
- 画布 / 对话 / 素材。
- 生成输出。

回滚后必须保留失败现场日志和失败 release 包，用于复盘。维护计划中必须定义最晚回滚时间点，例如维护窗口结束前 30-45 分钟必须完成是否回滚的决策。

### 回滚触发条件

出现以下任一情况，应进入回滚判断：

- 服务无法启动。
- 登录失败。
- 管理员无法进入。
- 普通用户隔离失效。
- 历史记录丢失。
- 画布打不开。
- 资源文件大量缺失。
- WebSocket 失败影响核心功能。
- 数据库迁移失败。
- 性能或错误率明显异常。
- 公网入口不可用。

## 8. 数据库迁移路线设计

长期目标：

- 短期：继续使用 SQLite，但建立 schema migration 机制。
- 中期：抽象数据访问层和迁移验证工具。
- 长期：优先 PostgreSQL。
- MySQL 作为可选备选，不作为优先目标。

PostgreSQL 优先原因：

- 更适合 JSON / JSONB。
- 更适合复杂 owner 映射、审计日志和数据治理查询。
- 事务、索引、约束能力更适合企业长期演进。
- 更适合未来多服务器部署。

OPS-1 不实施数据库迁移：

- 不写 migration 脚本。
- 不修改 schema。
- 不连接生产数据库。
- 不创建 PostgreSQL 配置。
- 不引入 ORM 或数据库依赖。
- 不改变当前 SQLite 生产运行。

未来迁移步骤建议：

1. 建立 SQLite schema version 表。
2. 建立 migration dry-run 工具。
3. 建立数据库备份与恢复校验。
4. 建立 owner map 数据一致性检查。
5. 建立 PostgreSQL 目标 schema ADR。
6. 建立 SQLite -> PostgreSQL 数据导出 / 导入验证。
7. 建立双环境演练。
8. 建立维护窗口切换方案。
9. 建立回滚方案。
10. 建立多服务器部署前置检查。

## 9. 数据治理设计

OPS-0 发现以下生产数据一致性风险：

- `history.json` 有 616 条，而 `user_history_map` 有 516 条，差约 100 条。
- `data/canvases` 有 80 个 json 文件，而 `user_canvas_map` 有 82 条。
- `data/conversations` 有 22 个 json 文件，而 `user_conversation_map` 有 25 条。
- `user_resource_map` 有 964 条，而 assets 总文件为 992 个。
- `data/update_backups` 位于 `data/` 目录内。
- 公网 WebSocket 支持状态未确认。

这些现象不在 OPS-1 中修复，也不直接判定为数据损坏。它们是 OPS-2 / OPS-5 / 数据治理阶段的输入。

后续治理检查应覆盖：

- history 记录是否有 owner。
- owner map 是否有对应实际文件。
- canvas 文件是否都有 owner。
- conversation 文件是否都有 owner。
- resource_url 是否能映射到磁盘文件。
- 磁盘图片是否有引用来源。
- 是否存在孤儿文件。
- 是否存在缺失文件。
- 是否存在跨用户可见风险。
- 是否存在旧版本 legacy 数据。
- 是否需要管理员确认归属 / 归档 / 删除。

任何归属修复、归档、删除都必须经过治理报告和管理员确认，不得自动执行。

## 10. 维护窗口设计

生产维护窗口建议安排在凌晨 3-5 点。

维护规则：

- 维护前确认完整备份。
- 维护前确认演练通过。
- 维护前确认回滚包可用。
- 维护前确认当前生产无关键任务运行。
- 维护期间暂停普通用户访问或明确维护提示。
- 维护期间只执行预先审阅过的步骤。
- 维护期间记录所有命令输出。
- 维护失败按最晚回滚时间点回滚。
- 维护结束后执行验收清单。

维护窗口内不得临时扩大操作范围。任何临时风险都应先停止操作，回传主对话复核。

## 11. 验收清单设计

升级后验收至少覆盖：

- 本机 `127.0.0.1` 访问。
- 局域网 `http://11.0.0.37:8000/` 访问。
- 公网域名访问。
- HTTPS。
- WebSocket。
- 登录页。
- 管理员登录。
- 普通用户登录。
- 用户 A / 用户 B 数据隔离。
- 管理员后台。
- 历史记录。
- 画布。
- 对话。
- 素材库。
- `assets/output` 图片访问。
- 生成输出。
- API provider 配置是否仍存在。
- ComfyUI / 第三方 API 配置是否仍存在。
- 审计日志是否写入。
- 错误日志检查。
- 回滚点确认。

不能仅以本机或局域网访问成功作为公网生产验收结论。

## 12. 后续任务拆分

建议后续任务顺序：

1. OPS-2：生产只读盘点脚本与备份脚本设计 / 实现。
2. OPS-3：离线 release 包生成机制。
3. OPS-4：生产升级演练。
4. OPS-5：数据完整性巡检工具。
5. OPS-6：管理员后台数据治理页面设计。
6. OPS-7：SQLite migration 机制。
7. OPS-8：PostgreSQL 迁移 ADR。
8. 3G-8：浏览器级自动化回归，暂后置但不取消。

每个 OPS 实现型任务都应保持 Draft PR，等待主对话复核和项目负责人验收。

## 13. OPS-1 不进入的事项

OPS-1 不做：

- 不开发备份脚本。
- 不开发升级脚本。
- 不开发 migration 脚本。
- 不开发数据治理工具。
- 不开发管理后台。
- 不修改生产。
- 不生成 release 包。
- 不做浏览器自动化测试。
- 不做 3G-8。
- 不做 PostgreSQL 实际迁移。

OPS-1 完成后，下一阶段优先进入 OPS-2；3G-8 暂后置但不取消。
