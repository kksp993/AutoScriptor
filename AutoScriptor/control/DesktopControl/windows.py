"""主机顶层窗口的查询与激活。

给主机控制用的最小窗口层：按标题/进程找到目标窗口、拿它的屏幕矩形、把它提到
前台。浏览器与 PC 客户端都是「先激活窗口，再按坐标操作」的用法，所以窗口矩形
和激活结果都属于点击适配的一部分。
"""

from __future__ import annotations

from dataclasses import dataclass

from AutoScriptor.control.DesktopControl import _win32
from AutoScriptor.core.box import Box
from AutoScriptor.logging.logger import logger


@dataclass(frozen=True)
class WindowInfo:
    """一个顶层窗口的快照（屏幕坐标）。"""

    handle: int
    title: str
    class_name: str
    process_id: int
    process_name: str
    rect: Box
    minimized: bool

    @property
    def process_key(self) -> str:
        """进程名的小写形式，用于忽略大小写比较。"""
        return self.process_name.lower()

    def __str__(self) -> str:
        size = f"{self.rect.width}x{self.rect.height}+{self.rect.left}+{self.rect.top}"
        state = " [最小化]" if self.minimized else ""
        return f"{self.process_name or '?'} hwnd={self.handle} {size}{state} 「{self.title}」"


def _describe(handle: int) -> WindowInfo:
    left, top, width, height = _win32.window_rect(handle)
    process_id = _win32.window_process_id(handle)
    return WindowInfo(
        handle=int(handle),
        title=_win32.window_title(handle),
        class_name=_win32.window_class_name(handle),
        process_id=process_id,
        process_name=_win32.process_name(process_id),
        rect=Box(left, top, width, height),
        minimized=_win32.is_iconic(handle),
    )


def list_windows(
    *,
    visible_only: bool = True,
    titled_only: bool = True,
    include_cloaked: bool = False,
) -> list[WindowInfo]:
    """列出顶层窗口。

    默认只返回「可见、有标题、未被 DWM 隐藏」的窗口——没有标题的多是工具窗口，
    cloaked 的（UWP 挂起、浏览器隐藏辅助窗口）虽然 ``IsWindowVisible`` 为真，
    但屏幕上并不存在，混进来会让按标题查找匹配到假目标。
    """
    windows: list[WindowInfo] = []
    for handle in _win32.enum_top_level_windows():
        if visible_only and not _win32.is_window_visible(handle):
            continue
        if not include_cloaked and _win32.is_window_cloaked(handle):
            continue
        info = _describe(handle)
        if titled_only and not info.title.strip():
            continue
        windows.append(info)
    return windows


def find_windows(
    *,
    title_contains: str | None = None,
    class_name: str | None = None,
    process_name: str | None = None,
    visible_only: bool = True,
    include_cloaked: bool = False,
) -> list[WindowInfo]:
    """按条件筛选窗口；条件之间是「与」的关系。

    ``title_contains`` 忽略大小写做子串匹配，``process_name`` 匹配可执行文件名
    （``"msedge.exe"``，同样忽略大小写）。
    """
    title_key = (title_contains or "").strip().lower()
    class_key = (class_name or "").strip().lower()
    process_key = (process_name or "").strip().lower()

    matched: list[WindowInfo] = []
    for info in list_windows(visible_only=visible_only, include_cloaked=include_cloaked):
        if title_key and title_key not in info.title.lower():
            continue
        if class_key and class_key != info.class_name.lower():
            continue
        if process_key and process_key != info.process_key:
            continue
        matched.append(info)
    return matched


def foreground_window() -> WindowInfo | None:
    """当前前台窗口；没有前台窗口时返回 None。"""
    handle = _win32.foreground_window_handle()
    if not handle or not _win32.is_window(handle):
        return None
    return _describe(handle)


def activate(handle: int) -> bool:
    """把窗口提到前台并获得焦点；成功返回 True。"""
    activated = _win32.activate_window(handle)
    if not activated:
        logger.warning(f"窗口 {handle} 激活失败（可能被系统前台锁挡住）")
    return activated
