# Infinite Canvas Enterprise 当前项目状态

更新时间：2026-07-09

## 1. 当前稳定基线

- 企业版仓库：`MEIS-DaCaiTou/Infinite-Canvas-Enterprise`
- 当前稳定 main / origin/main：`c357b89e9601ea65b2c67d8611922069d93facfb`
- 当前上游版本：`2026.07.6`
- 固定上游目标 commit：`hero8152/Infinite-Canvas@f1dd6834a72f3e7ff8340be05a84347d931e9cb9`
- 当前运行架构：浏览器 / 局域网用户 -> `enterprise/gateway.py:8000` -> `main.py:3001` -> 上游 `data / assets / output / static / workflows`
- U-1 / U-2 临时 worktree 已清理；后续任务从原主项目目录最新 `main` 新建分支。

## 2. 架构判断

当前企业版适配“单机无限画布小规模企业多用户化”的阶段目标。第一阶段重点不是组织协作，而是：

- 普通用户隔离。
- owner 归属。
- 管理员兜底。
- 关键 API 拦截。
- 实时事件隔离。
- 任务历史隔离。
- 权限开关。
- 审计记录。

当前“上游主应用 + enterprise gateway + interceptors + enterprise DB 映射”仍是阶段性正确路线。长期风险是 `enterprise/interceptors.py` 继续中心化膨胀；后续新增策略应逐步模块化到 `enterprise/policies/`，再由 gateway / interceptors 编排。

当前项目还不是完整企业协作平台。下一阶段应从“能隔离”升级为“可协作、可运维、可审计、可扩展、可验证”。

## 3. 已完成任务一览

| 阶段 | 状态 | 说明 |
| --- | --- | --- |
| 3G-4A | 已完成，PR #34 | 上传资源隔离与上传资源 owner 治理。 |
| 3G-4B | 已完成，PR #38 | 素材库完整隔离与素材业务 owner 治理。 |
| 3G-5 | 已完成，PR #42 | WebSocket 广播隔离与实时事件 owner 治理。 |
| 3G-6 | 已完成，PR #46 | 异步任务历史 owner 隔离；外部 provider 成功链路仍需有 Key 后补验。 |
| 3G-7A | 已完成，PR #49 | 管理员权限开关最小版 + 审计。 |
| Angle / Enhance 上传解耦 | 已完成，PR #53 | ModelScope / cloud 模式不再依赖本地 Comfy `/api/upload` 成功。 |
| 3G-7B-1 | 已完成，PR #55 | 用户删除影响 dry-run 预览。 |
| 3G-7B-2 | 已完成，PR #56 | soft delete 语义收口、管理员安全保护、feature override 清理。 |
| 3G-7B-3 | 已完成，PR #58 | 成员管理搜索、筛选、排序、分页，默认隐藏已停用用户。 |
| U-1 | 已完成，PR #60 | 上游同步只读审计。 |
| U-2 | 已完成，PR #61 | 受控同步到上游 `2026.07.6` 并补企业兼容。 |
| U-2-F1 / U-2-F2 | 已完成，PR #62 | 文生图 / Enhance 刷新后历史丢失定位与云端 history type 一致性修复。 |
| DOC-1 | 已完成，PR #63 | 项目文档体系全量同步与 Agent 交接资料更新。 |
| OPS-0 / OPS-0A | 已完成，PR #64 | 生产环境只读盘点和生产治理优先级文档化。 |

## 4. 当前能力矩阵摘要

| 能力域 | 当前状态 |
| --- | --- |
| 登录 / JWT Cookie | 已落地，企业网关统一校验。 |
| 管理后台 | 已有成员管理、项目归属、画布归属、对话归属、操作日志、权限开关。 |
| 成员治理 | 已有启用 / 禁用、soft delete、delete-impact dry-run、feature override 清理、成员搜索 / 筛选 / 分页。 |
| 项目 / 画布 / 对话隔离 | 已按 owner 过滤；管理员可治理归属。 |
| 上传资源隔离 | 已按 `user_resource_map` 记录和鉴权。 |
| 素材库隔离 | library / category / item 业务 owner 已治理。 |
| 历史记录隔离 | `user_history_map` owner 过滤已落地；zimage / enhance / klein 云端 type 已一致。 |
| 异步任务隔离 | `user_task_map` / `user_canvas_task_map` owner 拦截基线已落地。 |
| WebSocket 隔离 | stats / pong 保留，敏感事件按 owner / task owner 过滤或合成。 |
| API / 工作流权限 | feature flag + user override + 审计已落地；管理员 bypass，普通用户默认安全。 |
| 上游同步 | U-2 已受控同步到 `2026.07.6`，未直接 merge upstream。 |

