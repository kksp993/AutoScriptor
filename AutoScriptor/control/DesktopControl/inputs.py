"""主机键鼠动作。

坐标同样是「物理像素、虚拟桌面左上角为原点」：``click(x, y)`` 的 x/y 就是截图
上量到的像素位置，与本目录其它模块共用一套坐标系。

每个动作都按「系统是否真的收下事件」判断成败：`SendInput` 被更高权限窗口拦下时
会抛 ``InputInjectionBlocked``，不会静默地把没生效的点击当成成功。
"""

from __future__ import annotations

import time

from AutoScriptor.control.DesktopControl._win32 import (
    MOUSEEVENTF_LEFTDOWN,
    MOUSEEVENTF_LEFTUP,
    MOUSEEVENTF_MIDDLEDOWN,
    MOUSEEVENTF_MIDDLEUP,
    MOUSEEVENTF_RIGHTDOWN,
    MOUSEEVENTF_RIGHTUP,
    WHEEL_DELTA,
    cursor_position,
    key_event_input,
    mouse_event_input,
    move_cursor,
    resolve_vk,
    send_inputs,
    unicode_event_input,
    wheel_event_input,
)
from AutoScriptor.logging.logger import logger


# 按下键默认停留 30ms：浏览器和大多数 Win32 控件对 0ms 的瞬时按下也认，但
# 少数程序（含部分自绘 UI）会把过快的 down/up 当成误触丢掉。
DEFAULT_HOLD_S = 0.03
DEFAULT_INTERVAL_S = 0.08

_BUTTON_FLAGS: dict[str, tuple[int, int]] = {
    "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
    "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
    "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
}


def _button_flags(button: str) -> tuple[int, int]:
    name = str(button or "").strip().lower()
    if name not in _BUTTON_FLAGS:
        raise ValueError(f"不支持的鼠标键 {button!r}，可选：{sorted(_BUTTON_FLAGS)}")
    return _BUTTON_FLAGS[name]


def move_to(x: int, y: int) -> None:
    """把光标移到屏幕坐标 ``(x, y)``。"""
    move_cursor(int(x), int(y))


def click(
    x: int | None = None,
    y: int | None = None,
    *,
    button: str = "left",
    clicks: int = 1,
    hold_s: float = DEFAULT_HOLD_S,
    interval_s: float = DEFAULT_INTERVAL_S,
) -> tuple[int, int]:
    """点击；给了 ``x``/``y`` 就先移过去。返回点击时的光标位置。

    按下时长和连击间隔都可调：双击需要短间隔（默认 80ms 在 Windows 的双击
    时限内），拖动则需要更长的按下时间。
    """
    if (x is None) != (y is None):
        raise ValueError("x 和 y 必须同时给出或同时省略")
    if x is not None:
        move_to(x, y)
    down_flag, up_flag = _button_flags(button)
    repeat = max(1, int(clicks))
    for index in range(repeat):
        if index:
            time.sleep(max(0.0, interval_s))
        send_inputs([mouse_event_input(down_flag)])
        if hold_s > 0:
            time.sleep(hold_s)
        send_inputs([mouse_event_input(up_flag)])
    return cursor_position()


def mouse_down(button: str = "left") -> None:
    down_flag, _ = _button_flags(button)
    send_inputs([mouse_event_input(down_flag)])


def mouse_up(button: str = "left") -> None:
    _, up_flag = _button_flags(button)
    send_inputs([mouse_event_input(up_flag)])


def scroll(clicks: int, *, x: int | None = None, y: int | None = None, horizontal: bool = False) -> None:
    """滚轮：一个 ``click`` 是一格（``WHEEL_DELTA``），正值向上/向左。"""
    if x is not None and y is not None:
        move_to(x, y)
    amount = int(clicks)
    if amount == 0:
        return
    send_inputs([wheel_event_input(WHEEL_DELTA * amount, horizontal=horizontal)])


def drag(
    start: tuple[int, int],
    end: tuple[int, int],
    *,
    button: str = "left",
    duration_s: float = 0.3,
    steps: int | None = None,
) -> None:
    """按住拖动。

    必须分步移动：一步跳到终点只会在终点产生一个 move 事件，浏览器里的拖拽
    （选文本、拖滚动条）收不到中间轨迹会直接当成点击。
    """
    duration = max(0.0, float(duration_s))
    step_count = int(steps) if steps else max(4, int(round(duration / 0.02)))
    step_sleep = duration / step_count if step_count else 0.0
    start_x, start_y = int(start[0]), int(start[1])
    end_x, end_y = int(end[0]), int(end[1])

    move_to(start_x, start_y)
    mouse_down(button)
    try:
        for step in range(1, step_count + 1):
            ratio = step / step_count
            move_to(
                round(start_x + (end_x - start_x) * ratio),
                round(start_y + (end_y - start_y) * ratio),
            )
            if step_sleep:
                time.sleep(step_sleep)
    finally:
        # 无论中途出什么错都要抬起按键，否则系统会一直认为鼠标处于按下状态。
        mouse_up(button)


