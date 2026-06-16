# 无限画布企业版 · Codex 工作流

本文档定义 Codex 后续维护本项目时的标准流程。

---

## 1. 每次任务前必须阅读

Codex 每次开始任务前，必须先阅读：

1. `PROJECT_CHARTER.md`
2. `AGENT_CONTEXT.md`
3. `ARCHITECTURE.md`
4. `CODE_BOUNDARIES.md`
5. `CODEX_WORKFLOW.md`
6. `SECURITY_BASELINE.md`
7. `DEVELOPMENT_PLAN.md`
8. 必要时阅读 `ENTERPRISE_DOCS.md`
9. 与当前任务相关的 Issue 正文

如果当前任务涉及浏览器行为、登录权限、企业入口治理、上游同步、画布/对话/素材访问或管理后台回归，还必须阅读：

10. `enterprise/tests/BROWSER_REGRESSION_CHECKLIST.md`
11. `enterprise/tests/browser-regression.md`

阅读完成后，先确认当前任务边界，再开始修改文件。

---

## 2. 每次任务中必须遵守

- 只处理当前 Issue / 当前任务。
- 不扩大需求范围。
- 不顺手重构无关代码。
- 不移动无关文件。
- 不修改与任务无关的上游区域。
- 不引入与企业多用户版无关的项目语义。
- 不提交真实密钥、真实 Token、真实 Cookie、真实数据库或真实运行时配置。
- 不直接推送到 `main`。
- 如发现额外问题，只记录为后续建议，不在当前任务中直接实现。

---

## 3. 分支与 PR 规则

后续任务必须通过独立分支和 PR 交付。

标准流程：

```text
1. 从最新 main 创建任务分支
2. 在任务分支完成当前 Issue
3. 运行必要验证
4. 提交 commit
5. 推送任务分支
6. 创建 PR 到 main
7. 等待人工审核后合并
```

分支命名建议：

- `docs/...`：文档任务
- `fix/...`：缺陷修复
- `feat/...`：企业功能
- `test/...`：测试与验证
- `chore/...`：维护任务

---

## 4. 每次任务完成后必须提供

最终回复和 PR 描述必须包含：

- 变更摘要
- 修改文件列表
- 测试结果
- 风险说明
- 回滚方案
- 是否修改上游区域
- 是否提交或停止跟踪运行时/敏感配置
- 后续建议
- 关联 Issue

---

## 5. 验证规则

文档任务至少执行：

```powershell
git diff --name-only
```

并确认只涉及文档文件。

非破坏性验证可按需执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\enterprise\tests\diagnose.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\enterprise\tests\smoke.ps1
```

不要执行会中断当前服务的测试，除非当前任务明确要求。

涉及浏览器行为、企业入口治理、上游同步或权限边界的任务，必须按 `enterprise/tests/BROWSER_REGRESSION_CHECKLIST.md` 做浏览器级回归验收，并将结果摘要记录到 `enterprise/tests/UPDATE_TEST_LOG.md` 或 PR 描述中。若本轮只建立文档或无法运行浏览器，应在 PR 描述中明确说明未运行原因和后续执行入口。

---

## 6. 上游区域说明

`main.py`、`static/`、`workflows/`、`API/`、`python/`、`VERSION` 是上游更新覆盖区域。

默认不应修改这些文件。如果 PR 修改了这些区域，必须显式说明原因、风险、回滚方案，以及是否需要同步给上游。

