# Infinite Canvas Enterprise 代码与数据边界

更新时间：2026-09-21

项目已独立演进，不再把 `main.py`、`static/` 或 `workflows/` 视为永远禁止修改的“上游覆盖区”。所有产品代码都可在明确需求、测试和迁移计划下修改；风险边界取决于职责、数据兼容性和发布影响。

## 1. 常规修改区域

| 区域 | 主要职责 |
| --- | --- |
| `enterprise/` | Gateway、认证授权、管理、数据、Runtime、Release/Update、领域服务 |
| `enterprise-static/` | 企业登录、管理、个人中心和更新体验 |
| `enterprise/tests/` | 单元、集成、故障注入、浏览器和生命周期验证 |
| `docs/`、根目录权威文档 | 当前状态、架构、路线、ADR、实施与验收记录 |
| `.github/workflows/` | CI 检查与构建门禁 |

修改这些区域仍需遵守业务兼容、权限和数据迁移要求，不能因为它们是“企业目录”就降低审查强度。

## 2. 高影响区域

| 区域 | 主要风险 | 最低要求 |
| --- | --- | --- |
| `main.py` | 核心 API、业务生命周期、任务/资源数据 | 接口/任务/启动回归，说明数据兼容 |
| `static/` | 旧版视觉和交互、缓存、浏览器兼容 | 同尺寸视觉对照、关键交互与权限回归 |
| `workflows/`、Provider 适配 | 外部调用、费用、幂等、隐私 | 真实或受控沙箱闭环、超时/未知结果测试 |
| `enterprise/db.py`、`enterprise/migrations/` | schema、事务、恢复 | migration + backup/restore + failure injection |
| `enterprise/runtime/` | 进程所有权、重启、停机 | 生命周期、阻塞、断网、重启和状态恢复 |
| `enterprise/release/`、`enterprise/update_api.py` | 安装和在线升级 | Manifest/哈希、源版本、恢复和权限测试 |
| `release/`、启动/停止脚本 | 客户安装和运维 | 可复现打包、原位升级、回滚说明 |

这些文件可以修改，但必须小步、可审查、可回滚；不得继续用“等待上游修复”作为阻断本项目演进的理由。

## 3. 不得提交的内容

- `enterprise.env` 或任何真实环境配置。
- API key、Token、Cookie、Authorization、私钥、真实密码。
- `API/.env`、客户日志原件、客户数据库和客户素材。
- `data/`、`assets/`、`output/`、本地缓存、Runtime state/log、临时诊断包。
- 本机 Python/Node 运行时、构建缓存和未批准的大型二进制。

测试夹具必须脱敏、最小化并可从仓库重建。

## 4. 领域放置原则

- HTTP/WebSocket 入口只做协议适配和调用编排，不承载越来越多业务判断。
- 授权放入可复用 Policy；UI、API、Worker、Update、MCP 使用同一语义。
- 业务命令放入 Application Service；数据库/文件/Provider 放入 Adapter 或 Repository。
- 资源字节与元数据分离；路径通过 Storage Adapter 解析。
- 任务受理、执行、对账和费用记录属于持久业务域，不使用进程内字典作为事实源。
- 新增表前先定义 schema version、升级、备份、恢复和旧版本兼容。

## 5. 历史来源

`docs/upstream/` 记录截至 2026.07.6 的历史来源和同步审计。它不再规定文件修改权限，也不要求后续 PR 执行上游 merge/rebase/sync。若未来引入第三方代码更新，应作为新的依赖升级任务，明确许可证、差异、测试和回滚。

## 6. 变更前检查

1. 任务属于哪个固定路线阶段？前置阶段是否完成？
2. 当前 Base/Head/PR 是否与任务一致？
3. 是否改变 schema、资源标识、任务状态或权限语义？
4. 现有客户如何升级，失败如何恢复？
5. 需要哪些自动测试、故障注入和人工验证？
6. 是否错误地把分支、Release 或单设备结果写成主线/生产事实？
