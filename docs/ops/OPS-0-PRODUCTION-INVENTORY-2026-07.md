# OPS-0：生产环境只读盘点报告（2026-07）

更新时间：2026-07-09

## 1. 任务边界

OPS-0 是生产环境只读盘点。

本阶段明确不做：

- 不停机。
- 不升级。
- 不迁移数据库。
- 不修改生产数据。
- 不删除任何文件。
- 不执行 `git pull` / `checkout` / `reset`。
- 不让 Codex 直接连接生产主机。

生产命令由项目负责人在生产主机人工执行，输出脱敏后回传主对话复核。本文只记录脱敏后的盘点结论，供后续 OPS-1、OPS-2、生产升级、备份恢复、数据库迁移和数据治理使用。

## 2. 生产主机与开发环境隔离声明

- 生产主机和开发电脑 / Codex 工作环境不是同一台设备。
- 生产主机和开发电脑 / Codex 不在同一个局域网。
- 后续生产升级应采用离线发布包、人工转移、生产本机执行、日志回传复核的模式。
- Codex 只能在开发仓库中生成文档、脚本和发布包结构，不能直接操作生产主机。

## 3. 当前生产路径

```text
C:\Infinite-Canvas-Enterprise项目\Infinite-Canvas-Enterprise-2026-06-30\26-5-27-无限画布\26-5-27-无限画布
```

## 4. 当前生产版本

生产环境：

- 生产分支：`task/3g-4a-upload-isolation-impl`
- 生产 commit：`deb22620f792e68d8c2ccd86218510420733be97`
- 生产 VERSION：`2026.06.23`

当前开发仓库：

- main / origin/main：`d2351a5854fa96589bb89503747a7e2e61feb80a`
- DOC-1：PR #63 已合并。

结论：

- 当前生产版本明显落后于当前 main。
- 不允许直接在生产目录执行 `git pull` 或 `checkout main`。
- 不允许以开发仓库当前文件直接覆盖生产目录。

## 5. 当前启动方式

- 系统：Windows
- 启动方式：bat
- 启动脚本：`启动企业版.bat`
- 启动入口：`enterprise\launcher.py`
- Python：优先使用项目内 `python\python.exe`，不存在时回退 `python`

运行进程摘要：

- `8000`：`enterprise.gateway:app`，监听 `0.0.0.0:8000`
- `3001`：`main:app`，监听 `127.0.0.1:3001`

说明：

- `8000` 是企业网关对外入口。
- `3001` 是上游主应用，仅本机监听。
- 该监听方式符合当前 enterprise gateway 架构预期。

## 6. 当前访问链路

- 局域网访问地址：`http://11.0.0.37:8000/`
- 公网域名：暂未最终确定。
- 内网穿透：Windows 生产机 `frpc` -> 云服务器 `frps`。
- 反代：云服务器 1Panel 网站反代。
- HTTPS：有。
- 公网 WebSocket：未确认。

说明：

- 后续公网发布前必须验证 WebSocket upgrade 是否穿透 `frpc` / `frps` / 1Panel 反代链路。
- 不能仅以本机 `127.0.0.1` 或局域网访问成功作为公网生产验收结论。

## 7. 当前运行时数据规模

脱敏摘要：

| 路径 / 文件 | 数量 / 大小 |
| --- | ---: |
| `data` | 1702 个文件，约 59,004,653 字节，约 0.055 GB |
| `assets` | 992 个文件，约 3,536,142,968 字节，约 3.293 GB |
| `output` | 16 个文件，约 69,152 字节 |
| `history.json` | 约 1,072,734 字节，约 1.02 MB |
| `enterprise.db` | 573,440 字节 |
| `enterprise.env` | 存在，约 1,527 字节 |
| `API/.env` | 存在，约 384 字节 |

`data` 顶层重要项目：

- `canvases/`
- `conversations/`
- `media_previews/`
- `update_backups/`
- `update_staging/`
- `api_providers.json`
- `asset_library.json`
- `enterprise.db`
- `projects.json`
- `prompt_libraries.json`

## 8. env 配置项，仅记录 key 名称

本文只记录 key 名称，不记录任何值。

`enterprise.env` keys：

- `GATEWAY_PORT`
- `UPSTREAM_PORT`
- `JWT_SECRET`
- `JWT_EXPIRE_HOURS`
- `ADMIN_USERNAME`
- `ADMIN_PASSWORD`
- `DB_PATH`

`API/.env` keys：

