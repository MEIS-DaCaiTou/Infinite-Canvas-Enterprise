# Infinite Canvas Enterprise 开发工作流

更新时间：2026-09-21

## 1. 开始任务

1. 确认项目名称、仓库和本地路径，不能与 Aidan 系列项目混用。
2. `git fetch origin --prune`，记录 `origin/main`、当前分支、工作区状态和相关 PR。
3. 依次阅读：
   - `docs/README.md`
   - `docs/CURRENT_PROJECT_STATUS.md`
   - `ARCHITECTURE.md`
   - `docs/roadmap/DEVELOPMENT-ROADMAP-2026-2027.md`
   - `CODE_BOUNDARIES.md`
   - 任务对应 ADR、实施记录和测试说明
4. 若 Base/Head/PR 与任务描述不一致，停止修改并先纠正基线。
5. 检查未提交文件；不覆盖用户已有变更。

## 2. 路线门禁

任务必须落在固定顺序中：安全 → 数据升级 → 在线升级 → 部门与任务 → 资源缓存与桌面壳 → PostgreSQL/HA → 企业集成。

- 横向测试、日志、性能和模块化可以随当前阶段实施。
- 后续阶段可做只读调研或小型 spike，但不得把未完成前置能力包装成可交付产品。
- 涉及新增业务表时，先证明 Update Center 能迁移和恢复该 schema。

## 3. 实施规则

- 小步修改，优先复用领域服务和 Policy，不把业务规则继续堆入 Gateway。
- 所有输入做运行时校验；编译期类型不能替代兼容检查。
- 权限在服务端执行，前端隐藏只改善体验。
- Provider 请求写入持久任务/幂等信息后再执行；未知结果进入对账。
- 大型资源写入资源存储，数据库只写元数据和引用。
- schema 变化必须同时提供 migration、验证、备份/恢复和旧版本测试。
- Release/Update 变化必须固定源/目标版本、Manifest、哈希和失败恢复。

## 4. 分支与 PR

- 默认分支前缀：`codex/`。
- 一个 PR 只解决一个可验收主题；安全/数据/更新等高风险变化不得夹带无关重构。
- PR 说明必须列明：Base/Head、实现范围、未实现范围、数据/权限影响、测试结果、升级和回滚影响。
- GitHub Actions 通过不自动代表 Release 或生产批准。
- 发布、部署、客户升级和合并是四个独立动作，需要分别授权和记录。

## 5. 验证

按风险选择并记录：

- 单元和静态契约测试；
- 企业完整测试；
- CP314 Runtime 专项；
- 数据 migration/backup/restore 故障注入；
- Windows 生命周期与端口/进程身份验证；
- 浏览器关键流程与权限矩阵；
- 真实 Provider 的受控成功/超时/未知结果场景；
- 性能和容量基线。

项目负责人已取消独立 Windows 主机验收门禁。托管 CI 不能执行的场景应记录为限制，并通过可复现实验或必要人工验证补证；不得虚构覆盖。

## 6. 文档与汇报

实现完成时只更新权威入口：

- `docs/CURRENT_PROJECT_STATUS.md`：实现/分支/发布状态；
- 路线图：阶段进展和依赖；
- 对应 ADR/implementation record：为什么及如何实现；
- `enterprise/tests/README.md`：新增验证入口；
- Code Wiki：模块和运行方式发生实质变化时更新。

不再创建 Agent 交接包、第二份开发计划或按会话复制的状态文档。

最终汇报必须区分：本地修改、提交、推送、PR/CI、合并、Release、客户现场和通用生产批准。
