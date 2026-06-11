# 无限画布企业版 · 后续开发规划

更新时间：2026-06-11

---

## 总体顺序

后续维护围绕“企业多用户版 Infinite Canvas”这一唯一方向推进。所有阶段都必须遵守 `PROJECT_CHARTER.md`、`CODE_BOUNDARIES.md` 和 `CODEX_WORKFLOW.md`。

1. 文档治理与开发流程
2. 安全基线
3. 用户管理
4. 权限隔离
5. 画布 / 对话归属
6. 管理后台
7. 审计日志
8. 部署维护
9. 上游同步机制
10. 浏览器级冒烟测试

---

## 阶段一：文档治理与开发流程

目标：让任何 Codex 会话在上下文压缩后都能从仓库文档恢复项目方向、代码边界和交付流程。

已完成：

- `AGENT_CONTEXT.md` 作为压缩后第一入口。
- `DEVELOPMENT_PLAN.md` 固化长期路线。
- `PROJECT_CHARTER.md` 定义最高层项目方向。
- `ARCHITECTURE.md` 说明企业网关覆盖上游的结构。
- `CODE_BOUNDARIES.md` 明确可改和默认不应改的文件。
- `CODEX_WORKFLOW.md` 规定每次任务先读文档、只做当前 Issue、独立分支和 PR 交付。
- `docs/decisions/ADR-0001-enterprise-gateway-over-upstream.md` 记录核心架构决策。

待办：

- 随每次任务及时更新真实状态和测试记录。
- 保持 Issue、分支、PR 的交付方式，不直接推 `main`。

---

## 阶段二：安全基线

目标：确保企业版账号、密钥、运行数据和仓库边界可控。

待办：

- 复核 `enterprise.env`、`API/.env`、`data/` 是否持续被 Git 忽略。
- 确认企业仓库可见性是否应为 Private。
- 检查默认管理员密码和 JWT_SECRET 的生产环境修改要求。
- 建立安全配置检查清单。

---

## 阶段三：用户管理

目标：完善企业成员生命周期管理。

待办：

- 完善创建、禁用、启用、重置密码、管理员授权流程。
- 增加更清晰的管理员操作反馈。
- 为关键用户管理操作补审计日志。

---

## 阶段四：权限隔离

目标：保证普通用户只能看到自己的资源，管理员可按权限管理全局资源。

已完成：

- 企业层通过 `user_canvas_map` 和 `user_conversation_map` 实现归属。
- 企业网关注入用户上下文并执行响应过滤。

待办：

- 增加浏览器级验证：普通用户、管理员、未登录用户三类视角。
- 检查新增上游 API 是否需要纳入拦截和过滤。

---

## 阶段五：画布 / 对话归属

目标：让画布和对话归属清晰、可审计、可调整。

待办：

- 管理后台增加更强的归属筛选和批量操作能力。
- 对归属变更写入审计日志。
- 建立旧数据迁移和未归属资源处理流程。

---

## 阶段六：管理后台

目标：让管理员能高效管理用户、画布、日志和系统状态。

待办：

- 批量分配画布归属。
- 按用户筛选画布。
- 展示系统健康状态、版本、端口和最近错误。

---

## 阶段七：审计日志

目标：关键企业操作可追踪、可回溯。

待办：

- 记录管理员改归属、用户权限变更、更新/回滚、模型调用失败等操作。
- 增加日志筛选与导出能力。

---

## 阶段八：部署维护

目标：项目在局域网和服务器环境中可反复启动、停止、诊断和恢复。

已完成：

- `启动企业版.bat` 调用 `enterprise/launcher.py`，统一启动 `3001/8000`。
- `停止企业版.bat` 清理 `8000/3001`。
- `/enterprise/health` 可检查网关和内部上游可达性。
- `enterprise/tests/test_start_stop.ps1` 验证启动/停止闭环。
- `enterprise/tests/diagnose.ps1` 和 `enterprise/tests/smoke.ps1` 提供诊断与冒烟。
- 2026-06-11 已启动当前项目并完成非破坏性诊断/冒烟验证。

待办：

- 在诊断脚本里输出当前代理环境和推荐访问地址，但不强行修正固定 IP。
- 记录每次上游更新后的版本、测试结果和异常处理。

---

## 阶段九：上游同步机制

目标：降低上游更新造成的冲突和回归风险。

已完成：

- 测试脚本统一放在 `enterprise/tests/`。
- 企业私有仓库已推送到 `MEIS-DaCaiTou/Infinite-Canvas-Enterprise`。
- 上游 Smart Canvas LLM stale running bug 已提交 PR：`hero8152/Infinite-Canvas#67`。

待办：

- PR #67 当前与上游 main 冲突；需要单独 rebase 或基于上游最新 main 重提这个 LLM running-state 修复。
- 建立 `enterprise/tests/SMOKE_CHECKLIST.md` 的实际执行记录格式。
- 对 `.gitignore` 和仓库内容做一次安全复核，确保密钥、运行数据、内置运行时不进入 Git。
- 给上游更新流程补一份标准操作步骤：更新前备份、更新后重启、跑清单、记录结果。
- 确认企业仓库是否需要保持私有；2026-06-11 查询结果为 `PUBLIC`。

---

## 阶段十：浏览器级冒烟测试

目标：补齐真实浏览器中的登录、管理员后台、普通用户隔离和画布创建验证。

待办：

- 建立不破坏数据的浏览器级 smoke 流程。
- 验证登录页、管理员页、普通用户画布列表、创建画布归属。
- 验证上游更新后 Smart Canvas LLM 节点不会永久卡在运行态。

---

## 每次上游更新后的固定动作

1. 更新前确认 `enterprise.env`、`API/.env`、`data/` 不在 Git 跟踪中。
2. 点击更新按钮或按文档手动同步上游文件。
3. 重启企业版服务。
4. 执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\enterprise\tests\diagnose.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\enterprise\tests\smoke.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\enterprise\tests\test_start_stop.ps1 -StopExisting
```

5. 手工跑 `enterprise/tests/SMOKE_CHECKLIST.md`。
6. 如发现上游 bug，先提交上游 issue/PR，再决定是否保留本地临时热修。
