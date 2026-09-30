"""
AutoScriptor WebUI Server (FastAPI + WebSocket)
================================================
REST API endpoints under /api/*, WebSocket at /ws/logs,
static files served from ./static and ./vendor.

This module is the application shell: logger wiring, security middleware,
static mounts, process lifecycle, and the few endpoints that belong to the
process itself (login, log stream, favicons). Everything else lives in
``backend/webui/routes/`` split by domain, and reaches the orchestrator through
``api_context``.
"""

from __future__ import annotations

import asyncio
import os
import webbrowser
from http.cookies import CookieError, SimpleCookie

from AutoScriptor.logging.logger import logger

from AutoScriptor.utils.app_config import cfg
from backend.core.banner import _print_banner
from backend.webui.api_context import (
    mark_config_changed,
    persistence_diagnostics,
    persistence_error_message,
)
from backend.webui.api_response import api_error
from backend.webui.port import (
    DEFAULT_PORT,
    PORT_ENV,
    port_is_free,
    read_configured_port,
    resolve_listening_port,
)
from backend.webui.log_stream import (
    apply_log_level,
    broadcast_loop,
    ws_clients,
)
from orchestrator import orchestrator

# FastAPI Form/UploadFile 运行时依赖。Starlette 优先使用 python-multipart
# 提供的 `python_multipart`；显式导入它（而不是旧的 `multipart` shim），
# 保证表单解析依赖在导入期就暴露缺失，而不是等到第一个上传请求。
import python_multipart  # noqa: F401

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# ── 日志 ──
# 文件与浏览器两个 sink、级别策略、广播循环都在 backend/webui/log_stream.py。
# 这里只挂载 WebSocket 端点。

from AutoScriptor.utils.paths import get_app_root

# ── 全局状态 ──



# ── 安全模块 ──

from backend.webui.security import (
    clear_credential_unlock_cookie,
    credential_unlock_from_request,
    is_rate_limited,
    record_login_failure,
    hash_deploy_password as _hash_deploy_password,
    verify_deploy_password as _verify_deploy_password,
    create_session as _create_session,
    validate_session as _validate_session,
    login_limiter as _login_limiter,
    SESSION_TTL as _SESSION_TTL,
    revoke_credential_unlock as _revoke_credential_unlock,
)


VENDOR_DIR = str(get_app_root() / "backend" / "webui" / "vendor")
STATIC_DIR = str(get_app_root() / "backend" / "webui" / "static")
ELECTRON_ICON_PATH = str(get_app_root() / "frontend" / "electron" / "icon.png")


# ── 辅助函数 ──


orchestrator.configure_lifecycle(
    mark_config_changed=mark_config_changed,
    apply_log_level=apply_log_level,
)

# ── FastAPI 应用 ──

app = FastAPI(title="AutoScriptor WebUI")


def _scope_header(scope: dict, name: bytes) -> str:
    for key, value in scope.get("headers", []) or []:
        if key.lower() == name:
            return value.decode("latin-1")
    return ""


def _scope_cookie(scope: dict, name: str) -> str | None:
    raw = _scope_header(scope, b"cookie")
    if not raw:
        return None
    try:
        cookie = SimpleCookie()
        cookie.load(raw)
        morsel = cookie.get(name)
        return morsel.value if morsel is not None else None
    except CookieError:
        return None


class _AuthAndApiErrorMiddleware:
    """ASGI middleware that avoids Starlette's request-body replay layer."""

    def __init__(self, inner_app):
        self.inner_app = inner_app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.inner_app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "")
        try:
            password = cfg._config.get("deploy", {}).get("password")
            if password and path.startswith("/api/"):
                exempt = ("/api/auth", "/api/deploy")
                if not any(path.startswith(p) for p in exempt):
                    token = _scope_cookie(scope, "auth_token") or _scope_header(scope, b"x-auth-token")
                    if not _validate_session(token):
                        response = JSONResponse(status_code=401, content={"error": "unauthorized"})
                        await response(scope, receive, send)
                        return
            await self.inner_app(scope, receive, send)
        except BaseException as e:
            if isinstance(e, (KeyboardInterrupt, SystemExit)):
                raise
            logger.exception("api middleware error: %s %s", method, path)
            if path.startswith("/api/"):
                response = api_error(
                    500,
                    persistence_error_message(f"{path} 未捕获异常", e),
                    code="unhandled_api_error",
                    diagnostics=persistence_diagnostics(),
                )
                await response(scope, receive, send)
                return
            raise


