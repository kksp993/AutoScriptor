"""
AutoScriptor WebUI Server (FastAPI + WebSocket)
================================================
REST API endpoints under /api/*, WebSocket at /ws/logs,
static files served from ./static and ./vendor.
"""

from __future__ import annotations

import asyncio
import ctypes
import importlib
import json
import logging
import os
import shutil
import time as _time
import traceback
import urllib.request
import webbrowser
from copy import deepcopy
from queue import Queue, Empty
from threading import Thread
from typing import Set

import dpath
from AutoScriptor.utils.logger import logger, _TaskFilter as _LogTaskFilter

from AutoScriptor import *
from AutoScriptor.utils.constant import cfg
from ZmxyOL.task.battle_task_params import battle_flow_allowed_for_task
from services.core.task_manager import TaskManager
from services.core.banner import _print_banner
from services.core.scheduler import scheduler, SchedulerState
from AutoScriptor.utils.perf import set_thread_high_priority as _set_thread_high_priority

# FastAPI Form/UploadFile 运行时依赖；Nuitka 不会从 fastapi 静态跟到该包，须显式 import 以打入 standalone
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
    _BOLD  = '\033[1m'

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

from AutoScriptor.utils.paths import get_logs_root, get_static_dir, get_vendor_dir
from services.webui.error_archives import (
    delete_archives,
    get_archive_detail,
    import_zip_bytes,
    list_error_archives,
    read_archive_file,
)
sse_log_dir = str(get_logs_root())
sse_log_path = os.path.join(sse_log_dir, 'webui_sse.log')
file_handler = logging.FileHandler(sse_log_path, encoding='utf-8')
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(_plain_fmt)
file_handler.addFilter(_LogTaskFilter())
logger.addHandler(file_handler)

log_queue: Queue[str] = Queue(maxsize=10000)


class QueueHandler(logging.Handler):
    def __init__(self, q: Queue, level=logging.DEBUG):
        super().__init__(level)
        self.q = q

    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
            try:
                self.q.put_nowait(msg)
            except Exception:
                try:
                    self.q.get_nowait()
                except Exception:
                    pass
                try:
                    self.q.put_nowait(msg)
                except Exception:
                    pass
        except Exception:
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
RUN_THREAD: Thread | None = None
scheduler.set_task_manager(TASK_MANAGER)

# ── 安全模块 ──

