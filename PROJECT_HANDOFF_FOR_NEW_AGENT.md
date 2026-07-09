# Infinite Canvas Enterprise 新智能体交接包

更新时间：2026-07-08

> 本文用于在新的 Codex 对话窗口中无缝接手本项目。新智能体应先读本文，再读 `docs/CURRENT_PROJECT_STATUS.md`、`PROJECT_SCOPE_LOCK.md`、`AGENT_CONTEXT.md`、`DEVELOPMENT_PLAN.md`、`ENTERPRISE_ISOLATION_MATRIX.md` 和当前任务 Issue。

---

## 2026-07-08 当前接手重点

当前稳定开发基线：

- main / origin/main：`73a645f2bdded5df5c7109903c8b57eab9e3c459`
- 上游版本：`2026.07.6`
- 上游固定目标 commit：`hero8152/Infinite-Canvas@f1dd6834a72f3e7ff8340be05a84347d931e9cb9`
- U-1 / U-2 临时 worktree 已清理；不要再引用 `u1-audit` / `u2-sync` 作为当前运行目录。
- 当前允许存在本地运行时 `assets/uploads/*` 未跟踪文件，不得 stage / commit。

新 Agent 第一轮操作：

```powershell
git checkout main
git pull --ff-only origin main
git rev-parse HEAD
git status --short --untracked-files=all
```

期望 HEAD 为 `73a645f2bdded5df5c7109903c8b57eab9e3c459` 或其后的主线提交。如 main 已前进，先读取最新 `PROJECT_SCOPE_LOCK.md`、`docs/CURRENT_PROJECT_STATUS.md` 和对应 PR 记录，再决定是否继续。

当前所有新任务都必须从最新 `main` 新建独立分支，创建 Draft PR，等待主对话复核和必要的项目负责人浏览器验收。不得提交 `assets/`、`output/`、`history.json`、`data/`、数据库、`enterprise.env`、`API/.env`、`python/`、token、cookie、key 或本地日志。

---

## 当前完成状态摘要

当前 main 已完成 3G owner 隔离与安全治理底座第一阶段：

- PR #34：上传资源隔离与上传资源 owner 治理。
- PR #38：素材库完整隔离与素材业务 owner 治理。
- PR #42：WebSocket 广播隔离与实时事件 owner 治理。
- PR #46：异步任务历史 owner 隔离。
- PR #49：管理员权限开关最小版 + 审计。
- PR #53：Angle / Enhance ModelScope 上传解耦。
- PR #55：用户删除影响 dry-run 预览。
- PR #56：soft delete 语义收口 + feature override 清理。
- PR #58：成员管理搜索 / 筛选 / 分页和默认隐藏已停用用户。
- PR #60：U-1 上游同步只读审计。
- PR #61：U-2 受控同步到上游 `2026.07.6`。
- PR #62：U-2-F1 定位报告 + U-2-F2 云端 history type 一致性修复。

接手时不要把当前项目误判为完整企业协作平台。当前已完成的是“隔离底座”：普通用户隔离、owner 归属、管理员兜底、关键 API 拦截、实时事件隔离、任务历史隔离、权限开关和审计记录。下一阶段如果进入协作能力，必须先设计 project members、canvas grants、共享/撤销、审计和迁移策略，再进入实现。

当前架构“上游主应用 + enterprise gateway + interceptors + enterprise DB 映射”仍是阶段性正确路线；但 `enterprise/interceptors.py` 继续膨胀是长期风险。后续新增策略优先考虑拆到 `enterprise/policies/`，由 gateway / interceptors 编排，不要继续把所有业务判断堆进一个拦截器文件。

端到端验收以 `docs/manual-acceptance-enterprise-e2e.md` 为基线，必须同时覆盖前端入口和后端 API；当前架构决策见 `docs/decisions/ADR-current-architecture-and-next-stage.md`。当前任务队列见 `PROJECT_SCOPE_LOCK.md` 与 `docs/CURRENT_PROJECT_STATUS.md`。

---

## 1. 项目概览

本仓库是基于上游 `hero8152/Infinite-Canvas` 的企业多用户二次开发版本：

- GitHub 仓库：`MEIS-DaCaiTou/Infinite-Canvas-Enterprise`
- 本地路径：`D:\CodeProject\26-5-27-无限画布`
- 企业网关：`0.0.0.0:8000`
- 内部上游：`127.0.0.1:3001`
- 当前上游基线：`VERSION=2026.07.6`
- 上游来源：`hero8152/Infinite-Canvas`

企业能力主要通过 `enterprise/` 网关和企业数据库叠加在上游之上：

