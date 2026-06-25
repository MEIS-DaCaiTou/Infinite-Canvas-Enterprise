"""
企业网关主程序
- 监听 0.0.0.0:8000（局域网可访问）
- 上游 main.py 运行在 127.0.0.1:3001（仅本机可访问）
- 实现用户登录、鉴权、数据隔离
- 所有上游功能透明代理，无需修改上游代码

启动方式：
    python -m uvicorn enterprise.gateway:app --host 0.0.0.0 --port 8000
"""
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)

# 确保项目根目录在 sys.path 中
ROOT_DIR = Path(__file__).parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from enterprise.config import (
    ENTERPRISE_HIDE_UPSTREAM_AUTHOR,
    ENTERPRISE_REPO_URL,
    ENTERPRISE_STATIC_DIR,
    ENTERPRISE_UPDATE_ENABLED,
    GATEWAY_PORT,
    UPSTREAM_URL,
)
from enterprise.auth import authenticate, create_token, verify_token
from enterprise.db import init_db, log_action
from enterprise.interceptors import (
    is_static_asset,
    is_stream_path,
    post_process,
    pre_process,
    upstream_conversation_user_id,
)
from enterprise.admin_api import router as admin_router
from starlette.middleware.base import BaseHTTPMiddleware

# ── 应用初始化 ────────────────────────────────────────────

app = FastAPI(title="Infinite Canvas Enterprise Gateway", docs_url=None, redoc_url=None)


class AuthStateMiddleware(BaseHTTPMiddleware):
    """在所有路由处理前解析 Token，将用户信息挂载到 request.state.user"""
    async def dispatch(self, request: Request, call_next):
        token = request.cookies.get("enterprise_token")
        if not token:
            auth = request.headers.get("Authorization", "")
            if auth.startswith("Bearer "):
                token = auth[7:]
        request.state.user = verify_token(token) if token else None
        return await call_next(request)


app.add_middleware(AuthStateMiddleware)
app.include_router(admin_router, prefix="/enterprise")

# 共享 httpx 客户端（保持连接池）
_http_client: Optional[httpx.AsyncClient] = None


@app.on_event("startup")
async def startup() -> None:
    global _http_client
    init_db()
    _http_client = httpx.AsyncClient(
        base_url=UPSTREAM_URL,
        timeout=httpx.Timeout(connect=10, read=300, write=300, pool=10),
        follow_redirects=True,
        limits=httpx.Limits(max_connections=200, max_keepalive_connections=50),
    )
    print(f"[企业版] 网关启动，监听 0.0.0.0:{GATEWAY_PORT}")
    print(f"[企业版] 上游服务地址: {UPSTREAM_URL}")


@app.on_event("shutdown")
async def shutdown() -> None:
    if _http_client:
        await _http_client.aclose()


# ── 工具函数 ──────────────────────────────────────────────

