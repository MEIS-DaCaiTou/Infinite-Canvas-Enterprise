# Infinite Canvas Enterprise 项目范围锁定

更新时间：2026-10-03

本文件保留为 Release payload 与自动化所依赖的稳定文件名。项目当前事实见 [docs/CURRENT_PROJECT_STATUS.md](docs/CURRENT_PROJECT_STATUS.md)，详细路线见 [开发路线图](docs/roadmap/DEVELOPMENT-ROADMAP-2026-2027.md)。

## 1. 项目身份

- 唯一项目：`MEIS-DaCaiTou/Infinite-Canvas-Enterprise`。
- 本项目是持续开发维护的企业无限画布产品，不是临时兼容层。
- `Aidan-OS`、`Aidan-Canvas`、`Aidan-App-SDK` 的需求、实现和状态不得自动转入本项目。
- 历史来源为 `hero8152/Infinite-Canvas`；冻结基线为 `2026.07.6`，后续不再以持续同步上游为约束。

## 2. 固定实施顺序

实施顺序、阶段待办与验收只在 [唯一路线图](docs/roadmap/DEVELOPMENT-ROADMAP-2026-2027.md) 维护；本文件只锁定产品边界，不复制第二份任务队列。

主线已接入 migration/backup/restore；新增表仍须证明准确旧来源的交付/恢复路径，不因基础引擎存在就宣称全部客户可升级。

## 3. 产品硬边界

- 对外入口统一经过 Enterprise Gateway；内部 Canvas application 不直接暴露给 LAN。
- 权限必须覆盖 UI、HTTP、WebSocket、Worker、更新和未来 MCP/Agent 入口。
- 大型素材字节与业务数据库分离，引用使用资源 ID/版本/哈希。
- 新任务体系必须使已受理任务可持久查询；未知是合法状态。此为实施要求，不是旧内存任务已可全面恢复的声明。
- 桌面壳属于本产品，负责可选磁盘、容量控制、后台/断点下载和本地集成；浏览器版本继续受支持。
- 长期保留 SQLite 单机业务形态；团队服务端目标 PostgreSQL；员工客户端 SQLite 只缓存/设置，共享业务。不得把 SQLite 共享网络盘或单机部署包装成 HA。
- 更新必须可验证、可恢复、可审计；超级管理员确认不等于允许跳过备份、迁移或健康检查。

完整生命周期按 [统一交付 ADR](docs/decisions/ADR-DELIVERY-001-UNIFIED-INSTALL-UPDATE-LIFECYCLE-2026-10.md)：一个安装维护入口、一个更新引擎，稳定身份/目录/EXE；修复不重建数据、卸载默认保留。员工端和服务端分别更新，普通更新不夹带产品数据库迁移；已开放业务写入后不盲目回旧快照。远程采集不自动开启，未签名不关闭系统安全保护。

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
- 不设独立 Windows 主机/干净用户或付费签名前置门禁；保留 CI/必要回归，默认定向验证，不无理由重跑全套。
- 托管 Runner 的权限/Job Object 等平台限制必须记录；允许受控 skip，但不得宣称对应场景已由 CI 覆盖。
- 发布和部署始终是独立授权，不因代码合并自动发生。

## 6. 文档政策

- 只维护 [docs/README.md](docs/README.md) 指向的当前事实源。
- 不再新增 Agent 交接包、重复路线图或按会话堆叠的“当前状态”。
- 历史实施/证据分类保留，不重新成为任务入口；新增/移动资料同步 [登记表](docs/document-register.json)。