- 登录认证、JWT Cookie、企业用户管理
- 管理后台、审计日志、健康检查
- 画布、对话、资源、项目归属隔离
- 企业项目入口和更新权限治理
- 启动、停止、诊断、冒烟测试闭环

上游主功能仍由 `main.py`、`static/`、`workflows/` 等承担。企业版开发原则是：优先在企业层实现，不直接大改上游覆盖区。

---

## 2. 当前 main 状态

执行于 2026-07-08：

```powershell
git checkout main
git pull --ff-only origin main
git rev-parse HEAD
git status --short
```

确认结果：

- 当前分支：`main`
- 最新稳定 HEAD：`73a645f2bdded5df5c7109903c8b57eab9e3c459`
- origin/main：`73a645f2bdded5df5c7109903c8b57eab9e3c459`
- 当前上游版本：`2026.07.6`
- 工作区：允许存在本地运行时 `assets/uploads/*` 未跟踪文件，不得提交。
- 不得提交 `data/enterprise.db-shm`、`data/enterprise.db-wal`、`history.json`、`enterprise.env`、`API/.env` 或任何运行时文件。

最近关键提交包含：

- `73a645f`：PR #62，U-2-F1 / U-2-F2，修复文生图 / Enhance 云端 history type 一致性。
- `25a9c65`：PR #61，U-2 受控同步到上游 `2026.07.6`。
- `966a2aa`：PR #60，U-1 上游同步只读审计报告。
- `872729b`：PR #58，成员管理搜索 / 筛选 / 分页与默认隐藏已停用用户。
- `160791b`：PR #56，soft delete 语义收口与 feature override 清理。
- `7b18bbf`：PR #55，用户删除影响 dry-run 预览。
- `1f9ee81`：PR #24，项目、文件夹与画布列表隔离
- `06ffb7c`：PR #23，企业隔离设计与 API 矩阵
- `59a71ab`：PR #22，同步上游 `2026.06.23` 并保留企业补丁与日志去重
- `09f376d`：PR #21，旧 Smart Canvas 生成日志持久化兼容
- `8ea2119`：PR #20，旧画布 output 资源回填和持久化
- `fe0355e`：PR #19，生成 output 资源 owner 补记
- `3c1bdc1`：PR #18，画布、对话、资源基础归属隔离

---

## 3. 已合并 PR 时间线

1. 企业版基础壳
   - 建立 `enterprise/gateway.py` 反向代理。
   - 建立企业登录、JWT Cookie、管理员后台、用户管理、健康检查、启动/停止脚本。
   - 外部入口为 `8000`，内部上游为 `3001`。

2. PR #18：画布、对话、资源基础归属隔离
   - `user_canvas_map`、`user_conversation_map`、`user_resource_map` 成为基础 owner 模型。
   - 普通用户仅能访问自己归属的数据。
   - 未归属历史画布/对话默认仅管理员可见。
   - 受保护资源路径通过 owner 或画布/对话引用回溯授权。

3. PR #19：生成 output 资源补记
   - 修复普通用户生成 output 后立即访问受阻的问题。
   - 生成任务结果可补写资源 owner。

4. PR #20：output URL 规范化与旧画布资源回填
   - 规范化 `/assets/output/`、`/api/view`、`/api/download-output`、本地绝对 URL 等。
   - 已有 owner 的旧画布在读取/保存时可回填资源归属。
   - 刷新、退出重登后 output 仍可见。

5. PR #21：旧 Smart Canvas 日志兼容
   - 兼容旧画布缺失、空值或旧格式 `logs`。
   - 恢复/手工查询任务成功后也能补写生成日志。
   - 新画布日志行为不回归。

6. PR #22：同步上游 `2026.06.23`
   - 同步上游覆盖区域到 `hero8152/Infinite-Canvas@0da3ff9`。
   - 保留 PR #21 的 Smart Canvas 日志兼容补丁。
   - 修复正常完成路径和恢复路径重复写成功日志的问题。
   - 企业 README、企业入口治理、普通用户更新权限、隔离测试未被破坏。

7. PR #23：企业隔离设计与 API 矩阵
   - 新增 `ENTERPRISE_ISOLATION_MATRIX.md`。
   - 新增 `ENTERPRISE_PERMISSION_DESIGN.md`。
   - 明确项目、画布、对话、资源、历史、素材、任务、WebSocket、入口权限的后续治理路线。

