# 无限画布企业版 · 安全基线

本文档记录企业版部署前的最低安全要求和敏感文件治理方式。它不是一次性完成的安全审计，后续安全增强仍应通过 Issue、独立分支和 PR 继续推进。

---

## 1. 生产部署前必须修改

在局域网或服务器环境暴露服务前，必须复制 `enterprise.env.example` 为 `enterprise.env`，并至少修改：

- `JWT_SECRET`
- `ADMIN_PASSWORD`

建议生成 32 字符以上随机 `JWT_SECRET`，例如：

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

真实 `enterprise.env` 不得提交到 Git。

---

## 2. enterprise.env 配置

示例文件：`enterprise.env.example`

关键配置：

| 配置项 | 说明 |
|--------|------|
| `GATEWAY_PORT` | 企业网关对外端口，默认 `8000` |
| `UPSTREAM_PORT` | 内部上游端口，默认 `3001` |
| `JWT_SECRET` | JWT 签名密钥，生产环境必须改为长随机值 |
| `JWT_EXPIRE_HOURS` | 登录 Token 有效期，默认 `168` 小时 |
| `ADMIN_USERNAME` | 首次启动默认管理员用户名 |
| `ADMIN_PASSWORD` | 首次启动默认管理员密码，生产环境必须修改 |
| `DB_PATH` | 企业层 SQLite 数据库路径 |

可选生产保护：

- `ENTERPRISE_ENV=production`
- `ENTERPRISE_STRICT_SECURITY=1`

启用生产/严格模式后，如果 `JWT_SECRET` 仍是占位值，企业层会拒绝启动。

---

## 3. 默认管理员密码风险

默认 `ADMIN_PASSWORD=admin123` 只适合本地开发验证。任何局域网或服务器部署都必须修改。

企业层启动时如果检测到默认或示例管理员密码，会输出安全警告，但不会阻断本地开发启动。

---

## 4. JWT_SECRET 风险

默认 `JWT_SECRET=PLEASE_CHANGE_THIS_SECRET_KEY` 或示例占位值不能用于生产。使用默认密钥会导致 Cookie Token 可被伪造或跨环境复用。

企业层启动时会检查：

- 是否仍使用默认/示例 JWT_SECRET
- JWT_SECRET 是否少于 32 字符

开发模式下输出警告；生产/严格模式下，默认 JWT_SECRET 会阻断启动。

---

## 5. 不得提交到 Git 的文件

以下文件或目录不得提交到 Git：

- `enterprise.env`
- `API/.env`
- `.env`
- `data/enterprise.db`
- `data/*.db`
- `data/api_providers.json`
- `data/canvases/`
- `data/conversations/`
- `data/update_backups/`
- `assets/input/`
- `assets/output/`
- `assets/library/`
- `python/`
- `python.zip`
- `output/`

---

## 6. 运行时配置处理方式

`data/api_providers.json` 是运行时配置文件，可能包含环境相关服务地址、模型列表或未来新增的敏感字段。它不应继续作为仓库内的真实配置来源。

治理方式：

- 提交 `data/api_providers.example.json` 作为示例配置。
- 将 `data/api_providers.json` 加入 `.gitignore`。
- 使用 `git rm --cached data/api_providers.json` 仅停止 Git 跟踪，不删除本地真实配置文件。
- 本地真实配置继续保留在工作区，供当前部署使用。

---

## 7. 仓库可见性建议

企业版仓库包含企业维护逻辑、部署脚本和安全文档。即使敏感文件已忽略，也建议仓库保持 Private。

如果仓库必须公开，应确保：

- 不包含真实密钥、Token、Cookie、数据库
- 不包含真实业务数据或用户资产
- `enterprise.env` 和运行时配置未被跟踪

---

## 8. 安全检查清单

- [ ] `enterprise.env` 已从 `enterprise.env.example` 复制创建
- [ ] `JWT_SECRET` 已改为 32 字符以上随机值
- [ ] `ADMIN_PASSWORD` 已改为强密码
- [ ] `enterprise.env` 未被 Git 跟踪
- [ ] `API/.env` 未被 Git 跟踪
- [ ] `data/api_providers.json` 未被 Git 跟踪
- [ ] `data/api_providers.example.json` 不含真实密钥
- [ ] `data/enterprise.db` 未被 Git 跟踪
- [ ] 生产环境设置了 `ENTERPRISE_ENV=production` 或 `ENTERPRISE_STRICT_SECURITY=1`
- [ ] 仓库可见性符合企业部署要求