from services.webui.security import (
    hash_deploy_password as _hash_deploy_password,
    verify_deploy_password as _verify_deploy_password,
    create_session as _create_session,
    validate_session as _validate_session,
    check_request_freshness as _check_request_freshness,
    login_limiter as _login_limiter,
    verify_limiter as _verify_limiter,
    content_update_check_limiter as _content_update_check_limiter,
    content_update_apply_limiter as _content_update_apply_limiter,
    content_update_apply_min_interval as _content_update_apply_min_interval,
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
    """执行自动化前须持有由 /api/verify 或带密钥切换账号签发的解锁 Cookie。"""
    tok = _credential_unlock_from_request(request)
    if not _validate_credential_unlock(tok):
        return JSONResponse(
            status_code=403,
            content={
                "status": "error",
                "message": "请先验证安全密码后再执行任务",
                "need_credential_unlock": True,
            },
        )
    return None


# ── Vendor 文件管理 ──

_HERE = os.path.dirname(__file__)
VENDOR_DIR = str(get_vendor_dir())
STATIC_DIR = str(get_static_dir())
VENDOR_SOURCES = {
    'tailwind.css': 'https://cdn.tailwindcss.com',
    'vue.global.prod.js': 'https://unpkg.com/vue@3/dist/vue.global.prod.js',
    'element-plus.css': 'https://unpkg.com/element-plus/dist/index.css',
    'element-plus.full.js': 'https://unpkg.com/element-plus/dist/index.full.js',
    'ansi_up.min.js': 'https://cdn.jsdelivr.net/npm/ansi_up@5.2.1/ansi_up.min.js',
    'font-awesome.min.css': 'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/4.7.0/css/font-awesome.min.css',
    'fonts/fontawesome-webfont.woff2': 'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/4.7.0/fonts/fontawesome-webfont.woff2',
    'fonts/fontawesome-webfont.woff': 'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/4.7.0/fonts/fontawesome-webfont.woff',
    'fonts/fontawesome-webfont.ttf': 'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/4.7.0/fonts/fontawesome-webfont.ttf',
}


def _ensure_vendor_files():
    try:
        os.makedirs(VENDOR_DIR, exist_ok=True)
        os.makedirs(os.path.join(VENDOR_DIR, 'fonts'), exist_ok=True)
        for name, url in VENDOR_SOURCES.items():
            path = os.path.join(VENDOR_DIR, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            if os.path.exists(path) and os.path.getsize(path) > 1024:
                continue
            try:
                logger.info("downloading vendor: %s", url)
                with urllib.request.urlopen(url, timeout=10) as resp, open(path, 'wb') as f:
                    shutil.copyfileobj(resp, f)
            except Exception as e:
                try:
                    if os.path.exists(path) and os.path.getsize(path) <= 1024:
                        os.remove(path)
                except Exception:
                    pass
                logger.warning("download vendor failed: %s -> %s (%s)", url, path, e)
    except Exception as e:
        logger.warning("ensure vendor dir failed: %s", e)


# ── 辅助函数 ──

def read_config():
    global ORDER_MAP
    ordered_paths = _get_ordered_paths(CONFIG['tasks'])
    ORDER_MAP = {path: i for i, path in enumerate(ordered_paths)}


def _get_ordered_paths(data_dict, prefix=''):
    paths = []
    for key, value in data_dict.items():
        current_path = f"{prefix}/{key}" if prefix else key
        if isinstance(value, dict) and 'next_exec_time' not in value:
            paths.extend(_get_ordered_paths(value, prefix=current_path))
        else:
            paths.append(current_path)
    return paths


def _inject_param_meta_into_tasks(node: dict, prefix: str = "") -> None:
    """将 TaskRegistry 中的 param_meta / beta / custom / _due 挂到任务叶节点（仅用于 API 返回副本）。"""
    from AutoScriptor.utils.task_registry import task_registry
    from services.core.task_tree import TaskTree
    from services.core.scheduler import is_task_due
    import time as _t

    now_ts = _t.time()
    for key, val in node.items():
        if not isinstance(val, dict):
            continue
        path = f"{prefix}/{key}" if prefix else key
        if TaskTree.is_leaf(val):
            meta = task_registry.get_param_meta(path)
            if meta:
                val["param_meta"] = meta
            else:
                val.pop("param_meta", None)
            if task_registry.get_beta(path):
                val["beta"] = True
            else:
                val.pop("beta", None)
            if task_registry.get_custom(path):
                val["custom"] = True
            else:
                val.pop("custom", None)
            val["_due"] = is_task_due(val, path, now_ts)
        else:
            _inject_param_meta_into_tasks(val, path)


def _strip_runtime_tasks_fields(node: dict) -> None:
    """保存配置前移除仅运行期使用的字段，避免写入 JSON。"""
    from services.core.task_tree import TaskTree

    for key, val in list(node.items()):
        if not isinstance(val, dict):
            continue
        if TaskTree.is_leaf(val):
            val.pop("param_meta", None)
            val.pop("beta", None)
            val.pop("custom", None)
            val.pop("fn", None)
            val.pop("order", None)
            val.pop("_due", None)
        else:
            _strip_runtime_tasks_fields(val)


def make_public_config():
    config_data = deepcopy(cfg._config)
    for pattern in ["**/fn", "**/encryption", "**/weekday", "**/month",
                     "**/day", "**/year", "**/account", "**/password",
                     "**/security_key"]:
        try:
            dpath.delete(config_data, pattern)
        except Exception:
            pass
    tasks = config_data.get("tasks")
    if isinstance(tasks, dict):
        _inject_param_meta_into_tasks(tasks)
    config_data["active_character"] = cfg.active_character()
    config_data["characters_summary"] = _characters_summary()
    return config_data


def _characters_summary() -> dict:
    """Return { server: [char_name, ...] } without heavy tasks/status data."""
    tree = cfg.list_characters()
    return {srv: list(chars.keys()) for srv, chars in tree.items()} if tree else {}


def _task_leaf_status(node: dict, path: str, now_ts: float) -> str:
    from services.core.scheduler import is_task_due
    if not node.get('on'):
        return 'disabled'
    if node.get('error'):
        return 'error'
    return 'pending' if is_task_due(node, path, now_ts) else 'scheduled'


def _flatten_tasks(node: dict, now_ts: float, prefix: str = '') -> list:
    """Recursively flatten a tasks tree into a list of {path, name, status, beta, custom}."""
    from AutoScriptor.utils.task_registry import task_registry

    result = []
    for key, val in node.items():
        if not isinstance(val, dict):
            continue
        path = f"{prefix}/{key}" if prefix else key
        if 'on' in val and 'next_exec_time' in val:
            row = {
                'path': path,
                'name': key,
                'status': _task_leaf_status(val, path, now_ts),
                'beta': task_registry.get_beta(path),
            }
            if task_registry.get_custom(path):
                row['custom'] = True
            result.append(row)
        else:
            result.extend(_flatten_tasks(val, now_ts, path))
    return result


def _aggregate_stats_all_characters(now_ts: float) -> dict:
    """汇总当前账号下所有角色的任务统计（与单角色 stats 结构一致）。"""
    ac = cfg.active_character()
    active_server = ac.get('server', '')
    active_name = ac.get('name', '')
    chars = cfg._account_data.get('characters', {})
    total = pending = scheduled = error = disabled = 0
    for srv, srv_chars in chars.items():
        for char_name, char_data in srv_chars.items():
            if srv == active_server and char_name == active_name:
                tasks_tree = cfg._config.get('tasks', {})
            else:
                tasks_tree = char_data.get('tasks', {})
            flat = _flatten_tasks(tasks_tree, now_ts)
            for t in flat:
                total += 1
                st = t['status']
                if st == 'disabled':
                    disabled += 1
                elif st == 'pending':
                    pending += 1
                elif st == 'scheduled':
                    scheduled += 1
                elif st == 'error':
                    error += 1
    enabled = pending + scheduled + error
    return {
        'total': total, 'enabled': enabled, 'pending': pending,
        'scheduled': scheduled, 'error': error, 'disabled': disabled,
    }


def _overall_next_execution_all_characters() -> float | None:
    """当前账号下所有角色中，最早一次「有效」计划执行时间（含 sched_window 等）。"""
    from services.core.scheduler import (
        collect_active_times_from_tasks_tree,
        next_display_timestamp_from_times,
    )

    ac = cfg.active_character()
    active_server = ac.get('server', '')
    active_name = ac.get('name', '')
    chars = cfg._account_data.get('characters', {})
    candidates: list[float] = []
    for srv, srv_chars in chars.items():
        for char_name, char_data in srv_chars.items():
            if srv == active_server and char_name == active_name:
                tasks_tree = cfg._config.get('tasks', {})
            else:
                tasks_tree = char_data.get('tasks', {})
            times = collect_active_times_from_tasks_tree(tasks_tree)
            nxt = next_display_timestamp_from_times(times)
            if nxt is not None:
                candidates.append(nxt)
    if not candidates:
        return None
    return min(candidates)


def _all_characters_tasks_summary() -> dict:
    """Build task summary for every character in the current account."""
    from services.core.scheduler import (
        collect_active_times_from_tasks_tree,
        next_display_timestamp_from_times,
    )

    now_ts = _time.time()
    ac = cfg.active_character()
    active_server = ac.get('server', '')
    active_name = ac.get('name', '')
    chars = cfg._account_data.get('characters', {})
    result = {}
    for srv, srv_chars in chars.items():
        srv_result = {}
        for char_name, char_data in srv_chars.items():
            if srv == active_server and char_name == active_name:
                tasks_tree = cfg._config.get('tasks', {})
            else:
                tasks_tree = char_data.get('tasks', {})
            flat = _flatten_tasks(tasks_tree, now_ts)
            counts = {'total': 0, 'pending': 0, 'scheduled': 0, 'error': 0, 'disabled': 0}
            for t in flat:
                counts['total'] += 1
                counts[t['status']] += 1
            times = collect_active_times_from_tasks_tree(tasks_tree)
            next_exec = next_display_timestamp_from_times(times)
            srv_result[char_name] = {**counts, 'tasks_flat': flat, 'next_execution': next_exec}
        result[srv] = srv_result
    return result


# ── FastAPI 应用 ──

app = FastAPI(title="AutoScriptor WebUI")


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """WebUI 密码保护中间件 — 使用安全会话令牌验证，仅拦截 /api/ 请求"""
    password = cfg._config.get("deploy", {}).get("password")
    if password and request.url.path.startswith("/api/"):
        exempt = ("/api/auth", "/api/deploy")
        if not any(request.url.path.startswith(p) for p in exempt):
            token = request.cookies.get("auth_token") or request.headers.get("X-Auth-Token")
            if not _validate_session(token):
                return JSONResponse(status_code=401, content={"error": "unauthorized"})
    return await call_next(request)


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
from services.webui.routes.editor import router as editor_router
app.include_router(editor_router)

# 画布 API 路由
from services.webui.routes.canvas import router as canvas_router
app.include_router(canvas_router)

# 资讯 API 路由
from services.webui.routes.news import router as news_router
app.include_router(news_router)

# 开发环境：对 /static/ 下的 JS/CSS 禁用浏览器缓存，改文件后刷新即生效
@app.middleware("http")
async def no_cache_static_js_css(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/static/") and path.endswith((".js", ".css")):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response

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
        try:
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
        except Exception:
            pass
        await asyncio.sleep(0.5)


@app.on_event("startup")
async def _on_startup():
    asyncio.create_task(_log_broadcaster())


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
    return JSONResponse(status_code=404, content={})


# ── API 路由 ──

@app.get("/api/refresh")
async def refresh_config_api():
    try:
        TASK_MANAGER.reload_tasks()
        read_config()
        _apply_webui_log_level_from_config()
        return make_public_config()
    except Exception as e:
        logger.error("refresh error: %s", e)
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/config")
async def save_config_api(request: Request):
    data = await request.json()
    cfg["app"] = data["app"]
    cfg["emulator"] = data["emulator"]
    cfg["ocr"] = data["ocr"]
    cfg.save_config()
    return JSONResponse(status_code=204, content=None)


@app.post("/api/tasks")
async def save_tasks_api(request: Request):
    try:
        payload = await request.json()
        tasks = payload.get('tasks', payload)
        if not isinstance(tasks, dict):
            return JSONResponse(status_code=400, content={"error": "invalid tasks payload"})
        _strip_runtime_tasks_fields(tasks)
        try:
            TASK_MANAGER._cfg_lock.acquire()
            cfg._config.setdefault('tasks', {})
            cfg._config['tasks'] = tasks
            cfg.save_config()
            TASK_MANAGER.reload_tasks()
        finally:
            try:
                TASK_MANAGER._cfg_lock.release()
            except Exception:
                pass
        read_config()
        return make_public_config()
    except Exception as e:
        logger.error("save_tasks error: %s", e)
        return JSONResponse(status_code=500, content={"error": str(e)})


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
        with TASK_MANAGER._cfg_lock:
            cfg.switch_character(server, character)
            TASK_MANAGER.reload_tasks()
        scheduler.invalidate_login()
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
    global RUN_THREAD

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

    err = _apply_run_character_from_body(body)
    if err is not None:
        return err

    character_name = cfg._config.get("game", {}).get("character_name", "")
    if not character_name:
        return JSONResponse(status_code=403,
                            content={'status': 'error', 'message': '请先验证账号密码后再执行任务'})

    tasks = body.get("tasks", [])
    activate_sched = body.get("activate_scheduler", True)

    logger.debug("Received tasks: %s, activate_scheduler: %s", tasks, activate_sched)
    sorted_tasks = sorted(tasks, key=lambda x: ORDER_MAP.get(x, float('inf')))

    direct_busy = RUN_THREAD is not None and RUN_THREAD.is_alive()
    if activate_sched:
        if direct_busy:
            return JSONResponse(
                status_code=409,
                content={
                    "status": "error",
                    "message": "单任务或队列正在直接执行中，请先终止后再启动调度",
                },
            )
        scheduler.activate()
        scheduler.wake()
        return {'status': 'ok', 'tasks': sorted_tasks, 'mode': 'scheduler'}

    if direct_busy:
        return JSONResponse(
            status_code=409,
            content={
                "status": "error",
                "message": "已有任务正在执行，请先终止后再试",
            },
        )
    if scheduler.state == SchedulerState.RUNNING:
        return JSONResponse(
            status_code=409,
            content={
                "status": "error",
                "message": "调度器运行中，请先停止调度或结束当前调度周期后再执行单任务",
            },
        )

    def _run(ts):
        scheduler.run_direct(ts)
        logger.info("========== 所有任务执行完成 ==========")

    RUN_THREAD = Thread(target=_run, args=(sorted_tasks,), daemon=True)
    RUN_THREAD.start()
    _set_thread_high_priority(RUN_THREAD)
    return {'status': 'ok', 'tasks': sorted_tasks, 'mode': 'direct'}


@app.get("/api/run/status")
async def run_status_api():
    """直接执行任务使用的后台线程是否仍在运行（与调度器 state 无关）。"""
    alive = RUN_THREAD is not None and RUN_THREAD.is_alive()
    return {"running": alive}


@app.post("/api/stop")
async def stop_tasks_api():
    global RUN_THREAD
    try:
        def _async_raise(tid, exctype):
            if not isinstance(exctype, type):
                raise TypeError("Only types can be raised (not instances)")
            res = ctypes.pythonapi.PyThreadState_SetAsyncExc(
                ctypes.c_long(tid), ctypes.py_object(exctype))
            if res == 0:
                return False
            if res != 1:
                ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_long(tid), None)
                return False
            return True

        alive = RUN_THREAD.is_alive() if RUN_THREAD else False
        # 无论线程注入是否成功，都要设置取消事件 + 让调度器回到 PENDING
        # （PyThreadState_SetAsyncExc 在 C 扩展阻塞时不可靠，必须双保险）
        TASK_MANAGER.request_cancel()
        scheduler.deactivate()
        if alive and RUN_THREAD.ident:
            _async_raise(RUN_THREAD.ident, KeyboardInterrupt)
        logger.info("⏹ 已发送终止信号")
        return {'status': 'stopping' if alive else 'idle'}
    except Exception as e:
        logger.error("stop error: %s", e)
        return JSONResponse(status_code=500, content={'error': str(e)})


@app.get("/api/credential/status")
async def credential_status_api(request: Request):
    """前端同步「是否已通过安全密码解锁」——以服务端 HttpOnly Cookie 为准，避免 sessionStorage 误放行。"""
    tok = _credential_unlock_from_request(request)
    return {"unlocked": _validate_credential_unlock(tok)}


@app.post("/api/credential/revoke")
async def credential_revoke_api(request: Request):
    """用户主动「重新验证」时吊销解锁令牌并清除 Cookie。"""
    old = _credential_unlock_from_request(request)
    _revoke_credential_unlock(old)
    resp = JSONResponse(content={"status": "ok"})
    return _clear_credential_unlock_cookie(resp)


@app.post("/api/verify")
async def verify_account_api(request: Request):
    client_ip = request.client.host if request.client else "unknown"
    if _is_verify_rate_limited(client_ip):
        return JSONResponse(status_code=429, content={"error": "验证尝试过多，请5分钟后再试"})

    data = await request.json()
    if not _check_request_freshness(data):
        return JSONResponse(status_code=400, content={"error": "请求已过期，请重试"})
    security_key = data.get("security_key", "")
    enc = cfg._account_data.get("encryption", {})
    has_enc = bool(enc.get("encrypted_data"))
    if has_enc and not str(security_key).strip():
        return JSONResponse(status_code=401, content={"error": "请输入安全密码"})

    try:
        TASK_MANAGER.reload_tasks(security_key)
    except Exception as e:
        logger.error("verify reload_tasks: %s", e)
        return JSONResponse(status_code=500, content={"error": "加载配置失败"})

    cfg._config.setdefault("game", {})
    ac = cfg.active_character()
    character_name = cfg._config.get("game", {}).get("character_name", "")
    if not character_name:
        character_name = ac.get("name", "")
        if character_name:
            cfg._config["game"]["character_name"] = character_name

    server_name = cfg._config.get("game", {}).get("server_name", "")
    if not server_name:
        server_name = ac.get("server", "")
        if server_name:
            cfg._config["game"]["server_name"] = server_name

    if has_enc:
        if not cfg._config.get("game", {}).get("account"):
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
    resp = JSONResponse(
        content={
            "character_name": character_name,
            "active_character": cfg.active_character(),
        }
    )
    return _attach_credential_unlock_cookie(resp, tok)


@app.post("/api/account")
async def update_account_credentials_api(request: Request):
    """Update the encryption (account/password) for the current account."""
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

    existing_enc = cfg._account_data.get("encryption", {})
    if existing_enc.get("encrypted_data"):
        if not current_security_key:
            return JSONResponse(status_code=403, content={
                "error": "修改账密需要先验证当前安全密码",
                "need_current_key": True,
            })
        try:
            from AutoScriptor.crypto.config_manager import ConfigManager
            decrypted = ConfigManager.decrypt_data(existing_enc, current_security_key)
            if not decrypted:
                _record_verify_failure(client_ip)
                return JSONResponse(status_code=401, content={"error": "当前安全密码验证失败"})
        except Exception:
            _record_verify_failure(client_ip)
            return JSONResponse(status_code=401, content={"error": "当前安全密码验证失败"})

    existing_name = cfg._config.get("game", {}).get("character_name", "")
    if existing_name and not confirmed:
        return {
            "need_confirm": True,
            "message": f"更新账密会覆盖当前已有的加密设置（当前角色: {existing_name}），是否继续？"
        }
    try:
        from AutoScriptor.crypto.config_manager import ConfigManager
        sensitive = {"account": account, "password": password}
        cfg._account_data["encryption"] = ConfigManager.encrypt_data(sensitive, security_key)
        cfg._save_account_file()
        TASK_MANAGER.reload_tasks(security_key)
        character_name = cfg._config.get("game", {}).get("character_name", "")
    except Exception as e:
        logger.error("update_account error: %s", e)
        return JSONResponse(status_code=500, content={"error": str(e)})
    old_tok = _credential_unlock_from_request(request)
    _revoke_credential_unlock(old_tok)
    tok = _grant_credential_unlock()
    resp = JSONResponse(content={"character_name": character_name})
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
            return JSONResponse(status_code=400, content={'error': 'paths must be a list'})
        result = {}
        for p in paths:
            try:
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
                        and not battle_flow_allowed_for_task(m.value, task_path)
                    ):
                        continue
                    opts.append({"value": m.name, "label": label})
                result[p] = opts
            except Exception:
                result[p] = []
        return result
    except Exception as e:
        logger.error("enum_options error: %s", e)
        return JSONResponse(status_code=500, content={'error': str(e)})


@app.get("/api/ocr-status")
async def ocr_status_api():
    try:
        import paddle
        try:
            from AutoScriptor.recognition.ocr_rec import ocr_manager
        except Exception:
            ocr_manager = None
        compiled_with_cuda = False
        gpu_count = 0
        current_device = "unknown"
        try:
            compiled_with_cuda = paddle.device.is_compiled_with_cuda()
        except Exception:
            pass
        try:
            gpu_count = paddle.device.cuda.device_count()
        except Exception:
            pass
        try:
            current_device = paddle.get_device()
        except Exception:
            pass
        cfg_use_gpu = False
        try:
            cfg_use_gpu = bool(cfg["ocr"].get("use_gpu", cfg.get("ocr.use_gpu", False)))
        except Exception:
            cfg_use_gpu = False
        engine_ready = False
        try:
            engine_ready = ocr_manager.is_ready() if ocr_manager else False
        except Exception:
            pass
        return {
            "cfg_use_gpu": cfg_use_gpu,
            "compiled_with_cuda": compiled_with_cuda,
            "gpu_count": gpu_count,
            "current_device": current_device,
            "engine_ready": engine_ready,
        }
    except Exception as e:
        logger.error("ocr_status error: %s", e)
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/scheduler/status")
async def scheduler_status_api():
    return scheduler.status_dict()


@app.post("/api/scheduler/reset")
async def scheduler_reset_api():
    scheduler.reset()
    return scheduler.status_dict()


@app.post("/api/scheduler/deactivate")
async def scheduler_deactivate_api():
    """仅将调度器切回待运行，不取消直接执行线程、不发送 cancel。"""
    scheduler.deactivate()
    return scheduler.status_dict()


@app.get("/api/overview")
async def overview_data_api():
    try:
        from services.core.scheduler import is_task_due, calc_effective_next_time

        now_ts = _time.time()
        total = enabled = pending = scheduled = disabled = 0
        upcoming = []

        def _walk(node, prefix=''):
            nonlocal total, enabled, pending, scheduled, disabled
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
                        due = is_task_due(val, path, now_ts)
                        if due:
                            pending += 1
                        else:
                            scheduled += 1
                        nxt_display = calc_effective_next_time(val, now_ts)
                        upcoming.append({
                            'path': path,
                            'on': True,
                            'next_exec_time': nxt_display,
                            'status': 'pending' if due else 'scheduled',
                        })
                else:
                    _walk(val, path)

        _walk(cfg._config.get('tasks', {}))
        upcoming.sort(key=lambda x: (0 if x['status'] == 'pending' else 1, x['next_exec_time']))

        next_ts = scheduler.get_next_execution_timestamp()
        sched = scheduler.status_dict()
        sched['next_execution'] = next_ts

        stats_all = _aggregate_stats_all_characters(now_ts)
        overall_next = _overall_next_execution_all_characters()

        runtime_status = {}
        try:
            from services.core.runtime_context import runtime_ctx
            runtime_status = runtime_ctx.status_dict()
        except Exception:
            pass

        return {
            'scheduler': sched,
            'stats': {
                'total': total, 'enabled': enabled, 'pending': pending,
                'scheduled': scheduled, 'disabled': disabled,
            },
            'stats_all': stats_all,
            'overall_next_execution': overall_next,
            'upcoming': upcoming[:30],
            'runtime': runtime_status,
        }
    except Exception as e:
        logger.error("overview error: %s", e)
        return JSONResponse(status_code=500, content={'error': str(e)})


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
    data = await request.json()
    cfg["notify.enabled"] = data.get("enabled", False)
    cfg["notify.config_yaml"] = data.get("config_yaml", "provider: null")
    cfg.save_config()
    return {"status": "ok"}


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
    from services.core.updater import updater
    ok = updater.run_update()
    return {"success": ok, **updater.get_status()}


# ── 内容增量更新（bsdiff / manifest，与 Git 更新独立）──

@app.get("/api/content-update/status")
async def content_update_status_api():
    from services.core.content_delta_update import content_delta_updater
    return content_delta_updater.get_status()


@app.post("/api/content-update/check")
async def content_update_check_api(request: Request):
    client_ip = request.client.host if request.client else "unknown"
    if not _content_update_check_limiter.allow(client_ip):
        return JSONResponse(
            status_code=429,
            content={"error": "检查更新过于频繁，请稍后再试"},
        )
    from services.core.content_delta_update import content_delta_updater
    has_update, message = content_delta_updater.check_has_update()
    return {
        "has_update": has_update,
        "message": message,
        **content_delta_updater.get_status(),
    }


@app.post("/api/content-update/apply")
async def content_update_apply_api(request: Request):
    client_ip = request.client.host if request.client else "unknown"
    from services.core.content_delta_update import content_delta_updater

    rem_cd = content_delta_updater.apply_cooldown_remaining_sec()
    if rem_cd > 0:
        return JSONResponse(
            status_code=429,
            content={
                "error": f"全机冷却中，约 {int(rem_cd) + 1} 秒后再试",
                "apply_cooldown_remaining_sec": round(rem_cd, 1),
            },
        )
    if not _content_update_apply_min_interval.allow(client_ip):
        return JSONResponse(
            status_code=429,
            content={"error": "操作过于频繁，请稍后再试"},
        )
    if not _content_update_apply_limiter.allow(client_ip):
        return JSONResponse(
            status_code=429,
            content={"error": "应用更新过于频繁，请稍后再试"},
        )
    if content_delta_updater.requires_credential_unlock():
        cred_err = _require_credential_unlock(request)
        if cred_err is not None:
            return cred_err
    ok = content_delta_updater.apply_manifest()
    return {"success": ok, **content_delta_updater.get_status()}


# ── 远程访问 API ──

@app.get("/api/remote-access")
async def remote_access_status_api():
    from services.core.remote_access import RemoteAccess
    return RemoteAccess.get_status()


@app.post("/api/remote-access")
async def remote_access_toggle_api(request: Request):
    data = await request.json()
    from services.core.remote_access import RemoteAccess
    if data.get("enabled"):
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
        "characters": _characters_summary(),
    }


