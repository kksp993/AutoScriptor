"""Task discovery, import ordering and startup assembly.

``tasks/`` defines what a task is; this module decides which task modules exist,
in which order they load, and lands the result in ``cfg["tasks"]`` plus the
runtime ``TaskRegistry``.

The load is guarded: importing the same tree twice would re-run registration and
re-sort an already-sorted config, so callers go through :func:`load_tasks` and
:func:`force_reload_tasks` instead of the raw helpers.
"""
from __future__ import annotations

from AutoScriptor.logging.logger import logger
from AutoScriptor.utils.app_config import cfg
from tasks.task_registry import task_registry

from orchestrator.custom_task_loader import (
    get_custom_task_load_errors as get_custom_task_load_errors,
    has_custom_task_load_errors as has_custom_task_load_errors,
    load_custom_task_modules as load_custom_task_modules,
    prune_stale_custom_tasks as prune_stale_custom_tasks,
)
from orchestrator.pkg_utils import (
    gather_py_files as gather_py_files,
    import_modules as import_modules,
    migrate_hgwj_daily_task_leaf_to_wanjiefuben as migrate_hgwj_daily_task_leaf_to_wanjiefuben,
    migrate_remove_daily_login_task as migrate_remove_daily_login_task,
    normalize_cfg_tasks_to_cn as normalize_cfg_tasks_to_cn,
    sort_py_files as sort_py_files,
    sort_tasks as sort_tasks,
)


_loaded = False


def load_tasks() -> None:
    """Discover, import and sort every task module under ``tasks/``.

    Safe to call repeatedly; later calls are no-ops until
    :func:`force_reload_tasks` resets the guard.
    """
    global _loaded
    if _loaded:
        return
    _loaded = True
    sorted_files = sort_py_files(gather_py_files())
    import_modules(sorted_files)
    load_custom_task_modules()
    normalize_cfg_tasks_to_cn()
    migrate_remove_daily_login_task(cfg["tasks"])
    migrate_hgwj_daily_task_leaf_to_wanjiefuben(cfg["tasks"])
    prune_stale_custom_tasks()
    sort_tasks(cfg["tasks"])
    if has_custom_task_load_errors():
        logger.warning("任务加载存在自定义任务导入错误，跳过本轮配置保存")
        return
    cfg.save_config()


def force_reload_tasks() -> None:
    """Reset the load guard and re-run :func:`load_tasks`.

    Used by ``TaskManager.reload_tasks()`` after clearing ``sys.modules``.
    Clears the registry first so removed task modules cannot leave stale entries.
    """
    global _loaded
    _loaded = False
    task_registry.clear()
    load_tasks()