def _get_token_from_request(request: Request) -> Optional[str]:
    """优先从 Cookie，其次从 Authorization header 获取 Token"""
    token = request.cookies.get("enterprise_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    return token


def _get_user(request: Request) -> Optional[dict]:
    token = _get_token_from_request(request)
    if not token:
        return None
    return verify_token(token)


def _is_html_accept(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "text/html" in accept


def _build_enterprise_shell_guard(user: dict) -> str:
    """Inject enterprise project-entry and update-permission governance into upstream HTML."""
    payload = {
        "repoUrl": ENTERPRISE_REPO_URL,
        "isAdmin": bool(user.get("is_admin")),
        "updateEnabled": bool(ENTERPRISE_UPDATE_ENABLED and user.get("is_admin")),
        "hideUpstreamAuthor": bool(ENTERPRISE_HIDE_UPSTREAM_AUTHOR or not user.get("is_admin")),
    }
    script = r'''
<script id="__enterprise_shell_guard__">
(function(){
  const cfg = __ENTERPRISE_CONFIG__;
  const normalUser = !cfg.isAdmin;
  let installed = false;

  function byId(id){ return document.getElementById(id); }
  function setText(el, text){
    if(!el) return;
    if(el.textContent !== text) el.textContent = text;
    if(el.hasAttribute('data-i18n')) el.removeAttribute('data-i18n');
  }
  function versionLabel(value){
    const v = String(value || '').trim();
    return v ? (v.startsWith('v') ? v : 'v' + v) : 'v-';
  }
  function setAppInfoRepo(){
    try {
      appInfo = Object.assign({}, appInfo || {}, {
        repo_url: cfg.repoUrl,
        enterprise: {
          repo_url: cfg.repoUrl,
          update_enabled: !!cfg.updateEnabled,
          hide_upstream_author: !!cfg.hideUpstreamAuthor,
          is_admin: !!cfg.isAdmin
        }
      });
    } catch(e) {}
  }
  function setProjectEntry(){
    setAppInfoRepo();
    const btn = byId('github-entry-btn');
    if(!btn) return;
    btn.classList.remove('update-available');
    btn.title = '企业版项目主页';
    btn.setAttribute('aria-label', '企业版项目主页');
    btn.onclick = function(){
      window.open(cfg.repoUrl, '_blank', 'noopener');
      return false;
    };
    setText(btn.querySelector('.side-pill-text'), '企业版项目主页');
    try {
      window.openProjectPage = openProjectPage = function(){
        window.open(cfg.repoUrl, '_blank', 'noopener');
      };
    } catch(e) {
      window.openProjectPage = function(){
        window.open(cfg.repoUrl, '_blank', 'noopener');
      };
    }
  }
  function setVersionBadgeText(version){
    const badge = byId('project-version-badge');
    if(!badge) return;
    const label = versionLabel(version || badge.dataset.currentVersion || badge.textContent.replace(/^v/, ''));
    if(badge.textContent !== label) badge.textContent = label;
    const currentVersion = label.replace(/^v/, '');
    if(badge.dataset.currentVersion !== currentVersion) badge.dataset.currentVersion = currentVersion;
    if(normalUser || !cfg.updateEnabled) {
      badge.classList.remove('checking');
      badge.removeAttribute('onclick');
      badge.removeAttribute('onkeydown');
      badge.setAttribute('role', 'status');
      badge.setAttribute('tabindex', '-1');
      badge.title = '当前企业版版本';
    } else {
      badge.title = '当前企业版版本，管理员可检查企业版受控更新';
    }
  }
  async function enterpriseVersionOnly(){
    try {
      const info = await fetch('/api/app-info', { cache:'no-store' }).then(r => r.ok ? r.json() : {});
      if(info && info.version) setVersionBadgeText(info.version);
      setAppInfoRepo();
    } catch(e) {}
  }
  function blockUpdateAction(){
    return Promise.resolve(false);
  }
  function disableUpdateFunctions(){
    try { window.checkForUpdates = checkForUpdates = enterpriseVersionOnly; } catch(e) { window.checkForUpdates = enterpriseVersionOnly; }
    ['runProjectUpdate','confirmProjectUpdate','rollbackProjectUpdate','runUpdateConnectivityTest','openProjectUpdateModal'].forEach(function(name){
      try { window[name] = eval(name + ' = blockUpdateAction'); } catch(e) { window[name] = blockUpdateAction; }
    });
  }
  function hideUpdateUi(){
    ['update-now-btn','project-update-modal','update-source-list','project-update-summary','project-update-notes'].forEach(function(id){
      const el = byId(id);
      if(el) {
        if(!el.hidden) el.hidden = true;
        if(el.style.display !== 'none') el.style.display = 'none';
      }
    });
    const entry = byId('github-entry-btn');
    if(entry) {
      entry.classList.remove('update-available');
      delete entry.dataset.remoteVersion;
    }
  }
  function relabelAdminUpdate(){
    if(!cfg.isAdmin) return;
    const entry = byId('github-entry-btn');
    const remote = entry?.dataset?.remoteVersion || '';
    if(entry) entry.classList.remove('update-available');
    const btn = byId('update-now-btn');
    const text = byId('update-now-text');
    if(btn) {
      btn.title = remote ? ('企业版受控更新到 ' + versionLabel(remote)) : '企业版受控更新';
      btn.setAttribute('aria-label', btn.title);
    }
    if(text) {
      setText(text, remote ? ('企业版更新到 ' + versionLabel(remote)) : '企业版更新');
    }
    setText(byId('project-update-title'), '企业版受控更新');
    const kicker = document.querySelector('#project-update-modal .studio-modal-kicker');
    setText(kicker, '企业版更新');
    const copy = byId('project-update-copy');
    if(copy) {
      const copyText = '企业版受控更新会同步上游覆盖区域，并由企业版启动脚本维护 3001/8000 双进程模型。更新前请确认已备份并完成兼容性验证。';
      if(copy.textContent !== copyText) copy.textContent = copyText;
    }
  }
  function wrapAdminUpdateText(){
    ['refreshUpdateButtonText','updateProjectUpdateTitle','refreshProjectUpdateModalText','showUpdateNotice'].forEach(function(name){
      try {
        const original = eval(name);
        if(typeof original !== 'function' || original.__enterpriseWrapped) return;
        const wrapped = function(){
          const result = original.apply(this, arguments);
          setTimeout(applyGovernance, 0);
          return result;
        };
        wrapped.__enterpriseWrapped = true;
        window[name] = eval(name + ' = wrapped');
      } catch(e) {}
    });
  }
  function governAuthor(){
    const box = document.querySelector('.author-box');
    if(!box) return;
    if(cfg.hideUpstreamAuthor) {
      if(!box.hidden) box.hidden = true;
      if(box.style.display !== 'none') box.style.display = 'none';
      return;
    }
    box.title = '上游参考';
    setText(box.querySelector('.author-name-lite'), '上游参考');
  }
  function applyGovernance(){
    document.body?.classList.toggle('enterprise-normal-user', normalUser);
    document.body?.classList.toggle('enterprise-hide-upstream-author', !!cfg.hideUpstreamAuthor);
    setProjectEntry();
    governAuthor();
    if(normalUser || !cfg.updateEnabled) {
      hideUpdateUi();
      setVersionBadgeText();
    } else {
      relabelAdminUpdate();
      setVersionBadgeText();
    }
  }
  function installStyles(){
    if(byId('__enterprise_shell_guard_style__')) return;
    const style = document.createElement('style');
    style.id = '__enterprise_shell_guard_style__';
    style.textContent = [
      'body.enterprise-normal-user #update-now-btn,',
      'body.enterprise-normal-user #project-update-modal,',
      'body.enterprise-normal-user #update-source-list{display:none!important;}',
      'body.enterprise-hide-upstream-author .author-box{display:none!important;}',
      'body.enterprise-normal-user #project-version-badge{cursor:default!important;}'
    ].join('\n');
    document.head.appendChild(style);
  }
  function install(){
    if(installed) return;
    installed = true;
    installStyles();
    if(normalUser || !cfg.updateEnabled) disableUpdateFunctions();
    else wrapAdminUpdateText();
    applyGovernance();
    enterpriseVersionOnly();
    const target = document.body || document.documentElement;
    if(target) {
      new MutationObserver(function(){ applyGovernance(); }).observe(target, {
        subtree:true,
        childList:true
      });
    }
    window.setInterval(applyGovernance, 1500);
  }
  if(document.readyState === 'loading') {
    install();
    document.addEventListener('DOMContentLoaded', applyGovernance, { once:true });
  } else {
    install();
  }
})();
</script>
'''
    return script.replace("__ENTERPRISE_CONFIG__", json.dumps(payload, ensure_ascii=False))


# ── 企业专用路由 ──────────────────────────────────────────

@app.get("/enterprise/login", include_in_schema=False)
async def login_page(request: Request):
    """登录页面"""
    # 已登录则跳转首页
    if _get_user(request):
        return RedirectResponse("/")
    login_html = ENTERPRISE_STATIC_DIR / "login.html"
    return HTMLResponse(login_html.read_text(encoding="utf-8"))


@app.post("/enterprise/login", include_in_schema=False)
async def do_login(request: Request):
    """处理登录表单"""
    body = await request.json()
    username = (body.get("username") or "").strip()
    password = (body.get("password") or "").strip()

    if not username or not password:
        return JSONResponse({"error": "用户名和密码不能为空"}, status_code=400)

    user = authenticate(username, password)
    if not user:
        return JSONResponse({"error": "用户名或密码错误"}, status_code=401)

    log_action(user["id"], "login")
    token = create_token(user["id"], user["username"], bool(user["is_admin"]))

    next_url = request.query_params.get("next", "/")
    resp = JSONResponse({
        "success": True,
        "is_admin": bool(user["is_admin"]),
        "next": next_url,
    })
    resp.set_cookie(
        "enterprise_token",
        token,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 7,  # 7天
        path="/",
    )
    return resp


@app.get("/enterprise/logout", include_in_schema=False)
async def logout():
    """注销"""
    resp = RedirectResponse("/enterprise/login")
    resp.delete_cookie("enterprise_token", path="/")
    return resp


@app.get("/enterprise/admin", include_in_schema=False)
async def admin_page(request: Request):
    """管理后台页面"""
    user = _get_user(request)
    if not user:
        return RedirectResponse(f"/enterprise/login?next=/enterprise/admin")
    if not user.get("is_admin"):
        return HTMLResponse("<h2>无权限访问管理后台</h2>", status_code=403)
    admin_html = ENTERPRISE_STATIC_DIR / "admin.html"
    return HTMLResponse(admin_html.read_text(encoding="utf-8"))


@app.get("/enterprise/health", include_in_schema=False)
async def health_check():
    """服务健康检查（无需登录）"""
    import time
    upstream_ok = False
    upstream_latency_ms = None
    try:
        t0 = time.monotonic()
        resp = await _http_client.get("/api/app-info", timeout=5)
        upstream_latency_ms = round((time.monotonic() - t0) * 1000)
        upstream_ok = resp.status_code < 500
    except Exception:
        pass

    status = "ok" if upstream_ok else "degraded"
    return JSONResponse(
        {
            "status": status,
            "gateway": "ok",
            "upstream": "ok" if upstream_ok else "unreachable",
            "upstream_latency_ms": upstream_latency_ms,
        },
        status_code=200 if upstream_ok else 503,
    )


@app.get("/enterprise/profile", include_in_schema=False)
async def profile_page(request: Request):
    """用户个人中心页面（所有已登录用户均可访问）"""
    user = _get_user(request)
    if not user:
        return RedirectResponse(f"/enterprise/login?next=/enterprise/profile")
    profile_html = ENTERPRISE_STATIC_DIR / "profile.html"
    return HTMLResponse(profile_html.read_text(encoding="utf-8"))


@app.get("/enterprise/logs", include_in_schema=False)
async def logs_page(request: Request):
    """操作审计日志页面（仅管理员）"""
    user = _get_user(request)
    if not user:
        return RedirectResponse(f"/enterprise/login?next=/enterprise/logs")
    if not user.get("is_admin"):
        return HTMLResponse("<h2>需要管理员权限</h2>", status_code=403)
    logs_html = ENTERPRISE_STATIC_DIR / "logs.html"
    return HTMLResponse(logs_html.read_text(encoding="utf-8"))


@app.get("/enterprise-static/{filename:path}", include_in_schema=False)
async def enterprise_static(filename: str):
    """服务企业层静态文件（登录页/管理后台的 JS/CSS）"""
    file_path = ENTERPRISE_STATIC_DIR / filename
    if not file_path.exists() or not file_path.is_file():
        return Response(status_code=404)
    return FileResponse(str(file_path))


# ── WebSocket 代理 ────────────────────────────────────────

@app.websocket("/ws/{path:path}")
async def ws_proxy(websocket: WebSocket, path: str):
    """代理 WebSocket 连接到上游（需认证）"""
    token = websocket.cookies.get("enterprise_token")
    user = verify_token(token) if token else None
    if not user:
        await websocket.close(code=1008)
        return

    await websocket.accept()

    upstream_ws_url = UPSTREAM_URL.replace("http://", "ws://") + f"/ws/{path}"

    try:
        import websockets as ws_lib
        async with ws_lib.connect(upstream_ws_url) as upstream:
            async def recv_from_upstream():
                try:
                    async for msg in upstream:
                        await websocket.send_text(msg if isinstance(msg, str) else msg.decode())
                except Exception:
                    pass

            async def recv_from_client():
                try:
                    async for msg in websocket.iter_text():
                        await upstream.send(msg)
                except WebSocketDisconnect:
                    pass
                except Exception:
                    pass

            await asyncio.gather(recv_from_upstream(), recv_from_client())
    except ImportError:
        # websockets 未安装，降级处理：直接关闭（不影响主功能）
        await websocket.close(code=1011)
    except Exception:
        try:
            await websocket.close(code=1011)
        except Exception:
            pass


# ── HTTP 反向代理（核心路由） ─────────────────────────────

# 不需要鉴权的路径前缀
_PUBLIC_PATH_PREFIXES = (
    "enterprise/login",
    "enterprise-static/",
    "enterprise/logout",
)

# 不需要过滤的静态资源路径前缀
_UPSTREAM_STATIC_PREFIXES = (
    "static/",
    "vendor/",
    "assets/images/",
    "favicon",
)


@app.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
    include_in_schema=False,
)
async def reverse_proxy(path: str, request: Request):
    # ── 1. 企业专用路径已由上方路由处理，此处跳过 ──────────
    if path.startswith("enterprise"):
        return Response(status_code=404)

    # ── 2. 纯静态资源：不做鉴权直接透传 ──────────────────
    if not is_stream_path(path) and (
        any(path.startswith(p) for p in _UPSTREAM_STATIC_PREFIXES) or is_static_asset(path)
    ):
        return await _forward(path, request, user=None, skip_intercept=True)

    # ── 3. 所有其他请求：需要登录 ─────────────────────────
    user = getattr(request.state, "user", None)
    if not user:
        if _is_html_accept(request) or path in ("", "index.html"):
            return RedirectResponse(f"/enterprise/login?next=/{path}")
        return JSONResponse({"error": "未授权，请先登录", "code": 401}, status_code=401)

    body = await request.body()

    # ── 4. 前置拦截（访问控制） ───────────────────────────
    err = await pre_process(
        path,
        request.method,
        user,
        query_params=request.query_params,
        body=body,
    )
    if err:
        return err

    # ── 5. 流式路径：直接透传，不缓冲 ────────────────────
    if is_stream_path(path):
        return await _forward(path, request, user=user, skip_intercept=True, body=body)

    # ── 6. 普通请求：代理 + 后置过滤 ─────────────────────
    return await _forward(path, request, user=user, skip_intercept=False, body=body)


def _build_user_bar(user: dict) -> str:
    """生成注入到 HTML 页面的悬浮用户信息栏 HTML"""
    from html import escape
    display = escape(user.get("display_name") or user.get("username", ""))
    admin_btn = ""
    if user.get("is_admin"):
        admin_btn = (
            '<a href="/enterprise/admin" '
            'style="padding:4px 10px;border-radius:8px;border:1px solid var(--line,#e8ecf2);'
            'background:transparent;color:var(--muted,#64748b);text-decoration:none;'
            'font-size:12px;font-weight:600;white-space:nowrap;">管理后台</a>'
        )
    enterprise_shell_guard = _build_enterprise_shell_guard(user)
    return (
        '<div id="__ent_bar__" '
        'style="position:fixed;bottom:20px;right:20px;z-index:99999;'
        'display:flex;align-items:center;gap:8px;'
        'background:var(--panel,#fff);border:1px solid var(--line,#e8ecf2);'
        'border-radius:24px;padding:5px 10px 5px 14px;'
        'box-shadow:0 4px 20px rgba(0,0,0,.12);'
        'font-family:Inter,-apple-system,BlinkMacSystemFont,sans-serif;'
        'font-size:13px;color:var(--text,#0f172a);'
        'backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);">'
        f'<span style="font-weight:600;max-width:120px;overflow:hidden;'
        f'text-overflow:ellipsis;white-space:nowrap;" title="{display}">{display}</span>'
        f'{admin_btn}'
        '<a href="/enterprise/logout" '
        'style="padding:4px 10px;border-radius:20px;border:none;'
        'background:var(--text,#0f172a);color:var(--bg,#f7f8fa);text-decoration:none;'
        'font-size:12px;font-weight:600;white-space:nowrap;cursor:pointer;">退出</a>'
        '</div>'
        f'{enterprise_shell_guard}'
    )


async def _forward(
    path: str,
    request: Request,
    user: Optional[dict],
    skip_intercept: bool = False,
    body: Optional[bytes] = None,
) -> Response:
    """向上游转发请求，可选进行后置过滤"""
    if body is None:
        body = await request.body()

    # 企业版由启动脚本管理 3001/8000 双服务。上游自带更新接口的
    # auto_restart 会启动普通版 3000，因此经企业网关触发时强制改为手动重启。
    if (
        user
        and path == "api/update-from-github"
        and request.method.upper() == "POST"
        and body
    ):
        try:
            payload = json.loads(body.decode("utf-8"))
            if isinstance(payload, dict) and payload.get("auto_restart"):
                payload["auto_restart"] = False
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        except Exception:
            pass

    # 构建转发 headers（移除 host、cookie 等，注入用户信息）
    exclude_headers = {"host", "content-length", "transfer-encoding"}
    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in exclude_headers
    }
    # 企业用户信息注入（上游可选使用，不影响上游逻辑）
    if user:
        from urllib.parse import quote
        upstream_user_id = upstream_conversation_user_id(path, body, user) or user["user_id"]
        headers["x-enterprise-user-id"] = user["user_id"]
        # URL 编码用户名，防止中文等非 ASCII 字符导致 HTTP 头编码失败
        headers["x-enterprise-username"] = quote(user["username"], safe="")
        headers["x-enterprise-is-admin"] = "true" if user.get("is_admin") else "false"
        # 注入上游已支持的 x-user-id，使对话数据在上游层原生按用户隔离
        headers["x-user-id"] = upstream_user_id
    # 移除企业 Cookie，避免上游看到
    if "cookie" in headers:
        cookies_str = headers["cookie"]
        filtered_cookies = "; ".join(
            c for c in cookies_str.split("; ")
            if not c.strip().startswith("enterprise_token=")
        )
        if filtered_cookies:
            headers["cookie"] = filtered_cookies
        else:
            del headers["cookie"]

    # 构建上游 URL（保留 query string）
    qs = str(request.url.query)
    upstream_path = f"/{path}"
    if qs:
        upstream_path += f"?{qs}"

    try:
        upstream_resp = await _http_client.request(
            method=request.method,
            url=upstream_path,
            headers=headers,
            content=body,
        )
    except httpx.ConnectError:
        return JSONResponse(
            {"error": "上游服务未启动，请先运行主程序", "code": 503},
            status_code=503,
        )
    except Exception as e:
        return JSONResponse({"error": str(e), "code": 502}, status_code=502)

    # 构建响应 headers（过滤掉逐字节传输头）
    skip_resp_headers = {"transfer-encoding", "connection", "keep-alive"}
    resp_headers = {
        k: v for k, v in upstream_resp.headers.items()
        if k.lower() not in skip_resp_headers
    }

    # ── 后置过滤 ──────────────────────────────────────────
    if not skip_intercept and user:
        content_type = upstream_resp.headers.get("content-type", "")
        new_body, header_overrides = await post_process(
            path=path,
            method=request.method,
            status_code=upstream_resp.status_code,
            response_body=upstream_resp.content,
            content_type=content_type,
            user=user,
            request_body=body,
        )
        # 在 HTML 响应中注入用户信息栏
        if user and "text/html" in content_type:
            bar_html = _build_user_bar(user).encode("utf-8")
            new_body = new_body.replace(b"</body>", bar_html + b"\n</body>", 1)
            resp_headers.pop("content-length", None)
            header_overrides.pop("content-length", None)
        resp_headers.update(header_overrides)
        return Response(
            content=new_body,
            status_code=upstream_resp.status_code,
            headers=resp_headers,
            media_type=content_type,
        )

    # ── 流式透传（静态资源/下载） ──────────────────────────
    raw_ct = upstream_resp.headers.get("content-type", "")
    raw_content = upstream_resp.content
    # 对非静态资源的 HTML 也注入用户信息栏
    if user and "text/html" in raw_ct:
        bar_html = _build_user_bar(user).encode("utf-8")
        raw_content = raw_content.replace(b"</body>", bar_html + b"\n</body>", 1)
        resp_headers.pop("content-length", None)
    return Response(
        content=raw_content,
        status_code=upstream_resp.status_code,
        headers=resp_headers,
        media_type=raw_ct,
    )


# ── 独立启动入口 ──────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=GATEWAY_PORT)
