"""Per-task runtime status helpers.

Task status is persisted under the active character's ``cfg["status"]`` tree,
so it follows the same account/character split as task configuration.
"""
from __future__ import annotations

import re
import threading
from typing import Any

from AutoScriptor.utils.app_config import cfg

_task_ctx = threading.local()
_PROGRESS_RE = re.compile(r"^\s*(\d+)\s*/\s*(\d+)\s*$")


def set_current_task_path(task_path: str | None) -> None:
    _task_ctx.path = task_path


def current_task_path() -> str | None:
    return getattr(_task_ctx, "path", None)


def _resolve_task_path(task_path: str | None) -> str:
    resolved = task_path or current_task_path()
    if not resolved:
        raise RuntimeError("task_path is required outside task execution")
    return resolved


def _task_status_node(task_path: str, *, create: bool) -> dict[str, Any]:
    root = cfg._config.setdefault("status", {}).setdefault("tasks", {})
    if create:
        return root.setdefault(task_path, {})
    node = root.get(task_path, {})
    return node if isinstance(node, dict) else {}


def get_task_status(field: str, default: Any = None, *, task_path: str | None = None) -> Any:
    """Return a persisted status field for the current or specified task."""
    path = _resolve_task_path(task_path)
    return _task_status_node(path, create=False).get(field, default)


def set_task_status(field: str, value: Any, *, task_path: str | None = None, save: bool = True) -> Any:
    """Persist a status field for the current or specified task, then return it."""
    path = _resolve_task_path(task_path)
    _task_status_node(path, create=True)[field] = value
    if save:
        cfg.save_config()
    return value


def clear_task_status(field: str | None = None, *, task_path: str | None = None, save: bool = True) -> None:
    path = _resolve_task_path(task_path)
    if field is None:
        cfg._config.setdefault("status", {}).setdefault("tasks", {}).pop(path, None)
    else:
        _task_status_node(path, create=False).pop(field, None)
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
