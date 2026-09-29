"""Orchestrator: task-centric scheduling.

``tasks/`` says what a task is; this layer decides when it runs, in which
character, under which retry policy and on which device session. The backend
talks to :data:`orchestrator.orchestrator` instead of wiring the parts itself.

Seven modules, each answering one question:

- ``model``      -- what the task set looks like, and when each task is due (pure).
- ``catalog``    -- where the task set comes from: discovery, registration, startup.
- ``task_manager`` -- how one task is executed, retried and recovered.
- ``scheduler``  -- when tasks run, in which order, and on which device session.
- ``projection`` -- what the WebUI may see, and how it changes it.
- ``delivery``   -- everything that leaves the process: toasts, QQ, run reports.
- ``facade``     -- the composition root; ``orchestrator`` is its singleton.

Exports stay lazy (PEP 562): importing a single module such as
``orchestrator.model`` from deep inside the task loader must not pull the
scheduler, the lifecycle service and the whole ``tasks`` package in behind it.
"""
from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORTS: dict[str, tuple[str, str]] = {
    # the composed entry point
    "orchestrator": ("orchestrator.facade", "orchestrator"),
    "Orchestrator": ("orchestrator.facade", "Orchestrator"),
    "RuntimeController": ("orchestrator.facade", "RuntimeController"),
    "RuntimeExecutionBusyError": ("orchestrator.facade", "RuntimeExecutionBusyError"),
    # startup assembly
    "load_tasks": ("orchestrator.catalog", "load_tasks"),
    "force_reload_tasks": ("orchestrator.catalog", "force_reload_tasks"),
    # scheduling
    "scheduler": ("orchestrator.scheduler", "scheduler"),
    "Scheduler": ("orchestrator.scheduler", "Scheduler"),
    "SchedulerState": ("orchestrator.scheduler", "SchedulerState"),
    "ConfigWatcher": ("orchestrator.scheduler", "ConfigWatcher"),
    # execution
    "TaskManager": ("orchestrator.task_manager", "TaskManager"),
    # task tree, ordering and timing
    "TaskTree": ("orchestrator.model", "TaskTree"),
    "is_task_due": ("orchestrator.model", "is_task_due"),
    "is_human_takeover_blocked": ("orchestrator.model", "is_human_takeover_blocked"),
    "calc_effective_next_time": ("orchestrator.model", "calc_effective_next_time"),
    "collect_active_times_from_tasks_tree": (
        "orchestrator.model",
        "collect_active_times_from_tasks_tree",
    ),
    "collect_active_times_from_all_characters": (
        "orchestrator.model",
        "collect_active_times_from_all_characters",
    ),
    "iter_dispatch_characters": ("orchestrator.model", "iter_dispatch_characters"),
    "next_display_timestamp_from_times": (
        "orchestrator.model",
        "next_display_timestamp_from_times",
    ),
    "project_task_ordering": ("orchestrator.model", "project_task_ordering"),
    "normalize_task_ordering_overlay": ("orchestrator.model", "normalize_task_ordering_overlay"),
    "collect_task_paths": ("orchestrator.model", "collect_task_paths"),
    "sort_paths_by_task_ordering": ("orchestrator.model", "sort_paths_by_task_ordering"),
    "summarize_ordering_generations": ("orchestrator.model", "summarize_ordering_generations"),
    # WebUI projections and config lifecycle
    "TaskTreeService": ("orchestrator.projection", "TaskTreeService"),
    "WebUILifecycleService": ("orchestrator.projection", "WebUILifecycleService"),
    "bump_version": ("orchestrator.projection", "bump_version"),
    "current_version": ("orchestrator.projection", "current_version"),
    # results and delivery
    "CharacterReports": ("orchestrator.delivery", "CharacterReports"),
    "CharacterReport": ("orchestrator.delivery", "CharacterReport"),
    "create_character_reports": ("orchestrator.delivery", "create_character_reports"),
    "notify_runtime_event": ("orchestrator.delivery", "notify_runtime_event"),
    "notify_desktop": ("orchestrator.delivery", "notify_desktop"),
    "handle_notify": ("orchestrator.delivery", "handle_notify"),
    "QQSettings": ("orchestrator.delivery", "QQSettings"),
    "qq_notifier": ("orchestrator.delivery", "qq_notifier"),
}

# Addressable as attributes, e.g. ``orchestrator.catalog.load_tasks``.
_SUBMODULES = (
    "catalog",
    "delivery",
    "facade",
    "model",
    "projection",
    "scheduler",
    "task_manager",
)

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if target is not None:
        module_name, attribute_name = target
        value = getattr(import_module(module_name), attribute_name)
        globals()[name] = value
        return value
    if name in _SUBMODULES:
        module = import_module(f"{__name__}.{name}")
        globals()[name] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__) | set(_SUBMODULES))
