"""The single entry point the backend talks to, plus the execution gate.

Two things live here because they are both about "who is allowed to drive the
device right now":

- ``Orchestrator``: composes the pieces once (which task manager the scheduler
  drives, which tree the lifecycle service projects) so the backend never wires
  them itself. Sub-objects stay reachable (``orchestrator.scheduler``,
  ``orchestrator.tasks``) because the backend needs several distinct
  capabilities.
- ``RuntimeController``: arbitrates among the three participants that can run
  tasks -- the activated scheduler, a direct run from the task list, and editor
  code. Conflicts come back as plain payloads, not HTTP responses; turning one
  into a status code belongs to the caller.
"""
from __future__ import annotations

from threading import Lock, Thread, current_thread
from typing import Any, Callable, Literal

from AutoScriptor.logging.logger import logger
from AutoScriptor.utils.app_config import cfg

from orchestrator.catalog import load_tasks
from orchestrator.projection import TaskTreeService, WebUILifecycleService, task_tree_service
from orchestrator.scheduler import Scheduler, SchedulerState, scheduler
from orchestrator.task_manager import TaskManager


class Orchestrator:
    """Composed scheduling layer."""

    def __init__(self) -> None:
        self.task_manager = TaskManager()
        # ``scheduler`` is the process singleton; adopt it so any module that
        # imported it directly observes the same instance.
        self.scheduler: Scheduler = scheduler
        self.scheduler.set_task_manager(self.task_manager)
        self.execution = RuntimeController(self.scheduler, self.task_manager)
        # Adopt the module singleton so routes that import it directly observe
        # the same projection cache as callers going through the facade.
        self.tree: TaskTreeService = task_tree_service
        self.tasks: WebUILifecycleService | None = None

    # ── 装配 ──

    def configure_lifecycle(
        self,
        *,
        refresh_order_map: Callable[[], None],
        mark_config_changed: Callable[[str], int],
        apply_log_level: Callable[[], None] | None = None,
        clear_background: Callable[[], None] | None = None,
        reload_ui_map: Callable[[], None] | None = None,
    ) -> WebUILifecycleService:
        """Attach the lifecycle service once the backend's hooks exist.

        The hooks belong to the caller (version bumping, log level, UI caches),
        so they are injected rather than looked up.
        """
        self.tasks = WebUILifecycleService(
            cfg,
            self.task_manager,
            self.scheduler,
            self.tree,
            refresh_order_map,
            mark_config_changed,
            apply_log_level,
            clear_background,
            reload_ui_map,
        )
        return self.tasks

    # ── 任务注册 ──

    def load_tasks(self) -> None:
        load_tasks()

    def reload_tasks(self, security_key: str | None = None) -> None:
        self.task_manager.reload_tasks(security_key)

    # ── 调度 ──

    def start_scheduler(self) -> None:
        self.scheduler.activate()
        self.scheduler.wake()

    def recover_scheduler(self) -> None:
        """Leave the ERROR state and clear the consecutive-error budget."""
        self.scheduler.reset()

    def stop_scheduler(self) -> None:
        self.scheduler.request_stop()

    def scheduler_status(self) -> dict[str, Any]:
        return self.scheduler.status_dict()

    def is_scheduler_error(self) -> bool:
        return self.scheduler.state == SchedulerState.ERROR

    def scheduler_state_label(self) -> str:
        return self.scheduler.state_label

    # ── 执行 ──

    def is_busy(self) -> bool:
        return self.execution.is_busy()

    def is_direct_running(self) -> bool:
        return self.execution.direct_run_alive()

    def execution_status(self) -> dict[str, Any]:
        return self.execution.status()

    def stop_execution(self) -> str:
        return self.execution.request_stop()

    def guard_idle(self, action: str = "modify runtime config"):
        return self.execution.guard_idle(action)

    def busy_conflict(self, action: str = "modify runtime config"):
        return self.execution.busy_conflict(action)

    def run_tasks_direct(
        self,
        tasks: list[str],
        *,
        skip_character_login: bool = False,
        force_login: bool = False,
    ) -> None:
        """Run an explicit task list on the scheduler's pipeline, in background."""

        def _run(task_paths: list[str]) -> None:
            self.scheduler.run_direct(
                task_paths,
                skip_character_login=skip_character_login,
                force_login=force_login,
            )

        self.execution.start_direct(_run, sorted(tasks))

    def run_task_sequence(self, runs: list[Any], *, force_login: bool = True) -> None:
        self.scheduler.run_direct_sequence(runs, force_login=force_login)


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

    def busy_conflict(self, action: str = "modify runtime config") -> dict[str, Any]:
        """Describe what is blocking a config mutation or a new execution."""
        reason = self.busy_reason() or "runtime"
        reason_label = {"direct_run": "直接执行任务", "scheduler": "调度器", "editor": "编辑器代码"}.get(reason, "运行任务")
        if reason == "scheduler":
            message = "当前调度任务正在执行，请等待本轮结束后再继续；无需停止已启用的调度。"
        else:
            message = f"当前{reason_label}正在运行，请等待完成或点击「终止执行」后再继续。"
        return {
            "code": "runtime_busy",
            "reason": reason,
            "message": message,
            "action": action,
        }

    def guard_idle(self, action: str = "modify runtime config") -> dict[str, Any] | None:
        """Return the conflict payload when busy, otherwise ``None``."""
        if self.is_busy():
            return self.busy_conflict(action)
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


# The process-wide composition root. Built last: it needs RuntimeController.
orchestrator = Orchestrator()
