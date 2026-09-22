# SEC-P0 浏览器与代理边界实施记录

日期：2026-09-21

范围：Issue #111
状态：[PR #119](https://github.com/MEIS-DaCaiTou/Infinite-Canvas-Enterprise/pull/119) 等待审查与合并；不是正式 Release 或生产批准

## 1. 修复不变量

1. 未在 `main.py` 明确注册的方法/路径不得穿过 Gateway catch-all。
2. 公共静态资源只能来自固定命名空间，不能凭扩展名绕过认证。
3. Cookie 状态变更必须同源；Bearer CLI 保持非 Cookie 调用边界。
4. WebSocket 只允许同源 `/ws/stats`、客户端 `ping` 和显式已知服务端事件。
5. 登录失败必须有界限流，跳转必须留在站内，静态文件必须留在固定根目录。

## 2. 实现摘要

- 新增 `enterprise/route_policy.py`，登记上游精确路由、模板路由、公共静态目录、受保护资源目录和 WebSocket 路径。
- Gateway 在转发前执行方法/路径判定；未知 API 返回 404，不再按文件后缀放行。
- Cookie 写请求执行 `Origin` 与请求 `scheme + Host` 的精确比较；不采信任意客户端提供的 `X-Forwarded-*`。
- 登录对 JSON 形状、来源、失败速率和 `next` 执行校验；HTTPS 响应设置 `Secure` Cookie。
- 登录限流在密码校验前原子检查并预留，避免并发请求同时越过阈值；成功只释放本次预留，失败继续计数。
- 登出改为 POST + 303，管理后台、个人中心与注入导航同步使用表单，避免将 POST 重放到登录接口。
- 企业静态入口使用解析后的根目录 containment；目录逃逸返回 404。
- WebSocket 对未知路径、跨源连接、未知客户端消息和未知/非 JSON 服务端事件关闭或拒绝；任一转发方向结束后取消并等待另一方向，避免连接/任务泄漏。

## 3. 测试边界

聚焦测试使用 ASGI in-process、临时目录和临时数据库，不访问客户数据、生产服务或外部 Provider。完整套件和 GitHub Actions 的结果应记录在实施 PR；测试通过不等于发布、签名安装器或客户部署批准。

本地验证：

- 聚焦安全/权限回归：`37 passed, 4 warnings`；独立只读审查者复跑结果一致。
- CPython 3.11 完整企业套件：`947 passed, 10 skipped, 8 warnings in 460.77s`。
- 警告为既有 FastAPI `on_event` 弃用提示与测试夹具 JWT 短密钥提示；无失败。

## 4. 部署注意

`Secure` 依据 ASGI 请求 scheme 设置。若未来在受信反向代理后终止 TLS，必须显式配置可信代理链，使应用接收到正确 scheme；不得为了兼容代理而无条件信任来自互联网客户端的转发头。