@app.post("/api/accounts/switch")
async def accounts_switch_api(request: Request):
    data = await request.json()
    if not _check_request_freshness(data):
        return JSONResponse(status_code=400, content={"error": "请求已过期，请重试"})
    name = data.get("name", "")
    security_key = data.get("security_key", "")

    if not security_key:
        return JSONResponse(status_code=400, content={
            "error": "请输入安全密码以切换账号", "need_security_key": True,
        })
    try:
        cfg.switch_account(name, security_key)
        TASK_MANAGER.reload_tasks(security_key)
        scheduler.invalidate_login()
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
                "characters": _characters_summary(),
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
    data = await request.json()
    name = str(data.get("name", "") or "").strip()
    account = str(data.get("account", "") or "").strip()
    password = str(data.get("password", "") or "").strip()
    server = str(data.get("server", "") or "").strip()
    character_name = str(data.get("character_name", "") or "").strip()
    security_key = str(data.get("security_key", "") or "").strip()

    if not name:
        return JSONResponse(status_code=400, content={"error": "账号名称不能为空"})
    if not account:
        return JSONResponse(status_code=400, content={"error": "游戏账号不能为空"})
    if not password:
        return JSONResponse(status_code=400, content={"error": "游戏密码不能为空"})
    if not server:
        return JSONResponse(status_code=400, content={"error": "服务器不能为空"})
    if not character_name:
        return JSONResponse(status_code=400, content={"error": "角色名不能为空"})
    if not security_key:
        return JSONResponse(status_code=400, content={"error": "安全密码不能为空"})

    try:
        cfg.add_account(name, account, password, server, character_name, security_key)
        return {"accounts": cfg.list_accounts()}
    except Exception as e:
        logger.error("add account error: %s", e)
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/accounts/delete")
async def accounts_delete_api(request: Request):
    data = await request.json()
    name = data.get("name", "")
    try:
        cfg.delete_account(name)
        return {"accounts": cfg.list_accounts(), "current_account": cfg.current_account()}
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})


