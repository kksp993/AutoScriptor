from AutoScriptor.utils.constant import cfg
from AutoScriptor.utils.task_registry import task_registry
from ZmxyOL.task.pkg_utils import (
    gather_py_files, sort_py_files, import_modules,
    sort_tasks, update_order_files, normalize_cfg_tasks_to_cn,
)
from .task_register import register_task

_loaded = False


def load_tasks():
    """Discover, import, and sort all task modules under ZmxyOL/task/.

    Safe to call multiple times; subsequent calls are no-ops unless
    ``force_reload_tasks()`` resets the guard first.
    """
    global _loaded
    if _loaded:
        return
    _loaded = True
    all_py_files = gather_py_files()
    sorted_files = sort_py_files(all_py_files)
    import_modules(sorted_files)
    normalize_cfg_tasks_to_cn()
    sort_tasks(cfg['tasks'])
    update_order_files(sorted_files)
    cfg.save_config()


def force_reload_tasks():
    """Reset the load guard and re-run ``load_tasks()``.

    Used by ``TaskManager.reload_tasks()`` after clearing ``sys.modules``.
    Clears the TaskRegistry before re-registering to avoid stale entries.
    """
    global _loaded
    _loaded = False
    task_registry.clear()
    load_tasks()


__all__ = [
    "register_task",
    "task_registry",
    "load_tasks",
    "force_reload_tasks",
]