def type_text(text: str, *, interval_s: float = 0.01) -> int:
    """输入一段文本，返回字符数。

    走 ``KEYEVENTF_UNICODE`` 注入，不依赖键盘布局与输入法：网址、中文、全角
    标点都能原样进到控件里。逐字符发送（每个字符一对 down/up），字符之间留
    间隔，否则部分程序会吞字符。
    """
    content = str(text)
    for char in content:
        encoded = char.encode("utf-16-le")
        events = []
        for offset in range(0, len(encoded), 2):
            code_unit = int.from_bytes(encoded[offset:offset + 2], "little")
            events.append(unicode_event_input(code_unit, key_up=False))
            events.append(unicode_event_input(code_unit, key_up=True))
        send_inputs(events)
        if interval_s > 0:
            time.sleep(interval_s)
    return len(content)


def key_down(key: str | int) -> None:
    send_inputs([key_event_input(resolve_vk(key), key_up=False)])


def key_up(key: str | int) -> None:
    send_inputs([key_event_input(resolve_vk(key), key_up=True)])


def press(key: str | int, *, hold_s: float = DEFAULT_HOLD_S) -> None:
    """按一次键（如 ``press("enter")``）。"""
    vk = resolve_vk(key)
    send_inputs([key_event_input(vk, key_up=False)])
    if hold_s > 0:
        time.sleep(hold_s)
    send_inputs([key_event_input(vk, key_up=True)])


def hotkey(*keys: str | int, gap_s: float = 0.02) -> None:
    """组合键，例如 ``hotkey("ctrl", "l")``。

    先按序按下所有修饰键，再按下/抬起最后那个键，最后逆序释放修饰键。顺序不能
    乱：修饰键必须在目标键按下时处于按下状态，否则浏览器收到的是裸字母。
    """
    if not keys:
        raise ValueError("hotkey 至少需要一个键")
    modifiers = [resolve_vk(key) for key in keys[:-1]]
    main_key = resolve_vk(keys[-1])
    try:
        for vk in modifiers:
            send_inputs([key_event_input(vk, key_up=False)])
            if gap_s > 0:
                time.sleep(gap_s)
        send_inputs([key_event_input(main_key, key_up=False), key_event_input(main_key, key_up=True)])
    finally:
        for vk in reversed(modifiers):
            send_inputs([key_event_input(vk, key_up=True)])
            if gap_s > 0:
                time.sleep(gap_s)


def set_clipboard_text(text: str) -> None:
    """把文本写进 Windows 剪贴板（长文本粘贴比逐字注入快得多）。

    只做 WriteClipboard 这一层，不引入第三方剪贴板库。
    """
    import ctypes
    from ctypes import wintypes

    from AutoScriptor.control.DesktopControl._win32 import (
        IS_WINDOWS,
        DesktopControlError,
        _require_windows,
    )

    if not IS_WINDOWS:  # pragma: no cover
        _require_windows()
    content = str(text)
    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.OpenClipboard.argtypes = (wintypes.HWND,)
    user32.SetClipboardData.argtypes = (wintypes.UINT, wintypes.HANDLE)
    kernel32.GlobalAlloc.argtypes = (wintypes.UINT, ctypes.c_size_t)
    kernel32.GlobalLock.argtypes = (wintypes.HANDLE,)
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = (wintypes.HANDLE,)

    if not user32.OpenClipboard(None):
        raise DesktopControlError("打开剪贴板失败，可能有其它程序正占用它")
    try:
        user32.EmptyClipboard()
        encoded = content.encode("utf-16-le") + b"\x00\x00"
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(encoded))
        if not handle:
            raise DesktopControlError("剪贴板内存分配失败")
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            raise DesktopControlError("剪贴板内存加锁失败")
        try:
            ctypes.memmove(pointer, encoded, len(encoded))
        finally:
            kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            raise DesktopControlError("写入剪贴板失败")
    finally:
        user32.CloseClipboard()
    logger.debug(f"剪贴板已写入 {len(content)} 个字符")