8. PR #24：项目、文件夹与画布列表隔离
   - 新增 `user_project_map`。
   - 普通用户只看到自己的项目/文件夹和自己的虚拟默认项目。
   - 普通用户只看到自己的画布。
   - 项目计数按当前用户可见画布重算。
   - 管理员可查看和分配项目归属、画布归属。
   - 管理员把 A 的画布移动到 B 项目后，canvas owner 会同步为 B。
   - 管理员把画布 owner 分配给 B 时，如果原 project 不属于 B，则安全回退到 B 的 `default` 视图。

---

## 4. 企业版架构

```text
浏览器 / 局域网用户
        |
        v
enterprise/gateway.py  (0.0.0.0:8000)
        |
        |-- 登录认证 / JWT Cookie
        |-- pre_process: API 权限校验
        |-- post_process: 列表过滤、owner 记录、企业入口治理
        |-- HTML 注入: 用户条、入口治理、普通用户隐藏更新能力
        |
        v
main.py 上游服务 (127.0.0.1:3001)
        |
        v
data/, assets/, output/, static/, workflows/
```

企业层核心文件：

- `enterprise/config.py`：端口、JWT、安全配置、企业入口配置。
- `enterprise/gateway.py`：反向代理、登录状态要求、HTML 注入、转发和后处理调用。
- `enterprise/interceptors.py`：企业权限模型核心。前置授权、响应过滤、owner 记录、资源归一化都集中在这里。
- `enterprise/db.py`：企业 SQLite 表、用户、画布/对话/资源/项目 owner 映射、审计日志。
- `enterprise/admin_api.py`：管理员 REST API，包括用户、画布归属、项目归属、对话归属、审计查询。
- `enterprise-static/admin.html`：最小企业管理后台。
- `enterprise/tests/`：诊断、冒烟、owner 隔离和 Smart Canvas 日志测试。

---

## 5. 关键文件边界

优先允许修改：

- `enterprise/`
- `enterprise-static/`
- `enterprise/tests/`
- `enterprise.env.example`
- `data/*.example.json`
- 项目文档
- `启动企业版.bat`
- `停止企业版.bat`

默认不应修改的上游覆盖区：

- `main.py`
- `static/`
- `workflows/`
- `API/`
- `python/`
- `VERSION`

例外：

- 正在执行受控上游同步。
- 正在迁移已确认必须保留的最小上游兼容补丁，例如 PR #21/#22 对 `static/js/smart-canvas.js` 的日志兼容逻辑。
- 正在修复经过确认的上游 bug，并已说明风险、回滚和上游反馈路径。

如果必须修改 `static/js/smart-canvas.js`，必须明确说明原因，因为它属于上游覆盖区，每次上游同步都可能被覆盖。

---

## 6. 数据归属模型

当前核心映射表：

- `users`：企业用户。
- `user_canvas_map(canvas_id -> user_id)`：画布 owner。
- `user_conversation_map(conversation_id -> user_id)`：对话 owner。
- `user_resource_map(resource_url -> user_id)`：受保护本地资源 owner。
- `user_canvas_task_map(task_id -> user_id)`：Smart Canvas 图片任务 owner。
- `user_project_map(project_id -> user_id)`：项目/文件夹 owner。
- `usage_logs`：审计日志。

重要规则：

1. 普通用户对未知 owner / 未归属数据默认拒绝。
2. 管理员可见全局数据，但关键代管操作必须审计。
3. `default` 项目不是全局共享项目，而是每位用户独立呈现的虚拟默认项目。
4. 普通用户可见画布必须满足：
   - canvas owner 是当前用户；
   - 且 canvas.project 是 `default`，或该 project owner 是当前用户。
5. 管理员移动画布到其他用户项目后，canvas owner 必须同步为目标 project owner。
6. 管理员直接把画布 owner 改给 B 时，如果当前 project 不属于 B，画布 project 应回退到 `default`。
7. 资源访问优先看显式 resource owner；必要时从当前用户拥有的画布/对话引用中回溯授权。

---

## 7. PR #24 后已验证能力

人工真实浏览器验收已通过：

1. 用户 A 创建项目/文件夹 A，并创建画布 A1。
2. 用户 B 创建项目/文件夹 B。
3. 管理员在无限画布项目/文件夹页把 A1 从 A 文件夹剪切/移动到 B 文件夹。
4. `/enterprise/admin` -> 画布归属刷新后显示 A1 owner 已变成用户 B。
5. 用户 A 重新登录后不可见 A1。
6. 用户 B 重新登录后可见 A1。
7. 用户 B 打开 A1 生成 output，刷新、退出重登后 output 仍可见。
8. 管理员打开 A1 可见。
9. 其他普通用户不可见。
10. 用户 B 再把该画布移动到自己的另一个项目，仍正常可见。

