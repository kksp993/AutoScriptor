"""Windows 原生绑定：DPI、虚拟桌面坐标、键鼠注入、顶层窗口。

这是 ``DesktopControl`` 的最低层，只做 ctypes 绑定与参数校验，不含业务语义。

为什么直接用系统 API：键鼠注入用的是 Windows 自带的 ``SendInput`` /
``SetCursorPos``，pyautogui、pynput 这类成熟框架内部同样是包这一组 API，
所以不再引入新的第三方依赖（``requirements.txt`` 不需要动）。

坐标合同（整个 DesktopControl 只有这一套）：**物理像素，原点在虚拟桌面左上角**。
多显示器时原点可能是负数（副屏挂在主屏左侧）。截图数组下标和鼠标坐标都按这
一套算，所以「屏幕上量到的像素」可以直接当点击坐标用。

进程必须先声明 DPI 感知（``ensure_dpi_awareness``）。否则在 125% / 150% 缩放
的机器上，Windows 会按缩放比虚拟化分辨率和坐标，截图尺寸和鼠标坐标就对不上。
"""

from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes

from AutoScriptor.logging.logger import logger


IS_WINDOWS = sys.platform == "win32"


class DesktopControlError(RuntimeError):
    """Windows 主机控制的基础异常。"""


class UnsupportedPlatformError(DesktopControlError):
    """在非 Windows 平台使用主机控制。"""


class InputInjectionBlocked(DesktopControlError):
    """事件没有进入系统输入队列。

    最典型的原因是前台窗口属于更高完整性级别（例如以管理员身份运行的程序）：
    Windows 会静默丢弃普通权限进程注入的输入，``SendInput`` 返回 0 但不报错。
    这种情况必须显式抛错——「坐标算错」和「点了但系统没收」要用完全不同的
    方式排查，混在一起会把人带偏。
    """


# ---------------------------------------------------------------- 常量

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

WHEEL_DELTA = 120

SW_RESTORE = 9

SM_CXSCREEN = 0
SM_CYSCREEN = 1
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

_DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)
_DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE = ctypes.c_void_p(-3)
_PROCESS_PER_MONITOR_DPI_AWARE = 2

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_DWMWA_CLOAKED = 14
_DWMWA_EXTENDED_FRAME_BOUNDS = 9


# ---------------------------------------------------------------- 结构体

# dwExtraInfo 在 64 位下是 8 字节的 ULONG_PTR；用 POINTER(c_ulong) 之类写错
# 会让结构体尺寸对不上，SendInput 直接拒绝整批事件。
ULONG_PTR = ctypes.c_uint64 if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_uint32


class MOUSEINPUT(ctypes.Structure):
    _fields_ = (
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    )


class KEYBDINPUT(ctypes.Structure):
    _fields_ = (
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    )


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = (
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    )