@app.post("/api/auth")
async def auth_api(request: Request):
    client_ip = request.client.host if request.client else "unknown"
    if is_rate_limited(client_ip):
        return JSONResponse(status_code=429, content={"error": "登录尝试过多，请5分钟后再试"})

    data = await request.json()
    stored = cfg._config.get("deploy", {}).get("password")
    raw = data.get("password", "")

    if _verify_deploy_password(raw, stored):
        if stored and not stored.startswith("pbkdf2$"):
            cfg._config.setdefault("deploy", {})["password"] = _hash_deploy_password(raw)
            cfg.save_config()
            mark_config_changed("upgrade deploy password hash")
        old_cred = credential_unlock_from_request(request)
        _revoke_credential_unlock(old_cred)
        session_token = _create_session()
        resp = JSONResponse(content={"status": "ok"})
        resp.set_cookie(
            "auth_token", session_token,
            httponly=True, samesite="strict", max_age=_SESSION_TTL,
        )
        clear_credential_unlock_cookie(resp)
        return resp

    record_login_failure(client_ip)
    remaining = _login_limiter.remaining_before_lockout(client_ip)
    return JSONResponse(status_code=401, content={
        "error": f"密码错误（剩余 {max(remaining, 0)} 次尝试）"
    })


# 编辑器 API 路由
from backend.webui.routes.editor import (
    configure_editor_custom_task_save_controls,
    configure_editor_execution_controls,
    editor_execution_status,
    router as editor_router,
)
orchestrator.execution.set_external_status_getter("editor", editor_execution_status)
configure_editor_execution_controls(
    request_cancel=orchestrator.task_manager.request_cancel,
    reset_cancel=orchestrator.task_manager.reset_cancel,
    runtime_busy=orchestrator.execution.is_busy,
    acquire_execution=lambda: orchestrator.scheduler.acquire_execution("editor", blocking=False),
    release_execution=lambda: orchestrator.scheduler.release_execution("editor"),
)
configure_editor_custom_task_save_controls(
    reload_custom_tasks=lambda: orchestrator.tasks.reload_all(reason="save editor custom task"),
)
app.include_router(editor_router)

# ── 领域路由 ──
# server.py 只负责应用壳（日志、安全中间件、静态挂载、生命周期）与需要
# 直接操作进程的少数端点；其余按域拆分，各自只依赖 api_context / security。
from backend.webui.routes import accounts as accounts_routes
from backend.webui.routes import news as news_routes
from backend.webui.routes import notifications as notifications_routes
from backend.webui.routes import ops as ops_routes
from backend.webui.routes import overview as overview_routes
from backend.webui.routes import tasks as tasks_routes

for domain_router in (
    tasks_routes.router,
    overview_routes.router,
    accounts_routes.router,
    news_routes.router,
    ops_routes.router,
    notifications_routes.router,
):
    app.include_router(domain_router)

class _StaticCacheHeadersMiddleware:
    def __init__(self, inner_app):
        self.inner_app = inner_app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.inner_app(scope, receive, send)
            return

        rpath = scope.get("path", "")

        async def send_with_cache(message):
            if message.get("type") == "http.response.start":
                cache_control = None
                if rpath.startswith("/vendor/") or rpath.startswith("/fonts/"):
                    cache_control = b"public, max-age=86400"
                elif rpath.startswith("/static/") and rpath.endswith((".js", ".css")):
                    cache_control = b"no-cache"
                if cache_control is not None:
                    headers = [
                        (key, value)
                        for key, value in message.get("headers", [])
                        if key.lower() != b"cache-control"
                    ]
                    headers.append((b"cache-control", cache_control))
                    message = dict(message)
                    message["headers"] = headers
            await send(message)

        await self.inner_app(scope, receive, send_with_cache)


app.add_middleware(_StaticCacheHeadersMiddleware)
app.add_middleware(_AuthAndApiErrorMiddleware)

# 静态文件挂载
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/vendor", StaticFiles(directory=VENDOR_DIR), name="vendor")
app.mount("/fonts", StaticFiles(directory=os.path.join(VENDOR_DIR, 'fonts')), name="fonts")


@app.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    password = cfg._config.get("deploy", {}).get("password")
    if password:
        token = websocket.cookies.get("auth_token")
        if not _validate_session(token):
            await websocket.close(code=4001, reason="unauthorized")
            return
    await websocket.accept()
    ws_clients.add(websocket)
    try:
        await websocket.send_json({"data": "... Connection established ..."})
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        ws_clients.discard(websocket)


_init_done = False
_init_error = ""


@app.on_event("startup")
async def _on_startup():
    asyncio.create_task(broadcast_loop())
    asyncio.create_task(_deferred_heavy_init())


