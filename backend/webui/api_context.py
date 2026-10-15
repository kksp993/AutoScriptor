"""Shared request context for the WebUI API.

Every route needs the same small set of things, and each one is a fact the
orchestrator already owns -- so this module is the single place that reaches
for it, rather than each handler (or each route module) deciding for itself:

- the execution guard: config writes must not race a running task, and the
  conflict payload the orchestrator returns has to become one 409 shape;
- the public config projection: what the browser is allowed to see;
- the persistence diagnosis attached to a failed write.

Route modules import this instead of the server that happens to be running.
"""
from __future__ import annotations

from fastapi.responses import JSONResponse

from AutoScriptor.utils.app_config import cfg
from AutoScriptor.utils.paths import get_data_root
from ZmxyOL.accounts import get_accounts_dir
from backend.webui.api_response import api_error, api_ok
from orchestrator import (
    bump_version,
    current_version,
    orchestrator,
    summarize_ordering_generations,
)


# ── execution guard ──

def conflict_response(conflict: dict) -> JSONResponse:
    """Shape an execution conflict from the orchestrator into one 409."""
    return api_error(
        409,
        conflict["message"],
        code=conflict["code"],
        reason=conflict["reason"],
        action=conflict["action"],
    )


def guard_runtime_idle(action: str = "modify runtime config") -> JSONResponse | None:
    """The 409 to send when a task is running, or ``None`` when it is safe to write."""
    conflict = orchestrator.guard_idle(action)
    return None if conflict is None else conflict_response(conflict)


def busy_response(action: str) -> JSONResponse:
    """The 409 to send when a request wants to start execution that is already busy."""
    return conflict_response(orchestrator.busy_conflict(action))


# ── public config projection ──

def public_config_unlocked() -> dict:
    data = orchestrator.tree.public_config()
    data["config_version"] = current_version()
    return data


def public_config() -> dict:
    """The public config snapshot, taken under the lifecycle lock when attached."""
    service = orchestrator.tasks
    if service is None:
        return public_config_unlocked()
    with service.config_operation():
        return public_config_unlocked()


def task_ordering_response() -> dict:
    projection = orchestrator.tree.task_ordering_projection()
    return api_ok(
        status="ok",
        config_version=current_version(),
        projection=projection.to_public_dict(),
        generations=summarize_ordering_generations(projection),
        runtime=orchestrator.execution.status(),
    )


def mark_config_changed(reason: str) -> int:
    return bump_version(reason)


def consume_runtime_config_updates() -> bool:
    """Adopt task-state writes the scheduler made while the UI was polling."""
    if not orchestrator.scheduler.consume_tasks_updated():
        return False
    mark_config_changed("runtime tasks updated")
    return True


# ── persistence diagnosis ──

def persistence_diagnostics() -> dict[str, str]:
    return {
        "data_root": str(get_data_root()),
        "config_path": str(getattr(cfg, "CONFIG_PATH", "")),
        "accounts_dir": str(getattr(cfg, "ACCOUNTS_DIR", get_accounts_dir())),
        "current_account": str(cfg.current_account() or ""),
    }


def persistence_error_message(action: str, exc: Exception) -> str:
    diagnostics = persistence_diagnostics()
    return (
        f"{action}: {exc}; "
        f"config={diagnostics['config_path']}; accounts={diagnostics['accounts_dir']}; "
        f"dataRoot={diagnostics['data_root']}"
    )
