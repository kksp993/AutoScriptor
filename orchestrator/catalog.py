"""Where the task set comes from: discovery, import order, startup assembly.

``tasks/`` holds the task sources; this module is what turns that directory (plus
the user's ``data/custom_task/``) into ``cfg["tasks"]`` and the runtime
``TaskRegistry``. It is the only place that knows the on-disk layout of tasks.

``cfg["tasks"]`` is a flat table keyed by task id and mirrors the registered task
set: registration writes each entry, the prune pass drops entries no task claims.
The Chinese tree the WebUI shows is a projection built from the display paths, so
storage never depends on it.

Registration (``tasks/task_register.py``) stores runtime metadata for
already-imported tasks; this module decides which tasks get imported at all.
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
from tasks.task_register import LEGACY_TASK_FIELDS, task_registry

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
# - ``task_register`` owns the process-wide registry singleton. A second import
#   builds a second, empty registry while the task manager and this module keep
#   reading the first one -- no task resolves and the prune pass sees nothing.
# - ``task_params`` / ``task_state`` / ``time`` are the authoring plumbing. They
#   hold no per-load state, and ``task_params`` compares parameter defaults
#   against ``TableParam`` by class identity, so replacing it (or the game module
#   that defines the class) makes every table default unrecognizable.
#
# ``tasks`` itself and ``tasks.battle_task_params`` are deliberately absent: the
# package init re-exports the flow enum, and that enum aggregates ``@flow``
# registrations from the character scripts, so both have to be rebuilt for an
# edited character script to show up.
TASK_MODULES_KEPT_ON_RELOAD = frozenset({
    "tasks.task_params",
    "tasks.task_register",
    "tasks.task_state",
    "tasks.time",
})


def is_reloadable_task_module(module_name: str) -> bool:
    """True when a reload should re-import this module."""
    if module_name == "tasks":
        return True
    if module_name == "tasks.battle_task_params":
        return True
    return module_name.startswith("tasks.") and module_name not in TASK_MODULES_KEPT_ON_RELOAD


# Modules under ``ZmxyOL/`` that a reload must keep, because an object they own is
# already held somewhere this reload does not touch:
#
# - ``table_param`` defines ``TableParam``, and ``tasks/task_params.py`` compares
#   parameter defaults against it with ``isinstance``. A second copy of the class
#   makes every stored table default unrecognizable.
# - ``accounts`` / ``account_store`` own the account domain; the backend registered
#   with AutoScriptor's generic layer when ``account_store`` was first imported, and
#   ``orchestrator.projection`` holds ``INJECTED_TASK_FIELDS`` from it.
# - ``profession`` owns ``GAME_PROFESSIONS``, held by ``projection`` and the
#   overview route.
# - ``character`` / ``hero`` own the ``Hero`` base, the profession registry and the
#   ``h`` singleton. ``hero`` is reloaded *in place* by
#   ``reload_character_modules()``; re-importing it would build a second registry
#   and a second ``h`` while the running tasks still hold the first.
# - ``character/plan`` defines ``BattlePlan``, which ``data/character/hero.py``
#   binds at import time -- and that file is not re-executed by a reload.
#
# Everything else under ``ZmxyOL/`` -- navigation, battle procedures, the package
# resolver -- is plain logic with no object held across the boundary, so it is
# rebuilt. Both module-level side effects in that set are plain assignments
# (``set_app_package_resolver``, ``register_context_provider``), so re-running them
# is idempotent.
ZMXYOL_MODULES_KEPT_ON_RELOAD = frozenset({
    "ZmxyOL",
    "ZmxyOL.accounts",
    "ZmxyOL.accounts.account_store",
    "ZmxyOL.accounts.crypto",
    "ZmxyOL.accounts.crypto.config_manager",
    "ZmxyOL.battle.table_param",
    "ZmxyOL.character",
    "ZmxyOL.character.hero",
    "ZmxyOL.character.plan",
    "ZmxyOL.character.profession",
    "ZmxyOL.character.pros",
})

# Character scripts under ``data/character/`` are executed into
# ``ZmxyOL.character.hero``. ``reload_character_modules()`` re-runs them, and their
# module names are content hashes with no finder behind them, so a plain re-import
# would raise instead of rebuilding.
_ZMXYOL_CHARACTER_SCRIPT_PREFIX = "ZmxyOL.character._user_"


def is_reloadable_game_layer_module(module_name: str) -> bool:
    """True when a reload should re-import this game-layer module."""
    if not module_name.startswith("ZmxyOL."):
        return False
    if module_name.startswith(_ZMXYOL_CHARACTER_SCRIPT_PREFIX):
        return False
    return module_name not in ZMXYOL_MODULES_KEPT_ON_RELOAD


def is_reloadable_module(module_name: str) -> bool:
    """True when a reload re-imports this module, task script or game layer."""
    return is_reloadable_task_module(module_name) or is_reloadable_game_layer_module(module_name)


def reload_game_layer_modules() -> list[str]:
    """Rebuild the game-layer modules a reload may drop; return what was rebuilt.

    Dropping them without rebuilding would leave the work to whichever import
    happens to touch the module first, which can be a task halfway through a run.
    Rebuilding here means a game-layer module that no longer imports fails the
    reload instead of failing a task.

    Sorted order is dependency order: a package name is a prefix of every module
    under it, so parents are rebuilt before their children.
    """
    dropped = [name for name in sys.modules if is_reloadable_game_layer_module(name)]
    for name in dropped:
        sys.modules.pop(name, None)
    for name in sorted(dropped):
        try:
            importlib.import_module(name)
        except ModuleNotFoundError as error:
            # A source file the user deleted is legitimately gone and nothing
            # imports it any more. Anything else -- a broken import inside the
            # module, a missing dependency -- has to surface.
            if error.name != name:
                raise
            logger.debug("reload: %s 已不存在，跳过重建", name)
    return dropped


# ── Config shape normalization ──

def _looks_nested(task_table: dict) -> bool:
    """True when the table is still the old nested tree rather than a flat one."""
    if not task_table:
        return False
    return any(
        isinstance(value, dict) and "on" not in value
        for value in task_table.values()
    )


def normalize_task_table() -> bool:
    """Flatten a nested ``cfg["tasks"]`` into the flat, id-keyed table.

    The old shape nested each leaf under its path segments; the flat shape keys
    each entry directly by task id. The leaf bodies and the strings they are
    keyed by are unchanged -- ``每日任务/村庄/宠物培养`` is the key either way --
    so this rewrites the container only and moves no user value.

    Returns True when it rewrote the table. Refuses to write an empty result for
    a non-empty input: an unclassifiable tree must not silently become "no tasks".
    """
    task_table = cfg["tasks"]
    if not isinstance(task_table, dict) or not _looks_nested(task_table):
        return False
    flat: dict[str, dict] = {}
    for path_parts, leaf in TaskTree.collect_all_leaves(task_table):
        flat["/".join(path_parts)] = leaf
    if task_table and not flat:
        logger.error("cfg['tasks'] 既不是平表也提不出任务叶节点，保留原样以免清空用户配置")
        return False
    cfg["tasks"] = flat
    logger.info("任务配置已从嵌套树归一为平表: %d 个任务", len(flat))
    return True


# ── Discovery and import order ──


def gather_py_files() -> list[pathlib.Path]:
    """Every Python task source under the tasks package."""
    return list(PACKAGE_PATH.rglob("*.py"))


def sort_py_files(py_files: list[pathlib.Path]) -> list[pathlib.Path]:
    """Deterministic import order, derived from each source's path under ``tasks/``.

    Import order is the default task order: registration numbers tasks in the
    order they are imported, and the WebUI tree and execution order fall back to
    that number. Changing position is the user's job, through ``task_ordering``.
    """
    return sorted(
        py_files,
        key=lambda path: path.relative_to(PACKAGE_PATH).with_suffix("").parts,
    )


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
    """Drop config entries whose id no registered task claims.

    ``cfg["tasks"]`` mirrors the registered task set, so an entry with no task
    behind it is data the user cannot act on. Skipped when custom-task imports
    failed: an import error usually means the task exists but could not load, and
    deleting its config would lose user state.

    Also skipped when the registry came back empty. An empty registry never
    means "the user's tasks are stale"; it means registration did not run against
    the registry this function reads. Pruning there would delete every entry --
    the whole saved table -- so the guard is the difference between a bug and
    data loss.
    """
    if _last_custom_load_errors:
        logger.warning("custom_task: 本轮导入存在错误，跳过 stale 配置清理以保护用户配置")
        return False
    # include_deprecated: a task that only registers as deprecated still proves
    # registration ran, and its config entry is exactly what the prune should drop.
    if not task_registry.all_paths(include_deprecated=True):
        logger.error("任务注册表为空，跳过 stale 配置清理以保护用户配置")
        return False
    task_table = cfg["tasks"]
    if not isinstance(task_table, dict):
        return False
    claimed = set(task_registry.all_ids())
    stale = [task_id for task_id in task_table if task_id not in claimed]
    if stale:
        for task_id in stale:
            del task_table[task_id]
        logger.info("已清理 %d 个无任务认领的任务配置: %s", len(stale), stale)
    return bool(stale)


# ── Identity reconcile ──

def ensure_task_entries(task_table: dict) -> list[str]:
    """把表里缺的任务条目补齐，不重载任务模块。

    注册只在「那个角色是当前角色」时写那张表，所以刚新增的账号、刚建的角色、或者手改过
    账号文件之后，表里可能还没有这些条目——WebUI 就会显示成空任务树，看起来像「必须重启
    才能加载」。这里就地把缺的补上，默认值与首次注册一致：关闭、下次执行时间为 0、
    参数取签名默认值。

    只动传入的表，不读全局 cfg，这样调用方给哪张表就补哪张表。返回补上的任务名。
    """
    from tasks.task_params import hydrate_params

    if not isinstance(task_table, dict):
        return []
    added: list[str] = []
    for path, entry in task_registry.items():
        task_id = str(entry.get("id") or "").strip() or path.rsplit("/", 1)[-1]
        existing = task_table.get(task_id)
        if isinstance(existing, dict) and "on" in existing:
            continue
        task_table[task_id] = {
            "on": False,
            "next_exec_time": 0,
            "params": hydrate_params(task_registry.get_param_specs(path), {}),
        }
        added.append(task_id)
    if added:
        logger.info("已为当前角色补齐 %d 个任务条目: %s", len(added), added[:5])
    return added

def _retarget_stored_ordering(moved: dict[str, str]) -> bool:
    """把存盘排序里的旧键换成任务名键。"""
    overlay = cfg._config.get("task_ordering")
    if not isinstance(overlay, dict) or not moved:
        return False
    changed = False

    def rewrite(items) -> None:
        nonlocal changed
        for item in items or []:
            if not isinstance(item, dict):
                continue
            if isinstance(item.get("items"), list):
                rewrite(item["items"])
                continue
            key = item.get("id")
            if isinstance(key, str) and key in moved:
                item["id"] = moved[key]
                changed = True

    if isinstance(overlay.get("items"), list):
        rewrite(overlay["items"])
    user_order = overlay.get("user_order")
    if isinstance(user_order, list):
        rewritten = [moved.get(value, value) if isinstance(value, str) else value for value in user_order]
        if rewritten != user_order:
            overlay["user_order"] = rewritten
            changed = True
    return changed


def reconcile_task_identities() -> bool:
    """把以显示路径为键的旧配置并到任务名键上。

    身份是任务名，位置是它现在待在哪个目录。任务换目录之后，旧条目仍挂在旧路径上，
    而注册已经按任务名写下了默认条目；这里把旧的用户数据盖回去，键归到任务名，
    拖拽顺序一起跟过去。任务再移动就不需要任何手工处理。

    候选旧键必须同时满足：没有任何任务认领它、是路径形态（含 ``/``）、末段等于任务名。
    候选不唯一时不动它并报警——宁可让用户看见，也不猜哪一条才是这个任务的。
    deprecated 任务不参与，它们本来就不写配置。
    """
    from tasks.task_params import hydrate_params

    task_table = cfg["tasks"]
    if not isinstance(task_table, dict):
        return False
    claimed = set(task_registry.all_ids())
    adopted: dict[str, str] = {}

    for path, entry in task_registry.items():
        task_id = str(entry.get("id") or "").strip()
        if not task_id or task_id == path:
            continue
        candidates = [
            key
            for key in task_table
            if key not in claimed and "/" in key and key.rsplit("/", 1)[-1] == task_id
        ]
        if len(candidates) > 1:
            logger.warning("任务 %s 的旧配置有多个候选键，跳过以便人工确认: %s", task_id, candidates)
            continue
        if not candidates:
            continue

        old_entry = task_table.pop(candidates[0])
        target = task_table.setdefault(task_id, {})
        for key, value in (old_entry or {}).items():
            if key in LEGACY_TASK_FIELDS:
                continue
            target[key] = value
        # 参数按当前签名重新水合：旧值保留，新增的默认行、列补上。
        saved_params = target.get("params")
        target["params"] = hydrate_params(
            task_registry.get_param_specs(path),
            saved_params if isinstance(saved_params, dict) else {},
        )
        adopted[candidates[0]] = task_id

    ordering_changed = _retarget_stored_ordering(adopted)
    if adopted:
        logger.info("任务配置已按任务名归一: %s", adopted)
    return bool(adopted) or ordering_changed


# ── Startup assembly ──
#
# One pass in this order: normalize (older nested shape -> flat table) -> import
# (registration writes entries) -> reconcile (path keys -> task-name keys) ->
# prune (drop entries nothing claims). Guarded on purpose: running it twice would
# re-import every task module, so callers go through these two functions rather
# than the raw helpers above.

def load_tasks() -> None:
    """Discover, import and assemble every task module under ``tasks/``."""
    global _loaded
    if _loaded:
        return
    _loaded = True
    # Registration writes straight into the flat table, so the shape has to be
    # right before the first decorator runs.
    normalize_task_table()
    sorted_files = sort_py_files(gather_py_files())
    import_modules(sorted_files)
    load_custom_task_modules()
    reconcile_task_identities()
    prune_stale_tasks()
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