class _INPUTUNION(ctypes.Union):
    _fields_ = (("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT))


class INPUT(ctypes.Structure):
    _anonymous_ = ("union",)
    _fields_ = (("type", wintypes.DWORD), ("union", _INPUTUNION))


if IS_WINDOWS:
    _USER32 = ctypes.WinDLL("user32", use_last_error=True)
    _KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
    try:
        _SHCORE = ctypes.WinDLL("shcore", use_last_error=True)
    except OSError:
        _SHCORE = None
    try:
        _DWMAPI = ctypes.WinDLL("dwmapi", use_last_error=True)
    except OSError:
        _DWMAPI = None

    _WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    # 显式声明签名：64 位下句柄是指针宽度，让 ctypes 按默认 c_int 传会把高位截断，
    # 表现为「调用成功但作用在错误的窗口上」甚至进程崩溃。
    _USER32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
    _USER32.SendInput.restype = wintypes.UINT
    _USER32.SetCursorPos.argtypes = (ctypes.c_int, ctypes.c_int)
    _USER32.SetCursorPos.restype = wintypes.BOOL
    _USER32.GetCursorPos.argtypes = (ctypes.POINTER(wintypes.POINT),)
    _USER32.GetCursorPos.restype = wintypes.BOOL
    _USER32.GetSystemMetrics.argtypes = (ctypes.c_int,)
    _USER32.GetSystemMetrics.restype = ctypes.c_int
    _USER32.VkKeyScanW.argtypes = (wintypes.WCHAR,)
    _USER32.VkKeyScanW.restype = ctypes.c_short

    _USER32.EnumWindows.argtypes = (_WNDENUMPROC, wintypes.LPARAM)
    _USER32.EnumWindows.restype = wintypes.BOOL
    _USER32.IsWindow.argtypes = (wintypes.HWND,)
    _USER32.IsWindow.restype = wintypes.BOOL
    _USER32.IsWindowVisible.argtypes = (wintypes.HWND,)
    _USER32.IsWindowVisible.restype = wintypes.BOOL
    _USER32.IsIconic.argtypes = (wintypes.HWND,)
    _USER32.IsIconic.restype = wintypes.BOOL
    _USER32.GetWindowTextLengthW.argtypes = (wintypes.HWND,)
    _USER32.GetWindowTextLengthW.restype = ctypes.c_int
    _USER32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    _USER32.GetWindowTextW.restype = ctypes.c_int
    _USER32.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    _USER32.GetClassNameW.restype = ctypes.c_int
    _USER32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
    _USER32.GetWindowRect.restype = wintypes.BOOL
    _USER32.GetForegroundWindow.argtypes = ()
    _USER32.GetForegroundWindow.restype = wintypes.HWND
    _USER32.SetForegroundWindow.argtypes = (wintypes.HWND,)
    _USER32.SetForegroundWindow.restype = wintypes.BOOL
    _USER32.BringWindowToTop.argtypes = (wintypes.HWND,)
    _USER32.BringWindowToTop.restype = wintypes.BOOL
    _USER32.SetFocus.argtypes = (wintypes.HWND,)
    _USER32.SetFocus.restype = wintypes.HWND
    _USER32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
    _USER32.ShowWindow.restype = wintypes.BOOL
    _USER32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    _USER32.GetWindowThreadProcessId.restype = wintypes.DWORD
    _USER32.AttachThreadInput.argtypes = (wintypes.DWORD, wintypes.DWORD, wintypes.BOOL)
    _USER32.AttachThreadInput.restype = wintypes.BOOL

    _KERNEL32.GetCurrentThreadId.argtypes = ()
    _KERNEL32.GetCurrentThreadId.restype = wintypes.DWORD
    _KERNEL32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    _KERNEL32.OpenProcess.restype = wintypes.HANDLE
    _KERNEL32.QueryFullProcessImageNameW.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    )
    _KERNEL32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    _KERNEL32.CloseHandle.argtypes = (wintypes.HANDLE,)
    _KERNEL32.CloseHandle.restype = wintypes.BOOL

    if _DWMAPI is not None:
        _DWMAPI.DwmGetWindowAttribute.argtypes = (
            wintypes.HWND,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
        )
        _DWMAPI.DwmGetWindowAttribute.restype = ctypes.c_long
else:  # pragma: no cover - 项目只在 Windows 上运行，这里只是让模块可导入
    _USER32 = _KERNEL32 = _SHCORE = _DWMAPI = None
    _WNDENUMPROC = None


def _require_windows() -> None:
    if not IS_WINDOWS:
        raise UnsupportedPlatformError(
            f"DesktopControl 依赖 Windows 的 SendInput / 窗口 API，当前平台是 {sys.platform!r}"
        )


def _last_error_message() -> str:
    error_code = ctypes.get_last_error()
    if not error_code:
        return "GetLastError()=0（通常表示输入被更高权限的窗口拦下）"
    return f"GetLastError()={error_code}: {ctypes.FormatError(error_code)}"


# ---------------------------------------------------------------- DPI

_dpi_awareness_mode: str | None = None


def ensure_dpi_awareness() -> str:
    """让本进程按物理像素理解屏幕坐标；返回实际生效的模式（幂等）。

    按 Windows 版本从新到旧尝试：Per-Monitor V2（Win10 1703+）→ Per-Monitor
    （Win8.1+）→ System Aware。三种都失败说明进程已经被别人设过 DPI 感知
    （例如宿主外壳），这时沿用已有设置并如实返回，不再报错。

    注意：DPI 感知是**进程级**且不可撤销的设置，必须在任何截图/坐标计算之前
    调用一次。
    """
    global _dpi_awareness_mode
    if _dpi_awareness_mode is not None:
        return _dpi_awareness_mode
    _require_windows()

    set_context = getattr(_USER32, "SetProcessDpiAwarenessContext", None)
    if set_context is not None:
        set_context.argtypes = (ctypes.c_void_p,)
        set_context.restype = wintypes.BOOL
        if set_context(_DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2):
            _dpi_awareness_mode = "per-monitor-v2"
            return _dpi_awareness_mode
        if set_context(_DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE):
            _dpi_awareness_mode = "per-monitor"
            return _dpi_awareness_mode

    if _SHCORE is not None:
        try:
            if _SHCORE.SetProcessDpiAwareness(_PROCESS_PER_MONITOR_DPI_AWARE) == 0:
                _dpi_awareness_mode = "per-monitor"
                return _dpi_awareness_mode
        except OSError:
            pass

    if _USER32.SetProcessDPIAware():
        _dpi_awareness_mode = "system"
        return _dpi_awareness_mode

    # 已经被设置过（E_ACCESSDENIED / 0 都走这里），沿用现状。
    _dpi_awareness_mode = "unchanged"
    logger.debug("进程 DPI 感知已由其它组件设置，DesktopControl 沿用现状")
    return _dpi_awareness_mode


# ---------------------------------------------------------------- 坐标


def primary_screen_size() -> tuple[int, int]:
    """主屏物理像素尺寸。"""
    _require_windows()
    return int(_USER32.GetSystemMetrics(SM_CXSCREEN)), int(_USER32.GetSystemMetrics(SM_CYSCREEN))


def virtual_screen_rect() -> tuple[int, int, int, int]:
    """整个虚拟桌面（所有显示器）的 ``(left, top, width, height)``。

    多显示器时 ``left`` / ``top`` 可能是负数，这就是坐标原点可能不在 (0, 0)
    的原因。
    """
    _require_windows()
    left = int(_USER32.GetSystemMetrics(SM_XVIRTUALSCREEN))
    top = int(_USER32.GetSystemMetrics(SM_YVIRTUALSCREEN))
    width = int(_USER32.GetSystemMetrics(SM_CXVIRTUALSCREEN))
    height = int(_USER32.GetSystemMetrics(SM_CYVIRTUALSCREEN))
    if width <= 0 or height <= 0:
        # 极少见：会话没有显示器（例如无头 RDP 断开）。退回主屏尺寸，避免除零。
        width, height = primary_screen_size()
        left = top = 0
    return left, top, width, height


def move_cursor(x: int, y: int) -> None:
    """把光标移动到虚拟桌面坐标 ``(x, y)``。"""
    _require_windows()
    if not _USER32.SetCursorPos(int(x), int(y)):
        raise DesktopControlError(f"SetCursorPos({x}, {y}) 失败：{_last_error_message()}")


def cursor_position() -> tuple[int, int]:
    """当前光标位置（虚拟桌面坐标）。"""
    _require_windows()
    point = wintypes.POINT()
    if not _USER32.GetCursorPos(ctypes.byref(point)):
        raise DesktopControlError(f"GetCursorPos 失败：{_last_error_message()}")
    return int(point.x), int(point.y)


# ---------------------------------------------------------------- 输入注入


def send_inputs(inputs: list[INPUT]) -> int:
    """发送一批输入事件；被系统拦截时抛 ``InputInjectionBlocked``。

    ``SendInput`` 是「要么全收要么全丢」的语义：返回值小于请求数量就说明这批
    事件没有完整进入输入队列，此时绝不能当作点击成功。
    """
    _require_windows()
    if not inputs:
        return 0
    array = (INPUT * len(inputs))(*inputs)
    sent = int(_USER32.SendInput(len(inputs), array, ctypes.sizeof(INPUT)))
    if sent != len(inputs):
        raise InputInjectionBlocked(
            f"SendInput 只送进了 {sent}/{len(inputs)} 个事件：{_last_error_message()}。"
            f"如果前台窗口是以管理员身份运行的程序，普通权限的注入会被丢弃。"
        )
    return sent


def mouse_event_input(flags: int, data: int = 0) -> INPUT:
    item = INPUT(type=INPUT_MOUSE)
    item.mi = MOUSEINPUT(dx=0, dy=0, mouseData=data & 0xFFFFFFFF, dwFlags=flags, time=0, dwExtraInfo=0)
    return item


def wheel_event_input(delta: int, *, horizontal: bool = False) -> INPUT:
    return mouse_event_input(MOUSEEVENTF_HWHEEL if horizontal else MOUSEEVENTF_WHEEL, delta)


def key_event_input(vk: int, *, key_up: bool = False) -> INPUT:
    item = INPUT(type=INPUT_KEYBOARD)
    item.ki = KEYBDINPUT(
        wVk=vk & 0xFFFF,
        wScan=0,
        dwFlags=KEYEVENTF_KEYUP if key_up else 0,
        time=0,
        dwExtraInfo=0,
    )
    return item


def unicode_event_input(code_unit: int, *, key_up: bool = False) -> INPUT:
    """按 Unicode 码元注入字符，不依赖当前键盘布局与输入法。

    中文、全角标点、以及键盘上打不出来的字符都只能走这条路（``wVk`` 必须是 0，
    字符放在 ``wScan``，标志位加 ``KEYEVENTF_UNICODE``）。
    """
    item = INPUT(type=INPUT_KEYBOARD)
    item.ki = KEYBDINPUT(
        wVk=0,
        wScan=code_unit & 0xFFFF,
        dwFlags=KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if key_up else 0),
        time=0,
        dwExtraInfo=0,
    )
    return item


