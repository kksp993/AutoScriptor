"""The single entry point the backend talks to.

The backend starts the scheduler, runs tasks, saves task config and asks about
busy state -- it should not have to build or wire the pieces that make that
work. This module composes them once and exposes the result as ``orchestrator``.

Sub-objects stay reachable (``orchestrator.scheduler``, ``orchestrator.tasks``)
because the backend needs several distinct capabilities, but the wiring itself
(which task manager the scheduler drives, which tree the lifecycle service
projects) lives here, not in the caller.
"""
from __future__ import annotations

from typing import Any, Callable

from AutoScriptor.utils.app_config import cfg

from orchestrator.lifecycle import WebUILifecycleService
from orchestrator.registry import force_reload_tasks, load_tasks
from orchestrator.runtime_controller import RuntimeController
from orchestrator.scheduler import Scheduler, SchedulerState, scheduler
from orchestrator.task_manager import TaskManager
from orchestrator.task_tree_service import TaskTreeService, task_tree_service


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


orchestrator = Orchestrator()
