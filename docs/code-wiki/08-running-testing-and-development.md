# 运行、测试与开发方式

[返回索引](./README.md)

## 1. 前置条件

- Windows 10/11 x64。
- 源码开发可使用仓库自带 `python/python.exe`；正式安装必须使用 Release 内固定 Python。
- 复制 `enterprise.env.example` 为 `enterprise.env`，修改 JWT secret 与管理员密码。
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

当前代码树有 59 个 Python 测试文件。推荐从根目录使用仓库 Python：

```powershell
.\python\python.exe -m pytest enterprise\tests -q -p no:asyncio
```

如果 pytest 不在该开发 Runtime 中，应使用项目已验证的开发环境安装测试依赖；不要为了让测试运行而修改正式 Runtime lock。

测试域：

| 测试组 | 覆盖 |
| --- | --- |
| `test_ownership_isolation.py` 等 | A/B/admin 画布、项目、对话、资源与直接 ID 隔离 |
| `test_websocket_isolation.py` | WebSocket 用户事件隔离 |
| `test_feature_flags.py` | 全局开关与用户覆盖 |
| `test_sec_*`、`test_user_gov_mvp_1.py` | 角色、审计、bootstrap、用户治理 |
| `test_runtime_reliability.py`、`test_stab_*` | Supervisor、日志、健康和重启语义 |
| `test_env_*` | PathRoots、portable、固定 Python、构建与 Windows 验证契约 |
| `test_release_mvp_1.py`、`test_ops_release_manifest_v2.py` | Release/Manifest 闭包与防篡改 |
| `test_install_*` | 首次安装与 Inno Setup bridge |
| `test_update_mvp_1.py`、`test_ops_3a_online_update.py` | 更新准备、权限、切换、回滚与诊断 |
| `test_data_mvp_1.py` | SQLite 版本化迁移和恢复基础 |
| `test_canvas_task_journal.py` | 本地分支任务回执恢复 |

这些测试大量使用临时 SQLite、临时目录和 fixture；通过它们不等于真实客户设备、正式签名安装器或生产发布已经验收。

2026-09-19 收敛分支初次证据：CPython 3.11 完整企业套件为 `909 passed, 10 skipped, 1 failed`，唯一失败是受限后台子会话创建 service host 时的 `WinError 5`；同机直接 lifecycle 在 CPython 3.11 与 bundled CPython 3.14.6 下均 `3 passed`，可靠性与任务回执专项在两者下均 `33 passed`。这是历史测试结果，不能从计数中删除或写成全绿；后续处理和复跑见下段。

2026-09-21 本机复跑 CPython 3.11 完整企业套件为 `910 passed, 10 skipped`；后续中文路径编码和长路径主机差异夹具另以 `2 passed` 验证。GitHub-hosted Windows Runner 的 Job Object 禁止正式 Runtime 所需的 `CREATE_BREAKAWAY_FROM_JOB`，所以只在该托管环境显式跳过跨会话 Service Host 生命周期测试；仓库 Runtime 保留该标志。本机直接生命周期测试在 CP311 与 bundled CP314 下各 `3 passed`。项目负责人不要求独立 Windows 主机验收门禁；CI 通过也不能把显式跳过写成在托管 Runner 上已执行。

## 6. 浏览器回归

按 `enterprise/tests/BROWSER_REGRESSION_CHECKLIST.md` 和 `SMOKE_CHECKLIST.md` 执行，至少覆盖：

1. 普通用户 A、普通用户 B、管理员/超级管理员登录。
2. 工作台创建项目和画布。
3. 普通画布上传、平移、缩放、选择、拖动、保存、关闭重开。
4. 智能画布节点、连线、运行状态、导入导出。
5. A/B 列表过滤、直接 URL/ID 拒绝和 WebSocket 不串流。
6. Provider 设置脱敏与功能开关。
7. 进程重启后画布、素材、归属和会话语义。

前端无编译步骤，因此浏览器验证是发现资源缓存、脚本错误和行为回归的主要方式。

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
4. 先增加聚焦测试，再修改企业层；跨界修改 `main.py/static` 时补浏览器清单。
5. 运行聚焦测试、全套企业测试、smoke 和必要的浏览器回归。
6. 更新当前状态/实施记录，但不修改历史证据结论。
7. 审查 diff、确认没有 secret、数据库、客户数据或 Runtime 构建产物。

## 9. CI 现状

`codex/mainline-runtime-convergence-20260919@84f6fe2` 新增 `.github/workflows/enterprise-checks.yml`，在 Windows 上运行 CPython 3.11 完整企业套件和 CPython 3.14 Runtime 专项；PR #108 的两项检查在 2026-09-21 核验为 SUCCESS。工作流在 PR 合并前仍不是 `main` 能力。项目负责人已明确不设置独立 Windows 主机验收门禁；正式 bundled Runtime、签名、Release、客户现场和生产批准仍与普通 pytest/Actions 分开记录。

## 10. 常见故障定位

| 现象 | 首查 |
| --- | --- |
| 页面打不开 | `查看企业版状态.bat`、8000/3001 监听、`enterprise/health` |
| Gateway 正常但业务失败 | Upstream 健康、`main.py` 日志、Provider 超时 |
| 启动 blocked | JSON `code`、端口监听者身份、current pointer、Manifest/Python identity |
| 后台更新 403 | 当前角色、`system_update` 全局开关、`ENTERPRISE_UPDATE_ENABLED` |
| 检查更新失败 | GitHub API/资产 URL、系统与环境代理、Manifest 三件套 |
| 更新后回滚 | 作业 status/events、target health、source pointer 恢复结果 |
| 用户看到他人数据 | ownership map、拦截器列表/直接 ID、WebSocket 过滤四处一起检查 |
| 图片缺失 | 文件是否存在、资源 URL 标准化、owner map、preview/view 路径 |
