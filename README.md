# Infinite Canvas Enterprise

`Infinite-Canvas-Enterprise` 是持续维护的企业无限画布产品主线，仓库为
[`MEIS-DaCaiTou/Infinite-Canvas-Enterprise`](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise)。
它与 `Aidan-OS`、`Aidan-Canvas`、`Aidan-App-SDK` 是相互独立的项目，需求、分支、发布和验收结果不得互相套用。

项目最初基于 `hero8152/Infinite-Canvas`，当前以上游 `2026.07.6` 代码作为冻结的历史来源基线；后续产品演进由本仓库独立负责，不再以持续同步上游为约束。

## 当前状态

- 动态主线以 `origin/main` 为准，开始任务前必须重新获取并核验。
- Runtime 主线收敛已由 [PR #108](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/108) 合并；SEC-P0 浏览器边界已由 [PR #119](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/119) 合并到 `main@8cdb3c7b7399dbb144dbd828fc2ad876c79ae64a`。这些只代表代码主线状态，不等于正式 Release 或客户部署批准。
- 当前进入第二阶段数据升级能力：先完成 [#109](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/issues/109) 独立复核，再执行 [#114](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/issues/114) 的更新中心 migration/backup/restore 集成。
- 已有 Manifest v2、不可变 Release、Runtime Supervisor、最小在线更新和 SQLite migration/restore foundation；数据库迁移尚未完整接入更新中心。
- 客户 `2026.08.5` 到 `2026.09.4` 的现场定点热修只证明已确认设备恢复，不自动代表通用 Production Baseline。

完整边界见 [当前项目状态](docs/CURRENT_PROJECT_STATUS.md)。

## 当前运行架构

```text
LAN / browser users
        |
        v
Enterprise Gateway :8000
authentication / authorization / audit / proxy / admin
        |
        v
Canvas application :3001 (loopback only)
        |
        +-- SQLite and business files
        +-- assets / task records / configuration

Runtime Supervisor
        +-- independent liveness/readiness and recovery
        +-- immutable Release pointer and update jobs
```

当前形态是 Windows 单机模块化单体，不应被描述为 PostgreSQL、多节点、高可用或完整分布式任务平台。详见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 固定实施顺序

后续开发必须遵循：

1. 安全修复
2. 数据升级能力
3. 在线升级体验
4. 部门与任务
5. 资源缓存与桌面壳
6. PostgreSQL 及高可用
7. 企业集成

先建立可恢复的数据升级能力，再增加业务表和业务数据，防止功能完成后无法安全交付给存量客户。阶段目标、依赖和验收条件见 [开发路线图](docs/roadmap/DEVELOPMENT-ROADMAP-2026-2027.md)。

## 快速启动

Windows：

```powershell
.\启动企业版.bat
```

停止：

```powershell
.\停止企业版.bat
```

常用入口：

- 应用：`http://127.0.0.1:8000/`
- 管理后台：`http://127.0.0.1:8000/enterprise/admin`
- 存活探针：`/enterprise/live`
- 健康状态：`/enterprise/health`

生产部署前必须创建本地 `enterprise.env`，替换 `JWT_SECRET` 和管理员凭据；不得提交密钥、令牌、Cookie、真实数据库、素材、输出或运行日志。

## 开发入口

开始任务时按顺序阅读：

1. [文档索引](docs/README.md)
2. [当前项目状态](docs/CURRENT_PROJECT_STATUS.md)
3. [当前架构](ARCHITECTURE.md)
4. [开发路线图](docs/roadmap/DEVELOPMENT-ROADMAP-2026-2027.md)
5. [代码边界](CODE_BOUNDARIES.md)
6. 对应 ADR、实施记录和测试说明

代码导航见 [Code Wiki](docs/code-wiki/README.md)，开发流程见 [CODEX_WORKFLOW.md](CODEX_WORKFLOW.md)，企业层快速指南见 [ENTERPRISE_DOCS.md](ENTERPRISE_DOCS.md)。

## 测试

测试入口以 [enterprise/tests/README.md](enterprise/tests/README.md) 和 GitHub Actions 为准。常用非破坏性检查：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\enterprise\tests\diagnose.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\enterprise\tests\smoke.ps1
```

生命周期、故障注入和更新测试可能停止当前服务或写入隔离测试目录，执行前应读取对应测试说明。项目负责人已明确：后续不设置独立 Windows 主机验收门禁；托管 CI 的平台限制仍需如实记录，不得伪装成已覆盖。

## 来源与许可证

历史来源项目为 [hero8152/Infinite-Canvas](https://github.com/hero8152/Infinite-Canvas)。来源归属、许可证和历史同步记录予以保留，但不再构成当前产品路线或文件修改限制。
