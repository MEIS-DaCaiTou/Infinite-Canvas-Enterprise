# Infinite-Canvas-Enterprise 开发路线图（2026-2027）

## 1. 已完成阶段

| 阶段 | 状态 | 说明 |
| --- | --- | --- |
| 3G-7B-1 | 已完成 | 用户删除影响 dry-run 预览。 |
| 3G-7B-2 | 已完成 | soft delete 语义收口、管理员保护、feature override 清理。 |
| 3G-7B-3 | 已完成 | 成员管理搜索、筛选、排序、分页，默认隐藏已停用用户。 |
| U-1 | 已完成 | 上游同步只读审计。 |
| U-2 | 已完成 | 受控同步到上游 `2026.07.6` 并补企业兼容。 |
| U-2-F1 / U-2-F2 | 已完成 | 文生图 / Enhance 刷新后历史丢失定位与云端 history type 一致性修复。 |
| DOC-1 | 已完成 | 项目文档体系全量同步与 Agent 交接资料更新。 |
| OPS-0 | 已完成 | 生产环境只读盘点。 |
| OPS-0A | 已完成 | 生产只读盘点报告文档化，PR #64。 |
| OPS-1 | 已完成 | 生产备份、离线发布包、升级演练、回滚、数据库迁移与数据治理方案设计，PR #65。 |
| ARCH-1 | 已完成 | 企业架构蓝图、开发路线图、Docker / 1Panel 蓝图和 OPS 路线图，PR #66。 |

## 2. 当前优先阶段

当前进入 OPS-2A：生产运维脚本工具套件第一版。

3G-8 暂后置但不取消。

ARCH-1 已把企业层、上游边界、生产 OPS、日志、Docker / 1Panel、PostgreSQL、对象存储和多服务器部署路线沉淀为后续 Agent 可执行的统一蓝图。OPS-2A 从这条蓝图进入第一版工具实现。

## 3. 生产运维主线 OPS

| 阶段 | 目标 | 状态 |
| --- | --- | --- |
| OPS-2A | 生产运维脚本工具套件第一版：ops-runner、inventory、backup、check-data、validate-release、prepare-upgrade、OPS job 本地结构化日志。 | 下一步 |
| OPS-2B | release 包生成 / 校验机制增强。 | 规划 |
| OPS-3 | Update Center 页面接入 OPS 能力，支持 apply-upgrade / rollback。 | 规划 |
| OPS-4 | 生产升级演练。 | 规划 |
| OPS-5 | 数据完整性巡检工具。 | 规划 |
| OPS-6 | 管理员后台数据治理页面。 | 规划 |
| OPS-7 | SQLite migration 机制。 | 规划 |
| OPS-8 | PostgreSQL 迁移 ADR 与演练。 | 规划 |

OPS-2A 是当前最小可执行入口。它先建立盘点、备份、数据检查、发布包校验和计划生成能力，不直接执行升级或回滚。

## 4. 日志与可观测性主线 OPS-L

| 阶段 | 目标 |
| --- | --- |
| OPS-L1 | 本地结构化日志：access / app / error / security / ops job JSONL。 |
| OPS-L2 | 远程日志推送：脱敏后推送到外部日志服务。 |
| OPS-L3 | 日志查询 / 管理后台展示。 |
| OPS-L4 | 集中日志平台适配：Loki / ELK / OpenSearch / ClickHouse 等。 |

当前只有基础审计日志和进程输出，不应写成已有完整日志体系。

## 5. Docker / 1Panel / 部署主线 OPS-D

| 阶段 | 目标 |
| --- | --- |
| OPS-D1 | Docker / 1Panel 部署设计。 |
| OPS-D2 | Dockerfile + docker-compose.yml。 |
| OPS-D3 | 1Panel 部署手册与 WebSocket / HTTPS 验收。 |
| OPS-D4 | PostgreSQL + 对象存储生产化。 |
| OPS-D5 | 多服务器部署设计。 |

当前项目还不是 Docker-ready，不能宣称支持一键 Docker 部署。Docker / 1Panel 是后续部署目标。

## 6. 自动化测试主线 3G-8

3G-8 不取消，等 OPS 生产治理基线建立后推进。

3G-8 应覆盖：

- 登录 / 登出。
- 管理员登录。
- 普通用户登录。
- 用户 A / 用户 B 数据隔离。
- 历史记录。
- 画布。
- 对话。
- 素材库。
- 管理后台。
- Update Center。
- WebSocket。
- API 设置 / 工作流设置权限边界。
- 生成路径最小冒烟。

3G-8 的目标是把当前项目负责人手动验收的核心路径脚本化。

## 7. 企业后台主线

企业后台后续应逐步覆盖：

- 用户管理。
- 权限管理。
- 功能开关。
- 审计日志。
- OPS job 状态。
- 备份记录。
- 升级记录。
- 数据治理。
- 日志查看。

当前已经具备成员管理、归属管理、操作日志和权限开关。OPS job、备份记录、升级记录、数据治理和日志查看仍是后续规划。

## 8. 数据层主线

数据层路线：

- 短期保留 SQLite。
- 建立 schema version。
- 建立 migration dry-run。
- PostgreSQL 作为长期优先目标。
- MySQL 作为备选。
- 补齐 owner map 完整性检查。
- 设计对象存储 / NAS。
- 建立多服务器前置条件。

PostgreSQL 优先原因是它更适合 JSON / JSONB、复杂 owner 映射、审计日志和数据治理查询，也更适合未来多服务器部署。

## 9. 上游同步主线

上游同步应继续采用受控路线：

1. 上游同步只读审计。
2. 受控同步。
3. 企业兼容修复。
4. 生产副本演练。
5. 维护窗口升级。
6. 回滚。

不得直接 merge upstream/main，不得整目录覆盖 `static/`，不得提交运行时目录或敏感配置。

## 10. 优先级说明

当前优先级：

```text
OPS-2A
  -> OPS-L1 / OPS-D1 可并行设计
  -> OPS-3
  -> OPS-4
  -> 3G-8
  -> OPS-5 / OPS-6 / OPS-7 / OPS-8
```

这一路线的核心判断是：生产环境已有真实用户和真实数据。进入更多功能开发或自动化回归前，必须先建立生产备份、盘点、发布、日志和回滚基础。
