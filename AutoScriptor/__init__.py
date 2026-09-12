"""Public AutoScriptor API with lazy exports.

Importing subpackages such as ``AutoScriptor.control`` should not initialize
OCR, UI maps or device channels. Task scripts that use ``from AutoScriptor
import *`` still receive the same public symbols; they are loaded on demand.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from AutoScriptor.core.api import (
        click_all as click_all,
        close_app as close_app,
        go_home as go_home,
        init as init,
        launch_app as launch_app,
        swipe_precise as swipe_precise,
    )
    from AutoScriptor.core.display_contract import (
        MUMU_SIZE_1280_720 as MUMU_SIZE_1280_720,
        MUMU_SIZE_720_1280 as MUMU_SIZE_720_1280,
        getFrameSize as getFrameSize,
        setFrameSize as setFrameSize,
    )
    from AutoScriptor.utils.logger import logger as logger


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
    "ui": ("AutoScriptor.utils.ui_map", "ui"),
    # utils
    "cfg": ("AutoScriptor.utils.app_config", "cfg"),
    "logger": ("AutoScriptor.utils.logger", "logger"),
    "log_flush": ("AutoScriptor.utils.logger", "log_flush"),
    "make_box_grid": ("AutoScriptor.utils.box_grid", "make_box_grid"),
    "indexof": ("AutoScriptor.utils.box_grid", "indexof"),
    "get_task_status": ("AutoScriptor.utils.task_state", "get_task_status"),
    "set_task_status": ("AutoScriptor.utils.task_state", "set_task_status"),
    "setFrameSize": ("AutoScriptor.core.display_contract", "setFrameSize"),
    "getFrameSize": ("AutoScriptor.core.display_contract", "getFrameSize"),
    "MUMU_SIZE_1280_720": ("AutoScriptor.core.display_contract", "MUMU_SIZE_1280_720"),
    "MUMU_SIZE_720_1280": ("AutoScriptor.core.display_contract", "MUMU_SIZE_720_1280"),
    # runtime helpers
    "bg": ("AutoScriptor.core.background", "bg"),
    "BG_SIGNALS": ("AutoScriptor.core.background", "BG_SIGNALS"),
    "BgSignals": ("AutoScriptor.core.background", "BgSignals"),
}


for _name in [
    "init",
    "click",
    "click_all",
    "locate",
    "match",
    "input",
    "get_colors",
    "coloris",
    "swipe",
    "swipe_precise",
    "ui_T",
    "ui_F",
    "ui_idx",
    "key_event",
    "wait_for_appear",
    "wait_for_disappear",
    "wait_for_signal",
    "first",
    "simple",
    "full",
    "count",
    "switch_base",
    "ctrl_nemu",
    "ctrl_mumu",
    "sleep",
    "extract_info",
    "detect_floating_window",
    "dismiss_floating_window",
    "launch_app",
    "close_app",
    "go_home",
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
    # utils
    "cfg",
    "logger",
    "log_flush",
    "make_box_grid",
    "indexof",
    "get_task_status",
    "set_task_status",
    "setFrameSize",
    "getFrameSize",
    "MUMU_SIZE_1280_720",
    "MUMU_SIZE_720_1280",
    # api
    "init",
    "click",
    "click_all",
    "locate",
    "match",
    "input",
    "get_colors",
    "coloris",
    "swipe",
    "swipe_precise",
    "ui_T",
    "ui_F",
    "ui_idx",
    "key_event",
    "wait_for_appear",
    "wait_for_disappear",
    "wait_for_signal",
    "first",
    "simple",
    "full",
    "count",
    "switch_base",
    "ctrl_nemu",
    "ctrl_mumu",
    "sleep",
    "extract_info",
    "detect_floating_window",
    "dismiss_floating_window",
    "launch_app",
    "close_app",
    "go_home",
    "ensure_app_running",
    "ensure_all_environment_ready",
    "bg",
    "BG_SIGNALS",
    "BgSignals",
    "mixctrl",
    "mumu",
    "RequestHumanTakeover",
    "TaskRequireReTry",
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