- `MODELSCOPE_CHAT_MODELS`
- `API_PROVIDER_CUSTOM_API_KEY`
- `API_PROVIDER_CUSTOM_API_2_KEY`
- `API_PROVIDER_AGNES_AI_KEY`
- `COMFYUI_INSTANCES`

本文档不得记录任何 env value、API Key、JWT secret 值、管理员密码、Token、Cookie、FRP 凭据或云服务器登录信息。

## 9. SQLite 只读盘点摘要

- 数据库：`data/enterprise.db`
- SQLite version：`3.40.1`

表数量摘要：

| 表 | 数量 |
| --- | ---: |
| `users` | 57 |
| `usage_logs` | 645 |
| `user_project_map` | 8 |
| `user_canvas_map` | 82 |
| `user_conversation_map` | 25 |
| `user_history_map` | 516 |
| `user_resource_map` | 964 |
| `user_canvas_task_map` | 599 |

当前表：

- `sqlite_sequence`
- `usage_logs`
- `user_canvas_map`
- `user_canvas_task_map`
- `user_conversation_map`
- `user_history_map`
- `user_project_map`
- `user_resource_map`
- `users`

表用途：

- `users`：企业用户。
- `usage_logs`：审计日志。
- `user_project_map`：项目 owner 映射。
- `user_canvas_map`：画布 owner 映射。
- `user_conversation_map`：对话 owner 映射。
- `user_history_map`：历史记录 owner 映射。
- `user_resource_map`：资源 URL owner 映射。
- `user_canvas_task_map`：画布任务 owner 映射。

本文不记录任何密码哈希值。

## 10. JSON / 文件系统摘要

`history.json`：

- 616 条。
- type 分布：
  - `online`：589
  - `workflow-custom`：25
  - `workflow-test`：2

目录摘要：

| 路径 | 摘要 |
| --- | ---: |
| `data/canvases` | 80 个 json 文件 |
| `data/conversations` | 22 个 json 文件 |
| `data/media_previews` | 1345 个 webp 文件，约 27,917,784 字节 |
| `data/update_backups` | 249 个文件，约 28,318,260 字节 |
| `data/update_staging` | 0 个文件 |
| `assets` | 992 个文件，约 3,536,142,968 字节 |
| `assets/uploads` | 0 个文件 |
| `assets/output` | 654 个图片文件，约 2,132,395,748 字节 |
| `output` | 16 个文件，约 69,152 字节 |

## 11. 已发现的数据一致性风险

以下风险必须作为 OPS-1 / OPS-2 / 数据治理阶段输入，但当前不得判定为数据损坏：

- `history.json` 有 616 条，而 `user_history_map` 有 516 条，差约 100 条。
- `data/canvases` 有 80 个 json 文件，而 `user_canvas_map` 有 82 条。
- `data/conversations` 有 22 个 json 文件，而 `user_conversation_map` 有 25 条。
- `user_resource_map` 有 964 条，而 `assets` 总文件为 992 个；由于 resource URL、历史输出、画布引用、实际文件并非一一对应，不能直接判定异常，但后续必须做引用完整性检查。
- `data/update_backups` 位于 `data` 目录内，后续备份策略应明确是否保留、迁移或归档，但当前不得删除。
- 公网 WebSocket 支持状态未确认。

风险结论：

这些现象应作为 OPS-1 / OPS-2 / 数据治理阶段的兼容性风险输入，不得在 OPS-0A 中执行任何清理、归属修复或文件删除。

## 12. 当前生产升级结论

- 当前生产环境已有真实用户和真实业务数据。
- 当前没有每日备份。
- 不允许直接在生产目录执行 `git pull`、`checkout main`、`reset --hard` 或覆盖文件升级。
- 不允许直接替换 `data`、`assets`、`output`、`history.json`、`enterprise.db`、`enterprise.env`、`API/.env`。

后续升级必须走：

1. 完整备份。
2. 离线发布包。
3. 生产数据副本演练。
4. 数据库迁移 dry-run。
5. 文件引用完整性检查。
6. 凌晨维护窗口切换。
7. 回滚方案。
8. 登录 / 局域网 / 公网 / WebSocket 验收。

## 13. 后续任务建议

下一阶段：

- OPS-1：生产备份、离线发布包、升级演练、回滚、数据库迁移与数据治理方案设计。

后续可再拆：

- OPS-2：生产只读盘点脚本与备份脚本。
- OPS-3：离线 release 包生成机制。
- OPS-4：生产升级演练。
- 3G-8：浏览器级自动化回归，暂后置，不取消。
