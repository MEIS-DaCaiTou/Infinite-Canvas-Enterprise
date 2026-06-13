# 无限画布企业版 · 后续开发规划

更新时间：2026-06-13

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
- `README.md` 恢复为 Infinite Canvas Enterprise 企业版首页入口。
- `docs/upstream/README.upstream.md` 保存上游原版 README，仅作参考。
- `docs/upstream/SYNC_POLICY.md` 记录上游同步时 README 和上游文档边界。

待办：

- 随每次任务及时更新真实状态和测试记录。
- 保持 Issue、分支、PR 的交付方式，不直接推 `main`。
- 后续上游同步 PR 必须检查根目录 `README.md` 是否仍为企业版说明，不能被上游 README 覆盖。

---

## 阶段二：安全基线

目标：确保企业版账号、密钥、运行数据和仓库边界可控。

已完成：

- 新增 `enterprise.env.example`，明确 `GATEWAY_PORT`、`UPSTREAM_PORT`、`JWT_SECRET`、`JWT_EXPIRE_HOURS`、`ADMIN_USERNAME`、`ADMIN_PASSWORD`、`DB_PATH` 的示例配置。
- 新增 `SECURITY_BASELINE.md`，记录生产部署前必须修改项、不得提交文件、运行时配置处理方式和安全检查清单。
- 企业配置加载会对默认 `JWT_SECRET`、过短 `JWT_SECRET`、默认管理员密码输出清晰风险提示。
- 当 `ENTERPRISE_ENV=production` 或 `ENTERPRISE_STRICT_SECURITY=1` 时，默认 `JWT_SECRET` 会阻断启动，避免生产环境误用开发默认值。
- 新增 `data/api_providers.example.json` 作为模型配置模板，不包含真实密钥。
- `data/api_providers.json` 已加入 `.gitignore`，并通过 `git rm --cached data/api_providers.json` 停止 Git 跟踪；用户本地真实配置保留。

待办：

- 持续复核 `enterprise.env`、`API/.env`、`data/` 是否被 Git 忽略，避免真实密钥、Token、Cookie、数据库或运行时数据进入仓库。
- 确认企业仓库可见性是否应为 Private，并在部署前复核协作者权限。
- 增加生产部署安全检查脚本，用于自动检查默认管理员密码、默认 JWT_SECRET 和运行时配置泄漏风险。
- 继续审计其它运行态配置和模型供应商配置，不把本次安全基线写成一次性全部完成。

---

## 阶段三：用户管理

目标：完善企业成员生命周期管理。

已完成：

- 管理员可创建用户、重置密码、设置或撤销管理员角色。
- 管理员可通过 `PUT /enterprise/api/users/{id}/active` 启用或禁用账号。
- 管理员可通过 `PUT /enterprise/api/users/{id}/profile` 更新用户展示名；展示名为空时回退为用户名。
- `DELETE /enterprise/api/users/{id}` 保持兼容，语义为禁用/软删除账号。
- 管理员不能禁用或删除自己，目标用户不存在时返回 404。
- 管理后台做了最小适配：展示账号状态，提供启用/禁用入口和展示名编辑入口。

待办：

- 增加更清晰的管理员操作反馈。
- 增加批量启用/禁用、批量角色调整、成员筛选和搜索。
- 增加浏览器级验证：管理员、普通用户、禁用用户三类视角。

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

已完成：

- 用户管理关键操作写入审计日志：创建用户、重置密码、修改角色、禁用/软删除、启用、修改展示名。
- 用户管理审计日志的 `user_id` 记录执行操作的管理员 ID，`detail` 记录目标用户 ID、目标用户名和动作摘要。

待办：

- 记录管理员改归属、更新/回滚、模型调用失败等更多操作。
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
- 2026-06-12 Issue #9 已在上游更新兼容性演练中验证 `test_start_stop.ps1 -StopExisting`、`diagnose.ps1`、`smoke.ps1` 均通过。
- 2026-06-13 PR #10 复核补同步已验证 `diagnose.ps1`、`smoke.ps1`、企业健康检查、管理员用户管理、普通用户隔离、新建 Smart Canvas 归属和 Smart Canvas 浏览器打开；本轮未重跑 `test_start_stop.ps1 -StopExisting`，避免中断当前服务。

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
- Issue #9 / PR #10 已完成受控上游更新兼容性演练并补同步：从 `2026.06.02.1` 更新到当前上游真实版本 `2026.06.12`，上游 commit 为 `hero8152/Infinite-Canvas@9fb9a90`。同步范围包括 `main.py`、`VERSION`、`static/`、`workflows/`、`tools/`、`packages/`、`requirements.txt`、`get-pip.py`、`run.bat`、上游安装/登录脚本、README、macOS 脚本、运行说明和相关上游资源，并记录到 `enterprise/tests/UPDATE_TEST_LOG.md`。
- Issue #11 已恢复企业版 README 首页边界：根目录 `README.md` 是企业仓库入口，上游 README 移至 `docs/upstream/README.upstream.md`，同步规则写入 `docs/upstream/SYNC_POLICY.md`。
- Issue #13 已建立企业版项目入口与更新权限治理：前端项目主页指向企业仓库，普通用户隐藏更新提示、更新入口和上游作者社交区，更新相关接口继续由企业网关强制管理员权限；管理员更新文案定位为企业版受控运维能力。

待办：

- PR #67 当前与上游 main 冲突；需要单独 rebase 或基于上游最新 main 重提这个 LLM running-state 修复。
- 将 `enterprise/tests/SMOKE_CHECKLIST.md` 的手工项进一步脚本化，减少上游更新后人工验证成本。
- 对 `.gitignore` 和仓库内容做一次安全复核，确保密钥、运行数据、内置运行时不进入 Git。
- 给上游更新流程补一份标准操作步骤：更新前备份、更新后重启、跑清单、记录结果。
- 为现有更新 API 增加 GitHub token 配置或 git-fetch fallback，避免 anonymous GitHub REST rate limit 导致 HTTP 403。
- 单独评估 `python/` 运行时发布策略：上游当前跟踪 `python/`，但企业仓库仍按 `.gitignore` 将 `python/`、`python.zip` 作为本地运行时忽略，不应在上游同步 PR 中顺手改变。
- 把 README 边界检查加入上游同步清单：根目录 `README.md` 必须保持企业版说明；上游 README 如需同步，只能进入 `docs/upstream/README.upstream.md`。
- 把企业入口治理检查加入上游同步清单：每次上游更新后必须验证 `enterprise/gateway.py` 注入脚本仍能治理 `static/index.html` 的项目主页、版本更新按钮/提示和上游作者社交区；如上游 DOM 改动导致失效，应在同步 PR 中修复后再合并。
- 确认企业仓库是否需要保持私有；2026-06-11 查询结果为 `PUBLIC`。

---

## 阶段十：浏览器级冒烟测试

目标：补齐真实浏览器中的登录、管理员后台、普通用户隔离和画布创建验证。

已完成：

- Issue #9 使用 Playwright 浏览器验证 `/enterprise/logs` 默认 20 条、10/20/50/100 切换、上一页/下一页、用户筛选、操作类型筛选和组合筛选。
- Issue #9 使用真实浏览器打开更新后的 Smart Canvas，确认页面标题加载、console 0 error，未观察到明显永久 running 异常。

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
