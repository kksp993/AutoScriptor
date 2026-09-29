"""Where the task set comes from: discovery, import order, startup assembly.

``tasks/`` holds the task sources; this module is what turns that directory (plus
the user's ``data/custom_task/``) into ``cfg["tasks"]`` and the runtime
``TaskRegistry``. It is the only place that knows the on-disk layout of tasks.

The result is one Chinese-named tree, and ``cfg["tasks"]`` mirrors the registered
task set: registration writes each leaf (carrying a renamed task's saved config
onto its current path itself, see ``tasks.task_register``), the prune pass drops
leaves no task claims, and sorting puts branches in registration order. There is
no separate rename pass and no key translation pass -- a config path is only ever
what registration declared it to be.

Distinct from ``tasks/task_registry.py``: that one stores runtime metadata for
already-imported tasks, this one decides which tasks get imported at all.
"""
from __future__ import annotations

import hashlib
import importlib
import importlib.util
import pathlib
import sys

from AutoScriptor.logging.logger import logger
from AutoScriptor.utils.app_config import cfg
from ZmxyOL.accounts import get_custom_task_dir
from tasks.task_registry import task_registry

from orchestrator.model import TaskTree

import tasks as _tasks_package


# The task sources live in the ``tasks`` package; this module only drives their
# discovery, so the paths must point there rather than at this package.
PACKAGE_NAME = "tasks"
PACKAGE_PATH = pathlib.Path(_tasks_package.__file__).resolve().parent

_CUSTOM_TASK_MODULE_PREFIX = "tasks._ct_"
_last_custom_load_errors: list[dict[str, str]] = []
_loaded = False

# Modules under ``tasks/`` that a reload must keep.
#
# A reload re-imports the scripts so their decorators run again. Everything that
# merely *supports* those scripts has to survive, because re-importing it would
# replace objects other modules already hold:
#
# - ``task_registry`` owns the process-wide registry singleton. A second import
#   builds a second, empty registry while the task manager and this module keep
#   reading the first one -- no task resolves and the prune pass sees nothing.
# - ``task_params`` / ``task_register`` / ``task_state`` / ``translations`` /
#   ``time`` are the authoring plumbing. They hold no per-load state, and
#   ``task_params`` compares parameter defaults against ``TableParam`` by class
#   identity, so replacing it (or the game module that defines the class) makes
#   every table default unrecognizable.
#
# ``tasks`` itself and ``tasks.battle_task_params`` are deliberately absent: the
# package init re-exports the flow enum, and that enum aggregates ``@flow``
# registrations from the character scripts, so both have to be rebuilt for an
# edited character script to show up.
TASK_MODULES_KEPT_ON_RELOAD = frozenset({
    "tasks.task_params",
    "tasks.task_register",
    "tasks.task_registry",
    "tasks.task_state",
    "tasks.time",
    "tasks.translations",
})


def is_reloadable_task_module(module_name: str) -> bool:
    """True when a reload should re-import this module."""
    if module_name == "tasks":
        return True
    if module_name == "tasks.battle_task_params":
        return True
    return module_name.startswith("tasks.") and module_name not in TASK_MODULES_KEPT_ON_RELOAD


# ── Discovery and import order ──

def get_min_order(node, path_prefix: str = ""):
    """Smallest registration order found below a task tree node."""
    if isinstance(node, dict):
        if "on" in node:
            return task_registry.get_order(path_prefix)
        orders = []
        for key, value in node.items():
            if isinstance(value, dict):
                child_path = f"{path_prefix}/{key}" if path_prefix else key
                orders.append(get_min_order(value, child_path))
        return min(orders) if orders else float("inf")
    return float("inf")


def sort_tasks(node, path_prefix: str = "") -> None:
    """Reorder a task config tree to match runtime registration order."""
    for key, child in list(node.items()):
        if isinstance(child, dict) and "on" not in child:
            child_path = f"{path_prefix}/{key}" if path_prefix else key
            sort_tasks(child, child_path)
    sorted_items = sorted(
        node.items(),
        key=lambda item: get_min_order(
            item[1],
            f"{path_prefix}/{item[0]}" if path_prefix else item[0],
        ),
    )
    node.clear()
    node.update(sorted_items)


def get_custom_order_key(path: pathlib.Path):
    """Nested sort key built from the ``_order.txt`` seeds along the path."""
    try:
        relative_parts = path.relative_to(PACKAGE_PATH).parts
    except ValueError:
        return (float("inf"), str(path))

    order_key_list = []
    current_lookup_dir = PACKAGE_PATH

    for index, part_name in enumerate(relative_parts):
        order_file = current_lookup_dir / "_order.txt"
        order_index = float("inf")
        is_last_part = index == len(relative_parts) - 1
        name_to_check = path.stem if is_last_part and path.is_file() else part_name

        if order_file.is_file():
            with open(order_file, "r", encoding="utf-8") as handle:
                order_list = [line.strip() for line in handle.readlines()]
            if name_to_check in order_list:
                order_index = order_list.index(name_to_check)

        order_key_list.append((order_index, name_to_check))
        current_lookup_dir = current_lookup_dir / part_name

    return tuple(order_key_list)


