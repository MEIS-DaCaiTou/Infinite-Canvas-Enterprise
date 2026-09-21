# Infinite Canvas Enterprise Code Wiki

> 更新日期：2026-09-21
>
> 核验工作区：`D:\CodeProject\Infinite-Canvas-Enterprise-MAINLINE-CONVERGENCE`
>
> GitHub：`MEIS-DaCaiTou/Infinite-Canvas-Enterprise`

本 Wiki 面向开发、维护、代码审查与故障排查。内容以源码和 Git 元数据为依据，说明“代码当前是什么”，不替代发布审批、生产验收记录或产品路线图。

## 1. 基线说明

| 观察面 | 提交 | 说明 |
| --- | --- | --- |
| GitHub `origin/main` | `58dc98c09e213ee747024d2934aa181d14cf0c1d` | `feat(data): add versioned SQLite migration foundation (#107)` |
| 主线收敛分支 | `codex/mainline-runtime-convergence-20260919@84f6fe2` | [PR #108](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/108)，等待审查与合并 |
| PR #108 CI | 两项 Windows checks 均 SUCCESS（2026-09-21 核验） | CPython 3.11 企业套件与 CPython 3.14 Runtime 专项；不等于 Release/生产批准 |
| 发布标签 `2026.09.4` | `a0d1ccf7c2c3ddb5d90c5dc25aea76d5e13dc65a` | 位于独立发布历史，不等同于 `main` 或本地 `HEAD` |
| 客户恢复工具分支 | `codex/customer-hotfix-2026.08.5-20260911@75da5c8` | 已推送、未合并主线，保存升级恢复执行器后续修复 |

因此：

- 通用结构说明覆盖 `origin/main` 与主线收敛分支。
- 收敛分支能力在 PR 合并前仍标注“分支增量”。
- 标签存在只证明 Git 中存在发布对象，不自动表示已合入主线、已部署或已成为正式生产基线。
- GitHub 仓库可见性应以实时状态为准，不在本 Wiki 固化。

## 2. 阅读顺序

1. [系统架构](./01-system-architecture.md)
2. [仓库结构与模块职责](./02-repository-map.md)
3. [后端类与函数参考](./03-backend-reference.md)
4. [前端、API 与 WebSocket](./04-frontend-api-and-websocket.md)
5. [数据、权限与安全](./05-data-permissions-and-security.md)
6. [Runtime、安装、发布与在线更新](./06-runtime-install-release-update.md)
7. [依赖与外部集成](./07-dependencies-and-integrations.md)
8. [运行、测试与开发方式](./08-running-testing-and-development.md)
9. [已知限制、风险与维护建议](./09-known-limitations-and-maintenance.md)

## 3. 一句话架构

这是一个以旧版无限画布 `main.py + static/` 为业务内核、以 `enterprise/` FastAPI Gateway 为认证授权与运维外壳、以 SQLite 和文件目录为事实存储、由 Windows Supervisor 管理 Gateway/Upstream 双进程、并通过不可变 Release 目录和 Manifest v2 实现安装与同 Schema 在线更新的单机企业版模块化单体。

## 4. 能力状态速览

| 能力 | 当前代码状态 |
| --- | --- |
| 画布、智能画布、素材库、对话、AI/工作流入口 | 已在旧业务内核与静态前端中实现 |
| 登录、固定三角色、资源归属、功能开关、管理后台 | 已在企业覆盖层实现 |
| Gateway/Upstream 生命周期与存活/健康检查 | `main` 已有基础；收敛分支合并任务回执、独立探针、单飞、外层截止与启动宽限修复 |
| Windows 固定 Python、路径根、不可变 Release、安装器 | 已有实现与大量契约测试 |
| 在线更新 | 仅支持 Manifest v2、同数据库 Schema、无迁移的安全更新 |
| 版本化 SQLite 迁移/恢复基础 | `origin/main` 已实现基础原语，尚未完整接入 Update Center |
| PostgreSQL、水平扩展、分布式任务队列 | 未实现 |
| GitHub Actions | PR #108 已新增 Windows 工作流，2026-09-21 两项检查通过；合并后 `main` 状态仍需实时核验 |

## 5. 相关事实源

- [项目 README](../../README.md)
- [当前项目状态](../CURRENT_PROJECT_STATUS.md)
- [当前架构摘要](../../ARCHITECTURE.md)
- [代码边界](../../CODE_BOUNDARIES.md)
- [测试说明](../../enterprise/tests/README.md)
- [文档索引](../README.md)

历史 ADR、验收记录和阶段性报告用于解释决策与证据，不能覆盖当前 Git 与源码事实。