# ── 角色管理 API ──

@app.get("/api/characters")
async def characters_list_api():
    return {
        "active_character": cfg.active_character(),
        "characters": _characters_summary(),
    }


@app.post("/api/characters/switch")
async def characters_switch_api(request: Request):
    data = await request.json()
    if not _check_request_freshness(data):
        return JSONResponse(status_code=400, content={"error": "请求已过期，请重试"})
    server = data.get("server", "")
    character = data.get("character", "")
    try:
        cfg.switch_character(server, character)
        TASK_MANAGER.reload_tasks()
        scheduler.invalidate_login()
        return {
            "active_character": cfg.active_character(),
            "character_name": character,
            "characters": _characters_summary(),
        }
    except (KeyError, ValueError) as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    except Exception as e:
        logger.error("switch character error: %s", e)
        return JSONResponse(status_code=500, content={"error": "切换角色失败"})


@app.post("/api/characters/add")
async def characters_add_api(request: Request):
    data = await request.json()
    server = data.get("server", "")
    character = data.get("character", "")
    try:
        cfg.add_character(server, character)
        return {
            "active_character": cfg.active_character(),
            "characters": _characters_summary(),
        }
    except (ValueError, KeyError) as e:
        return JSONResponse(status_code=400, content={"error": str(e)})


