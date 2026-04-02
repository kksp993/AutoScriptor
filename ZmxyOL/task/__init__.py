from AutoScriptor.utils.constant import cfg
from AutoScriptor.utils.task_registry import task_registry
from ZmxyOL.task.pkg_utils import (
    gather_py_files, sort_py_files, import_modules,
    sort_tasks, update_order_files, normalize_cfg_tasks_to_cn,
    migrate_hgwj_daily_task_leaf_to_wanjiefuben,
    migrate_remove_daily_login_task,
)
from ZmxyOL.task.custom_task_loader import load_custom_task_modules, prune_stale_custom_tasks
from .task_register import register_task
from ZmxyOL.task.battle_task_params import (
    BattleFlowName,
    DEFAULT_BATTLE_FLOW,
    DEFAULT_JJC_BATTLE_FLOW,
    get_battle_profile,
)

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
    load_custom_task_modules()
    normalize_cfg_tasks_to_cn()
    migrate_remove_daily_login_task(cfg["tasks"])
    migrate_hgwj_daily_task_leaf_to_wanjiefuben(cfg["tasks"])
    prune_stale_custom_tasks()
    sort_tasks(cfg["tasks"])
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
    "BattleFlowName",
    "DEFAULT_BATTLE_FLOW",
    "DEFAULT_JJC_BATTLE_FLOW",
    "get_battle_profile",
]
