"""Orchestrator: task-centric scheduling.

``tasks/`` says what a task is; this layer decides when it runs, in which
character, under which retry policy and on which device session. The backend
talks to :data:`orchestrator.orchestrator` instead of wiring the parts itself.

Exports stay lazy (PEP 562): importing a single module such as
``orchestrator.task_tree`` from deep inside the task loader must not pull the
scheduler, the lifecycle service and the whole `tasks` package in behind it.
"""
from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORTS: dict[str, tuple[str, str]] = {
    # the composed entry point
    "orchestrator": ("orchestrator.facade", "orchestrator"),
    "Orchestrator": ("orchestrator.facade", "Orchestrator"),
    # startup assembly
    "load_tasks": ("orchestrator.registry", "load_tasks"),
    "force_reload_tasks": ("orchestrator.registry", "force_reload_tasks"),
    # scheduling
    "scheduler": ("orchestrator.scheduler", "scheduler"),
    "Scheduler": ("orchestrator.scheduler", "Scheduler"),
    "SchedulerState": ("orchestrator.scheduler", "SchedulerState"),
    "is_task_due": ("orchestrator.scheduler", "is_task_due"),
    "is_human_takeover_blocked": ("orchestrator.scheduler", "is_human_takeover_blocked"),
    "calc_effective_next_time": ("orchestrator.scheduler", "calc_effective_next_time"),
    "collect_active_times_from_tasks_tree": (
        "orchestrator.scheduler",
        "collect_active_times_from_tasks_tree",
    ),
    "collect_active_times_from_all_characters": (
        "orchestrator.scheduler",
        "collect_active_times_from_all_characters",
    ),
    "iter_dispatch_characters": ("orchestrator.scheduler", "iter_dispatch_characters"),
    "next_display_timestamp_from_times": (
        "orchestrator.scheduler",
        "next_display_timestamp_from_times",
    ),
    # execution
    "TaskManager": ("orchestrator.task_manager", "TaskManager"),
    "RuntimeController": ("orchestrator.runtime_controller", "RuntimeController"),
    "RuntimeExecutionBusyError": (
        "orchestrator.runtime_controller",
        "RuntimeExecutionBusyError",
    ),
    # task tree and ordering
    "TaskTree": ("orchestrator.task_tree", "TaskTree"),
    "TaskTreeService": ("orchestrator.task_tree_service", "TaskTreeService"),
    "project_task_ordering": ("orchestrator.task_ordering", "project_task_ordering"),
    "normalize_task_ordering_overlay": (
        "orchestrator.task_ordering",
        "normalize_task_ordering_overlay",
    ),
    "collect_task_paths": ("orchestrator.task_ordering", "collect_task_paths"),
    "sort_paths_by_task_ordering": (
        "orchestrator.task_ordering",
        "sort_paths_by_task_ordering",
    ),
    "summarize_ordering_generations": (
        "orchestrator.task_ordering",
        "summarize_ordering_generations",
    ),
    # lifecycle and config version
    "WebUILifecycleService": ("orchestrator.lifecycle", "WebUILifecycleService"),
    "bump_version": ("orchestrator.state_version", "bump_version"),
    "current_version": ("orchestrator.state_version", "current_version"),
    # results and delivery
    "CharacterReports": ("orchestrator.character_reports", "CharacterReports"),
    "CharacterReport": ("orchestrator.character_reports", "CharacterReport"),
    "create_character_reports": (
        "orchestrator.character_reports",
        "create_character_reports",
    ),
    "notify_runtime_event": ("orchestrator.notify", "notify_runtime_event"),
    "notify_desktop": ("orchestrator.notify", "notify_desktop"),
    "handle_notify": ("orchestrator.notify", "handle_notify"),
    "QQSettings": ("orchestrator.qq_notify", "QQSettings"),
    "qq_notifier": ("orchestrator.qq_notify", "qq_notifier"),
    # file watching
    "ConfigWatcher": ("orchestrator.watcher", "ConfigWatcher"),
}

# Addressable as attributes, e.g. ``orchestrator.registry.load_tasks``.
_SUBMODULES = (
    "character_reports",
    "custom_task_loader",
    "facade",
    "lifecycle",
    "notify",
    "pkg_utils",
    "qq_notify",
    "registry",
    "runtime_controller",
    "scheduler",
    "state_version",
    "task_manager",
    "task_ordering",
    "task_tree",
    "task_tree_service",
    "watcher",
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
