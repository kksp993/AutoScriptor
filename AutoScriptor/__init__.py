"""Public AutoScriptor API with lazy exports.

Importing subpackages such as ``AutoScriptor.control`` should not initialize
OCR, UI maps or device channels. Task scripts that use ``from AutoScriptor
import *`` still receive the same public symbols; they are loaded on demand.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any


_ERROR_EXPORTS = [
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


_EXPORTS: dict[str, tuple[str, str]] = {
    # targets
    "Box": ("AutoScriptor.utils.box", "Box"),
    "box_cell_in_grid": ("AutoScriptor.utils.box", "box_cell_in_grid"),
    "Target": ("AutoScriptor.core.targets", "Target"),
    "B": ("AutoScriptor.core.targets", "B"),
    "I": ("AutoScriptor.core.targets", "I"),
    "T": ("AutoScriptor.core.targets", "T"),
    "V": ("AutoScriptor.core.targets", "V"),
    "ui": ("AutoScriptor.utils.ui_map", "ui"),
    # utils
    "cfg": ("AutoScriptor.utils.app_config", "cfg"),
    "log_flush": ("AutoScriptor.utils.logger", "log_flush"),
    "perf_boost": ("AutoScriptor.utils.perf", "boost"),
    "make_box_grid": ("AutoScriptor.utils.box_grid", "make_box_grid"),
    "indexof": ("AutoScriptor.utils.box_grid", "indexof"),
    # runtime helpers
    "bg": ("AutoScriptor.core.background", "bg"),
    "BG_SIGNALS": ("AutoScriptor.core.background", "BG_SIGNALS"),
    "BgSignals": ("AutoScriptor.core.background", "BgSignals"),
    "set_config": ("AutoScriptor.crypto.update_config", "set_config"),
    "verify_config": ("AutoScriptor.crypto.update_config", "verify_config"),
}


for _name in [
    "init",
    "click",
    "locate",
    "input",
    "get_colors",
    "edit_img",
    "swipe",
    "ui_T",
    "ui_F",
    "ui_idx",
    "key_event",
    "wait_for_appear",
    "wait_for_disappear",
    "first",
    "simple",
    "full",
    "count",
    "switch_base",
    "sleep",
    "extract_info",
    "detect_floating_window",
    "dismiss_floating_window",
    "ensure_app_running",
    "ensure_all_environment_ready",
    "mixctrl",
    "mumu",
]:
    _EXPORTS[_name] = ("AutoScriptor.core.api", _name)


for _name in _ERROR_EXPORTS:
    _EXPORTS[_name] = ("AutoScriptor.errors", _name)


__all__ = [
    # targets
    "Box",
    "box_cell_in_grid",
    "Target",
    "ui",
    "B",
    "I",
    "T",
    "V",
    # utils
    "cfg",
    "log_flush",
    "make_box_grid",
    "indexof",
    # api
    "init",
    "click",
    "locate",
    "input",
    "get_colors",
    "edit_img",
    "swipe",
    "ui_T",
    "ui_F",
    "ui_idx",
    "key_event",
    "wait_for_appear",
    "wait_for_disappear",
    "first",
    "simple",
    "full",
    "count",
    "switch_base",
    "sleep",
    "extract_info",
    "detect_floating_window",
    "dismiss_floating_window",
    "ensure_app_running",
    "ensure_all_environment_ready",
    "bg",
    "BG_SIGNALS",
    "BgSignals",
    "mixctrl",
    "mumu",
    "set_config",
    "verify_config",
    "RequestHumanTakeover",
    "TaskRequireReTry",
    "perf_boost",
    *_ERROR_EXPORTS,
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
