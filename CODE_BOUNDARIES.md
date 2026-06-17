# 无限画布企业版 · 代码边界

本文档定义本仓库的修改边界。Codex 和开发者每次任务开始前都必须阅读，并据此判断哪些文件可以修改。

---

## 1. 优先允许修改

企业功能、维护能力和测试能力应优先放在以下位置：

- `enterprise/`
- `enterprise-static/`
- `enterprise/tests/`
- `enterprise.env.example`
- `data/*.example.json`
- `启动企业版.bat`
- `停止企业版.bat`
- 项目文档，例如：
  - `PROJECT_CHARTER.md`
  - `AGENT_CONTEXT.md`
  - `ARCHITECTURE.md`
  - `CODE_BOUNDARIES.md`
  - `CODEX_WORKFLOW.md`
  - `DEVELOPMENT_PLAN.md`
  - `ENTERPRISE_DOCS.md`
  - `SECURITY_BASELINE.md`
  - `README.md`
  - `docs/upstream/*.md`
  - `docs/decisions/*.md`

---

## 2. 谨慎修改

以下文件可在明确需要时修改，但必须说明原因：

- `.gitignore`
- README / 说明文档
- 企业层依赖文件
- 示例配置文件
- 企业测试脚本
- 企业启动/停止脚本

修改这些文件时，必须确认没有影响上游同步能力、敏感文件保护或现有测试脚本。

真实运行配置不属于示例配置。`enterprise.env`、`data/api_providers.json`、数据库、Token、Cookie、API Key 等只能保留在本地运行环境，不应提交到 Git。

根目录 `README.md` 是企业版项目首页入口，应保持 Infinite Canvas Enterprise 的项目定位、启动方式、代码边界和上游同步说明。上游 README 不应直接覆盖根目录 `README.md`；如需保留上游 README，应同步到 `docs/upstream/README.upstream.md` 并标注仅供参考。

上游首页 Shell 中的项目主页、版本提示、更新按钮和作者社交入口由企业网关注入层治理。默认实现位置是 `enterprise/gateway.py` 和 `enterprise/interceptors.py`；除非注入无法稳定覆盖，否则不应为企业入口治理直接重构 `static/index.html`。如确需最小修改 `static/index.html`，PR 必须说明这是企业版对上游首页 Shell 的兼容补丁。

画布、对话和受保护资源的多用户隔离必须优先集中在 `enterprise/interceptors.py`、`enterprise/db.py`、`enterprise/admin_api.py`、`enterprise-static/admin.html` 和 `enterprise/tests/` 中演进。普通用户对未归属或未知归属数据默认拒绝；管理员可查看并分配归属。不要为了隔离功能直接改 `main.py` 或 `static/`。

---

## 3. 默认不应修改

以下区域属于上游更新覆盖区域，默认不应作为企业功能开发入口：

- `main.py`
- `static/`
- `workflows/`
- `API/`
- `python/`
- `VERSION`

禁止为了普通企业功能直接修改这些区域。企业能力应通过企业网关、拦截器、企业数据库、企业前端和企业测试体系实现。

---

## 4. 上游区域例外规则

如确需修改上游覆盖区域，必须满足以下条件之一：

1. 正在执行上游版本同步。
2. 正在做经过确认的最小上游 bugfix 热修。
3. 正在将已被上游合并的修复同步回本仓库。

并且必须在 PR 中说明：

- 修改原因
- 是否属于上游同步或最小 bugfix
- 风险范围
- 如何回滚
- 是否需要向上游提交 issue 或 PR

---

## 5. 本任务级约束

每次任务必须只处理当前目标：

- 不扩大需求范围
- 不顺手重构无关代码
- 不移动无关文件
- 不删除现有测试脚本
- 不改动运行时数据
- 不提交真实密钥、真实 Token、真实 Cookie、真实数据库或真实运行时配置
- 不引入与企业多用户版无关的新方向

如果发现额外问题，应记录在 PR 说明或后续 Issue 建议中，不在当前任务中直接实现。

