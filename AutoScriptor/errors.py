"""Unified exception exports with lazy runtime-control dependencies."""

from __future__ import annotations

from importlib import import_module
from typing import Any


class TaskRequireReTry(Exception):
    """Task can be retried without counting as a terminal failure."""

    pass


_EXPORTS: dict[str, tuple[str, str]] = {
    "RequestHumanTakeover": ("AutoScriptor.control.NemuIpc.device.method.nemu_ipc", "RequestHumanTakeover"),
    "NemuIpcIncompatible": ("AutoScriptor.control.NemuIpc.device.method.nemu_ipc", "NemuIpcIncompatible"),
    "NemuIpcError": ("AutoScriptor.control.NemuIpc.device.method.nemu_ipc", "NemuIpcError"),
    "JobError": ("AutoScriptor.control.NemuIpc.device.method.pool", "JobError"),
    "JobTimeout": ("AutoScriptor.control.NemuIpc.device.method.pool", "JobTimeout"),
    "_JobKill": ("AutoScriptor.control.NemuIpc.device.method.pool", "_JobKill"),
    "PackageNotInstalled": ("AutoScriptor.control.NemuIpc.device.method.utils", "PackageNotInstalled"),
    "ImageTruncated": ("AutoScriptor.control.NemuIpc.device.method.utils", "ImageTruncated"),
    "ImageNotSupported": ("AutoScriptor.control.NemuIpc.base.utils.utils", "ImageNotSupported"),
}


__all__ = [
    "RequestHumanTakeover",
    "NemuIpcIncompatible",
    "NemuIpcError",
    "JobError",
    "JobTimeout",
    "_JobKill",
    "PackageNotInstalled",
    "ImageTruncated",
    "ImageNotSupported",
    "TaskRequireReTry",
]


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = target
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