@app.post("/api/characters/delete")
async def characters_delete_api(request: Request):
    data = await request.json()
    server = data.get("server", "")
    character = data.get("character", "")
    try:
        cfg.delete_character(server, character)
        return {
            "active_character": cfg.active_character(),
            "characters": _characters_summary(),
        }
    except (ValueError, KeyError) as e:
        return JSONResponse(status_code=400, content={"error": str(e)})


@app.get("/api/characters/all_tasks_summary")
async def characters_all_tasks_summary_api():
    try:
        return {"characters": _all_characters_tasks_summary()}
    except Exception as e:
        logger.error("all_tasks_summary error: %s", e)
        return JSONResponse(status_code=500, content={"error": str(e)})


# ── 调度队列 API ──

@app.get("/api/dispatch/queue")
async def dispatch_queue_get_api():
    queue = cfg._account_data.get("dispatch_queue", [])
    return {"queue": queue}


@app.post("/api/dispatch/queue")
async def dispatch_queue_save_api(request: Request):
    data = await request.json()
    queue = data.get("queue", [])
    cfg._account_data["dispatch_queue"] = queue
    cfg._save_account_file()
    return {"queue": queue}


# ── 兼容旧前端的 profiles API（转发到 accounts） ──

@app.get("/api/profiles")
async def profiles_list_api():
    return {
        "current": cfg.current_account(),
        "profiles": cfg.list_accounts(),
    }


