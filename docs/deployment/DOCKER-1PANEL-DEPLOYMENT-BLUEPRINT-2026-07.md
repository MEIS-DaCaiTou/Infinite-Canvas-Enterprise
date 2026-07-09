# Docker / 1Panel 部署蓝图（2026-07）

## 1. 当前结论

当前项目还不是 Docker-ready。

当前架构具备较好的 Docker 化基础，但不应宣称已经支持一键 Docker 部署。后续通过 Dockerfile、docker-compose、entrypoint、volume、日志、健康检查和 1Panel 反代文档后，可以达到一键部署目标。

OPS-1 / ARCH-1 阶段只做设计，不新增 Dockerfile，不新增 docker-compose.yml，不写容器启动脚本。

## 2. 当前适配基础

当前适合容器化的基础：

- `8000 / 3001` 双进程模型适合在容器内由 entrypoint 或进程管理器拉起。
- `enterprise.env` 配置适合容器环境变量化。
- `data/`、`assets/`、`output/`、`history.json`、`logs/` 适合 volume 化。
- gateway 隔离上游，适合前置反代。
- 3001 当前仅本机访问，天然适合作为容器内部端口。
- 8000 当前是企业入口，适合作为容器对外端口。

## 3. 当前适配障碍

当前障碍：

- 当前 launcher 偏 Windows bat / bundled python。
- Docker 需要 Linux/container entrypoint。
- 当前无 Dockerfile。
- 当前无 docker-compose.yml。
- 当前无正式 volume 映射文档。
- 当前无容器健康检查接口规范。
- 当前无容器日志规范。
- 当前 SQLite 不适合长期多服务器。
- 当前 `assets/`、`output/` 不适合长期只依赖容器本地盘。

因此 Docker 化应进入 OPS-D 主线，不能在普通功能 PR 中顺手完成。

## 4. 推荐 Docker 阶段

### D-1：单容器

目标：

- app container。
- 8000 exposed。
- 3001 internal。
- SQLite volume。
- `data/`、`assets/`、`output/`、`history.json`、`logs/` volume。

适合小规模企业单机部署和从 Windows 生产迁移到 Linux / 1Panel 的第一步。

### D-2：Docker Compose

目标：

- app。
- postgres。
- redis 可选。
- minio 可选。
- 1Panel / OpenResty / Nginx 反代。

Compose 阶段应建立 healthcheck、volume、日志、备份和网络隔离规范。

### D-3：多服务器

目标：

- 多 app 实例。
- PostgreSQL。
- Redis。
- 对象存储 / NAS。
- 集中日志。
- 统一反代。

多服务器部署必须先解决会话、WebSocket、任务队列、文件共享、数据库事务和日志集中化。

## 5. 推荐 volume 映射

建议长期 volume 映射：

| 容器路径 | 用途 |
| --- | --- |
| `/app/data` | 上游和企业业务数据。 |
| `/app/assets` | 上传、素材和生成资源。 |
| `/app/output` | 上游输出目录。 |
| `/app/history.json` | 历史记录文件。 |
| `/app/logs` | 结构化日志。 |
| `/app/enterprise.env` | 企业配置。 |
| `/app/API/.env` | provider / ComfyUI 等上游配置。 |

敏感 env 文件不得提交 Git。发布包和镜像也不得内置生产 env 文件。

## 6. 1Panel 适配设计

1Panel 适配需要覆盖：

- 1Panel 网站反代。
- HTTPS。
- WebSocket upgrade。
- 大文件上传。
- 长任务超时。
- 容器日志查看。
- 数据库管理。
- 计划任务备份。
- 证书续期。
- 文件管理。

1Panel 不是单纯反代配置。它还会影响上传大小、长连接超时、证书、备份路径、容器日志查看和生产维护流程。

## 7. WebSocket / 反代验收

Docker / 1Panel 上线验收至少覆盖：

- 页面访问。
- 登录。
- WebSocket。
- 长连接。
- 上传。
- 图片访问。
- API 超时。
- HTTPS。
- 公网域名。
- 局域网入口。

不能只以本机容器启动成功作为生产验收结论。

## 8. 与 OPS 的关系

OPS plan / manifest / backup / logs 应平台无关。

当前 PowerShell 是 Windows 生产现状下的执行器。后续 Linux runner / Docker runner 应复用同样的 manifest schema。

OPS 设计不得只绑定 Windows 绝对路径。长期应抽象：

- app root。
- data root。
- assets root。
- output root。
- log root。
- env file path。
- release root。
- backup root。

这样同一套 OPS plan 可以被 Windows、Linux 裸机、Docker 和 1Panel 复用。
