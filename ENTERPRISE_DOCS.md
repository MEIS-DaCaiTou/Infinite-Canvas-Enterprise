# Infinite Canvas Enterprise 企业层开发指南

更新时间：2026-09-21

本文是快速开发指南，不是当前状态或路线图。完整导航见 [docs/README.md](docs/README.md)，模块细节见 [Code Wiki](docs/code-wiki/README.md)。

## 1. 运行拓扑

- Enterprise Gateway：`:8000`，对 LAN/浏览器开放。
- Canvas application：`127.0.0.1:3001`，仅供 Gateway/Runtime 使用。
- Runtime Supervisor：管理两个进程、身份、状态、日志、健康、退避和停机。
- 数据：SQLite + 业务文件；尚不是 PostgreSQL/多节点架构。

项目历史上使用“Enterprise/Upstream”双层称呼。现在两层均属于本产品；`upstream` 仅是部分模块和 Runtime role 的兼容命名，不再表示持续同步外部项目。

## 2. 代码入口

| 需求 | 首选位置 |
| --- | --- |
| 登录、会话、Gateway 路由 | `enterprise/gateway.py`、`enterprise/auth.py` |
| HTTP/事件授权 | `enterprise/interceptors.py`，新增逻辑优先抽到领域 Policy |
| 管理后台 API | `enterprise/admin_api.py` 及对应 Application Service |
| 企业数据库 | `enterprise/db.py`、`enterprise/migrations/`、Repository |
| Runtime | `enterprise/runtime/` |
| Release/Update | `enterprise/release/`、`enterprise/update_api.py` |
| 企业页面 | `enterprise-static/` |
| 画布/工作流/Provider | `main.py`、`static/`、`workflows/` 及后续领域 Adapter |
| 测试 | `enterprise/tests/` |

`main.py`、`static/` 和 `workflows/` 可以修改，但属于高影响区域；必须提供接口、交互、数据和升级回归。不要为了保留历史“上游不修改”规则而把不合适的补丁强塞到 Gateway。

## 3. 权限规则

- UI、HTTP、WebSocket、Worker、更新和未来 MCP 入口使用同一业务授权语义。
- 未知路由、未知事件和未知 owner 默认拒绝。
- 普通用户只能访问明确属于其用户/项目/组织的数据。
- 超级管理员高风险能力必须显式授权并审计。
- 管理后台的前端按钮不能代替 API 权限。
- 身份模型保留内部 `user_id` 与多个外部 identity 的映射能力，不按邮箱自动合并。

## 4. 数据规则

- 新增表或字段前先定义 `schema_version`、migration、backup、restore、验证和兼容范围。
- 大型图片/视频字节不进入普通数据库事务。
- 文件路径经 PathRoots/Storage Adapter 解析，不把本机绝对路径写进业务对象。
- 任务先持久受理，再调用 Provider；结果未知时进入 reconciliation。
- 费用记录固化部门、项目、Provider、模型和计价版本，不按当前配置回算历史。

## 5. Runtime 与更新

- liveness 不访问数据库或 Provider；readiness 与依赖健康分开。
- 短暂依赖故障降级，真实退出才按退避恢复。
- 更新流程必须包含：授权、兼容检查、通知/排空、下载校验、备份、迁移、切换、健康、提交或恢复。
- 更新 Job 必须跨浏览器断开和服务重启持久化。
- Release 资产不可变，具备 Manifest、哈希/签名、源版本范围和回滚说明。

## 6. 前端规则

- 旧无限画布的视觉与核心交互是产品基线；改动工作区、画布、拖拽、缩放、上传和任务反馈时做同尺寸对照。
- 可访问性、键盘操作和响应式变化不能破坏既有高频路径。
- 大资源使用缩略图、懒加载、虚拟化、ETag/Range；不要每次打开都拉取原文件。
- 更新期间展示维护通知和持久进度，不允许用户误以为保存/生成仍可用。

## 7. 本地运行与测试

```powershell
.\启动企业版.bat
powershell -NoProfile -ExecutionPolicy Bypass -File .\enterprise\tests\diagnose.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\enterprise\tests\smoke.ps1
```

其它测试、破坏性说明和 CI 范围见 [enterprise/tests/README.md](enterprise/tests/README.md)。修改 Python 后重启受影响进程；修改静态文件时仍需确认 Release 构建/缓存策略，而不是假定运行目录可被随意写入。

## 8. 安全与提交

不得提交真实密钥、Token、Cookie、数据库、素材、输出、日志、Runtime state 或本机运行时。修改高风险区域前阅读 [CODE_BOUNDARIES.md](CODE_BOUNDARIES.md) 和 [SECURITY_BASELINE.md](SECURITY_BASELINE.md)。

## 9. 文档

完成实现后更新 CURRENT、路线图、对应实施记录和测试说明；不要再创建新的交接包或重复规划文档。
