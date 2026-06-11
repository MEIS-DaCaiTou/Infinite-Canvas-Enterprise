# 无限画布企业版 · 后续开发规划

更新时间：2026-06-11

---

## 总体顺序

后续维护按三阶段推进：

1. 稳运行：启动、停止、健康检查、局域网访问、上游更新后可恢复。
2. 稳维护：文档、测试清单、Git 提交边界、上游热修跟踪。
3. 扩功能：管理后台、权限审计、批量归属、团队协作与可观测性。

---

## 阶段一：稳运行

目标：项目在局域网多用户环境中可反复启动、停止、更新、恢复。

已完成：

- `启动企业版.bat` 调用 `enterprise/launcher.py`，统一启动 `3001/8000`。
- `停止企业版.bat` 清理 `8000/3001`。
- `/enterprise/health` 可检查网关和内部上游可达性。
- `enterprise/tests/test_start_stop.ps1` 验证启动/停止闭环。
- `enterprise/tests/diagnose.ps1` 和 `enterprise/tests/smoke.ps1` 提供诊断与冒烟。
- 2026-06-11 已启动当前项目并完成非破坏性诊断/冒烟验证。

待办：

- 补充浏览器级冒烟：登录页、管理员后台、普通用户画布隔离、创建画布归属。
- 在诊断脚本里输出当前代理环境和推荐访问地址，但不强行修正固定 IP。
- 记录每次上游更新后的版本、测试结果和异常处理。

---

## 阶段二：稳维护

目标：任何 Agent 在上下文压缩后都能沿正确方向维护项目。

已完成：

- 新增 `AGENT_CONTEXT.md` 作为压缩后第一入口。
- 新增 `DEVELOPMENT_PLAN.md` 固化开发路线。
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

## 阶段三：扩功能

目标：在运行和维护稳定后，再增强企业版能力。

优先级建议：

1. 管理后台增强：批量分配画布归属、按用户筛选画布、禁用/启用账号。
2. 审计增强：记录更新、回滚、模型调用失败、管理员改归属等关键操作。
3. 用户体验：登录态过期提示、普通用户无权限提示、管理员入口更清晰。
4. 多用户协作稳定性：并发编辑提示、保存冲突提示、WebSocket 断线重连状态。
5. 可观测性：诊断页或管理员健康页展示版本、端口、上游状态、最近错误。

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
