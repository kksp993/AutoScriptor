"""In-process version counter for WebUI configuration snapshots."""
from __future__ import annotations

from threading import Lock

_lock = Lock()
_version = 1


def bump_version(_reason: str = "") -> int:
    global _version
    with _lock:
        _version += 1
        return _version


def current_version() -> int:
    with _lock:
        return _version