@app.post("/api/profiles/switch")
async def profiles_switch_api(request: Request):
    data = await request.json()
    if not _check_request_freshness(data):
        return JSONResponse(status_code=400, content={"error": "请求已过期，请重试"})
    name = data.get("name", "")
    security_key = data.get("security_key", "")
    if not security_key:
        return JSONResponse(status_code=400, content={
            "error": "请输入安全密码以切换账号", "need_security_key": True,
        })
    try:
        cfg.switch_account(name, security_key)
        TASK_MANAGER.reload_tasks(security_key)
        scheduler.invalidate_login()
        character_name = cfg._config.get("game", {}).get("character_name", "")
        old_tok = _credential_unlock_from_request(request)
        _revoke_credential_unlock(old_tok)
        tok = _grant_credential_unlock()
        resp = JSONResponse(content={"current": name, "character_name": character_name})
        return _attach_credential_unlock_cookie(resp, tok)
    except KeyError as e:
        return JSONResponse(status_code=404, content={"error": str(e)})
    except Exception as e:
        logger.error("switch profile error: %s", e)
        return JSONResponse(status_code=500, content={"error": "切换失败，请检查安全密码是否正确"})


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
    try:
        data = await request.json()
        if not isinstance(data, dict):
            return JSONResponse(status_code=400, content={"error": "invalid JSON"})
        data.pop("encryption", None)
        data.pop("current_profile", None)
        data.pop("current_account", None)
        data.pop("profiles", None)
        data.pop("game", None)
        data.pop("active_character", None)
        data.pop("characters_summary", None)
        if "deploy" in data and isinstance(data["deploy"], dict):
            data["deploy"].pop("password", None)
            data["deploy"].pop("ssl_key", None)
            data["deploy"].pop("ssl_cert", None)
        for key in ("app", "emulator", "ocr", "llm", "tasks", "deploy", "notify", "update", "remote_access"):
            if key in data:
                val = data[key]
                if key == "tasks" and isinstance(val, dict):
                    _strip_runtime_tasks_fields(val)
                cfg._config[key] = val
        cfg.save_config()
        TASK_MANAGER.reload_tasks()
        read_config()
        return {"status": "ok"}
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
        media = "image/png" if suffix == ".png" else "image/jpeg" if suffix in (".jpg", ".jpeg") else "application/octet-stream"
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
            cfg._config[section] = data[section]
    cfg.save_config()
    _apply_webui_log_level_from_config()
    return {"status": "ok"}


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

    # ── 设备 / 运行时初始化（与 run.py CLI 入口对齐） ──
    from AutoScriptor.core.api import init as _init_env
    _init_env()

    from services.core.runtime_context import runtime_ctx
    from AutoScriptor.core.api import mixctrl, mumu
    runtime_ctx.init(mixctrl, mumu)
    runtime_ctx.init_bg()
    runtime_ctx.init_vlm()

    from ZmxyOL.task import load_tasks
    load_tasks()

    _ensure_vendor_files()
    read_config()
    _apply_webui_log_level_from_config()
    _print_banner()

    # 启动自动更新检查 & 传递重启事件
    try:
        from services.core.updater import updater as _updater
        if restart_event is not None:
            _updater.set_restart_event(restart_event)
        interval = cfg.get("update.check_interval_minutes", 30)
        if cfg.get("update.auto_check", True) and interval > 0:
            _updater.start_scheduled_check(interval)
    except Exception as e:
        logger.debug("自动更新检查启动失败: %s", e)

    webbrowser.open("http://127.0.0.1:5000")

    # Allow Electron to request info-level logs so it can detect startup completion
    log_level = os.environ.get('UVICORN_LOG_LEVEL', 'warning')
    ssl_key = cfg.get("deploy.ssl_key")
    ssl_cert = cfg.get("deploy.ssl_cert")
    config = uvicorn.Config(
        app, host="127.0.0.1", port=5000, log_level=log_level,
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

    try:
        scheduler.deactivate()
    except Exception:
        pass
    try:
        scheduler.stop(timeout=3)
    except Exception:
        pass
    try:
        from AutoScriptor.utils.perf import unboost
        unboost()
    except Exception:
        pass
    try:
        from services.core.runtime_context import runtime_ctx
        if runtime_ctx.bg is not None:
            runtime_ctx.bg.stop()
        runtime_ctx.shutdown()
    except Exception:
        pass
    try:
        if _server:
            _server.should_exit = True
    except Exception:
        pass


if __name__ == '__main__':
    try:
        run_webui()
    except Exception as e:
        logger.error("Error: %s", e)
        traceback.print_exc()
        logger.info("程序已退出")
    finally:
        shutdown_webui()
