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
from services.core.task_manager import TaskManager
from services.core.banner import _print_banner
from services.core.scheduler import scheduler, SchedulerState
from AutoScriptor.utils.perf import set_thread_high_priority as _set_thread_high_priority

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
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

sse_log_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'logs'))
os.makedirs(sse_log_dir, exist_ok=True)
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
    SESSION_TTL as _SESSION_TTL,
)


def _is_rate_limited(ip: str) -> bool:
    return _login_limiter.is_limited(ip)


def _record_login_failure(ip: str):
    _login_limiter.record_failure(ip)


def _is_verify_rate_limited(ip: str) -> bool:
    return _verify_limiter.is_limited(ip)


def _record_verify_failure(ip: str):
    _verify_limiter.record_failure(ip)


# ── Vendor 文件管理 ──

_HERE = os.path.dirname(__file__)
VENDOR_DIR = os.path.join(_HERE, 'vendor')
STATIC_DIR = os.path.join(_HERE, 'static')
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
    """将 TaskRegistry 中的 param_meta 挂到任务叶节点，供 WebUI 枚举下拉使用（仅用于 API 返回副本）。"""
    from AutoScriptor.utils.task_registry import task_registry
    from services.core.task_tree import TaskTree

    for key, val in node.items():
        if not isinstance(val, dict):
            continue
        path = f"{prefix}/{key}" if prefix else key
        if TaskTree.is_leaf(val):
            meta = task_registry.get_param_meta(path)
            if meta:
                val["param_meta"] = meta
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
            val.pop("fn", None)
            val.pop("order", None)
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
    return config_data


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
        session_token = _create_session()
        resp = JSONResponse(content={"status": "ok"})
        resp.set_cookie(
            "auth_token", session_token,
            httponly=True, samesite="strict", max_age=_SESSION_TTL,
        )
        return resp

    _record_login_failure(client_ip)
    remaining = _MAX_LOGIN_FAILURES - len(_login_failures.get(client_ip, []))
    return JSONResponse(status_code=401, content={
        "error": f"密码错误（剩余 {max(remaining, 0)} 次尝试）"
    })


# 编辑器 API 路由
from services.webui.routes.editor import router as editor_router
app.include_router(editor_router)

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


@app.post("/api/run")
async def run_tasks_api(request: Request):
    global RUN_THREAD

    character_name = cfg._config.get("game", {}).get("character_name", "")
    if not character_name:
        return JSONResponse(status_code=403,
                            content={'status': 'error', 'message': '请先验证账号密码后再执行任务'})

    body = await request.json()

    if isinstance(body, dict):
        tasks = body.get("tasks", [])
        activate_sched = body.get("activate_scheduler", True)
    else:
        tasks = body
        activate_sched = True

    logger.debug("Received tasks: %s, activate_scheduler: %s", tasks, activate_sched)
    sorted_tasks = sorted(tasks, key=lambda x: ORDER_MAP.get(x, float('inf')))

    if activate_sched:
        scheduler.activate()
        scheduler.wake()
        return {'status': 'ok', 'tasks': sorted_tasks, 'mode': 'scheduler'}

    def _run(ts):
        scheduler.run_direct(ts)
        logger.info("========== 所有任务执行完成 ==========")

    RUN_THREAD = Thread(target=_run, args=(sorted_tasks,), daemon=True)
    RUN_THREAD.start()
    _set_thread_high_priority(RUN_THREAD)
    return {'status': 'ok', 'tasks': sorted_tasks, 'mode': 'direct'}


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


@app.post("/api/verify")
async def verify_account_api(request: Request):
    client_ip = request.client.host if request.client else "unknown"
    if _is_verify_rate_limited(client_ip):
        return JSONResponse(status_code=429, content={"error": "验证尝试过多，请5分钟后再试"})

    data = await request.json()
    if not _check_request_freshness(data):
        return JSONResponse(status_code=400, content={"error": "请求已过期，请重试"})
    security_key = data.get('security_key', '')
    TASK_MANAGER.reload_tasks(security_key)
    cfg._config.setdefault('game', {})
    character_name = cfg["game"].get("character_name", "")
    if not character_name and security_key:
        _record_verify_failure(client_ip)
    cfg._config['game']['character_name'] = character_name
    return {"character_name": character_name}


@app.post("/api/account")
async def add_account_api(request: Request):
    data = await request.json()
    if not _check_request_freshness(data):
        return JSONResponse(status_code=400, content={"error": "请求已过期，请重试"})

    client_ip = request.client.host if request.client else "unknown"
    if _is_verify_rate_limited(client_ip):
        return JSONResponse(status_code=429, content={"error": "操作过于频繁，请5分钟后再试"})

    account = data.get('account', '')
    password = data.get('password', '')
    character_name = data.get('character_name', '')
    security_key = data.get('security_key', '')
    confirmed = data.get('confirmed', False)
    current_security_key = data.get('current_security_key', '')

    existing_enc = cfg._config.get("encryption", {})
    if existing_enc.get("encrypted_data"):
        if not current_security_key:
            return JSONResponse(status_code=403, content={
                "error": "修改账密需要先验证当前安全密码",
                "need_current_key": True,
            })
        try:
            from AutoScriptor.crypto.config_manager import ConfigManager
            cm = ConfigManager(cfg.CONFIG_PATH)
            decrypted = cm.decrypt_config(current_security_key)
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
            "message": f"更新账密会覆盖当前已有的设置（当前角色: {existing_name}），是否继续？"
        }
    try:
        from AutoScriptor.crypto.update_config import config_manager
        config_manager.update_game_config(account, password, character_name, security_key)
        TASK_MANAGER.reload_tasks(security_key)
        character_name = cfg["game"].get("character_name", "")
    except Exception as e:
        logger.error("add_account error: %s", e)
    return {"character_name": character_name}