## 5. 当前人工确认

合并后最小浏览器确认已通过：

- `/api/app-info` 显示 `2026.07.6`。
- 登录页可打开。
- zimage / enhance / klein 页面可打开。
- user_a 云端生成后刷新历史仍在。
- user_b 仍看不到 user_a 历史。

U-2 项目负责人浏览器验收已通过，重点覆盖登录、普通用户管理后台拒绝、API 设置页新版推荐平台与 CLI 设置展示、权限边界、版本显示、Smart Canvas / Classic Canvas 基础路径、RunningHub / Angle / Enhance 相关入口和企业隔离核心路径。

## 6. 后续任务队列

最近已完成的文档任务：

- DOC-1：已完成，PR #63，项目文档体系全量同步与 Agent 交接资料更新。

OPS-0 / OPS-0A 已完成，生产环境只读盘点已文档化。当前进入 OPS-1：生产备份、离线发布包、升级演练、回滚、数据库迁移与数据治理方案设计。

OPS-1 仍是 docs-only，不写脚本、不改代码、不操作生产。由于已有早期版本上线生产，且生产环境与开发 / Codex 环境隔离，3G-8 暂时后置但不取消。下一步优先级从 OPS-1 继续推进。

下一步优先级：

1. OPS-1：生产备份、离线发布包、升级演练、回滚、数据库迁移与数据治理方案设计。
2. OPS-2：生产只读盘点脚本与备份脚本。
3. OPS-3：离线 release 包生成机制。
4. OPS-4：生产升级演练。
5. 3G-8：浏览器级自动化回归。
6. 3G-6 外部 provider 成功链路补验。
7. 3G-9：生产部署安全治理。
8. 协作权限设计 ADR + 端到端验收矩阵。
9. `enterprise/interceptors.py` 模块化只读审计。

## 7. 当前不进入主线的事项

- team / workspace / project_members / canvas_grants / asset_library_grants 实现。
- 用户共享、复杂 ACL、复杂 RBAC、部门权限。
- 每用户独立 API Key。
- SaaS 多租户。
- 计费。
- 插件市场 / 工作流市场。
- 大规模 UI 改版。
- 模型质量、第三方中转站、Provider 2K/high 等非企业隔离主线问题。
- 物理文件 GC 或删除 `assets/` / `output/` / `history.json` / 数据库。

## 8. 禁止提交范围

不得提交：

- `assets/`
- `output/`
- `history.json`
- `data/`
- `data/enterprise.db` 或任何数据库文件
- `enterprise.env`
- `API/.env`
- `python/`
- Token / Cookie / API Key / 本地日志 / 缓存 / 运行时图片 / 上传文件

上游覆盖区 `main.py`、`static/`、`workflows/`、`API/`、`python/`、`VERSION` 默认不修改。只有在受控上游同步或明确 bugfix 任务中，才允许最小化修改并在 PR 中说明原因、风险、回滚方案和测试结果。

## 9. 后续 Agent 启动 Checklist

```powershell
git checkout main
git pull --ff-only origin main
git rev-parse HEAD
git status --short --untracked-files=all
```

确认 HEAD 为 `c357b89e9601ea65b2c67d8611922069d93facfb` 或其后的 main。若 main 已前进，先读取最新 `PROJECT_SCOPE_LOCK.md`、本文件和最近 PR，再开始新任务。

每个新任务必须：

- 新建独立分支。
- 只处理当前 Issue。
- 创建 Draft PR。
- 明确测试结果。
- 有前端 / 权限行为时等待项目负责人浏览器验收。
- 不提交运行时数据或敏感配置。
