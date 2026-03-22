"""
协作式任务取消
==============
与 services.core.task_manager.TaskManager._cancel_event 绑定后，
在 locate/click/sleep 等热点路径中检查并抛出 TaskCancelled。
"""

from __future__ import annotations

import threading
import time
from typing import Optional

_ev: Optional[threading.Event] = None


class TaskCancelled(Exception):
    """用户请求终止当前任务（WebUI 停止 / 调度器 request_cancel）。"""


def bind_cancel_event(ev: Optional[threading.Event]) -> None:
    """由 TaskManager.__init__ 注册全局取消事件（单例覆盖）。"""
    global _ev
    _ev = ev


def check_cancel_raise() -> None:
    """若已请求取消则抛出 TaskCancelled。"""
    if _ev is not None and _ev.is_set():
        raise TaskCancelled("任务已终止")


def cancellable_sleep(seconds: float, chunk: float = 0.05) -> None:
    """可响应取消的 sleep，将长等待拆成小段并在每段前检查取消。"""
    end = time.time() + seconds
    while True:
        check_cancel_raise()
        remaining = end - time.time()
        if remaining <= 0:
            return
        time.sleep(min(chunk, remaining))