@app.post("/api/enum-options")
async def enum_options_api(request: Request):
    try:
        data = await request.json()
        paths = data.get('paths', [])
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


@app.get("/api/overview")
async def overview_data_api():
    try:
        from services.core.task_manager import (
            parse_sched_window_hours,
            clamp_to_sched_window,
            parse_allowed_weekdays,
            calc_next_allowed_weekday_ts,
        )

        now_ts = _time.time()
        total = enabled = pending = completed = disabled = 0
        upcoming = []

        def _walk(node, prefix=''):
            nonlocal total, enabled, pending, completed, disabled
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
                        nxt = val.get('next_exec_time', 0)
                        if nxt <= now_ts:
                            pending += 1
                        else:
                            completed += 1
                        sw = parse_sched_window_hours(val)
                        nxt_show = clamp_to_sched_window(max(nxt, now_ts), sw[0], sw[1]) if sw else nxt
                        aw = parse_allowed_weekdays(val)
                        if aw is not None:
                            import datetime as _dt
                            now_dt = _dt.datetime.fromtimestamp(now_ts)
                            wd = now_dt.weekday() + 1
                            if nxt_show <= now_ts and wd not in set(aw):
                                nxt_show = calc_next_allowed_weekday_ts(now_dt, aw)
                            elif nxt_show > now_ts:
                                tdt = _dt.datetime.fromtimestamp(nxt_show)
                                if (tdt.weekday() + 1) not in set(aw):
                                    nxt_show = calc_next_allowed_weekday_ts(tdt, aw)
                        upcoming.append({
                            'path': path,
                            'on': val.get('on', False),
                            'next_exec_time': nxt_show,
                            'status': 'pending' if nxt <= now_ts else 'completed',
                        })
                else:
                    _walk(val, path)

        _walk(cfg._config.get('tasks', {}))
        upcoming.sort(key=lambda x: (0 if x['status'] == 'pending' else 1, x['next_exec_time']))

        next_ts = scheduler.get_next_execution_timestamp()
        sched = scheduler.status_dict()
        sched['next_execution'] = next_ts

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
                'completed': completed, 'disabled': disabled,
            },
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


# ── 多账号档案 API ──

@app.get("/api/profiles")
async def profiles_list_api():
    return {
        "current": cfg.current_profile(),
        "profiles": cfg.list_profiles(),
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
            "error": "请输入安全密码以切换档案", "need_security_key": True,
        })
    try:
        cfg.switch_profile(name, security_key)
        TASK_MANAGER.reload_tasks(security_key)
        character_name = cfg._config.get("game", {}).get("character_name", "")
        return {"current": name, "character_name": character_name}
    except KeyError as e:
        return JSONResponse(status_code=404, content={"error": str(e)})
    except Exception as e:
        logger.error("switch profile error: %s", e)
        return JSONResponse(status_code=500, content={"error": "切换失败，请检查安全密码是否正确"})


@app.post("/api/profiles/add")
async def profiles_add_api(request: Request):
    data = await request.json()
    name = data.get("name", "")
    if not name:
        return JSONResponse(status_code=400, content={"error": "name is required"})

    account = data.get("account", "")
    password = data.get("password", "")
    character_name = data.get("character_name", "")
    security_key = data.get("security_key", "")

    if not security_key:
        return JSONResponse(status_code=400, content={"error": "安全密码不能为空"})

    try:
        cfg.add_profile(name, account, password, character_name, security_key)
        return {"profiles": cfg.list_profiles()}
    except Exception as e:
        logger.error("add profile error: %s", e)
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/profiles/delete")
async def profiles_delete_api(request: Request):
    data = await request.json()
    name = data.get("name", "")
    try:
        cfg.delete_profile(name)
        return {"profiles": cfg.list_profiles(), "current": cfg.current_profile()}
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})


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
        data.pop("profiles", None)
        data.pop("game", None)
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


def run_webui():
    """阻塞式启动 uvicorn 服务。"""
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

    # 启动自动更新检查
    try:
        from services.core.updater import updater as _updater
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
    _server.run()


def shutdown_webui():
    from AutoScriptor.utils.perf import unboost
    try:
        scheduler.deactivate()
        scheduler.stop()
        unboost()
        bg.stop()
        if _server:
            _server.should_exit = True
    except Exception as e:
        logger.error("shutdown_webui error: %s", e)


if __name__ == '__main__':
    try:
        run_webui()
    except Exception as e:
        logger.error("Error: %s", e)
        traceback.print_exc()
        logger.info("程序已退出")
    finally:
        from AutoScriptor.utils.perf import unboost
        try:
            shutdown_webui()
            unboost()
        except Exception as e:
            logger.error("shutdown_webui error: %s", e)
