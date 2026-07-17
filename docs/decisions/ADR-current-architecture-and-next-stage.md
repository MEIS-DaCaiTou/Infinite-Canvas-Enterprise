# ADR: Infinite Canvas Enterprise 当前架构评估与下一阶段演进决策

> **状态：Superseded。** 当前架构形态由 [ADR-ENV-001](./ADR-ENV-001-MODULAR-MONOLITH-MIDTERM-ARCHITECTURE-2026-07.md) 决定，当前阶段顺序见 [开发路线图](../roadmap/DEVELOPMENT-ROADMAP-2026-2027.md)。本文保留 2026-07-08 的历史判断。

原状态：Accepted

日期：2026-07-08

## 背景

Infinite Canvas Enterprise 基于上游 `hero8152/Infinite-Canvas` 做企业多用户二次开发。上游仍持续维护 `main.py`、`static/`、`workflows/`、`API/`、`python/` 和 `VERSION`。

截至 2026-07-08，企业版已完成第一阶段隔离底座，并已受控同步到上游 `2026.07.6`：

- 3G-4A：上传资源隔离。
- 3G-4B：素材库完整隔离。
- 3G-5：WebSocket 广播隔离。
- 3G-6：异步任务历史 owner 隔离。
- 3G-7A：管理员权限开关最小版 + 审计。
- 3G-7B：用户删除影响预览、soft delete 安全保护、feature override 清理、成员管理搜索 / 筛选 / 分页。
- U-2：上游 `2026.07.6` 受控同步与企业兼容。
- U-2-F2：zimage / enhance / klein 云端 history type 一致性修复。

Angle / Enhance ModelScope 上传解耦已由 PR #53 完成；上游 `2026.07.6` 受控同步已由 PR #61 完成；刷新后历史丢失问题已由 PR #62 修复。当前不再依赖 PR #61 / #62 分支或临时 worktree。

## 决策

当前企业版继续采用以下阶段性架构：

```text
浏览器 / 局域网用户
        ↓
enterprise/gateway.py
        ↓
enterprise/interceptors.py + enterprise DB owner / permission / audit mappings
        ↓
main.py 上游服务
        ↓
上游 data / assets / output / static / workflows
```

该架构适配“单机无限画布小规模企业多用户化”的阶段目标。第一阶段重点不是组织协作，而是：

- 普通用户隔离。
- owner 归属。
- 管理员兜底。
- 关键 API 拦截。
- 实时事件隔离。
- 任务历史隔离。
- 权限开关。
- 审计记录。

当前项目还不是完整企业协作平台。下一阶段应从“能隔离”升级为：

- 可协作。
- 可运维。
- 可审计。
- 可扩展。
- 可验证。

## 架构评价

“上游主应用 + enterprise gateway + interceptors + enterprise DB 映射”当前仍是正确路线：

- 能尽量保留上游功能和同步能力。
- 企业数据、owner 映射、审计和权限开关不侵入上游 JSON 主结构。
- 普通用户入口、后端 API、资源直链和 WebSocket 都可通过企业层统一治理。
- 上游覆盖区变更可以保持例外处理，降低同步冲突。

但当前也出现明确长期风险：

- `enterprise/interceptors.py` 已聚合大量路径判断、owner 校验、响应过滤、资源归一化、feature gate 和 post process。
- 继续把所有新策略堆进单文件会降低可读性、测试局部性和上游同步复核效率。
- 后续协作权限如果继续沿用单 owner 判断，会很容易出现临时 ACL、绕过审计或共享撤销不完整的问题。

## 下一阶段方向

DOC-1 已由 PR #63 完成。下一阶段不应直接进入大规模协作功能实现，而应先完成浏览器级自动化回归、外部 provider 成功链路补验、生产部署安全治理，再进入协作权限设计：

- project members。
- canvas grants。
- 素材共享 / 取消共享。
- 授权来源、授权撤销和授权审计。
- 管理员代管与普通协作的边界。
- owner、grant、resource scope、task scope 的优先级。

新增策略应逐步模块化到 `enterprise/policies/`，例如：

- `enterprise/policies/resources.py`
- `enterprise/policies/assets.py`
- `enterprise/policies/tasks.py`
- `enterprise/policies/realtime.py`
- `enterprise/policies/features.py`

`enterprise/gateway.py` 和 `enterprise/interceptors.py` 应逐步退回到编排层：解析请求、调用 policy、转发上游、合成响应和记录审计。

## 验收决策

建立端到端验收矩阵作为长期基线：

- admin / user_a / user_b 三账号。
- 项目、画布、对话、资源、素材库、历史、任务、WebSocket、权限开关。
- 前端入口和后端 API 必须同时验证。
- 管理员操作必须验证审计。
- Provider / token / 模型质量 / ComfyUI 自定义节点缺失不得误判为企业隔离失败。

验收矩阵记录在 `docs/manual-acceptance-enterprise-e2e.md`。

## 不做事项

本 ADR 不批准立即实现：

- team / workspace / project_members / canvas grants。
- 数据库 schema 功能改造。
- `enterprise/interceptors.py` 大重构。
- Postgres / 队列 / 运维系统。
- 上游同步实现。
- Angle / Enhance ModelScope 上传解耦实现，已由 PR #53 完成，后续只做回归。
- provider 质量、中转站、ModelScope Key、2K/high 问题优化。

这些内容必须分别立项、定位、设计和验收。

## 后果

收益：

- 保持当前企业隔离底座稳定。
- 为后续协作权限设计留出清晰边界。
- 避免把上游同步、小修 bug、协作权限和架构重构混在同一个 PR。
- 为人工验收和未来自动化浏览器回归提供统一基线。

代价：

- `enterprise/interceptors.py` 的模块化不会在本 ADR 立即完成，短期仍需谨慎维护。
- 协作能力需要额外设计周期，不能直接复用单 owner 模型。
- 外部 provider 成功链路仍需要有可用 Key 后补验，不能把 provider / token / 模型质量问题误判为企业隔离失败。
