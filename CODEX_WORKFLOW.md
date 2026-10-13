# Infinite Canvas Enterprise 开发工作流

更新时间：2026-10-03

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

任务顺序只认 [路线图](docs/roadmap/DEVELOPMENT-ROADMAP-2026-2027.md)，当前优先统一安装更新。[统一交付 ADR](docs/decisions/ADR-DELIVERY-001-UNIFIED-INSTALL-UPDATE-LIFECYCLE-2026-10.md) 是认可的设计，不是实现完成。

- 横向测试、日志、性能和模块化可以随当前阶段实施。
- 后续阶段可做只读调研或小型 spike，但不得把未完成前置能力包装成可交付产品。
- 涉及新增业务表时，先证明 Update Center 能迁移和恢复该 schema。

## 3. 实施规则

- 小步修改，优先复用领域服务和 Policy，不把业务规则继续堆入 Gateway。
- 所有输入做运行时校验；编译期类型不能替代兼容检查。
- 权限在服务端执行，前端隐藏只改善体验。
- 新任务体系先持久受理再执行；未提交暂停、已受理继续查、未知待对账。旧实现尚未全部具备，不能靠本条文档假定可安全恢复或重提。
- 大型资源写入资源存储，数据库只写元数据和引用。
- schema 变化必须同时提供 migration、验证、备份/恢复和旧版本测试。
- Release/Update 变化必须固定源/目标版本、Manifest、哈希和失败恢复。

## 4. 分支与 PR

- 默认分支前缀：`codex/`。
- 一个 PR 只解决一个可验收主题；安全/数据/更新等高风险变化不得夹带无关重构。
- PR 说明必须列明：Base/Head、实现范围、未实现范围、数据/权限影响、测试结果、升级和回滚影响。
- GitHub Actions 通过不自动代表 Release 或生产批准。
- 发布、部署、客户升级和合并是不同动作，核对实际授权并分别记录。既有明确授权可以适用，但文档整改不自动授权客户操作或业务发布。
- 维护分支是过渡；回归 main 同时核对源码、安全、测试和文档，不复活旧队列或丢失主线记录。

## 5. 验证

默认运行受影响定向测试，复用已有 CI。跨模块风险、必要失败复核、合并要求或明确请求才重跑全套，并说明理由。纯文档变更运行：

```powershell
py -3.11 -B tools/check_docs.py
py -3.11 -B -m unittest discover -s enterprise/tests -p test_documentation_contract.py
```

业务变更再按风险选择并记录：

- 单元和静态契约测试；
- 企业完整测试；
- CP314 Runtime 专项；
- 数据 migration/backup/restore 故障注入；
- Windows 生命周期与端口/进程身份验证；
- 浏览器关键流程与权限矩阵；
- 真实 Provider 的受控成功/超时/未知结果场景；
- 性能和容量基线。

项目负责人已取消独立 Windows 主机与干净用户环境前置门禁。托管 CI 不能执行的场景应记录为限制，并通过可复现实验或必要人工验证补证；不得虚构覆盖。

## 6. 文档与汇报

实现完成时只更新权威入口：

- `docs/CURRENT_PROJECT_STATUS.md`：实现/分支/发布状态；
- 路线图：阶段进展和依赖；
- 对应 ADR/implementation record：为什么及如何实现；
- `enterprise/tests/README.md`：验证入口实际改变时更新；
- Code Wiki：模块和运行方式发生实质变化时更新。

新增/移动/改名资料同步 `docs/document-register.json`。旧决定有替代指向，验收不改写；不再创建交接包、第二路线图或会话状态副本。

临时产物集中于产品专用 artifact 根或受管工作区，不散落盘符根目录；清理只处理核准归属的本项目对象，不删除用户其他项目、客户数据或有效恢复证据。

最终汇报必须区分：本地修改、提交、推送、PR/CI、合并、Release、客户现场和通用生产批准。
