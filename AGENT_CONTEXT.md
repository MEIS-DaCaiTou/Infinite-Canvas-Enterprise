# 无限画布企业版 · Agent 当前上下文入口

> 给后续 Codex / Agent 的第一阅读文件。上下文压缩、换线程、长期维护恢复时，先读本文，再读 `ENTERPRISE_DOCS.md` 和 `enterprise/tests/SMOKE_CHECKLIST.md`。

更新时间：2026-06-11

---

## 1. 项目一句话定位

本项目是在上游开源项目 [hero8152/Infinite-Canvas](https://github.com/hero8152/Infinite-Canvas) 之上构建的企业多用户版本。

企业层本质是反向代理和权限隔离层：

- 对外服务：`enterprise/gateway.py` 监听 `0.0.0.0:8000`
- 内部上游：`main.py` 监听 `127.0.0.1:3001`
- 企业功能：登录、JWT Cookie、用户管理、画布归属、数据隔离、审计日志、健康检查、启动/停止闭环
- 上游功能：无限画布、资产、模型调用、更新按钮、静态前端资源

---

## 2. 阅读顺序

1. `AGENT_CONTEXT.md`：当前真实状态、风险、路线，防止上下文压缩后跑偏。
2. `ENTERPRISE_DOCS.md`：企业层完整开发规范。
3. `enterprise/tests/README.md`：测试脚本位置与用途。
4. `enterprise/tests/SMOKE_CHECKLIST.md`：每次上游更新后的必跑检查。
5. 必要时再读 `HANDOVER.md`：历史交接材料。该文件较长，部分终端可能显示乱码，不应作为唯一权威入口。

---

## 3. 当前实际状态

| 项 | 当前状态 |
|----|----------|
| 本地上游版本 | `2026.06.02.1` |
| 企业私有仓库 | `MEIS-DaCaiTou/Infinite-Canvas-Enterprise` |
| 企业仓库最新提交 | 以 `git log -1 --oneline` 为准；2026-06-11 维护前基线为 `03d0f1b chore: sync upstream and document enterprise maintenance` |
| 上游源码仓库 | `hero8152/Infinite-Canvas` |
| 上游 bugfix PR | [hero8152/Infinite-Canvas#67](https://github.com/hero8152/Infinite-Canvas/pull/67)，状态 OPEN；2026-06-11 查询为 `CONFLICTING` |
| 当前运行端口 | `8000` 企业网关，`3001` 内部上游 |
| 当前健康检查 | `/enterprise/health` 返回 `gateway=ok`、`upstream=ok` |
| 测试脚本目录 | 统一放在 `enterprise/tests/`，不要散落到根目录或上游目录 |

2026-06-11 维护中确认：12 个 `static/*.html` 改动均为资源版本参数从 `2026.06.02` 同步到 `2026.06.02.1`，用于让浏览器刷新缓存；这类改动属于上游静态资源版本归档，不是企业层功能开发方向。

---

## 4. 不可偏离的开发边界

### 企业层功能优先放在企业层

企业化能力应优先在这些位置实现：

- `enterprise/`
- `enterprise-static/`
- `enterprise.env`
- `启动企业版.bat`
- `停止企业版.bat`
- `enterprise/tests/`
- 项目文档

### 上游文件默认不作为企业二开入口

以下属于上游更新覆盖面：

- `main.py`
- `static/`
- `workflows/`
- `API/`
- `python/`
- `VERSION`

原则：企业层不应为了企业功能修改上游文件。

例外：如果确认是上游项目自身 bug，可以先做最小本地热修用于生产验证，但必须同时：

1. 在文档中记录原因和影响范围。
2. 向上游提交 issue 或 PR。
3. 后续上游合并后移除本地热修差异。
4. 每次上游更新后按 `enterprise/tests/SMOKE_CHECKLIST.md` 重新验证。

---

## 5. 已完成的重要工作

- 企业版启动器改为受控双进程模型：内部上游 `127.0.0.1:3001`，企业网关 `0.0.0.0:8000`。
- 新增 `停止企业版.bat`，用于清理 `8000/3001` 监听。
- 新增诊断、冒烟、启动停止闭环脚本，统一在 `enterprise/tests/`。
- 修正 `/enterprise/health` 探测上游 `/api/app-info`，其语义是“上游可达性检查”，不是严格版本差异检查。
- 私有 GitHub 仓库已改为 `Infinite-Canvas-Enterprise` 并完成首次推送。
- 明确局域网地址选择策略：不固定主机 IP；`11.*` 地址如果受浏览器代理影响，本机可能访问失败，关闭代理或配置绕过后可正常访问。
- 发现 Smart Canvas LLM 节点“长时间运行”问题：本质是前端 `running` 临时状态被持久化或未及时保存清理，同时带 `*` 的通配模型名可被用户选中导致上游 503。
- 已向上游提交 PR：`hero8152/Infinite-Canvas#67`。

---

## 6. 当前已知风险

1. 上游更新会覆盖 `main.py` 和 `static/`，因此任何上游热修都可能在更新后丢失。
2. 当前 `data/api_providers.json` 是运行时配置，可能包含不可用或占位模型名；模型可用性需要以实际接口测试为准。
3. 内置 `python/` 运行时与 GitHub TLS 曾出现兼容问题；必要时用 PowerShell 下载上游文件绕过 Python SSL 问题。
4. `enterprise.env`、`API/.env`、`data/` 是运行态/敏感数据，不应提交到 Git。
5. 多用户局域网使用依赖防火墙、代理绕过和主机当前网络路由，不能硬编码固定 LAN 地址。

---

## 7. 后续维护原则

- 先稳运行，再稳维护，再扩功能。
- 每次上游更新后，先跑诊断和冒烟，再做功能开发。
- 遇到上游 bug：最小复现、最小补丁、提交上游 PR，本地只保留临时热修。
- 遇到企业需求：优先代理层、拦截层、企业前端实现。
- 不要把测试脚本、临时诊断脚本散落到项目根目录；统一放入 `enterprise/tests/`。

---

## 8. 最近一次验证记录

验证时间：2026-06-11

已执行：

- 启动 `enterprise/launcher.py`，拉起 `127.0.0.1:3001` 与 `0.0.0.0:8000`。
- `enterprise/tests/diagnose.ps1`
- `enterprise/tests/smoke.ps1`

结果：

- 本机健康检查 `http://127.0.0.1:8000/enterprise/health`：HTTP 200。
- 内部上游 `http://127.0.0.1:3001/api/app-info`：HTTP 200，版本 `2026.06.02.1`。
- 监听端口：`0.0.0.0:8000`、`127.0.0.1:3001`。
- 当前推荐 LAN 地址：`11.0.1.98`。
- Windows 代理开启：`127.0.0.1:7897`；普通请求访问 `11.0.1.98:8000` 会被代理影响而超时。
- `curl --noproxy` 访问 `http://11.0.1.98:8000/enterprise/health`：HTTP 200。
- 冒烟检查全部通过：健康检查、登录页、管理员页鉴权、根路径鉴权/跳转。
- 企业仓库当前 GitHub 可见性查询为 `PUBLIC`；如需私有，需要在 GitHub 仓库设置中调整。

本轮未执行 `test_start_stop.ps1 -StopExisting`，因为它会中断当前正在运行的服务。需要验证启动/停止闭环时，先告知当前页面会短暂不可用，再执行。

---

历史记录：

验证时间：2026-06-03

已执行：

- `enterprise/tests/diagnose.ps1`
- `enterprise/tests/smoke.ps1`

结果：

- 本机健康检查 `http://127.0.0.1:8000/enterprise/health`：HTTP 200。
- 内部上游 `http://127.0.0.1:3001/api/app-info`：HTTP 200，版本 `2026.06.02.1`。
- 监听端口：`0.0.0.0:8000`、`127.0.0.1:3001`。
- 当前推荐 LAN 地址：`11.0.1.98`。
- Windows 代理开启：`127.0.0.1:7897`；普通请求访问 `11.0.1.98:8000` 会被代理影响而超时。
- `curl --noproxy` 访问 `http://11.0.1.98:8000/enterprise/health`：HTTP 200。
- 冒烟检查全部通过：健康检查、登录页、管理员页鉴权、根路径鉴权/跳转。

本轮未执行 `test_start_stop.ps1 -StopExisting`，因为它会中断当前正在运行的服务。需要验证启动/停止闭环时，先告知当前页面会短暂不可用，再执行。
