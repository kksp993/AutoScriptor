"""The WebUI log stream: what goes to the browser, and at which level.

The file log keeps everything; this module owns the second sink the WebUI reads
over ``/ws/logs``. Two callers need it -- the socket endpoint and the routes that
apply a changed ``deploy.log_level`` -- so the level policy lives here rather
than in whichever module happens to define the queue.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from logging.handlers import RotatingFileHandler
from queue import Empty, Full, Queue
from typing import Any, Set

from AutoScriptor.logging.logger import logger, _TaskFilter
from AutoScriptor.utils.app_config import cfg
from AutoScriptor.utils.paths import get_logs_root


# 仿星铁风格的 ANSI 彩色 Formatter，ansi_up 可正确渲染为彩色 HTML
class ColoredFormatter(logging.Formatter):
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


class QueueHandler(logging.Handler):
    """Push formatted records onto a bounded queue, dropping the oldest first."""

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


# ── file sink ──

_PLAIN_FORMAT = logging.Formatter(
    "%(asctime)s | %(levelname)-8s | %(module)s:%(lineno)d - %(task_prefix)s%(message)s",
    datefmt="%H:%M:%S",
)

# 日志只增不减，而错误归档每次都要回读尾部；给它一个上限，避免无限增长。
_FILE_HANDLER = RotatingFileHandler(
    os.path.join(str(get_logs_root()), 'webui.log'),
    maxBytes=8 * 1024 * 1024,
    backupCount=3,
    encoding='utf-8',
)
_FILE_HANDLER.setLevel(logging.INFO)
_FILE_HANDLER.setFormatter(_PLAIN_FORMAT)
_FILE_HANDLER.addFilter(_TaskFilter())
logger.addHandler(_FILE_HANDLER)


# ── browser sink ──

log_queue: Queue = Queue(maxsize=10000)

queue_handler = QueueHandler(log_queue, level=logging.DEBUG)
queue_handler.setFormatter(ColoredFormatter())
queue_handler.addFilter(_TaskFilter())
logger.addHandler(queue_handler)


def apply_log_level() -> None:
    """Limit what the browser receives to ``deploy.log_level`` (template default info)."""
    raw = (cfg._config.get("deploy") or {}).get("log_level", "debug")
    name = raw.strip().upper() if isinstance(raw, str) else "INFO"
    level = getattr(logging, name, None)
    queue_handler.setLevel(level if isinstance(level, int) else logging.INFO)


apply_log_level()


# ── broadcast ──

ws_clients: Set[Any] = set()


async def broadcast_loop(interval: float = 0.5) -> None:
    """Drain the queue and push it to every connected client."""
    while True:
        batch: list[str] = []
        while True:
            try:
                batch.append(log_queue.get_nowait())
            except Empty:
                break
        if batch:
            payload = json.dumps({"data": "\n".join(batch)})
            dead = set()
            for ws in ws_clients.copy():
                try:
                    await ws.send_text(payload)
                except Exception:
                    dead.add(ws)
            ws_clients.difference_update(dead)
        await asyncio.sleep(interval)