async def _deferred_heavy_init():
    """在 uvicorn 已开始监听后，后台执行任务注册等轻量初始化。"""
    global _init_done, _init_error
    loop = asyncio.get_event_loop()
    _init_done = False
    _init_error = ""
    try:
        logger.info("后台初始化：运行时/任务加载（不启动设备）...")
        await loop.run_in_executor(None, _do_heavy_init)
        if cfg.get("scheduler.auto_start", False):
            if cfg.has_decrypted_credentials():
                orchestrator.scheduler.activate()
                orchestrator.scheduler.wake()
                logger.info("Scheduler auto-started from config")
            else:
                logger.info("Scheduler auto-start is enabled but account is not verified yet")
        _init_done = True
        logger.info("后台初始化完成")
    except Exception as e:
        _init_error = str(e)
        logger.exception("后台初始化失败")


def _do_heavy_init():
    """同步版初始化：只做不触碰模拟器的准备工作。"""
    from AutoScriptor.core.runtime_context import runtime_ctx

    runtime_ctx.init_bg()
    orchestrator.task_manager.reload_tasks()


@app.get("/api/init-status")
async def init_status():
    payload = {"ready": _init_done}
    if _init_error:
        payload["error"] = _init_error
    return payload


@app.on_event("shutdown")
async def _on_shutdown():
    shutdown_webui()


# ── 首页 ──

@app.get("/")
async def index():
    return FileResponse(os.path.join(STATIC_DIR, 'index.html'))


@app.get("/favicon.ico")
async def favicon():
    path = os.path.join(STATIC_DIR, 'favicon.ico')
    if os.path.exists(path):
        return FileResponse(path)
    if os.path.exists(ELECTRON_ICON_PATH):
        return FileResponse(ELECTRON_ICON_PATH, media_type="image/png")
    return JSONResponse(status_code=404, content={})


@app.get("/favicon.png")
async def favicon_png():
    if os.path.exists(ELECTRON_ICON_PATH):
        return FileResponse(ELECTRON_ICON_PATH, media_type="image/png")
    return JSONResponse(status_code=404, content={})


# ── API 路由 ──


# ── 通知 API ──


# ── 更新 API ──


# ── 多账号 API ──


# ── 角色管理 API ──


# ── 调度队列 API ──


# ── 配置导入导出 API ──


# ── 错误归档 API ──


# ── 部署配置 API ──


# ── 入口 ──



_server = None
_shutdown_done = False


def run_webui(restart_event=None):
    """阻塞式启动 uvicorn 服务。

    Args:
        restart_event: multiprocessing.Event，更新完成后 set 以通知父进程重启。
    """
    global _server
    import uvicorn

    electron_mode = bool(
        os.environ.get("AUTOSCRIPTOR_ELECTRON")
        or os.environ.get("AUTOSCRIPTOR_ELECTRON_PIPE")
    )
    port, port_notice = resolve_listening_port(
        read_configured_port(), allow_shift=not electron_mode
    )
    if port_notice:
        logger.warning(port_notice)

    apply_log_level()
    _print_banner(port=port)

    # 仅传递重启事件；更新检查改为手动触发（点击「检查更新」）
    from backend.core.updater import updater as _updater
    if restart_event is not None:
        _updater.set_restart_event(restart_event)

    if not electron_mode:
        webbrowser.open(f"http://127.0.0.1:{port}")

    # Allow Electron to request info-level logs so it can detect startup completion
    log_level = os.environ.get('UVICORN_LOG_LEVEL', 'warning')
    ssl_key = cfg.get("deploy.ssl_key")
    ssl_cert = cfg.get("deploy.ssl_cert")
    config = uvicorn.Config(
        app, host="127.0.0.1", port=port, log_level=log_level,
        access_log=not electron_mode,
        ssl_keyfile=ssl_key if ssl_key else None,
        ssl_certfile=ssl_cert if ssl_cert else None,
    )
    _server = uvicorn.Server(config)
    try:
        _server.run()
    finally:
        shutdown_webui()


def shutdown_webui():
    """停止调度器、释放运行时资源、通知 uvicorn 退出。幂等，多次调用安全。"""
    global _shutdown_done
    if _shutdown_done:
        return
    _shutdown_done = True

    def _silent(call):
        try:
            call()
        except Exception:
            pass

    _silent(orchestrator.scheduler.deactivate)
    _silent(lambda: orchestrator.scheduler.stop(timeout=3))
    _silent(_shutdown_runtime)
    _silent(lambda: setattr(_server, "should_exit", True) if _server else None)


def _shutdown_runtime():
    from AutoScriptor.core.runtime_context import runtime_ctx
    if runtime_ctx.bg is not None:
        runtime_ctx.bg.stop()
    runtime_ctx.shutdown()


if __name__ == '__main__':
    from backend.core.single_instance import ensure_single_instance
    ensure_single_instance()
    run_webui()
