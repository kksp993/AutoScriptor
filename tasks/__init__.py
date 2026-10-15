"""Task scripts: what a task *is*.

This package owns the authoring surface (``@register_task``), the runtime
metadata table and task-local state. Deciding which task modules exist, in what
order they load and how the task tree lands in config is ``orchestrator``'s job.

The exports here are eager on purpose. ``task_register`` runs
``from ZmxyOL import *``, and ``ZmxyOL`` maps ``register_task`` back to this
package -- resolving that lazily would re-enter the module that is still being
imported. Binding the real attributes up front removes the re-entry.
"""
from __future__ import annotations

# Game-layer self-registration. Importing these attaches the account backend,
# the package-name resolver and navigation to AutoScriptor's generic layer, so a
# task script imported on its own still finds them ready. Idempotent.
from ZmxyOL.accounts import account_store as _account_store  # noqa: F401
from ZmxyOL import app_package_resolve as _app_package_resolve  # noqa: F401
from ZmxyOL import nav as _nav  # noqa: F401

from tasks.battle_task_params import (
    BattleFlowName as BattleFlowName,
    DEFAULT_BATTLE_FLOW as DEFAULT_BATTLE_FLOW,
    DEFAULT_JJC_BATTLE_FLOW as DEFAULT_JJC_BATTLE_FLOW,
    get_battle_profile as get_battle_profile,
)
# 注册入口和注册表同出一处：表就是 task_register 里的那一个实例。
from tasks.task_register import register_task as register_task
from tasks.task_register import task_registry as task_registry
from tasks.task_state import (
    clear_task_status as clear_task_status,
    get_task_status as get_task_status,
    set_task_status as set_task_status,
)


__all__ = [
    "register_task",
    "task_registry",
    "BattleFlowName",
    "DEFAULT_BATTLE_FLOW",
    "DEFAULT_JJC_BATTLE_FLOW",
    "get_battle_profile",
    "get_task_status",
    "set_task_status",
    "clear_task_status",
]
