"""Lazy public exports for ``AutoScriptor.core``.

Importing a lightweight submodule such as ``AutoScriptor.core.background``
must not initialize OCR, MuMu control, or other runtime-heavy modules. Star
imports still expose the legacy public API; those symbols are loaded on demand.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORTS: dict[str, tuple[str, str]] = {
    "Target": ("AutoScriptor.core.targets", "Target"),
    "B": ("AutoScriptor.core.targets", "B"),
    "I": ("AutoScriptor.core.targets", "I"),
    "T": ("AutoScriptor.core.targets", "T"),
    "make_box_grid": ("AutoScriptor.core.box_grid", "make_box_grid"),
    "indexof": ("AutoScriptor.core.box_grid", "indexof"),
    "bg": ("AutoScriptor.core.background", "bg"),
    "BG_SIGNALS": ("AutoScriptor.core.background", "BG_SIGNALS"),
    "BgSignals": ("AutoScriptor.core.background", "BgSignals"),
    # device session lifetime
    "runtime_ctx": ("AutoScriptor.core.runtime_context", "runtime_ctx"),
    "RuntimeContext": ("AutoScriptor.core.runtime_context", "RuntimeContext"),
}

for _name in [
    "init",
    "click",
    "click_all",
    "locate",
    "match",
    "wait_for_appear",
    "wait_for_disappear",
    "wait_for_signal",
    "input",
    "get_colors",
    "coloris",
    "swipe",
    "swipe_precise",
    "ui_T",
    "ui_F",
    "ui_idx",
    "first",
    "simple",
    "full",
    "count",
    "switch_base",
    "ctrl_nemu",
    "ctrl_mumu",
    "sleep",
    "extract_info",
    "key_event",
    "launch_app",
    "close_app",
    "go_home",
    "mixctrl",
    "mumu",
    "ensure_app_running",
    "ensure_all_environment_ready",
]:
    _EXPORTS[_name] = ("AutoScriptor.core.api", _name)


# Addressable as attributes, e.g. ``AutoScriptor.core.runtime_context``.
_SUBMODULES = ("runtime_context",)


__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if target is not None:
        module_name, attr_name = target
        value = getattr(import_module(module_name), attr_name)
        globals()[name] = value
        return value
    if name in _SUBMODULES:
        module = import_module(f"{__name__}.{name}")
        globals()[name] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__) | set(_SUBMODULES))
