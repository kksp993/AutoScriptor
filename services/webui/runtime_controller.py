"""Runtime execution state for the WebUI.

This module owns the direct-run thread and exposes a single busy/stopping
source for routes and the frontend. The scheduler still owns scheduled
execution; this controller only composes its state with direct execution.
"""
from __future__ import annotations

from threading import Lock, Thread, current_thread
from typing import Any, Callable, Literal

from AutoScriptor.utils.logger import logger
from services.core.scheduler import Scheduler
from services.core.task_manager import TaskManager
from services.webui.api_response import api_error

RuntimeReason = Literal["direct_run", "scheduler", "editor"]


class RuntimeExecutionBusyError(RuntimeError):
    """Raised when another participant owns exclusive runtime execution."""


class RuntimeController:
    def __init__(self, scheduler: Scheduler, task_manager: TaskManager):
        self.scheduler = scheduler
        self.task_manager = task_manager
        self._lock = Lock()
        self._direct_thread: Thread | None = None
        self._stop_requested = False
        self._external_status_getters: dict[RuntimeReason, Callable[[], dict[str, Any]]] = {}

    def set_external_status_getter(self, reason: RuntimeReason, getter: Callable[[], dict[str, Any]]) -> None:
        """Register a runtime participant owned outside RuntimeController.

        Editor execution is intentionally implemented in its route module, but
        config mutation guards still need a single busy projection.
        """
        with self._lock:
            self._external_status_getters[reason] = getter

    def direct_run_alive(self) -> bool:
        with self._lock:
            if self._direct_thread is None:
                return False
            if self._direct_thread.is_alive():
                return True
            self._direct_thread = None
            return False

    def scheduler_busy(self) -> bool:
        return bool(getattr(self.scheduler, "is_scheduled_execution", False))

    def _external_statuses(self) -> dict[RuntimeReason, dict[str, Any]]:
        with self._lock:
            status_getters = dict(self._external_status_getters)
        statuses: dict[RuntimeReason, dict[str, Any]] = {}
        for reason, status_getter in status_getters.items():
            try:
                status = status_getter()
            except Exception as exc:
                logger.warning("runtime external status getter failed for %s: %s", reason, exc, exc_info=True)
                continue
            if isinstance(status, dict):
                statuses[reason] = status
        return statuses

    def busy_reason(self) -> RuntimeReason | None:
        if self.direct_run_alive():
            return "direct_run"
        if self.scheduler_busy():
            return "scheduler"
        for reason, status in self._external_statuses().items():
            if status.get("busy") or status.get("running"):
                return reason
        return None

    def is_busy(self) -> bool:
        return self.busy_reason() is not None

    def status(self) -> dict:
        scheduler_status = self.scheduler.status_dict()
        direct_running = self.direct_run_alive()
        scheduler_busy = self.scheduler_busy()
        external_statuses = self._external_statuses()
        external_reason = None
        for candidate_reason, external_status in external_statuses.items():
            if external_status.get("busy") or external_status.get("running"):
                external_reason = candidate_reason
                break
        reason = "direct_run" if direct_running else "scheduler" if scheduler_busy else external_reason
        if reason is None:
            with self._lock:
                self._stop_requested = False
        external_stopping = bool(external_statuses.get(reason, {}).get("stopping")) if reason else False
        stopping = bool(reason and (self._stop_requested or external_stopping))
        current_task_path = None
        current_task_path_getter = getattr(self.task_manager, "current_task_path", None)
        if reason and callable(current_task_path_getter):
            current_task_path = current_task_path_getter()
        return {
            "running": reason is not None,
            "busy": reason is not None,
            "stopping": stopping,
            "reason": reason,
            "direct_running": direct_running,
            "current_task_path": current_task_path,
            "external": external_statuses,
            "scheduler": scheduler_status,
        }

    def busy_response(self, action: str = "modify runtime config"):
        reason = self.busy_reason() or "runtime"
        reason_label = {"direct_run": "直接执行任务", "scheduler": "调度器", "editor": "编辑器代码"}.get(reason, "运行任务")
        if reason == "scheduler":
            message = "当前调度任务正在执行，请等待本轮结束后再继续；无需停止已启用的调度。"
        else:
            message = f"当前{reason_label}正在运行，请等待完成或点击「终止执行」后再继续。"
        return api_error(
            409,
            message,
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
            raise RuntimeExecutionBusyError("direct run is already running")
        if not self.scheduler.acquire_execution("direct_run", blocking=False):
            raise RuntimeExecutionBusyError("runtime execution is already owned")
        with self._lock:
            self._stop_requested = False

        def _wrapped() -> None:
            try:
                target(tasks)
            finally:
                try:
                    self.scheduler.release_execution("direct_run")
                finally:
                    with self._lock:
                        if self._direct_thread is current_thread():
                            self._direct_thread = None
                        self._stop_requested = False

        thread = Thread(target=_wrapped, daemon=True, name="WebUI-DirectRun")
        with self._lock:
            self._direct_thread = thread
        try:
            thread.start()
        except BaseException:
            with self._lock:
                if self._direct_thread is thread:
                    self._direct_thread = None
            self.scheduler.release_execution("direct_run")
            raise
        return thread

    def request_stop(self) -> str:
        direct_alive = self.direct_run_alive()
        scheduler_alive = self.scheduler_busy()
        external_alive = any(
            status.get("busy") or status.get("running")
            for status in self._external_statuses().values()
        )
        with self._lock:
            self._stop_requested = direct_alive or scheduler_alive or external_alive

        self.task_manager.request_cancel()
        self.scheduler.request_stop()
        self.scheduler.invalidate_login()

        logger.info("⏹ 已发送终止信号，等待任务协作退出")
        return "stopping" if (direct_alive or scheduler_alive or external_alive) else "idle"