后端回归测试覆盖：

- A/B/admin 项目 owner、项目列表过滤、项目计数。
- 普通用户跨项目移动拒绝。
- 管理员移动 A 画布到 B 项目后 owner 同步为 B。
- 管理员把画布移动到 `default` 不会误改 owner。
- 管理员分配项目 owner 后，该项目内画布 owner 同步。
- 管理后台画布 owner 查询与 `user_canvas_map` 一致。
- 画布、对话、资源直接 ID 访问拒绝。
- Smart Canvas 日志兼容和去重不回归。

普通用户 `POST /api/update-from-github` 仍应返回 403。

---

## 8. 当前未完成任务矩阵

以下为 2026-07-08 稳定基线后的任务队列。历史 PR #24 后的 3G-3 至 3G-7A/7B 已完成，DOC-1 已由 PR #63 完成，不应再按旧待办执行：

| 后续任务 | 范围 | 当前状态 |
| --- | --- | --- |
| Task 3G-8 | 浏览器级自动化回归，把 A/B/admin 关键路径脚本化 | 待启动 |
| 3G-6 外部成功链路补验 | RunningHub / ModelScope / provider 有可用 Key 后做真实成功链路补验 | 待启动 |
| Task 3G-9 | 生产部署安全治理、默认密钥/管理员密码/运行时配置检查 | 待启动 |
| 协作权限设计 ADR | project members、canvas grants、共享/撤销、授权审计和迁移规则 | 待设计 |
| interceptors 模块化只读审计 | 评估 `enterprise/interceptors.py` 拆分到 `enterprise/policies/` 的路径 | 待审计 |

仍未进入当前主线的范围：

- team / workspace / project_members / canvas_grants / asset grants 实现。
- 复杂 RBAC、部门权限、计费、每用户独立 API Key。
- SaaS 多租户。
- 插件市场、工作流市场、大规模 UI 改版。
- 模型质量、第三方中转站、Provider 2K/high 等非企业隔离主线问题。

不要在交接任务或 Task 3G-2 后续收尾中顺手实现这些内容。

---

## 9. 后续任务优先级

推荐顺序：

1. Task 3G-8：浏览器级自动化回归。
2. 3G-6 外部 provider 成功链路补验。
3. Task 3G-9：生产部署安全治理。
4. 协作权限设计 ADR + 端到端验收矩阵。
5. `enterprise/interceptors.py` 模块化只读审计。

每个任务必须独立分支、独立 Draft PR、独立测试和浏览器验收。不要一次性处理多个 Task。

---

## 10. 每次 Codex 执行标准流程

每次开始任务：

1. 先读：
   - `PROJECT_HANDOFF_FOR_NEW_AGENT.md`
   - `AGENT_CONTEXT.md`
   - `PROJECT_CHARTER.md`
   - `ARCHITECTURE.md`
   - `CODE_BOUNDARIES.md`
   - `CODEX_WORKFLOW.md`
   - `DEVELOPMENT_PLAN.md`
   - 当前任务相关设计文档和代码。
2. 同步 main：

```powershell
git checkout main
git pull --ff-only origin main
git status --short
```

3. 为当前任务新建独立分支。
4. 只处理当前任务，不扩大范围。
5. 实现前先定位真实 API、存储、权限边界。
6. 修改后运行对应自动化测试。
7. 有前端/权限行为时必须做 A/B/admin 浏览器验收。
8. 提交、推送、创建 Draft PR。
9. PR 描述必须写清修改文件、测试结果、风险、回滚方案、是否修改上游覆盖区、是否提交运行时数据。

---

## 11. 验证命令清单

最小健康检查：

```powershell
python -m py_compile enterprise\db.py enterprise\interceptors.py enterprise\admin_api.py enterprise\gateway.py enterprise\config.py
python .\enterprise\tests\test_ownership_isolation.py
node --check static/js/smart-canvas.js
node .\enterprise\tests\test_smart_canvas_logs.js
powershell -NoProfile -ExecutionPolicy Bypass -File .\enterprise\tests\diagnose.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\enterprise\tests\smoke.ps1
```

上游同步后还应参考：

- `enterprise/tests/SMOKE_CHECKLIST.md`
- `enterprise/tests/BROWSER_REGRESSION_CHECKLIST.md`
- `enterprise/tests/UPDATE_TEST_LOG.md`

