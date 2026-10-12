"""Windows 主机（桌面）键鼠与截屏控制。

控制的是**主机上的普通 Windows 程序**（浏览器、PC 客户端等），与模拟器控制互补：

* 模拟器 / 游戏本体：``AutoScriptor.core.control.MixControl``（NemuIpc / ADB）；
* 主机桌面程序：本包 ``DesktopControl``。

设计要点：

* 键鼠注入用系统自带的 ``SendInput`` / ``SetCursorPos``（pyautogui、pynput 这类
  成熟框架内部包的就是这组 API），不新增第三方依赖，也不需要改 ``requirements.txt``。
* 识别复用项目既有框架：``T("文字")`` / ``I(图片)`` / ``B(Box)`` 目标 + 
  ``locate_on_screen``，返回统一的 ``Box``，与游戏识别同一套代码。
* 坐标合同：物理像素、虚拟桌面左上角为原点；使用前先声明 DPI 感知（``control``
  会自己调），否则 125%/150% 缩放下截图尺寸和鼠标坐标对不上。

典型用法::

    from AutoScriptor.control.DesktopControl import get_desktop
    from AutoScriptor import T

    desktop = get_desktop()
    desktop.activate_window("msedge.exe")     # 先把目标窗口提到前台
    desktop.hotkey("ctrl", "l")               # 聚焦地址栏
    desktop.type_text("http://127.0.0.1:5000")
    desktop.press("enter")
    desktop.click_text(T("终止执行"))          # 定位识别出来的按钮再点它的中心
"""

from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORTS: dict[str, tuple[str, str]] = {
    "DesktopControl": ("AutoScriptor.control.DesktopControl.control", "DesktopControl"),
    "get_desktop": ("AutoScriptor.control.DesktopControl.control", "get_desktop"),
    "WindowInfo": ("AutoScriptor.control.DesktopControl.windows", "WindowInfo"),
    "find_windows": ("AutoScriptor.control.DesktopControl.windows", "find_windows"),
    "foreground_window": ("AutoScriptor.control.DesktopControl.windows", "foreground_window"),
    "capture": ("AutoScriptor.control.DesktopControl.screen", "capture"),
    "virtual_screen_box": ("AutoScriptor.control.DesktopControl.screen", "virtual_screen_box"),
    "DesktopControlError": ("AutoScriptor.control.DesktopControl._win32", "DesktopControlError"),
    "InputInjectionBlocked": ("AutoScriptor.control.DesktopControl._win32", "InputInjectionBlocked"),
    "UnsupportedPlatformError": ("AutoScriptor.control.DesktopControl._win32", "UnsupportedPlatformError"),
}

# 子模块导出刻意不收 ``inputs``：它会在 ``import *`` 时遮蔽内置的 ``input``。
_MODULE_EXPORTS = {
    "control": "AutoScriptor.control.DesktopControl.control",
    "inputs": "AutoScriptor.control.DesktopControl.inputs",
    "screen": "AutoScriptor.control.DesktopControl.screen",
    "windows": "AutoScriptor.control.DesktopControl.windows",
}

__all__ = [
    "DesktopControl",
    "get_desktop",
    "WindowInfo",
    "find_windows",
    "foreground_window",
    "capture",
    "virtual_screen_box",
    "DesktopControlError",
    "InputInjectionBlocked",
    "UnsupportedPlatformError",
    "control",
    "screen",
    "windows",
]


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
