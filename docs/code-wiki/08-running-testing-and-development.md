# 运行、测试与开发方式

2026-10-27现行开发基线：CPython **3.14.6**与`runtime/windows/requirements.lock`的30项发行依赖。下文较早的3.11命令仅是历史验证记录，不是当前强制兼容目标。应用依赖不再分别在根目录与enterprise维护；两个旧requirements入口均指向同一发行锁。

新开发环境使用独立3.14.6解释器/虚拟环境，执行`python -m pip install --require-hashes -r requirements-dev.txt`，再运行`python -B tools/check_development_runtime.py`；测试前设置`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`。test-tools.lock只添加测试工具，不改变发行闭包。复制现有固定Runtime用于开发时，保留原发行依赖，将测试工具单独置于开发路径，不修改已安装的原Runtime或全局Python。

2026-10-27开发预览记录：本机预览沿用18000/18001和原测试数据，使用独立3.14.6开发Runtime，服务均只监听127.0.0.1。该段为历史运行记录，实际预览状态需现场核验。

2026-10-26队列定向验证：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1，py -3.11 -B -m pytest -q enterprise/tests/test_comfy_queue.py enterprise/tests/test_canvas_task_dispatch_main.py enterprise/tests/test_canvas_task_dispatch_policy.py enterprise/tests/test_comfy_cancellation.py enterprise/tests/test_canvas_comfy_recovery.py enterprise/tests/test_comfy_io.py。使用真实journal、受控后端队列和HTTP受理路径，覆盖多用户轮转及持续加入、跨工作流/地址额度、外部占用、重启、取消和阶段拒绝。浏览器从根首页进入后台验证配置保存，再从原目录进入经典画布；隔离卡片验证平台等待与本地取消、刷新终态。该组不向真实GPU提交任务，保留原开发服务供负责人验收。

> 源码参考快照（2026-10-13）：main@e89a288（已合并 #154/#155/#156）；产品功能源码基点 #156@4bdd9a1 保留；C5/C6/C7 已合并，构建与验收范围仍引用其准确记录。本文是代码/运行参考，当前 PR/CI、Release 和验收只见 [CURRENT](../CURRENT_PROJECT_STATUS.md)，实施顺序只认路线图。

[返回索引](./README.md)

更新时间：2026-10-13。命令为源码/旧安装参考；产品交付和现场状态回到 [CURRENT](../CURRENT_PROJECT_STATUS.md)。