# ---------------------------------------------------------------- 键名映射

VK_NAMES: dict[str, int] = {
    "backspace": 0x08,
    "tab": 0x09,
    "enter": 0x0D,
    "return": 0x0D,
    "shift": 0x10,
    "ctrl": 0x11,
    "control": 0x11,
    "alt": 0x12,
    "pause": 0x13,
    "capslock": 0x14,
    "esc": 0x1B,
    "escape": 0x1B,
    "space": 0x20,
    "pageup": 0x21,
    "pgup": 0x21,
    "pagedown": 0x22,
    "pgdn": 0x22,
    "end": 0x23,
    "home": 0x24,
    "left": 0x25,
    "arrowleft": 0x25,
    "up": 0x26,
    "arrowup": 0x26,
    "right": 0x27,
    "arrowright": 0x27,
    "down": 0x28,
    "arrowdown": 0x28,
    "printscreen": 0x2C,
    "insert": 0x2D,
    "delete": 0x2E,
    "del": 0x2E,
    "win": 0x5B,
    "lwin": 0x5B,
    "rwin": 0x5C,
    "apps": 0x5D,
    "numlock": 0x90,
    "scrolllock": 0x91,
    "lshift": 0xA0,
    "rshift": 0xA1,
    "lctrl": 0xA2,
    "rctrl": 0xA3,
    "lalt": 0xA4,
    "ralt": 0xA5,
}

