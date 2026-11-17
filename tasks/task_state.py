"""Per-task runtime status helpers.

Task status is persisted under the active character's ``cfg["status"]`` tree,
with cycle deadlines stored separately from script-defined tag names.
"""
from __future__ import annotations

import math
import numbers
import re
import threading
import time
from copy import deepcopy
from datetime import datetime
from typing import Any

from AutoScriptor.utils.app_config import cfg
from tasks.task_schedule import next_regular_execution_time, resolve_reschedule

_task_ctx = threading.local()
_PROGRESS_RE = re.compile(r"^\s*(\d+)\s*/\s*(\d+)\s*$")


def set_current_task_path(task_path: str | None) -> None:
    _task_ctx.path = task_path
    _task_ctx.next_run_at = None


def current_task_path() -> str | None:
    return getattr(_task_ctx, "path", None)


def set_task_next_run(delay_seconds: float) -> None:
    """Request another stage after a positive delay, without changing reschedule.

    Only usable inside the executing task thread. The last call wins; it does
    not sleep or return from the task. The executor commits the request only
    after the entire function (including cleanup) returns without cancellation
    or an exception. A later invocation without a request completes normally.
    """
    if current_task_path() is None:
        raise RuntimeError("set_task_next_run is only available during task execution")
    if isinstance(delay_seconds, bool) or not isinstance(delay_seconds, numbers.Real):
        raise TypeError("delay_seconds must be a positive finite number")
    if not math.isfinite(delay_seconds) or delay_seconds <= 0:
        raise ValueError("delay_seconds must be a positive finite number")
    next_run_at = time.time() + delay_seconds
    try:
        datetime.fromtimestamp(next_run_at)
    except (OverflowError, OSError, ValueError):
        raise ValueError("delay_seconds exceeds the supported date range") from None
    _task_ctx.next_run_at = next_run_at


def get_requested_next_run_time() -> float | None:
    """Executor-only access to the current attempt's uncommitted request."""
    return getattr(_task_ctx, "next_run_at", None)


def _resolve_task_path(task_path: str | None) -> str:
    resolved = task_path or current_task_path()
    if not resolved:
        raise RuntimeError("task_path is required outside task execution")
    return resolved


def _resolve_status_schedule(task_path: str) -> dict:
    from tasks.task_register import task_registry

    entry = (cfg._config.get("tasks") or {}).get(task_registry.id_of(task_path))
    return resolve_reschedule(task_path, entry)


def _is_current_status_cycle(cycle: dict | None, spec: dict, now_ts: float) -> bool:
    if not isinstance(cycle, dict):
        # Legacy periodic tags have no provable cycle; never adopt them as today's work.
        return spec["mode"] == "once"
    if cycle.get("mode") != spec["mode"] or cycle.get("hours") != spec["hours"]:
        return False
    reset_at = cycle.get("reset_at")
    if spec["mode"] == "once":
        return reset_at is None
    return isinstance(reset_at, (int, float)) and math.isfinite(reset_at) and now_ts < reset_at


def task_status_snapshot(status: dict, task_path: str, spec: dict, now_ts: float) -> dict[str, Any]:
    """Read-only current-cycle view for APIs and active/inactive character projections."""
    cycle = (status.get("task_cycles") or {}).get(task_path)
    if not _is_current_status_cycle(cycle, spec, now_ts):
        return {}
    node = (status.get("tasks") or {}).get(task_path, {})
    return deepcopy(node) if isinstance(node, dict) else {}


def refresh_task_status_cycle(task_path: str, *, now_ts: float | None = None, completed: bool = False) -> None:
    """Prepare a cycle without saving; continuations must never move its deadline."""
    if now_ts is None:
        now_ts = time.time()
    spec = _resolve_status_schedule(task_path)
    status = cfg._config.setdefault("status", {})
    cycles = status.setdefault("task_cycles", {})
    cycle = cycles.get(task_path)
    current_cycle = _is_current_status_cycle(cycle, spec, now_ts)
    if not current_cycle:
        status.setdefault("tasks", {}).pop(task_path, None)
    if not current_cycle or cycle is None:
        cycles[task_path] = {
            "mode": spec["mode"],
            "hours": spec["hours"],
            "reset_at": next_regular_execution_time(datetime.fromtimestamp(now_ts), spec),
        }
    elif completed and spec["mode"] == "offset":
        # An ordinary N-hour schedule starts its next interval at final completion.
        cycles[task_path]["reset_at"] = next_regular_execution_time(datetime.fromtimestamp(now_ts), spec)


def get_task_status(field: str, default: Any = None, *, task_path: str | None = None) -> Any:
    """Read a current-cycle tag; expired/missing tags return default without saving."""
    path = _resolve_task_path(task_path)
    status = cfg._config.get("status") or {}
    return task_status_snapshot(status, path, _resolve_status_schedule(path), time.time()).get(field, default)


def set_task_status(field: str, value: Any, *, task_path: str | None = None, save: bool = True) -> Any:
    """Persist a JSON-compatible tag until the regular schedule's cycle boundary.

    Names are script-defined; ``progress`` retains its executor-managed meaning.
    Task/character/account state is isolated. Continuation delays do not extend
    tag lifetime; daily resets at local 05:00, weekly at Monday 05:00.
    """
    path = _resolve_task_path(task_path)
    refresh_task_status_cycle(path)
    cfg._config["status"].setdefault("tasks", {}).setdefault(path, {})[field] = value
    if save:
        cfg.save_config()
    return value


def clear_task_status(field: str | None = None, *, task_path: str | None = None, save: bool = True) -> None:
    path = _resolve_task_path(task_path)
    status = cfg._config.setdefault("status", {})
    if field is None:
        status.setdefault("tasks", {}).pop(path, None)
        status.setdefault("task_cycles", {}).pop(path, None)
    else:
        (status.get("tasks") or {}).get(path, {}).pop(field, None)
    if save:
        cfg.save_config()


def progress_tuple(value: Any) -> tuple[int, int] | None:
    if isinstance(value, dict):
        done = value.get("done", value.get("current", value.get("completed")))
        total = value.get("total")
    elif isinstance(value, (list, tuple)) and len(value) >= 2:
        done, total = value[0], value[1]
    elif isinstance(value, str):
        m = _PROGRESS_RE.match(value)
        if not m:
            return None
        done, total = m.groups()
    else:
        return None
    try:
        done_i, total_i = int(done), int(total)
    except (TypeError, ValueError):
        return None
    if total_i <= 0:
        return None
    return done_i, total_i


def progress_label(value: Any) -> str | None:
    pair = progress_tuple(value)
    if pair is None:
        return None
    return f"{pair[0]}/{pair[1]}"


def progress_incomplete(value: Any) -> bool:
    pair = progress_tuple(value)
    return pair is not None and pair[0] < pair[1]
