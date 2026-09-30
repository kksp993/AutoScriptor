"""ZmxyOL package: game layer — battle, navigation, task, account and crypto.

Exports stay lazy (PEP 562) on purpose. Importing this package eagerly used to
pull in ``ZmxyOL.battle`` -> ``character`` -> ``data/character``
-> ``AutoScriptor``, which re-enters ``AutoScriptor.utils.app_config`` while it
is still initializing and fails on a partially initialized ``cfg``.

Resolving each name on first access keeps ``from ZmxyOL import *`` and
``from ZmxyOL import h`` working exactly as before, while a lightweight
submodule import such as ``ZmxyOL.accounts.crypto.config_manager`` no longer drags the
whole battle/task chain into a caller that is mid-initialization.

This package also owns the account domain that ``AutoScriptor`` only consumes
through an injected backend: ``ZmxyOL.accounts.account_store`` registers itself
with ``AutoScriptor.utils.app_config.set_account_backend``.
"""
from __future__ import annotations

# Underscore-prefixed on purpose: a star-import that falls back to the module
# namespace (see __getattr__ below) must not leak these into callers.
import sys as _sys
from importlib import import_module as _import_module
from typing import TYPE_CHECKING as _TYPE_CHECKING, Any as _Any

# Register the asset tree before anything can load the UI map.
from ZmxyOL.accounts import register_assets_root as _register_assets_root

_register_assets_root()

if _TYPE_CHECKING:
    from ZmxyOL.battle import (
        BattlePlan as BattlePlan,
        Hero as Hero,
        battle_plan as battle_plan,
        combo as combo,
        flow as flow,
        get_task_table as get_task_table,
        h as h,
    )
    from ZmxyOL.nav import (
        Env as Env,
        Loc as Loc,
        LoginClient as LoginClient,
        MapManager as MapManager,
        ensure_in as ensure_in,
        login as login,
        mm as mm,
        path as path,
        try_close_via_x as try_close_via_x,
    )
    from ZmxyOL.nav.envs.decorators import LOC_ENV as LOC_ENV
    from tasks import (
        BattleFlowName as BattleFlowName,
        DEFAULT_BATTLE_FLOW as DEFAULT_BATTLE_FLOW,
        DEFAULT_JJC_BATTLE_FLOW as DEFAULT_JJC_BATTLE_FLOW,
        get_battle_profile as get_battle_profile,
        register_task as register_task,
        task_registry as task_registry,
    )

# Public name -> module that owns it. Resolution happens on first access.
_EXPORTS: dict[str, str] = {
    # battle layer
    "h": "ZmxyOL.battle",
    "combo": "ZmxyOL.battle",
    "get_task_table": "ZmxyOL.battle",
    "Hero": "ZmxyOL.battle",
    "battle_plan": "ZmxyOL.battle",
    "flow": "ZmxyOL.battle",
    "BattlePlan": "ZmxyOL.battle",
    # nav layer
    "MapManager": "ZmxyOL.nav",
    "Loc": "ZmxyOL.nav",
    "Env": "ZmxyOL.nav",
    "mm": "ZmxyOL.nav",
    "path": "ZmxyOL.nav",
    "ensure_in": "ZmxyOL.nav",
    "try_close_via_x": "ZmxyOL.nav",
    "LoginClient": "ZmxyOL.nav",
    "login": "ZmxyOL.nav",
    "LOC_ENV": "ZmxyOL.nav.envs.decorators",
    # 4399 平台悬浮窗业务
    "detect_floating_window": "ZmxyOL.nav.envs.floating_window",
    "detect_floating_window_on_frame": "ZmxyOL.nav.envs.floating_window",
    "dismiss_floating_window": "ZmxyOL.nav.envs.floating_window",
    # task layer
    "register_task": "tasks",
    "task_registry": "tasks",
    "BattleFlowName": "tasks",
    "DEFAULT_BATTLE_FLOW": "tasks",
    "DEFAULT_JJC_BATTLE_FLOW": "tasks",
    "get_battle_profile": "tasks",
    # runtime task state helpers
    "get_task_status": "tasks.task_state",
    "set_task_status": "tasks.task_state",
}

# Subpackages / modules addressable as attributes, e.g. ``ZmxyOL.nav.mm``.
_SUBMODULES = (
    "accounts",
    "app_package_resolve",
    "battle",
    "character",
    "nav",
)

_PUBLIC_NAMES = [
    "h","combo",
    "Hero", "battle_plan", "flow", "BattlePlan",
    # nav
    'MapManager', 'Loc', 'Env', 'mm', 'path', 'ensure_in', 'try_close_via_x',
    'LoginClient', 'login',
    "detect_floating_window", "detect_floating_window_on_frame", "dismiss_floating_window",
    # task
    'register_task', "task_registry", "get_task_table",
    "get_task_status", "set_task_status",
    "BattleFlowName", "DEFAULT_BATTLE_FLOW", "DEFAULT_JJC_BATTLE_FLOW", "get_battle_profile",
    # loc env
    "LOC_ENV"  
]


def _package_init_is_running() -> bool:
    """True while a package that owns these exports is still initializing.

    ``tasks/task_register.py`` and the battle procedures run
    ``from ZmxyOL import *`` while ``tasks`` itself is only half built, so
    resolving an export would re-enter the very package being imported.
    Publishing ``__all__`` in that window makes the star-import request every
    name, including ones that cannot exist yet; reporting "no ``__all__``"
    instead lets it pick up whatever is already resolved.

    Only package initializers count. A leaf module that is mid-import (for
    example ``tasks/每日任务/荒古万界/遗境副本.py``) must still see the full
    export list, because those modules rely on ``from ZmxyOL import *`` to pick
    up names such as ``DEFAULT_BATTLE_FLOW``.
    """
    domain_roots = (__name__, "tasks")
    for module_name, module in tuple(_sys.modules.items()):
        if not any(
            module_name == root or module_name.startswith(root + ".")
            for root in domain_roots
        ):
            continue
        if not hasattr(module, "__path__"):
            continue
        spec = getattr(module, "__spec__", None)
        if spec is not None and getattr(spec, "_initializing", False):
            return True
    return False


def __getattr__(name: str) -> _Any:
    if name == "__all__":
        # Modules imported from a subpackage __init__ (task_register.py and the
        # battle procedures) run `from ZmxyOL import *` while that subpackage is
        # only partially built, so some export names cannot exist yet. Publishing
        # __all__ there would turn a historically silent star-import into a hard
        # AttributeError. Report "no __all__" for that window only, and publish
        # the full list for every later import.
        if _package_init_is_running():
            raise AttributeError(
                "__all__ is not available while ZmxyOL submodules initialize"
            )
        return _PUBLIC_NAMES
    source = _EXPORTS.get(name)
    if source is not None:
        value = getattr(_import_module(source), name)
        globals()[name] = value
        return value
    if name in _SUBMODULES:
        module = _import_module(f"{__name__}.{name}")
        globals()[name] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_PUBLIC_NAMES) | set(_SUBMODULES))


def drop_cached_exports() -> None:
    """Forget names this package resolved from a module that gets re-imported.

    ``__getattr__`` memoizes each export into ``globals()`` on first access, so a
    later ``from ZmxyOL import *`` reuses the bound object. A reload re-imports
    ``tasks`` and ``tasks.battle_task_params`` -- the task authoring surface and
    the flow enum -- and those names would otherwise keep serving the objects
    from before the reload. Names whose owning module survived the reload resolve
    back to the same object, so forgetting them is free.
    """
    for name in list(_EXPORTS):
        globals().pop(name, None)