def gather_py_files() -> list[pathlib.Path]:
    """Every Python task source under the tasks package."""
    return list(PACKAGE_PATH.rglob("*.py"))


def sort_py_files(py_files: list[pathlib.Path]) -> list[pathlib.Path]:
    """Sort sources by their ``_order.txt`` seed."""
    py_files.sort(key=get_custom_order_key)
    return py_files


def import_modules(py_files) -> None:
    """Import each source as a module of the tasks package."""
    for py_file in py_files:
        if py_file.name == "__init__.py":
            continue
        relative_path = py_file.relative_to(PACKAGE_PATH)
        relative_module_path = ".".join(relative_path.with_suffix("").parts)
        importlib.import_module(f"{PACKAGE_NAME}.{relative_module_path}")


# ── Custom tasks (user scripts under data/custom_task) ──

def get_custom_task_load_errors() -> list[dict[str, str]]:
    """Import errors recorded during the most recent custom-task load."""
    return list(_last_custom_load_errors)


def has_custom_task_load_errors() -> bool:
    return bool(_last_custom_load_errors)


def load_custom_task_modules() -> list[str]:
    """Import every ``.py`` under ``data/custom_task/`` to trigger registration.

    Module names use a content hash so ``TaskManager.reload_tasks`` can clear
    them by prefix.
    """
    root = get_custom_task_dir()
    root.mkdir(parents=True, exist_ok=True)
    _last_custom_load_errors.clear()
    loaded: list[str] = []
    py_files = sorted(p for p in root.rglob("*.py") if p.name != "__init__.py")
    for py_file in py_files:
        digest = hashlib.sha256(str(py_file.resolve()).encode("utf-8")).hexdigest()[:16]
        module_name = f"{_CUSTOM_TASK_MODULE_PREFIX}{digest}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, py_file)
            if spec is None or spec.loader is None:
                _last_custom_load_errors.append({"path": str(py_file), "error": "无法创建 spec"})
                logger.error("custom_task: 无法创建 spec: %s", py_file)
                continue
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            loaded.append(module_name)
        except Exception as error:
            _last_custom_load_errors.append({"path": str(py_file), "error": str(error)})
            logger.error("custom_task: 导入失败 %s: %s", py_file, error)
    return loaded


def prune_stale_tasks() -> bool:
    """Drop config leaves whose task no longer registers that path.

    ``cfg["tasks"]`` mirrors the registered task set -- registration writes the
    Chinese-named tree and moves any renamed task's saved config onto its current
    path itself -- so a leaf with no task behind it is data the user cannot act
    on. Skipped when custom-task imports failed: an import error usually means
    the task exists but could not load, and deleting its config would lose user
    state.

    Also skipped when the registry came back empty. An empty registry never
    means "the user's tree is stale"; it means registration did not run against
    the registry this function reads. Pruning there would delete every leaf --
    the whole saved tree -- so the guard is the difference between a bug and
    data loss.
    """
    if _last_custom_load_errors:
        logger.warning("custom_task: 本轮导入存在错误，跳过 stale 配置清理以保护用户配置")
        return False
    # include_deprecated: a task that only registers as deprecated still proves
    # registration ran, and its config leaf is exactly what the prune should drop.
    if not task_registry.all_paths(include_deprecated=True):
        logger.error("任务注册表为空，跳过 stale 配置清理以保护用户配置")
        return False
    tasks = cfg["tasks"]
    if not isinstance(tasks, dict):
        return False
    TaskTree.prune_leaves_not_in_registry(tasks, "", task_registry.has_task)
    return True


# ── Startup assembly ──
#
# One pass in this order: import (registration writes the tree) -> prune (drop
# leaves nothing claims) -> sort (registration order). Guarded on purpose: running
# it twice would re-import every task module and re-sort an already-sorted config,
# so callers go through these two functions rather than the raw helpers above.

def load_tasks() -> None:
    """Discover, import and assemble every task module under ``tasks/``."""
    global _loaded
    if _loaded:
        return
    _loaded = True
    sorted_files = sort_py_files(gather_py_files())
    import_modules(sorted_files)
    load_custom_task_modules()
    prune_stale_tasks()
    sort_tasks(cfg["tasks"])
    if has_custom_task_load_errors():
        logger.warning("任务加载存在自定义任务导入错误，跳过本轮配置保存")
        return
    cfg.save_config()


def force_reload_tasks() -> None:
    """Reset the load guard and re-run :func:`load_tasks`.

    Used by ``TaskManager.reload_tasks()`` after clearing ``sys.modules``. The
    registry is cleared first so removed task modules cannot leave stale entries.
    """
    global _loaded
    _loaded = False
    task_registry.clear()
    load_tasks()