2026-10-24本地流程调整：开发增量先启动原Gateway和业务服务，在固定内置浏览器入口交负责人手工测试；保留测试数据，反馈先在同一源码工作区修订。真实登录/角色实例与模拟身份的自动测试夹具分开；源码预览不要求每次打包或升级正式版本。人工确认后再提交PR，实际候选包与准确升级路径另验收。入口状态见[CURRENT](../CURRENT_PROJECT_STATUS.md)，具体规则见[开发工作流](../../CODEX_WORKFLOW.md#31-开发机人工验收与反复修订负责人2026-10-24要求)。

## 1. 前置条件

- Windows 10/11 x64。
- 源码开发使用已确认的解释器，不假设源码目录自带 Python；正式安装必须使用 Release 内固定 Python。
- 源码首次部署按安全基线配置；新装器负责首次配置，旧安装沿用环境/数据库，不每次复制示例或重置管理员。
- 不要提交 `enterprise.env`、真实数据库、客户素材、Token 或诊断包。

## 2. 企业版开发启动

从仓库根目录执行：

```powershell
.\启动企业版.bat
```

随后访问：

- 入口：`http://127.0.0.1:8000/`
- 登录：`http://127.0.0.1:8000/enterprise/login`
- 管理后台：`http://127.0.0.1:8000/enterprise/admin`
- 健康：`http://127.0.0.1:8000/enterprise/health`
- 存活：`http://127.0.0.1:8000/enterprise/live`

控制命令：

```powershell
.\查看企业版状态.bat
.\企业版健康检查.bat
.\重启企业版.bat
.\停止企业版.bat
```

这些脚本输出结构化 JSON；非零退出码表示 blocked/unhealthy/command failure，应先读取 `code` 再处理。

## 3. 旧 Upstream 调试入口

```powershell
.\run.bat
# 或
.\启动服务.bat
```

它们直接启动 `main.py` 并使用 3000 端口的旧行为，不提供企业登录、归属隔离和企业更新。只应用于明确的 Upstream 调试，不用于客户或企业验收。

## 4. 诊断与 smoke

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\enterprise\tests\diagnose.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\enterprise\tests\smoke.ps1
```

`diagnose.ps1` 检查版本、LAN IP、代理、8000/3001 监听者、进程路径和健康响应。`smoke.ps1` 检查企业健康、登录页、后台认证跳转和根入口认证跳转。

## 5. Python 测试

默认选择受影响范围，禁用非必要外部插件；以下是数据库专项示例，不是每轮全套命令：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
python -B -m pytest enterprise/tests/test_data_mvp_1.py -q
```

纯文档使用标准库检查：

```powershell
python -B tools/check_docs.py
python -B -m unittest discover -s enterprise/tests -p test_documentation_contract.py
```

如果 pytest 不在该开发 Runtime 中，应使用项目已验证的开发环境安装测试依赖；不要为了让测试运行而修改正式 Runtime lock。

测试域：

| 测试组 | 覆盖 |
| --- | --- |
| `test_ownership_isolation.py` 等 | A/B/admin 画布、项目、对话、资源与直接 ID 隔离 |
| `test_websocket_isolation.py` | WebSocket 用户事件隔离 |
| `test_sec_p0_browser_boundaries.py` | HTTP/静态路由清单、Origin/CSRF、登录限流、站内跳转、Cookie、WebSocket fail-closed 与路径 containment |
| `test_feature_flags.py` | 全局开关与用户覆盖 |
| `test_sec_*`、`test_user_gov_mvp_1.py` | 角色、审计、bootstrap、用户治理 |
| `test_runtime_reliability.py`、`test_stab_*` | Supervisor、日志、健康和重启语义 |
| `test_env_*` | PathRoots、portable、固定 Python、构建与 Windows 验证契约 |
| `test_release_mvp_1.py`、`test_ops_release_manifest_v2.py` | Release/Manifest 闭包与防篡改 |
| `test_install_*` | 首次安装与 Inno Setup bridge |
| `test_update_mvp_1.py`、`test_ops_3a_online_update.py` | 更新准备、权限、切换、回滚与诊断 |
| `test_data_mvp_1.py` | SQLite 版本化迁移和恢复基础 |
| `test_canvas_task_journal.py` | 已合并的两类画布回执基础，不是全部持久任务 |

这些测试大量使用临时 SQLite、临时目录和 fixture；通过它们不等于真实客户设备、正式签名安装器或生产发布已经验收。

以下为历史测试记录，不是本轮新跑分；实时 CI 回到 CURRENT/相关 PR。

2026-09-19 收敛分支初次证据：CPython 3.11 完整企业套件为 `909 passed, 10 skipped, 1 failed`，唯一失败是受限后台子会话创建 service host 时的 `WinError 5`；同机直接 lifecycle 在 CPython 3.11 与 bundled CPython 3.14.6 下均 `3 passed`，可靠性与任务回执专项在两者下均 `33 passed`。这是历史测试结果，不能从计数中删除或写成全绿；后续处理和复跑见下段。

2026-09-21 本机复跑 CPython 3.11 完整企业套件为 `910 passed, 10 skipped`；后续中文路径编码和长路径主机差异夹具另以 `2 passed` 验证。GitHub-hosted Windows Runner 的 Job Object 禁止正式 Runtime 所需的 `CREATE_BREAKAWAY_FROM_JOB`，所以只在该托管环境显式跳过跨会话 Service Host 生命周期测试；仓库 Runtime 保留该标志。本机直接生命周期测试在 CP311 与 bundled CP314 下各 `3 passed`。项目负责人不要求独立 Windows 主机验收门禁；CI 通过也不能把显式跳过写成在托管 Runner 上已执行。

2026-09-22 SEC-P0 最终快照在 CPython 3.11 上复跑完整企业套件为 `947 passed, 10 skipped, 8 warnings`，耗时 `460.77s`。警告为既有 FastAPI `on_event` 弃用提示和测试夹具 JWT 短密钥提示；本轮无测试失败。该本机结果仍需由实施 PR 的 GitHub Actions 复核。

## 6. 浏览器回归

按 `enterprise/tests/BROWSER_REGRESSION_CHECKLIST.md` 和 `SMOKE_CHECKLIST.md` 执行，至少覆盖：

1. 普通用户 A、普通用户 B、管理员/超级管理员登录。
2. 工作台创建项目和画布。
3. 普通画布上传、平移、缩放、选择、拖动、保存、关闭重开。
4. 智能画布节点、连线、运行状态、导入导出。
5. A/B 列表过滤、直接 URL/ID 拒绝和 WebSocket 不串流。
6. Provider 设置脱敏与功能开关。
7. 进程重启后画布、素材、归属和会话语义。

现有原生前端无统一 TypeScript 编译流程；Vue 3＋TypeScript 仅试做方向。当前浏览器验证是发现资源缓存、脚本错误和行为回归的主要方式。

## 7. 发布/安装验证

正式 Release 不是 `git archive` 或源码 ZIP。发布流程需：

1. 从干净 Git commit/tree 构建静态树和应用 payload。
2. 生成固定 Windows Runtime、依赖证据和 SBOM。
3. 生成 archive inventory、`release-payload-inventory.json` 和 `ops-release-manifest-v2.json`。
4. materialize 后验证 APP_ROOT 闭包与启动核心哈希。
5. 在受控 Windows 环境执行 start/status/health/stop、首次安装、更新成功与失败回滚；不要求单独准备一台验收主机。
6. 只有满足单独审批标准后才可标记正式 Release/生产基线。

具体构建脚本随阶段记录变化，应从 `enterprise/release/`、`runtime/windows/` 和对应实施文档选择，而不是复制历史聊天命令。

## 8. 开发工作流

1. `git fetch --prune origin`，记录 `origin/main`、当前分支和目标 tag。
2. 阅读 `docs/CURRENT_PROJECT_STATUS.md`、`CODE_BOUNDARIES.md` 和相关 ADR。
3. 为单一行为创建 `codex/*` 分支。
4. 完整工程包内复用既有实现和有效证据，按实际风险安排必要定向校验；低影响文档不启动业务全套，画布交互变更核对目标浏览器路径。
5. 优先聚焦测试，按风险补 smoke/浏览器回归；跨模块风险、必要复核或合并要求才重跑全套并解释原因。
6. 更新当前状态/实施记录，但不修改历史证据结论。
7. 审查 diff、确认没有 secret、数据库、客户数据或 Runtime 构建产物。

## 9. CI 现状

主线既有 `.github/workflows/enterprise-checks.yml` 在 Windows 运行 CP311 企业套件及 CP314 Runtime 专项。维护线通用工具有独立定向 CI，不能互换覆盖；文档契约用轻量 `documentation-checks.yml`。结果以准确 PR/提交记录为准，不手动无理由重跑全套，也不要求独立干净设备。

## 10. 常见故障定位

| 现象 | 首查 |
| --- | --- |
| 页面打不开 | `查看企业版状态.bat`、8000/3001 监听、`enterprise/health` |
| Gateway 正常但业务失败 | Upstream 健康、`main.py` 日志、Provider 超时 |
| 启动 blocked | JSON `code`、端口监听者身份、current pointer、Manifest/Python identity |
| 后台操作 403 | 角色/治理激活、API 契约/审计；更新再查 `system_update` / `ENTERPRISE_UPDATE_ENABLED`，不放宽授权 |
| 来源身份不匹配 | 精确 Release/Manifest/完整结构；导出脱敏诊断，不删表或改旧证据 |
| 检查更新失败 | GitHub API/资产 URL、系统与环境代理、Manifest 三件套 |
| 更新后回滚 | 作业 status/events、target health、source pointer 恢复结果 |
| 用户看到他人数据 | ownership map、拦截器列表/直接 ID、WebSocket 过滤四处一起检查 |
| 图片缺失 | 文件是否存在、资源 URL 标准化、owner map、preview/view 路径 |

## 11. 本轮新增模块的定向入口

图像构造：test_model_request_contract.py；个人模型：test_user_model_preferences.py；后台契约：test_product_integration_fixes.py；素材边界：test_sec_p0_browser_boundaries.py 及实际扩展 JS 请求证据。对应 #156 功能提交已有定向/HTTP/Browser 结果，文档变更只运行文档合同、链接和源码索引复核，不重跑这些业务检查。

维护候选的真实安装副本/GUI/CI 采用 C5/C6/C7 各自准确来源，不能把源码 ZIP 当正式 Release 或在普通开发树运行破坏性演练。工作区同步先检查每个工作树和本地提交，只有干净的目标 main 可正常切换/快进；不 reset/clean/stash 用户变更，不改其他候选。
