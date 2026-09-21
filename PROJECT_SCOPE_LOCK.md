# Infinite Canvas Enterprise 项目范围锁定

更新时间：2026-09-21

本文件保留为 Release payload 与自动化所依赖的稳定文件名。项目当前事实见 [docs/CURRENT_PROJECT_STATUS.md](docs/CURRENT_PROJECT_STATUS.md)，详细路线见 [开发路线图](docs/roadmap/DEVELOPMENT-ROADMAP-2026-2027.md)。

## 1. 项目身份

- 唯一项目：`MEIS-DaCaiTou/Infinite-Canvas-Enterprise`。
- 本项目是持续开发维护的企业无限画布产品，不是临时兼容层。
- `Aidan-OS`、`Aidan-Canvas`、`Aidan-App-SDK` 的需求、实现和状态不得自动转入本项目。
- 历史来源为 `hero8152/Infinite-Canvas`；冻结基线为 `2026.07.6`，后续不再以持续同步上游为约束。

## 2. 固定实施顺序

1. 安全修复
2. 数据升级能力
3. 在线升级体验
4. 部门与任务
5. 资源缓存与桌面壳
6. PostgreSQL 及高可用
7. 企业集成

禁止在数据 migration/backup/restore 尚未接入更新中心时，先大规模增加部门、账本和任务业务表并声称可交付给现有客户。

## 3. 产品硬边界

- 对外入口统一经过 Enterprise Gateway；内部 Canvas application 不直接暴露给 LAN。
- 权限必须覆盖 UI、HTTP、WebSocket、Worker、更新和未来 MCP/Agent 入口。
- 大型素材字节与业务数据库分离，引用使用资源 ID/版本/哈希。
- 所有已受理任务必须可持久查询；Provider 结果未知是合法状态。
- 桌面壳属于本产品，负责可选磁盘、容量控制、后台/断点下载和本地集成；浏览器版本继续受支持。
- SQLite 是单机形态；PostgreSQL 是后续团队/高可用形态。不得把 SQLite 多进程共享包装成高可用。
- 更新必须可验证、可恢复、可审计；超级管理员确认不等于允许跳过备份、迁移或健康检查。

## 4. 状态表达

每次汇报必须分别说明：

- 代码是否只在本地工作区；
- 是否已提交/推送；
- 是否进入 PR，CI 是否通过；
- 是否合并 `main`；
- 是否形成 GitHub Release；
- 是否在客户设备验证；
- 是否获得通用生产批准。

不得用后一个层级的词描述前一个层级。单台客户设备恢复不等于通用 Production Baseline。

## 5. 验收政策

- 以 GitHub Actions、隔离测试、故障注入和必要人工浏览器回归组成证据链。
- 项目负责人已明确不设置独立 Windows 主机验收门禁。
- 托管 Runner 的权限/Job Object 等平台限制必须记录；允许受控 skip，但不得宣称对应场景已由 CI 覆盖。
- 发布和部署始终是独立授权，不因代码合并自动发生。

## 6. 文档政策

- 只维护 [docs/README.md](docs/README.md) 指向的当前事实源。
- 不再新增 Agent 交接包、重复路线图或按会话堆叠的“当前状态”。
- 历史实施/证据文档可以保留，但不得重新成为任务入口。