for _function_key_index in range(1, 25):
    VK_NAMES[f"f{_function_key_index}"] = 0x6F + _function_key_index
del _function_key_index


def resolve_vk(key: str | int) -> int:
    """把键名解析成虚拟键码（VK）。

    支持 ``"enter"`` 这类名字、``"a"`` / ``"5"`` 这类单字符，以及直接给 VK 数字。
    单字符走 ``VkKeyScanW``，键盘上不存在的字符会明确报错——要输入文本请用
    ``type_text``（它走 Unicode 注入，不受键盘布局限制）。
    """
    _require_windows()
    if isinstance(key, int):
        if not 1 <= key <= 0xFE:
            raise ValueError(f"虚拟键码超出范围：{key!r}")
        return key

    name = str(key or "").strip().lower()
    if not name:
        raise ValueError("键名不能为空")
    if name in VK_NAMES:
        return VK_NAMES[name]
    if len(name) == 1:
        scan = _USER32.VkKeyScanW(name)
        if scan == -1:
            raise ValueError(f"当前键盘布局没有字符 {name!r} 对应的按键；输入文本请用 type_text")
        return scan & 0xFF
    raise ValueError(f"无法识别的键名：{key!r}")


# ---------------------------------------------------------------- 窗口


def enum_top_level_windows() -> list[int]:
    """所有顶层窗口句柄（含隐藏窗口，过滤交给上层）。"""
    _require_windows()
    handles: list[int] = []

    def _collect(hwnd, _lparam):
        handles.append(int(hwnd))
        return True

    callback = _WNDENUMPROC(_collect)
    if not _USER32.EnumWindows(callback, 0):
        error_code = ctypes.get_last_error()
        if error_code:
            raise DesktopControlError(f"EnumWindows 失败：{_last_error_message()}")
    return handles


def is_window(handle: int) -> bool:
    _require_windows()
    return bool(_USER32.IsWindow(wintypes.HWND(handle)))


def is_window_visible(handle: int) -> bool:
    _require_windows()
    return bool(_USER32.IsWindowVisible(wintypes.HWND(handle)))


def is_iconic(handle: int) -> bool:
    """窗口是否最小化。"""
    _require_windows()
    return bool(_USER32.IsIconic(wintypes.HWND(handle)))


