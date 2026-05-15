"""
协作式任务取消
==============
与 services.core.task_manager.TaskManager._cancel_event 绑定后，
在 locate/click/sleep 等热点路径中检查并抛出 TaskCancelled。
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from typing import Callable, Optional

_ev: Optional[threading.Event] = None
_tls = threading.local()


class TaskCancelled(Exception):
    """用户请求终止当前任务（WebUI 停止 / 调度器 request_cancel）。"""


def bind_cancel_event(ev: Optional[threading.Event]) -> None:
    """由 TaskManager.__init__ 注册全局取消事件（单例覆盖）。"""
    global _ev
    _ev = ev


def _cancel_checks_suppressed() -> bool:
    """当前线程是否临时忽略终止检查（如 WebUI 编辑器遥控 / 手动片段）。"""
    return getattr(_tls, "suppress", 0) > 0


@contextmanager
def suppress_cancel_checks():
    """在本线程内暂时不响应终止标记，用于任务已停止后仍允许手动遥控或调试代码。"""
    old = getattr(_tls, "suppress", 0)
    _tls.suppress = old + 1
    try:
        yield
    finally:
        if old:
            _tls.suppress = old
        else:
            delattr(_tls, "suppress")


def check_cancel_raise() -> None:
    """若已请求取消则抛出 TaskCancelled。"""
    if _cancel_checks_suppressed():
        return
    if _ev is not None and _ev.is_set():
        raise TaskCancelled("任务已终止")


def sleep_with_cancel(
    seconds: float,
    cancel_check: Callable[[], None] | None = None,
    chunk: float = 0.05,
) -> None:
    """可响应取消的 sleep；支持传入局部取消检查函数。"""
    check = cancel_check or check_cancel_raise
    end = time.monotonic() + seconds
    while True:
        check()
        remaining = end - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(chunk, remaining))


def join_with_cancel(
    thread: threading.Thread,
    timeout: float,
    cancel_check: Callable[[], None] | None = None,
    chunk: float = 0.1,
) -> None:
    """可响应取消的 thread.join，用于设备探测这类可能卡住的后台调用。"""
    check = cancel_check or check_cancel_raise
    deadline = time.monotonic() + timeout
    while thread.is_alive():
        check()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        thread.join(min(chunk, remaining))


def cancellable_sleep(seconds: float, chunk: float = 0.05) -> None:
    """可响应取消的 sleep，将长等待拆成小段并在每段前检查取消。"""
    sleep_with_cancel(seconds, check_cancel_raise, chunk=chunk)
