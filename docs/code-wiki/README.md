# Infinite Canvas Enterprise Code Wiki

更新时间：2026-10-03
项目：`MEIS-DaCaiTou/Infinite-Canvas-Enterprise`

Wiki 是源码/运行参考，不是第二份状态表、路线图或生产批准。主线核验快照为 `main@7905ecf39efabeb3101d7b63c709d8dcd230c9a0`；部分章节保留较早源码索引，具体函数和规模统计须结合当前 Git 复核。

## 1. 阅读范围

- 数据迁移/恢复、一次确认与路由检查已接入 main，不能再笼统写“只支持同 Schema 更新”。
- 09.9 应用与通用 EXE 工具来自维护线；没有整体回归 main，BAT 表格仍是源码/旧安装兼容参考。
- 最新主线、PR/CI、Release 和现场结果只见 [CURRENT](../CURRENT_PROJECT_STATUS.md)，每轮重新核验。
- 安装更新设计见 [统一交付 ADR](../decisions/ADR-DELIVERY-001-UNIFIED-INSTALL-UPDATE-LIFECYCLE-2026-10.md)，任务只按 [路线图](../roadmap/DEVELOPMENT-ROADMAP-2026-2027.md)。

## 2. 章节

1. [系统架构](./01-system-architecture.md)
2. [仓库结构与模块职责](./02-repository-map.md)
3. [后端类与函数参考](./03-backend-reference.md)
4. [前端、API 与 WebSocket](./04-frontend-api-and-websocket.md)
5. [数据、权限与安全](./05-data-permissions-and-security.md)
6. [Runtime、安装、发布与在线更新](./06-runtime-install-release-update.md)
7. [依赖与外部集成](./07-dependencies-and-integrations.md)
8. [运行、测试与开发方式](./08-running-testing-and-development.md)
9. [已知限制、风险与维护建议](./09-known-limitations-and-maintenance.md)

## 3. 维护

模块/接口/入口实质变化时更新对应章节，不每个 PR 重写全部 Wiki。历史测试记录保留日期，不改写为本轮跑分；代码路径区分 main、维护线和已安装产品。

原则、边界和任务分别回到 [架构](../../ARCHITECTURE.md)、[范围](../../PROJECT_SCOPE_LOCK.md) 和 [路线图](../roadmap/DEVELOPMENT-ROADMAP-2026-2027.md)。新增/移动资料同步 [登记表](../document-register.json) 并做轻量检查；不把源码快照当永久当前值。