如执行启动/停止闭环，会中断当前服务：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\enterprise\tests\test_start_stop.ps1 -StopExisting
```

---

## 12. 禁止事项

- 不直接推 `main`。
- 不提交真实数据库、运行时图片、缓存、API Key、Token、Cookie、`enterprise.env`、`API/.env`。
- 不为了企业功能默认修改 `main.py`、`static/`、`workflows/`、`API/`、`python/`、`VERSION`。
- 不把第三方 provider、模型调用失败、token 过期、2K/high 失败误判为企业隔离问题。
- 不用前端隐藏替代后端鉴权。
- 不把多个 Task 合并到一个 PR。
- 不顺手重构无关代码。
- 不在项目根目录散落临时测试脚本；脚本统一放 `enterprise/tests/`。
- 不对未知 owner 数据默认放行。

---

## 13. 新 Codex 对话第一条提示词

下面内容可直接复制到新的 Codex 对话窗口：

```text
你将全面接手 Infinite-Canvas-Enterprise 企业版二开项目的后续长期开发与维护。

仓库：
MEIS-DaCaiTou/Infinite-Canvas-Enterprise

本地路径：
D:\CodeProject\26-5-27-无限画布

当前运行架构：
- 企业网关：0.0.0.0:8000
- 内部上游：127.0.0.1:3001
- 当前稳定基线：73a645f2bdded5df5c7109903c8b57eab9e3c459 或其后的 main
- 当前上游基线：VERSION=2026.07.6

请先阅读并遵守：
1. PROJECT_HANDOFF_FOR_NEW_AGENT.md
2. docs/CURRENT_PROJECT_STATUS.md
3. PROJECT_SCOPE_LOCK.md
4. AGENT_CONTEXT.md
5. PROJECT_CHARTER.md
6. ARCHITECTURE.md
7. CODE_BOUNDARIES.md
8. CODEX_WORKFLOW.md
9. DEVELOPMENT_PLAN.md
10. ENTERPRISE_ISOLATION_MATRIX.md
11. ENTERPRISE_PERMISSION_DESIGN.md
12. enterprise/tests/README.md

当前 main 已包含关键 PR：
- PR #18：画布/对话/资源基础归属隔离
- PR #34：上传资源隔离
- PR #38：素材库完整隔离
- PR #42：WebSocket 广播隔离
- PR #46：异步任务历史 owner 隔离
- PR #49：管理员权限开关最小版 + 审计
- PR #53：Angle / Enhance ModelScope 上传解耦
- PR #55：delete-impact dry-run
- PR #56：soft delete + feature override 清理
- PR #58：成员管理搜索 / 筛选 / 分页
- PR #60：U-1 上游同步只读审计
- PR #61：U-2 受控同步到上游 2026.07.6
- PR #62：U-2-F1 / U-2-F2，云端 history type 一致性修复

接手前先执行：
git checkout main
git pull --ff-only origin main
git rev-parse HEAD
git status --short

然后运行最小健康检查：
python -m py_compile enterprise\db.py enterprise\interceptors.py enterprise\admin_api.py enterprise\gateway.py enterprise\config.py
python .\enterprise\tests\test_ownership_isolation.py
node --check static/js/smart-canvas.js
node .\enterprise\tests\test_smart_canvas_logs.js
powershell -NoProfile -ExecutionPolicy Bypass -File .\enterprise\tests\diagnose.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\enterprise\tests\smoke.ps1

开发边界：
- 默认不要修改 main.py、static/、workflows/、API/、python/、VERSION。
- 企业功能优先放 enterprise/、enterprise-static/、enterprise/tests/ 和项目文档。
- 每个任务必须单独分支、单独 Draft PR，不直接推 main。
- 不提交真实数据库、运行时图片、缓存、history.json、assets/、output/、data/、API Key、Token、Cookie、enterprise.env、API/.env、python/。
- 前端隐藏不能替代后端鉴权。
- 普通用户对未知归属数据默认拒绝，管理员可见但关键操作需审计。
- 不要把第三方 provider、模型调用失败、token 过期、2K/high 失败误判为企业隔离问题。

当前已经完成企业安全隔离底座第一阶段、3G-7B 用户治理、U-2 受控上游同步和 U-2-F2 history type 修复。

推荐下一个开发任务：
DOC-1 文档体系同步已完成，PR #63。后续按 PROJECT_SCOPE_LOCK.md 当前队列推进 3G-8 浏览器级自动化回归、3G-6 外部 provider 成功链路补验、3G-9 生产部署安全治理、协作权限设计 ADR 和 interceptors 模块化只读审计。

执行任何任务前，先确认当前 Issue 范围并复核代码边界。实现后必须补充 A/B/admin 自动化或浏览器验收，并在 PR 描述里写清测试结果、风险、回滚方案、是否修改上游覆盖区、是否提交运行时数据。
```
