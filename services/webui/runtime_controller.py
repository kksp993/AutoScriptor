"""Runtime execution state for the WebUI.

This module owns the direct-run thread and exposes a single busy/stopping
source for routes and the frontend. The scheduler still owns scheduled
execution; this controller only composes its state with direct execution.
"""
from __future__ import annotations

from threading import Lock, Thread, current_thread
from typing import Any, Callable, Literal

from AutoScriptor.utils.logger import logger
from services.core.scheduler import Scheduler, SchedulerState
from services.core.task_manager import TaskManager
from services.webui.api_response import api_error

RuntimeReason = Literal["direct_run", "scheduler"]


class RuntimeController:
    def __init__(self, scheduler: Scheduler, task_manager: TaskManager):
        self.scheduler = scheduler
        self.task_manager = task_manager
        self._lock = Lock()
        self._direct_thread: Thread | None = None
        self._stop_requested = False

    def direct_run_alive(self) -> bool:
        with self._lock:
            if self._direct_thread is None:
                return False
            if self._direct_thread.is_alive():
                return True
            self._direct_thread = None
            return False

    def scheduler_busy(self) -> bool:
        return (
            self.scheduler.state == SchedulerState.RUNNING
            or getattr(self.scheduler, "is_executing", False)
        )

    def busy_reason(self) -> RuntimeReason | None:
        if self.direct_run_alive():
            return "direct_run"
        if self.scheduler_busy():
            return "scheduler"
        return None

    def is_busy(self) -> bool:
        return self.busy_reason() is not None

    def status(self) -> dict:
        scheduler_status = self.scheduler.status_dict()
        direct_running = self.direct_run_alive()
        scheduler_busy = self.scheduler_busy()
        reason = "direct_run" if direct_running else "scheduler" if scheduler_busy else None
        if reason is None:
            with self._lock:
                self._stop_requested = False
        stopping = bool(reason and self._stop_requested)
        return {
            "running": reason is not None,
            "busy": reason is not None,
            "stopping": stopping,
            "reason": reason,
            "direct_running": direct_running,
            "scheduler": scheduler_status,
        }

    def busy_response(self, action: str = "modify runtime config"):
        reason = self.busy_reason() or "runtime"
        reason_label = {"direct_run": "直接执行任务", "scheduler": "调度器"}.get(reason, "运行任务")
        return api_error(
            409,
            f"当前{reason_label}正在运行，请先点击「终止执行」再继续操作。",
            code="runtime_busy",
            reason=reason,
            action=action,
        )

    def guard_idle(self, action: str = "modify runtime config"):
        if self.is_busy():
            return self.busy_response(action)
        return None

    def start_direct(
        self,
        target: Callable[[list[Any]], None],
        tasks: list[Any],
    ) -> Thread:
        if self.direct_run_alive():
            raise RuntimeError("direct run is already running")
        with self._lock:
            self._stop_requested = False

        def _wrapped() -> None:
            try:
                target(tasks)
            finally:
                with self._lock:
                    if self._direct_thread is current_thread():
                        self._direct_thread = None
                    self._stop_requested = False

        thread = Thread(target=_wrapped, daemon=True, name="WebUI-DirectRun")
        with self._lock:
            self._direct_thread = thread
        thread.start()
        return thread

    def request_stop(self) -> str:
        direct_alive = self.direct_run_alive()
        scheduler_alive = self.scheduler_busy()
        with self._lock:
            self._stop_requested = direct_alive or scheduler_alive

        self.task_manager.request_cancel()
        self.scheduler.request_stop()
        self.scheduler.invalidate_login()

        logger.info("⏹ 已发送终止信号，等待任务协作退出")
        return "stopping" if (direct_alive or scheduler_alive) else "idle"
