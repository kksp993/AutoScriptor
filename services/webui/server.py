"""
AutoScriptor WebUI Server (FastAPI + WebSocket)
================================================
REST API endpoints under /api/*, WebSocket at /ws/logs,
static files served from ./static and ./vendor.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import logging
import os
import time as _time
import webbrowser
from http.cookies import CookieError, SimpleCookie
from queue import Empty, Full, Queue
from typing import Any, Set

from AutoScriptor.utils.logger import logger, _TaskFilter as _LogTaskFilter

from AutoScriptor.control.MumuAdaptor.device_facade import get_device_facade
from AutoScriptor.utils.app_config import cfg
from AutoScriptor.utils.game_profession import GAME_PROFESSIONS
from AutoScriptor.utils.mumu_discovery import discover_mumu_setup
from services.core.task_manager import TaskManager
from services.core.banner import _print_banner
from services.core.scheduler import scheduler, SchedulerState
from services.webui.api_response import api_error, api_ok
from services.webui.lifecycle_service import WebUILifecycleService
from services.webui.runtime_controller import RuntimeController
from services.webui.state_version import bump_version, current_version
from services.webui.task_tree_service import task_tree_service
from services.core.task_ordering import summarize_ordering_generations


def _battle_flow_allowed_for_task(flow_value: str, task_path: str | None) -> bool:
    from ZmxyOL.task.battle_task_params import battle_flow_allowed_for_task

    return battle_flow_allowed_for_task(flow_value, task_path)

# FastAPI Form/UploadFile 运行时依赖；显式导入以保证 multipart 解析可用。
import multipart  # noqa: F401

from fastapi import FastAPI, File, WebSocket, WebSocketDisconnect, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# ── 日志队列 ──

# 仿星铁风格的 ANSI 彩色 Formatter，ansi_up 可正确渲染为彩色 HTML
class _ColoredFormatter(logging.Formatter):
    _LEVEL_COLORS = {
        'DEBUG':    '\033[36m',    # cyan
        'INFO':     '\033[32m',    # green
        'WARNING':  '\033[33m',    # yellow
        'ERROR':    '\033[31m',    # red
        'CRITICAL': '\033[1;31m',  # bold red
    }
    _RESET = '\033[0m'
    _DIM   = '\033[2m'

    def format(self, record: logging.LogRecord) -> str:
        color = self._LEVEL_COLORS.get(record.levelname, '')
        time_str = self.formatTime(record, '%H:%M:%S')
        # 网页日志区：级别列收紧（常见 DEBUG/INFO 约 4–5 字符，不拉满 8 格）
        level_tag = f"{color}{record.levelname:<5}{self._RESET}"
        msg = record.getMessage()
        if record.exc_info:
            msg += '\n' + self.formatException(record.exc_info)
        task_prefix = getattr(record, 'task_prefix', '')
        return f"{self._DIM}{time_str}{self._RESET} | {level_tag} | {task_prefix}{msg}"


_colored_fmt = _ColoredFormatter()
_plain_fmt    = logging.Formatter(
    "%(asctime)s | %(levelname)-8s | %(module)s:%(lineno)d - %(task_prefix)s%(message)s",
    datefmt="%H:%M:%S",
)

from AutoScriptor.utils.paths import get_accounts_dir, get_app_root, get_data_root, get_logs_root, get_static_dir, get_vendor_dir
from services.webui.error_archives import (
    delete_archives,
    get_archive_detail,
    import_zip_bytes,
    list_error_archives,
    read_archive_file,
)
webui_log_path = os.path.join(str(get_logs_root()), 'webui.log')
file_handler = logging.FileHandler(webui_log_path, encoding='utf-8')
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(_plain_fmt)
file_handler.addFilter(_LogTaskFilter())
logger.addHandler(file_handler)

log_queue: Queue[str] = Queue(maxsize=10000)


class QueueHandler(logging.Handler):
    def __init__(self, q: Queue, level=logging.DEBUG):
        super().__init__(level)
        self.q = q

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
        except Exception:
            self.handleError(record)
            return

        try:
            self.q.put_nowait(msg)
        except Full:
            try:
                self.q.get_nowait()
            except Empty:
                pass
            try:
                self.q.put_nowait(msg)
            except Full:
                pass


queue_handler = QueueHandler(log_queue, level=logging.DEBUG)
queue_handler.setFormatter(_colored_fmt)
queue_handler.addFilter(_LogTaskFilter())
logger.addHandler(queue_handler)


def _apply_webui_log_level_from_config():
    """按 config deploy.log_level 限制推送到 WebUI 的日志级别（与模板默认 info 一致）。"""
    raw = (cfg._config.get("deploy") or {}).get("log_level", "debug")
    if isinstance(raw, str):
        name = raw.strip().upper()
    else:
        name = "INFO"
    level = getattr(logging, name, None)
    if not isinstance(level, int):
        level = logging.INFO
    queue_handler.setLevel(level)


_apply_webui_log_level_from_config()

# ── 全局状态 ──

CONFIG = cfg
ORDER_MAP: dict[str, int] = {}
TASK_MANAGER = TaskManager()
scheduler.set_task_manager(TASK_MANAGER)
runtime_controller = RuntimeController(scheduler, TASK_MANAGER)
lifecycle_service: WebUILifecycleService | None = None


def _guard_runtime_idle(action: str = "modify runtime config") -> JSONResponse | None:
    return runtime_controller.guard_idle(action)

# ── 安全模块 ──

from services.webui.security import (
    hash_deploy_password as _hash_deploy_password,
    verify_deploy_password as _verify_deploy_password,
    create_session as _create_session,
    validate_session as _validate_session,
    check_request_freshness as _check_request_freshness,
    login_limiter as _login_limiter,
    verify_limiter as _verify_limiter,
    SESSION_TTL as _SESSION_TTL,
    grant_credential_unlock as _grant_credential_unlock,
    validate_credential_unlock as _validate_credential_unlock,
    revoke_credential_unlock as _revoke_credential_unlock,
    CREDENTIAL_UNLOCK_COOKIE_NAME as _CREDENTIAL_UNLOCK_COOKIE_NAME,
    CREDENTIAL_UNLOCK_TTL as _CREDENTIAL_UNLOCK_TTL,
)


def _is_rate_limited(ip: str) -> bool:
    return _login_limiter.is_limited(ip)


def _record_login_failure(ip: str):
    _login_limiter.record_failure(ip)


def _is_verify_rate_limited(ip: str) -> bool:
    return _verify_limiter.is_limited(ip)


def _record_verify_failure(ip: str):
    _verify_limiter.record_failure(ip)


def _credential_unlock_from_request(request: Request) -> str | None:
    return request.cookies.get(_CREDENTIAL_UNLOCK_COOKIE_NAME) or request.headers.get(
        "X-Credential-Unlock"
    )


def _attach_credential_unlock_cookie(response: JSONResponse, token: str) -> JSONResponse:
    response.set_cookie(
        _CREDENTIAL_UNLOCK_COOKIE_NAME,
        token,
        httponly=True,
        samesite="strict",
        max_age=_CREDENTIAL_UNLOCK_TTL,
        path="/",
    )
    return response


def _clear_credential_unlock_cookie(response: JSONResponse) -> JSONResponse:
    response.delete_cookie(_CREDENTIAL_UNLOCK_COOKIE_NAME, path="/")
    return response



def _require_credential_unlock(request: Request) -> JSONResponse | None:
    """执行自动化前仅依据 cfg 中是否已有已解密账密判断。"""
    if not cfg.has_decrypted_credentials():
        return api_error(
            403,
            "请先验证账号密码后再执行任务",
            code="credential_locked",
            need_credential_unlock=True,
        )
    return None


VENDOR_DIR = str(get_vendor_dir())
STATIC_DIR = str(get_static_dir())
WEBAPP_ICON_PATH = os.path.join(str(get_app_root()), "webapp", "icon.png")


# ── 辅助函数 ──

def read_config():
    global ORDER_MAP
    ORDER_MAP = task_tree_service.read_order_map()


def _make_public_config_unlocked():
    data = task_tree_service.public_config()
    data["config_version"] = current_version()
    return data


def make_public_config():
    service = lifecycle_service
    if service is None:
        return _make_public_config_unlocked()
    with service.config_operation():
        return _make_public_config_unlocked()


def _mark_config_changed(reason: str) -> int:
    return bump_version(reason)


def _persistence_diagnostics() -> dict[str, str]:
    return {
        "data_root": str(get_data_root()),
        "config_path": str(getattr(cfg, "CONFIG_PATH", "")),
        "accounts_dir": str(getattr(cfg, "ACCOUNTS_DIR", get_accounts_dir())),
        "current_account": str(cfg.current_account() or ""),
    }


def _persistence_error_message(action: str, exc: Exception) -> str:
    diag = _persistence_diagnostics()
    return (
        f"{action}: {exc}; "
        f"config={diag['config_path']}; accounts={diag['accounts_dir']}; dataRoot={diag['data_root']}"
    )


def _consume_runtime_config_updates() -> bool:
    if not scheduler.consume_tasks_updated():
        return False
    if getattr(scheduler, "is_executing", False):
        _mark_config_changed("runtime tasks updated")
        return True
    read_config()
    _mark_config_changed("runtime tasks updated")
    return True


lifecycle_service = WebUILifecycleService(
    cfg,
    TASK_MANAGER,
    scheduler,
    task_tree_service,
    read_config,
    _mark_config_changed,
    _apply_webui_log_level_from_config,
)

_GIFT_REDEEM_TASK_PATH = "一般任务/活动/兑换豪礼礼品兑换"


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
                    _persistence_error_message(f"{path} 未捕获异常", e),
                    code="unhandled_api_error",
                    diagnostics=_persistence_diagnostics(),
                )
                await response(scope, receive, send)
                return
            raise


@app.post("/api/auth")
async def auth_api(request: Request):
    client_ip = request.client.host if request.client else "unknown"
    if _is_rate_limited(client_ip):
        return JSONResponse(status_code=429, content={"error": "登录尝试过多，请5分钟后再试"})

    data = await request.json()
    stored = cfg._config.get("deploy", {}).get("password")
    raw = data.get("password", "")

    if _verify_deploy_password(raw, stored):
        if stored and not stored.startswith("pbkdf2$"):
            cfg._config.setdefault("deploy", {})["password"] = _hash_deploy_password(raw)
            cfg.save_config()
            _mark_config_changed("upgrade deploy password hash")
        old_cred = _credential_unlock_from_request(request)
        _revoke_credential_unlock(old_cred)
        session_token = _create_session()
        resp = JSONResponse(content={"status": "ok"})
        resp.set_cookie(
            "auth_token", session_token,
            httponly=True, samesite="strict", max_age=_SESSION_TTL,
        )
        _clear_credential_unlock_cookie(resp)
        return resp

    _record_login_failure(client_ip)
    remaining = _login_limiter.remaining_before_lockout(client_ip)
    return JSONResponse(status_code=401, content={
        "error": f"密码错误（剩余 {max(remaining, 0)} 次尝试）"
    })


# 编辑器 API 路由
from services.webui.routes.editor import (
    configure_editor_custom_task_save_controls,
    configure_editor_execution_controls,
    editor_execution_status,
    router as editor_router,
)
runtime_controller.set_external_status_getter("editor", editor_execution_status)
configure_editor_execution_controls(
    request_cancel=TASK_MANAGER.request_cancel,
    reset_cancel=TASK_MANAGER.reset_cancel,
    runtime_busy=lambda: runtime_controller.busy_reason() in ("direct_run", "scheduler"),
)
configure_editor_custom_task_save_controls(
    reload_custom_tasks=lambda: lifecycle_service.reload_all(reason="save editor custom task"),
)
app.include_router(editor_router)

# 资讯 API 路由
from services.webui.routes.news import router as news_router
app.include_router(news_router)

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


# ── WebSocket 日志广播 ──

ws_clients: Set[WebSocket] = set()


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


async def _log_broadcaster():
    """后台协程：从线程安全的日志队列取数据，广播给所有 WebSocket 客户端。"""
    while True:
        batch: list[str] = []
        while True:
            try:
                batch.append(log_queue.get_nowait())
            except Empty:
                break
        if batch:
            payload = json.dumps({"data": "\n".join(batch)})
            dead: set[WebSocket] = set()
            for ws in ws_clients.copy():
                try:
                    await ws.send_text(payload)
                except Exception:
                    dead.add(ws)
            ws_clients.difference_update(dead)
        await asyncio.sleep(0.5)


_init_done = False
_init_error = ""


@app.on_event("startup")
async def _on_startup():
    asyncio.create_task(_log_broadcaster())
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
                scheduler.activate()
                scheduler.wake()
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
    from services.core.runtime_context import runtime_ctx

    runtime_ctx.init_bg()
    TASK_MANAGER.reload_tasks()
    read_config()


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
    if os.path.exists(WEBAPP_ICON_PATH):
        return FileResponse(WEBAPP_ICON_PATH, media_type="image/png")
    return JSONResponse(status_code=404, content={})


@app.get("/favicon.png")
async def favicon_png():
    if os.path.exists(WEBAPP_ICON_PATH):
        return FileResponse(WEBAPP_ICON_PATH, media_type="image/png")
    return JSONResponse(status_code=404, content={})


# ── API 路由 ──

@app.get("/api/refresh")
async def refresh_config_api():
    try:
        with lifecycle_service.config_operation():
            _consume_runtime_config_updates()
            read_config()
            _apply_webui_log_level_from_config()
            return _make_public_config_unlocked()
    except Exception as e:
        logger.error("refresh error: %s", e)
        return api_error(500, str(e), code="refresh_failed")


@app.post("/api/tasks/reload")
async def reload_tasks_api():
    busy = _guard_runtime_idle("reload tasks")
    if busy is not None:
        return busy
    try:
        with lifecycle_service.config_operation():
            lifecycle_service.reload_task_state(reason="reload tasks")
            return _make_public_config_unlocked()
    except Exception as e:
        logger.error("reload_tasks error: %s", e)
        return api_error(500, str(e), code="reload_tasks_failed")


@app.post("/api/config/sync")
async def sync_config_api(request: Request):
    busy = _guard_runtime_idle("sync config")
    if busy is not None:
        return busy
    try:
        data = await request.json()
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    security_key = data.get("security_key")
    try:
        version = lifecycle_service.sync_all_config(security_key, reason="sync config")
        return api_ok(status="ok", config_version=version)
    except Exception as e:
        logger.error("sync_config error: %s", e)
        return api_error(500, str(e), code="sync_config_failed")


@app.post("/api/tasks/reload-all")
async def reload_all_tasks_api():
    busy = _guard_runtime_idle("reload all tasks")
    if busy is not None:
        return busy
    try:
        with lifecycle_service.config_operation():
            lifecycle_service.reload_all(reason="reload all")
            return _make_public_config_unlocked()
    except Exception as e:
        logger.error("reload_all_tasks error: %s", e)
        return api_error(500, str(e), code="reload_all_tasks_failed")


@app.post("/api/config")
async def save_config_api(request: Request):
    busy = _guard_runtime_idle("save config")
    if busy is not None:
        return busy
    data = await request.json()
    if not isinstance(data, dict):
        return api_error(400, "invalid config payload", code="invalid_payload")
    try:
        return api_ok(config_version=lifecycle_service.save_runtime_config(data))
    except (KeyError, ValueError) as e:
        return api_error(400, str(e), code="invalid_payload")
    except Exception as e:
        logger.error("save config error: %s", e)
        return api_error(
            500,
            _persistence_error_message("保存配置失败", e),
            code="save_config_failed",
            diagnostics=_persistence_diagnostics(),
        )


@app.post("/api/tasks")
async def save_tasks_api(request: Request):
    busy = _guard_runtime_idle("save tasks")
    if busy is not None:
        return busy
    try:
        payload = await request.json()
        tasks = payload.get('tasks', payload)
        if not isinstance(tasks, dict):
            return api_error(400, "invalid tasks payload", code="invalid_payload")
        with lifecycle_service.config_operation():
            lifecycle_service.save_tasks(tasks)
            return _make_public_config_unlocked()
    except Exception as e:
        logger.error("save_tasks error: %s", e)
        return api_error(
            500,
            _persistence_error_message("保存任务失败", e),
            code="save_tasks_failed",
            diagnostics=_persistence_diagnostics(),
        )


@app.get("/api/task-ordering")
async def task_ordering_api():
    try:
        with lifecycle_service.config_operation():
            projection = task_tree_service.task_ordering_projection()
            return api_ok(
                config_version=current_version(),
                projection=projection.to_public_dict(),
                generations=summarize_ordering_generations(projection),
                runtime=runtime_controller.status(),
            )
    except Exception as e:
        logger.error("task_ordering read error: %s", e, exc_info=True)
        return api_error(500, str(e), code="task_ordering_read_failed")


@app.post("/api/task-ordering")
async def save_task_ordering_api(request: Request):
    busy = _guard_runtime_idle("save task ordering")
    if busy is not None:
        return busy
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            return api_error(400, "invalid task ordering payload", code="invalid_payload")
        raw_overlay = payload.get("overlay", payload)
        with lifecycle_service.config_operation():
            lifecycle_service.save_task_ordering(raw_overlay)
            return _make_public_config_unlocked()
    except ValueError as e:
        return api_error(400, str(e), code="invalid_task_ordering")
    except Exception as e:
        logger.error("save_task_ordering error: %s", e, exc_info=True)
        return api_error(
            500,
            _persistence_error_message("保存任务排序失败", e),
            code="save_task_ordering_failed",
            diagnostics=_persistence_diagnostics(),
        )


@app.post("/api/task-ordering/layout")
async def save_task_ordering_layout_api(request: Request):
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            return api_error(400, "invalid task ordering layout payload", code="invalid_payload")
        raw_layout = payload.get("layout", payload)
        config_version = lifecycle_service.save_task_ordering_layout(raw_layout)
        projection = task_tree_service.task_ordering_projection()
        return api_ok(
            status="ok",
            config_version=config_version,
            projection=projection.to_public_dict(),
        )
    except ValueError as e:
        return api_error(400, str(e), code="invalid_task_ordering_layout")
    except Exception as e:
        logger.error("save_task_ordering_layout error: %s", e, exc_info=True)
        return api_error(
            500,
            _persistence_error_message("保存任务图布局失败", e),
            code="save_task_ordering_layout_failed",
            diagnostics=_persistence_diagnostics(),
        )


def _apply_run_character_from_body(body: dict):
    """
    若请求携带 server + character，在后端切换当前角色并写回 config/账号文件，
    再使调度器下次执行前重新登录，避免前端已选角色与进程内 cfg 不一致。
    成功返回 None，失败返回 JSONResponse。
    """
    server = (body.get("server") or "").strip()
    character = (body.get("character") or "").strip()
    if not server or not character:
        return None
    try:
        lifecycle_service.switch_character(server, character, reason="select run character")
        logger.info("Selected role for execution: %s/%s", server, character)
    except (KeyError, ValueError) as e:
        return JSONResponse(status_code=400, content={"status": "error", "message": str(e)})
    except Exception as e:
        logger.error("run: switch character: %s", e)
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": "切换角色失败"},
        )
    return None


@app.post("/api/run")
async def run_tasks_api(request: Request):
    raw = await request.json()
    if isinstance(raw, list):
        body = {"tasks": raw, "activate_scheduler": True}
    elif isinstance(raw, dict):
        body = raw
    else:
        body = {}

    err = _require_credential_unlock(request)
    if err is not None:
        return err

    activate_sched = bool(body.get("activate_scheduler", True))
    direct_busy = runtime_controller.direct_run_alive()
    if activate_sched:
        if runtime_controller.is_busy():
            return runtime_controller.busy_response("start scheduler")
        if scheduler.state == SchedulerState.ERROR:
            return JSONResponse(
                status_code=409,
                content={
                    "status": "error",
                    "message": "调度器处于错误状态，请先恢复调度后再启动",
                },
            )
        if not task_tree_service.normalize_dispatch_queue(cfg._account_data.get("dispatch_queue", [])):
            return JSONResponse(
                status_code=400,
                content={
                    "status": "error",
                    "message": "调度队列为空，请先添加要参与调度的角色",
                },
            )
    elif runtime_controller.is_busy():
        return runtime_controller.busy_response("run task")

    err = _apply_run_character_from_body(body)
    if err is not None:
        return err

    character_name = cfg._config.get("game", {}).get("character_name", "")
    if not character_name:
        return JSONResponse(status_code=403,
                            content={'status': 'error', 'message': '请先验证账号密码后再执行任务'})

    tasks = body.get("tasks", [])

    logger.debug("Received tasks: %s, activate_scheduler: %s", tasks, activate_sched)
    sorted_tasks = sorted(tasks, key=lambda x: ORDER_MAP.get(x, float('inf')))

    if activate_sched:
        if direct_busy:
            return api_error(
                409,
                "单任务或队列正在直接执行中，请先终止后再启动调度",
                code="runtime_busy",
                reason="direct_run",
            )
        scheduler.activate()
        scheduler.wake()
        return api_ok(status='ok', tasks=sorted_tasks, mode='scheduler')

    if direct_busy:
        return api_error(
            409,
            "已有任务正在执行，请先终止后再试",
            code="runtime_busy",
            reason="direct_run",
        )
    if scheduler.state == SchedulerState.RUNNING:
        return api_error(
            409,
            "调度器运行中，请先停止调度或结束当前调度周期后再执行单任务",
            code="runtime_busy",
            reason="scheduler",
        )

    def _run(ts):
        scheduler.run_direct(ts)
        logger.info("========== 所有任务执行完成 ==========")

    runtime_controller.start_direct(_run, sorted_tasks)
    return api_ok(status='ok', tasks=sorted_tasks, mode='direct')


@app.get("/api/run/status")
async def run_status_api():
    """轻量运行状态接口；统一前端状态以 /api/runtime/snapshot 为准。"""
    return {"running": runtime_controller.direct_run_alive(), "runtime": runtime_controller.status()}


def _gift_redeem_character_options() -> list[dict[str, Any]]:
    """Return account/character choices without exposing credentials, encryption, tasks, or status."""
    accounts: list[dict[str, Any]] = []
    current = cfg.current_account()
    for name in cfg.list_accounts():
        characters: dict[str, Any] = {}
        if name == current:
            characters = cfg.list_characters()
        else:
            path = os.path.join(cfg.ACCOUNTS_DIR, f"{name}.json")
            try:
                with open(path, "r", encoding="utf-8-sig") as f:
                    payload = json.load(f)
                raw_chars = payload.get("characters") or {}
                if isinstance(raw_chars, dict):
                    characters = raw_chars
            except (OSError, json.JSONDecodeError):
                characters = {}

        roles: list[dict[str, str]] = []
        for server, server_chars in characters.items():
            if not isinstance(server_chars, dict):
                continue
            for char_name in server_chars.keys():
                roles.append({
                    "server": str(server),
                    "name": str(char_name),
                    "label": f"{server}:{char_name}",
                })
        accounts.append({
            "name": name,
            "current": name == current,
            "roles": roles,
        })
    return accounts


@app.get("/api/news/redeem_targets")
async def news_redeem_targets_api():
    return api_ok(
        current_account=cfg.current_account(),
        active_character=cfg.active_character(),
        credential_unlocked=cfg.has_decrypted_credentials(),
        accounts=_gift_redeem_character_options(),
        runtime=runtime_controller.status(),
    )


def _credential_locked_response(message: str) -> JSONResponse:
    return api_error(
        403,
        message,
        code="credential_locked",
        need_credential_unlock=True,
        need_security_key=True,
    )


def _gift_redeem_codes_from_payload(data: dict[str, Any]) -> list[str]:
    raw_codes = data.get("redeem_codes")
    if isinstance(raw_codes, list):
        candidates = raw_codes
    else:
        candidates = [data.get("redeem_code")]
    codes: list[str] = []
    seen: set[str] = set()
    for raw in candidates:
        code = str(raw or "").strip()
        if not code or code in seen:
            continue
        seen.add(code)
        codes.append(code)
    return codes


@app.post("/api/news/gift_codes/redeem")
async def news_gift_code_redeem_api(request: Request):
    data = await request.json()
    if not isinstance(data, dict):
        return api_error(400, "invalid redeem payload", code="invalid_payload")
    if not _check_request_freshness(data):
        return api_error(400, "请求已过期，请重试", code="stale_request")
    if runtime_controller.is_busy():
        return runtime_controller.busy_response("redeem gift code")

    redeem_codes = _gift_redeem_codes_from_payload(data)
    account = str(data.get("account") or "").strip()
    server = str(data.get("server") or "").strip()
    character = str(data.get("character") or "").strip()
    security_key = str(data.get("security_key") or "").strip()

    if not redeem_codes:
        return api_error(400, "兑换码不能为空", code="invalid_payload")
    if len(redeem_codes) > 30:
        return api_error(400, "一次最多兑换 30 个兑换码", code="invalid_payload")
    if not account:
        return api_error(400, "请选择账号", code="invalid_payload")
    if not server or not character:
        return api_error(400, "请选择角色", code="invalid_payload")

    client_ip = request.client.host if request.client else "unknown"
    if security_key and _is_verify_rate_limited(client_ip):
        return api_error(429, "验证尝试过多，请5分钟后再试", code="rate_limited")
    credential_granted = False

    try:
        if account != cfg.current_account():
            if not security_key:
                return _credential_locked_response("切换账号需要输入安全密码")
            if not cfg.verify_account_security_key(account, security_key):
                _record_verify_failure(client_ip)
                return api_error(401, "安全密码错误", code="invalid_security_key", need_security_key=True)
            lifecycle_service.switch_account(account, security_key)
            credential_granted = True
        elif not cfg.has_decrypted_credentials():
            if cfg.has_encrypted_credentials():
                if not security_key:
                    return _credential_locked_response("请先输入安全密码以验证账号")
                if not cfg.verify_account_security_key(account, security_key):
                    _record_verify_failure(client_ip)
                    return api_error(401, "安全密码错误", code="invalid_security_key", need_security_key=True)
                lifecycle_service.reload_verified_account(security_key)
                _mark_config_changed("redeem credential unlock")
                credential_granted = True
            else:
                return _credential_locked_response("当前账号未配置游戏账号密码")

        if not cfg.has_decrypted_credentials():
            return _credential_locked_response("请先验证账号密码后再兑换")

        lifecycle_service.switch_character(server, character, reason="redeem code select character")

        from AutoScriptor.utils.task_registry import task_registry

        if not task_registry.has_task(_GIFT_REDEEM_TASK_PATH):
            lifecycle_service.reload_all(reason="reload redeem task")
        if not task_registry.has_task(_GIFT_REDEEM_TASK_PATH):
            return api_error(
                404,
                "未找到兑换码任务，请确认一般任务已加载",
                code="redeem_task_missing",
            )
    except (KeyError, ValueError) as e:
        return api_error(400, str(e), code="invalid_payload")
    except Exception as e:
        logger.error("gift code redeem prepare failed: %s", e, exc_info=True)
        return api_error(500, "启动兑换任务失败", code="redeem_start_failed")

    task_runs = [
        {
            "id": "redeem:batch",
            "task": _GIFT_REDEEM_TASK_PATH,
            "params": {"redeem_code": redeem_codes if len(redeem_codes) > 1 else redeem_codes[0]},
        }
    ]

    def _run(runs):
        scheduler.run_direct_sequence(runs, force_login=True)
        logger.info("========== 兑换码任务执行完成，共 %d 个 ==========", len(redeem_codes))

    runtime_controller.start_direct(_run, task_runs)
    resp = JSONResponse(content=api_ok(
        status="ok",
        mode="direct",
        task=_GIFT_REDEEM_TASK_PATH,
        redeem_codes=redeem_codes,
        redeem_count=len(redeem_codes),
        account=cfg.current_account(),
        active_character=cfg.active_character(),
        config_version=current_version(),
    ))
    if credential_granted:
        old_tok = _credential_unlock_from_request(request)
        _revoke_credential_unlock(old_tok)
        tok = _grant_credential_unlock()
        return _attach_credential_unlock_cookie(resp, tok)
    return resp


@app.post("/api/stop")
async def stop_tasks_api():
    try:
        return api_ok(status=runtime_controller.request_stop(), runtime=runtime_controller.status())
    except Exception as e:
        logger.error("stop error: %s", e)
        return api_error(500, str(e), code="stop_failed")


@app.get("/api/credential/status")
async def credential_status_api(request: Request):
    """前端同步「是否可执行」：仅看 cfg 中是否已有已解密账密。"""
    return {"unlocked": cfg.has_decrypted_credentials()}


@app.post("/api/credential/revoke")
async def credential_revoke_api(request: Request):
    """用户主动「重新验证」时吊销解锁令牌并清除 Cookie。"""
    busy = _guard_runtime_idle("revoke credentials")
    if busy is not None:
        return busy
    old = _credential_unlock_from_request(request)
    _revoke_credential_unlock(old)
    cfg.clear_decrypted_credentials()
    resp = JSONResponse(content={"status": "ok"})
    return _clear_credential_unlock_cookie(resp)


@app.post("/api/verify")
async def verify_account_api(request: Request):
    client_ip = request.client.host if request.client else "unknown"
    if _is_verify_rate_limited(client_ip):
        return JSONResponse(status_code=429, content={"error": "验证尝试过多，请5分钟后再试"})

    busy = _guard_runtime_idle("verify account")
    if busy is not None:
        return busy

    data = await request.json()
    if not _check_request_freshness(data):
        return JSONResponse(status_code=400, content={"error": "请求已过期，请重试"})
    security_key = data.get("security_key", "")
    has_enc = cfg.has_encrypted_credentials()
    if has_enc and not str(security_key).strip():
        return JSONResponse(status_code=401, content={"error": "请输入安全密码"})

    try:
        character_name = lifecycle_service.reload_verified_account(security_key)
    except Exception as e:
        logger.error("verify reload_tasks: %s", e)
        return JSONResponse(status_code=500, content={"error": "加载配置失败"})

    if has_enc:
        if not cfg.has_decrypted_credentials():
            _record_verify_failure(client_ip)
            return JSONResponse(status_code=401, content={"error": "安全密码错误"})

    if not character_name:
        return JSONResponse(
            status_code=400,
            content={"error": "账号中未找到角色，请先选择或创建角色"},
        )

    old_tok = _credential_unlock_from_request(request)
    _revoke_credential_unlock(old_tok)
    tok = _grant_credential_unlock()
    if cfg.get("scheduler.auto_start", False):
        logger.info("Scheduler auto-start is armed; waiting for explicit run after account verification")
    version = _mark_config_changed("verify account")
    resp = JSONResponse(
        content={
            "character_name": character_name,
            "active_character": cfg.active_character(),
            "config_version": version,
        }
    )
    return _attach_credential_unlock_cookie(resp, tok)


@app.post("/api/account")
async def update_account_credentials_api(request: Request):
    """Update the encryption (account/password) for the current account."""
    busy = _guard_runtime_idle("update account credentials")
    if busy is not None:
        return busy
    data = await request.json()
    if not _check_request_freshness(data):
        return JSONResponse(status_code=400, content={"error": "请求已过期，请重试"})

    client_ip = request.client.host if request.client else "unknown"
    if _is_verify_rate_limited(client_ip):
        return JSONResponse(status_code=429, content={"error": "操作过于频繁，请5分钟后再试"})

    account = data.get('account', '')
    password = data.get('password', '')
    security_key = data.get('security_key', '')
    confirmed = data.get('confirmed', False)
    current_security_key = data.get('current_security_key', '')
    unlocked = _validate_credential_unlock(_credential_unlock_from_request(request))

    if cfg.has_encrypted_credentials():
        if not unlocked and not current_security_key:
            return JSONResponse(status_code=403, content={
                "error": "修改账密需要先验证当前安全密码",
                "need_current_key": True,
            })
        if not unlocked:
            if not cfg.verify_account_security_key(cfg.current_account(), current_security_key):
                _record_verify_failure(client_ip)
                return JSONResponse(status_code=401, content={"error": "当前安全密码验证失败"})
       

    existing_name = cfg._config.get("game", {}).get("character_name", "")
    if existing_name and not confirmed:
        return {
            "need_confirm": True,
            "message": f"更新账密会覆盖当前已有的加密设置（当前角色: {existing_name}），是否继续？"
        }
    try:
        character_name, version = lifecycle_service.update_account_credentials(account, password, security_key)
    except Exception as e:
        logger.error("update_account error: %s", e)
        return JSONResponse(status_code=500, content={"error": str(e)})
    old_tok = _credential_unlock_from_request(request)
    _revoke_credential_unlock(old_tok)
    tok = _grant_credential_unlock()
    resp = JSONResponse(content={"character_name": character_name, "config_version": version})
    return _attach_credential_unlock_cookie(resp, tok)


@app.post("/api/enum-options")
async def enum_options_api(request: Request):
    try:
        data = await request.json()
        paths = data.get('paths', [])
        raw_tp = data.get('task_path')
        if isinstance(raw_tp, str):
            task_path = raw_tp.strip() or None
        else:
            task_path = None
        if not isinstance(paths, list):
            return api_error(400, 'paths must be a list', code='invalid_payload')
        result = {}
        for p in paths:
            if not isinstance(p, str) or '.' not in p:
                return api_error(400, f'invalid enum path: {p!r}', code='invalid_payload')
            module_name, class_name = p.rsplit('.', 1)
            mod = importlib.import_module(module_name)
            EnumClass = getattr(mod, class_name)
            opts = []
            for m in EnumClass:
                if isinstance(m.value, str):
                    label = m.value
                elif isinstance(m.value, int):
                    label = str(m.value)
                else:
                    label = m.name
                if (
                    task_path
                    and EnumClass.__name__ == 'BattleFlowName'
                    and isinstance(m.value, str)
                    and not _battle_flow_allowed_for_task(m.value, task_path)
                ):
                    continue
                opts.append({"value": m.name, "label": label})
            result[p] = opts
        return result
    except Exception as e:
        logger.error("enum_options error: %s", e)
        return api_error(500, str(e), code='enum_options_failed')


@app.get("/api/ocr-status")
async def ocr_status_api():
    try:
        import paddle
        from AutoScriptor.recognition.ocr_rec import ocr_manager

        cfg_use_gpu = bool((cfg.get("ocr") or {}).get("use_gpu", cfg.get("ocr.use_gpu", False)))
        compiled_with_cuda = paddle.device.is_compiled_with_cuda()
        gpu_count = paddle.device.cuda.device_count()
        current_device = paddle.get_device()
        engine_ready = ocr_manager.is_ready()
        return {
            "cfg_use_gpu": cfg_use_gpu,
            "compiled_with_cuda": compiled_with_cuda,
            "gpu_count": gpu_count,
            "current_device": current_device,
            "engine_ready": engine_ready,
        }
    except Exception as e:
        logger.error("ocr_status error: %s", e)
        return api_error(500, str(e), code="ocr_status_failed")


@app.get("/api/scheduler/status")
async def scheduler_status_api():
    return scheduler.status_dict()


@app.post("/api/scheduler/reset")
async def scheduler_reset_api():
    busy = _guard_runtime_idle("reset scheduler")
    if busy is not None:
        return busy
    scheduler.reset()
    return scheduler.status_dict()


@app.post("/api/scheduler/deactivate")
async def scheduler_deactivate_api():
    """仅将调度器切回待运行，不取消直接执行线程、不发送 cancel。"""
    scheduler.deactivate()
    return scheduler.status_dict()


def _build_overview_payload(now_ts: float | None = None) -> dict:
    from services.core.scheduler import (
        calc_effective_next_time,
        is_human_takeover_blocked,
        is_task_due,
    )

    now_ts = now_ts or _time.time()
    total = enabled = pending = scheduled = error = disabled = 0
    upcoming = []

    def _walk(node, prefix=''):
        nonlocal total, enabled, pending, scheduled, error, disabled
        for key, val in node.items():
            if not isinstance(val, dict):
                continue
            path = f"{prefix}/{key}" if prefix else key
            if 'on' in val and 'next_exec_time' in val:
                total += 1
                if not val.get('on'):
                    disabled += 1
                else:
                    enabled += 1
                    blocked = is_human_takeover_blocked(val, now_ts) or bool(val.get("error"))
                    due = False if blocked else is_task_due(val, path, now_ts)
                    if blocked:
                        error += 1
                    elif due:
                        pending += 1
                    else:
                        scheduled += 1
                    status = 'error' if blocked else ('pending' if due else 'scheduled')
                    task_status = ((cfg._config.get("status") or {}).get("tasks") or {}).get(path, {})
                    progress = task_status.get("progress") if isinstance(task_status, dict) else None
                    progress_display = None
                    if progress is not None:
                        from AutoScriptor.utils.task_state import progress_label

                        progress_display = progress_label(progress) or str(progress)
                    upcoming.append({
                        'path': path,
                        'on': True,
                        'next_exec_time': calc_effective_next_time(val, now_ts),
                        'status': status,
                        'progress': progress,
                        'progress_display': progress_display,
                        'human_takeover_error': val.get('human_takeover_error'),
                        'human_takeover_at': val.get('human_takeover_at'),
                    })
            else:
                _walk(val, path)

    _walk(cfg._config.get('tasks', {}))
    order = {'pending': 0, 'error': 1, 'scheduled': 2}
    upcoming.sort(key=lambda x: (order.get(x['status'], 3), x['next_exec_time']))

    sched = scheduler.status_dict()
    sched['next_execution'] = scheduler.get_next_execution_timestamp()

    from services.core.runtime_context import runtime_ctx
    return {
        'scheduler': sched,
        'stats': {
            'total': total, 'enabled': enabled, 'pending': pending,
            'scheduled': scheduled, 'error': error, 'disabled': disabled,
        },
        'stats_all': task_tree_service.aggregate_stats_all_characters(now_ts),
        'overall_next_execution': task_tree_service.overall_next_execution_all_characters(),
        'upcoming': upcoming[:30],
        'runtime': runtime_ctx.status_dict(),
    }


@app.get("/api/overview")
async def overview_data_api():
    try:
        _consume_runtime_config_updates()
        return _build_overview_payload()
    except Exception as e:
        logger.error("overview error: %s", e)
        return api_error(500, str(e), code="overview_failed")


@app.get("/api/runtime/snapshot")
async def runtime_snapshot_api(request: Request):
    try:
        _consume_runtime_config_updates()
        now_ts = _time.time()
        overview = _build_overview_payload(now_ts)
        queue = task_tree_service.normalize_dispatch_queue(cfg._account_data.get("dispatch_queue", []))
        return api_ok(
            config_version=current_version(),
            credential={"unlocked": cfg.has_decrypted_credentials()},
            current_account=cfg.current_account(),
            accounts=cfg.list_accounts(),
            active_character=cfg.active_character(),
            character_name=cfg._config.get("game", {}).get("character_name", ""),
            characters=task_tree_service.characters_summary(),
            game_professions_by_character=task_tree_service.game_professions_by_character(),
            game_profession_options=list(GAME_PROFESSIONS),
            dispatch_queue=queue,
            all_tasks_summary=task_tree_service.all_characters_tasks_summary(),
            overview=overview,
            scheduler=overview["scheduler"],
            runtime=runtime_controller.status(),
        )
    except Exception as e:
        logger.error("runtime snapshot error: %s", e)
        return api_error(500, str(e), code="snapshot_failed")


@app.get("/api/device/diagnostics")
async def device_diagnostics_api(screenshot: bool = False, require_app: bool = False):
    try:
        diagnostics = get_device_facade().diagnostics(
            include_screenshot=screenshot,
            require_app=require_app,
        )
        diagnostics["discovery"] = discover_mumu_setup(cfg["emulator"], probe_adb=False)
        return api_ok(diagnostics=diagnostics)
    except Exception as e:
        logger.error("device diagnostics error: %s", e)
        return api_error(500, str(e), code="device_diagnostics_failed")


@app.get("/api/device/discover")
async def device_discover_api(probe_adb: bool = True):
    try:
        return api_ok(discovery=discover_mumu_setup(cfg["emulator"], probe_adb=probe_adb))
    except Exception as e:
        logger.error("device discovery error: %s", e)
        return api_error(500, str(e), code="device_discovery_failed")


@app.post("/api/device/discover/apply")
async def device_discover_apply_api(request: Request):
    busy = _guard_runtime_idle("apply device discovery")
    if busy is not None:
        return busy
    try:
        data = await request.json()
        emulator = data.get("emulator", data) if isinstance(data, dict) else {}
        version = lifecycle_service.apply_discovered_emulator_config(emulator)
        return api_ok(config_version=version, discovery=discover_mumu_setup(cfg["emulator"], probe_adb=False))
    except (KeyError, ValueError) as e:
        return api_error(400, str(e), code="invalid_payload")
    except Exception as e:
        logger.error("device discovery apply error: %s", e)
        return api_error(500, str(e), code="device_discovery_apply_failed")


# ── 通知 API ──

@app.post("/api/notify/test")
async def notify_test_api(request: Request):
    try:
        data = await request.json()
        config_yaml = data.get("config_yaml", "")
        from services.core.notify import handle_notify
        ok = handle_notify(config_yaml, title="AutoScriptor 测试", content="通知推送测试成功")
        return {"success": ok}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/notify/save")
async def notify_save_api(request: Request):
    busy = _guard_runtime_idle("save notify settings")
    if busy is not None:
        return busy
    data = await request.json()
    version = lifecycle_service.save_notify_settings(
        data.get("enabled", False),
        data.get("config_yaml", "provider: null"),
    )
    return api_ok(status="ok", config_version=version)


# ── 更新 API ──

@app.get("/api/update/status")
async def update_status_api():
    from services.core.updater import updater
    return updater.get_status()


@app.post("/api/update/check")
async def update_check_api():
    from services.core.updater import updater
    has_update = updater.check_update()
    return {"has_update": has_update, **updater.get_status()}


@app.post("/api/update/run")
async def update_run_api():
    busy = _guard_runtime_idle("run source update")
    if busy is not None:
        return busy
    from services.core.updater import updater
    ok = updater.run_update()
    return {"success": ok, **updater.get_status()}


@app.get("/api/remote-access")
async def remote_access_status_api():
    from services.core.remote_access import RemoteAccess
    return RemoteAccess.get_status()


@app.post("/api/remote-access")
async def remote_access_toggle_api(request: Request):
    data = await request.json()
    from services.core.remote_access import RemoteAccess
    if data.get("enabled"):
        if not cfg._config.get("deploy", {}).get("password"):
            return api_error(
                403,
                "开启远程访问前请先设置 WebUI 访问密码",
                code="deploy_password_required",
            )
        RemoteAccess.start(
            local_port=5000,
            ssh_server=cfg.get("remote_access.ssh_server", ""),
            ssh_user=cfg.get("remote_access.ssh_user", ""),
            ssh_executable=cfg.get("remote_access.ssh_executable", "ssh"),
        )
    else:
        RemoteAccess.stop()
    return RemoteAccess.get_status()


# ── 多账号 API ──

@app.get("/api/accounts")
async def accounts_list_api():
    return {
        "current_account": cfg.current_account(),
        "accounts": cfg.list_accounts(),
        "active_character": cfg.active_character(),
        "characters": task_tree_service.characters_summary(),
    }


@app.post("/api/accounts/switch")
async def accounts_switch_api(request: Request):
    busy = _guard_runtime_idle("switch account")
    if busy is not None:
        return busy
    data = await request.json()
    if not _check_request_freshness(data):
        return JSONResponse(status_code=400, content={"error": "请求已过期，请重试"})
    name = data.get("name", "")
    security_key = data.get("security_key", "")
    client_ip = request.client.host if request.client else "unknown"

    if not security_key:
        return JSONResponse(status_code=400, content={
            "error": "请输入安全密码以切换账号", "need_security_key": True,
        })
    if not cfg.verify_account_security_key(name, security_key):
        _record_verify_failure(client_ip)
        return JSONResponse(status_code=401, content={"error": "安全密码错误"})
    try:
        version = lifecycle_service.switch_account(name, security_key)
        character_name = cfg._config.get("game", {}).get("character_name", "")
        ac = cfg.active_character()
        old_tok = _credential_unlock_from_request(request)
        _revoke_credential_unlock(old_tok)
        tok = _grant_credential_unlock()
        resp = JSONResponse(
            content={
                "current_account": name,
                "character_name": character_name,
                "active_character": ac,
                "characters": task_tree_service.characters_summary(),
                "config_version": version,
            }
        )
        return _attach_credential_unlock_cookie(resp, tok)
    except KeyError as e:
        return JSONResponse(status_code=404, content={"error": str(e)})
    except Exception as e:
        logger.error("switch account error: %s", e)
        return JSONResponse(status_code=500, content={"error": "切换失败，请检查安全密码是否正确"})


@app.post("/api/accounts/add")
async def accounts_add_api(request: Request):
    busy = _guard_runtime_idle("add account")
    if busy is not None:
        return busy
    data = await request.json()
    if not _check_request_freshness(data):
        return api_error(400, "请求已过期，请重试", code="stale_request")
    name = str(data.get("name", "") or "").strip()
    account = str(data.get("account", "") or "").strip()
    password = str(data.get("password", "") or "").strip()
    server = str(data.get("server", "") or "").strip()
    character_name = str(data.get("character_name", "") or "").strip()
    security_key = str(data.get("security_key", "") or "").strip()

    if not name:
        return api_error(400, "账号名称不能为空", code="invalid_payload")
    if not account:
        return api_error(400, "游戏账号不能为空", code="invalid_payload")
    if not password:
        return api_error(400, "游戏密码不能为空", code="invalid_payload")
    if not server:
        return api_error(400, "服务器不能为空", code="invalid_payload")
    if not character_name:
        return api_error(400, "角色名不能为空", code="invalid_payload")
    if not security_key:
        return api_error(400, "安全密码不能为空", code="invalid_payload")

    try:
        version = lifecycle_service.add_account(name, account, password, server, character_name, security_key)
        old_tok = _credential_unlock_from_request(request)
        _revoke_credential_unlock(old_tok)
        tok = _grant_credential_unlock()
        resp = JSONResponse(content=api_ok(
            accounts=cfg.list_accounts(),
            current_account=cfg.current_account(),
            character_name=cfg._config.get("game", {}).get("character_name", ""),
            active_character=cfg.active_character(),
            characters=task_tree_service.characters_summary(),
            credential={"unlocked": cfg.has_decrypted_credentials()},
            config_version=version,
        ))
        return _attach_credential_unlock_cookie(resp, tok)
    except ValueError as e:
        return api_error(400, str(e), code="invalid_account")
    except Exception as e:
        logger.error("add account error: %s", e)
        return api_error(
            500,
            _persistence_error_message("创建账号失败", e),
            code="add_account_failed",
            diagnostics=_persistence_diagnostics(),
        )


@app.post("/api/accounts/delete")
async def accounts_delete_api(request: Request):
    busy = _guard_runtime_idle("delete account")
    if busy is not None:
        return busy
    data = await request.json()
    name = data.get("name", "")
    try:
        version = lifecycle_service.delete_account(name)
        return {
            "accounts": cfg.list_accounts(),
            "current_account": cfg.current_account(),
            "config_version": version,
        }
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})


# ── 角色管理 API ──

@app.get("/api/characters")
async def characters_list_api():
    return {
        "active_character": cfg.active_character(),
        "characters": task_tree_service.characters_summary(),
    }


@app.post("/api/characters/switch")
async def characters_switch_api(request: Request):
    busy = _guard_runtime_idle("switch character")
    if busy is not None:
        return busy
    data = await request.json()
    if not _check_request_freshness(data):
        return JSONResponse(status_code=400, content={"error": "请求已过期，请重试"})
    server = data.get("server", "")
    character = data.get("character", "")
    try:
        version = lifecycle_service.switch_character(server, character)
        return {
            "active_character": cfg.active_character(),
            "character_name": character,
            "characters": task_tree_service.characters_summary(),
            "config_version": version,
        }
    except (KeyError, ValueError) as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    except Exception as e:
        logger.error("switch character error: %s", e)
        return JSONResponse(status_code=500, content={"error": "切换角色失败"})


@app.post("/api/characters/add")
async def characters_add_api(request: Request):
    busy = _guard_runtime_idle("add character")
    if busy is not None:
        return busy
    data = await request.json()
    server = data.get("server", "")
    character = data.get("character", "")
    try:
        version = lifecycle_service.add_character(server, character)
        return {
            "active_character": cfg.active_character(),
            "characters": task_tree_service.characters_summary(),
            "config_version": version,
        }
    except (ValueError, KeyError) as e:
        return JSONResponse(status_code=400, content={"error": str(e)})


@app.post("/api/characters/delete")
async def characters_delete_api(request: Request):
    busy = _guard_runtime_idle("delete character")
    if busy is not None:
        return busy
    data = await request.json()
    server = data.get("server", "")
    character = data.get("character", "")
    try:
        version = lifecycle_service.delete_character(server, character)
        return {
            "active_character": cfg.active_character(),
            "characters": task_tree_service.characters_summary(),
            "config_version": version,
        }
    except (ValueError, KeyError) as e:
        return JSONResponse(status_code=400, content={"error": str(e)})


@app.post("/api/characters/game_profession")
async def characters_game_profession_api(request: Request):
    busy = _guard_runtime_idle("change character profession")
    if busy is not None:
        return busy
    """写入指定角色的游戏职业（存账号 JSON），当前角色同步 cfg.game。"""
    data = await request.json()
    if not _check_request_freshness(data):
        return JSONResponse(status_code=400, content={"error": "请求已过期，请重试"})
    server = (data.get("server") or "").strip()
    character = (data.get("character") or "").strip()
    profession = (data.get("game_profession") or "").strip()
    try:
        version = lifecycle_service.set_character_profession(server, character, profession)
        return {
            "game_professions_by_character": task_tree_service.game_professions_by_character(),
            "game": {"game_profession": cfg._config.get("game", {}).get("game_profession", "")},
            "config_version": version,
        }
    except (KeyError, ValueError) as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    except Exception as e:
        logger.error("game_profession error: %s", e)
        return JSONResponse(status_code=500, content={"error": "保存职业失败"})


@app.get("/api/characters/all_tasks_summary")
async def characters_all_tasks_summary_api():
    try:
        return {"characters": task_tree_service.all_characters_tasks_summary()}
    except Exception as e:
        logger.error("all_tasks_summary error: %s", e)
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/characters/task")
async def get_character_task_api(server: str, character: str, path: str):
    try:
        node = task_tree_service.get_character_task_public(server, character, path)
        if not node:
            return api_error(404, "task not found", code="task_not_found")
        return api_ok(task=node, path=path, server=server, character=character)
    except Exception as e:
        logger.error("get_character_task error: %s", e)
        return api_error(500, str(e), code="get_character_task_failed")


@app.post("/api/characters/task")
async def save_character_task_api(request: Request):
    busy = _guard_runtime_idle("save character task")
    if busy is not None:
        return busy
    try:
        body = await request.json()
        if not isinstance(body, dict):
            return api_error(400, "invalid payload", code="invalid_payload")
        server = (body.get("server") or "").strip()
        character = (body.get("character") or "").strip()
        path = (body.get("path") or "").strip()
        task = body.get("task")
        if not server or not character or not path or not isinstance(task, dict):
            return api_error(400, "invalid character task payload", code="invalid_payload")
        lifecycle_service.save_character_task(server, character, path, task)
        ac = cfg.active_character()
        if ac.get("server") == server and ac.get("name") == character:
            return make_public_config()
        version = current_version()
        return api_ok(config_version=version)
    except (KeyError, ValueError) as e:
        return api_error(400, str(e), code="invalid_payload")
    except Exception as e:
        logger.error("save_character_task error: %s", e)
        return api_error(
            500,
            _persistence_error_message("保存任务失败", e),
            code="save_character_task_failed",
            diagnostics=_persistence_diagnostics(),
        )


# ── 调度队列 API ──

@app.get("/api/dispatch/queue")
async def dispatch_queue_get_api():
    queue = task_tree_service.normalize_dispatch_queue(cfg._account_data.get("dispatch_queue", []))
    return {"queue": queue}


@app.post("/api/dispatch/queue")
async def dispatch_queue_save_api(request: Request):
    busy = _guard_runtime_idle("save dispatch queue")
    if busy is not None:
        return busy
    data = await request.json()
    queue, version = lifecycle_service.save_dispatch_queue(data.get("queue", []))
    return {"queue": queue, "config_version": version}


# ── 配置导入导出 API ──

@app.get("/api/config/export")
async def config_export_api():
    from fastapi.responses import Response
    safe = make_public_config()
    content = json.dumps(safe, ensure_ascii=False, indent=4)
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=autoscriptor-config.json"},
    )


@app.post("/api/config/import")
async def config_import_api(request: Request):
    busy = _guard_runtime_idle("import config")
    if busy is not None:
        return busy
    try:
        data = await request.json()
        if not isinstance(data, dict):
            return JSONResponse(status_code=400, content={"error": "invalid JSON"})
        version = lifecycle_service.import_config(data)
        return api_ok(status="ok", config_version=version)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


# ── 错误归档 API ──

@app.get("/api/error-archives")
async def error_archives_list_api():
    try:
        return list_error_archives()
    except Exception as e:
        logger.exception("error-archives list failed")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/error-archives/detail")
async def error_archives_detail_api(folder: str):
    try:
        detail = get_archive_detail(folder)
        if not detail:
            return JSONResponse(status_code=404, content={"error": "not found"})
        return detail
    except Exception as e:
        logger.exception("error-archives detail failed")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/error-archives/file")
async def error_archives_file_api(folder: str, path: str):
    try:
        p = read_archive_file(folder, path)
        if not p:
            return JSONResponse(status_code=404, content={"error": "not found"})
        suffix = p.suffix.lower()
        media = "image/png" if suffix == ".png" else "image/jpeg" if suffix in (".jpg", ".jpeg") else "video/mp4" if suffix == ".mp4" else "application/octet-stream"
        return FileResponse(p, media_type=media, filename=p.name)
    except Exception as e:
        logger.exception("error-archives file failed")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.delete("/api/error-archives")
async def error_archives_delete_api(request: Request):
    try:
        data = await request.json()
        folders = data.get("folders") or []
        if not isinstance(folders, list):
            return JSONResponse(status_code=400, content={"error": "folders must be a list"})
        return delete_archives([str(x) for x in folders])
    except Exception as e:
        logger.exception("error-archives delete failed")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/error-archives/import")
async def error_archives_import_api(file: UploadFile = File(...)):
    try:
        raw = await file.read()
        if not raw:
            return JSONResponse(status_code=400, content={"error": "empty file"})
        name = (file.filename or "import").rsplit(".", 1)[0]
        result = import_zip_bytes(raw, suggested_name=name)
        if not result.get("ok"):
            return JSONResponse(status_code=400, content=result)
        return result
    except Exception as e:
        logger.exception("error-archives import failed")
        return JSONResponse(status_code=500, content={"error": str(e)})


# ── 部署配置 API ──

@app.get("/api/deploy")
async def deploy_get_api():
    deploy_copy = dict(cfg._config.get("deploy", {}))
    has_pwd = bool(deploy_copy.get("password"))
    deploy_copy["password"] = ""
    return {
        "deploy": deploy_copy,
        "password_protected": has_pwd,
        "notify": cfg._config.get("notify", {}),
        "update": cfg._config.get("update", {}),
        "remote_access": cfg._config.get("remote_access", {}),
    }


@app.post("/api/deploy")
async def deploy_save_api(request: Request):
    busy = _guard_runtime_idle("save deploy settings")
    if busy is not None:
        return busy
    data = await request.json()
    for section in ("deploy", "notify", "update", "remote_access"):
        if section in data:
            if section == "deploy":
                incoming = data["deploy"]
                incoming_pwd = incoming.get("password")
                existing_pwd = cfg._config.get("deploy", {}).get("password")
                current_pwd = incoming.pop("current_password", None)

                if incoming_pwd is None and existing_pwd:
                    if not current_pwd or not _verify_deploy_password(current_pwd, existing_pwd):
                        return JSONResponse(status_code=403, content={"error": "清除密码需要验证当前密码"})
                    incoming["password"] = None
                elif incoming_pwd == "":
                    incoming["password"] = existing_pwd
                elif incoming_pwd:
                    if existing_pwd:
                        if not current_pwd or not _verify_deploy_password(current_pwd, existing_pwd):
                            return JSONResponse(status_code=403, content={"error": "修改密码需要验证当前密码"})
                    incoming["password"] = _hash_deploy_password(incoming_pwd)
    return api_ok(status="ok", config_version=lifecycle_service.save_deploy_sections(data))


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

    read_config()
    _apply_webui_log_level_from_config()
    _print_banner()

    # 仅传递重启事件；更新检查改为手动触发（点击「检查更新」）
    from services.core.updater import updater as _updater
    if restart_event is not None:
        _updater.set_restart_event(restart_event)

    webbrowser.open("http://127.0.0.1:5000")

    # Allow Electron to request info-level logs so it can detect startup completion
    log_level = os.environ.get('UVICORN_LOG_LEVEL', 'warning')
    ssl_key = cfg.get("deploy.ssl_key")
    ssl_cert = cfg.get("deploy.ssl_cert")
    electron_mode = bool(
        os.environ.get("AUTOSCRIPTOR_ELECTRON")
        or os.environ.get("AUTOSCRIPTOR_ELECTRON_PIPE")
    )
    config = uvicorn.Config(
        app, host="127.0.0.1", port=5000, log_level=log_level,
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

    _silent(scheduler.deactivate)
    _silent(lambda: scheduler.stop(timeout=3))
    _silent(_shutdown_runtime)
    _silent(lambda: setattr(_server, "should_exit", True) if _server else None)


def _shutdown_runtime():
    from services.core.runtime_context import runtime_ctx
    if runtime_ctx.bg is not None:
        runtime_ctx.bg.stop()
    runtime_ctx.shutdown()


if __name__ == '__main__':
    from services.single_instance import ensure_single_instance
    ensure_single_instance()
    run_webui()
