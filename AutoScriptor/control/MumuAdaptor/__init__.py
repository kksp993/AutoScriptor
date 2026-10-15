"""MuMu adapter package with lazy public exports."""

from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORTS: dict[str, tuple[str, str]] = {
    "Mumu": ("AutoScriptor.control.MumuAdaptor.mumu", "Mumu"),
    "AndroidKey": ("AutoScriptor.control.MumuAdaptor.constant", "AndroidKey"),
    "utils": ("AutoScriptor.control.MumuAdaptor.utils", "utils"),
}

_MODULE_EXPORTS = {
    "api": "AutoScriptor.control.MumuAdaptor.api",
    "constant": "AutoScriptor.control.MumuAdaptor.constant",
}

__all__ = ["Mumu", "constant", "utils", "api", "AndroidKey"]


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if target is not None:
        module_name, attr_name = target
        value = getattr(import_module(module_name), attr_name)
        globals()[name] = value
        return value
    module_name = _MODULE_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = import_module(module_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