def is_window_cloaked(handle: int) -> bool:
    """窗口是否被 DWM 隐藏（cloaked）。

    UWP 挂起的应用、以及浏览器/Electron 的隐藏辅助窗口会「IsWindowVisible 为真
    但看不见」，只看可见性标志会把它们当成真窗口，点上去毫无反应。
    """
    _require_windows()
    if _DWMAPI is None:
        return False
    value = wintypes.DWORD(0)
    result = _DWMAPI.DwmGetWindowAttribute(
        wintypes.HWND(handle), _DWMWA_CLOAKED, ctypes.byref(value), ctypes.sizeof(value)
    )
    return result == 0 and value.value != 0


def window_title(handle: int) -> str:
    _require_windows()
    length = int(_USER32.GetWindowTextLengthW(wintypes.HWND(handle)))
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    _USER32.GetWindowTextW(wintypes.HWND(handle), buffer, length + 1)
    return buffer.value


def window_class_name(handle: int) -> str:
    _require_windows()
    buffer = ctypes.create_unicode_buffer(256)
    _USER32.GetClassNameW(wintypes.HWND(handle), buffer, 256)
    return buffer.value


def window_rect(handle: int) -> tuple[int, int, int, int]:
    """窗口的 ``(left, top, width, height)``。

    优先用 DWM 的 extended frame bounds：``GetWindowRect`` 会把不可见的窗口边框
    （Win10 起左右各 7px 左右）算进去，而那部分区域不响应点击，用它算出来的
    「窗口中心」会偏移。
    """
    _require_windows()
    rect = wintypes.RECT()
    if _DWMAPI is not None:
        result = _DWMAPI.DwmGetWindowAttribute(
            wintypes.HWND(handle),
            _DWMWA_EXTENDED_FRAME_BOUNDS,
            ctypes.byref(rect),
            ctypes.sizeof(rect),
        )
        if result == 0 and rect.right > rect.left and rect.bottom > rect.top:
            return int(rect.left), int(rect.top), int(rect.right - rect.left), int(rect.bottom - rect.top)
    if not _USER32.GetWindowRect(wintypes.HWND(handle), ctypes.byref(rect)):
        raise DesktopControlError(f"GetWindowRect 失败：{_last_error_message()}")
    return int(rect.left), int(rect.top), int(rect.right - rect.left), int(rect.bottom - rect.top)


def foreground_window_handle() -> int:
    _require_windows()
    return int(_USER32.GetForegroundWindow() or 0)


def window_thread_id(handle: int) -> int:
    _require_windows()
    return int(_USER32.GetWindowThreadProcessId(wintypes.HWND(handle), None))


def window_process_id(handle: int) -> int:
    _require_windows()
    process_id = wintypes.DWORD(0)
    _USER32.GetWindowThreadProcessId(wintypes.HWND(handle), ctypes.byref(process_id))
    return int(process_id.value)


def process_name(process_id: int) -> str:
    """进程可执行文件名（例如 ``msedge.exe``）；拿不到时返回空串。"""
    _require_windows()
    if process_id <= 0:
        return ""
    handle = _KERNEL32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, process_id)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not _KERNEL32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return ""
        return os.path.basename(buffer.value)
    finally:
        _KERNEL32.CloseHandle(handle)


def activate_window(handle: int) -> bool:
    """把窗口提到前台并获得焦点；成功返回 True。

    Windows 只允许「当前前台线程」或「刚收到用户输入的进程」切换前台窗口，
    所以后台进程直接 ``SetForegroundWindow`` 常常失败。这里按 pywinauto /
    pygetwindow 等库的通行做法兜底：临时把自己挂到前台线程的输入队列上
    （``AttachThreadInput``）再切换。
    """
    _require_windows()
    if not is_window(handle):
        return False
    if is_iconic(handle):
        _USER32.ShowWindow(wintypes.HWND(handle), SW_RESTORE)
    if foreground_window_handle() == int(handle):
        return True
    if _USER32.SetForegroundWindow(wintypes.HWND(handle)):
        return True

    foreground = foreground_window_handle()
    foreground_thread = window_thread_id(foreground) if foreground else 0
    current_thread = int(_KERNEL32.GetCurrentThreadId())
    attached = False
    try:
        if foreground_thread and foreground_thread != current_thread:
            attached = bool(_USER32.AttachThreadInput(current_thread, foreground_thread, True))
        _USER32.BringWindowToTop(wintypes.HWND(handle))
        _USER32.SetForegroundWindow(wintypes.HWND(handle))
        _USER32.SetFocus(wintypes.HWND(handle))
    finally:
        if attached:
            _USER32.AttachThreadInput(current_thread, foreground_thread, False)
    return foreground_window_handle() == int(handle)
