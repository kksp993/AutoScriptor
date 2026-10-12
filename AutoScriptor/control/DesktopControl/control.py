"""主机（Windows 桌面）控制的对外门面。

把三件事拼成一个可用对象：

1. 主机截屏（``screen.capture``）；
2. 键鼠动作（``inputs``）；
3. 目标定位——``T("文字")`` / ``I(图片)`` / ``B(Box)`` 复用 ``AutoScriptor.core.targets``，
   识别复用 ``AutoScriptor.recognition.locate.locate_on_screen``，返回项目统一的
   ``Box``。也就是说主机识别和游戏识别走同一套代码，不需要为桌面再造一套。

点击适配：主机屏幕不是模拟器的 1280x720，所以定位前会把目标的默认 ROI 换成本次
截图的真实尺寸，并把显式区域裁剪到屏幕内；``click_text`` 先定位再点 OCR 框的
中心，找不到就按超时重试——不落任何硬编码坐标。多显示器与高 DPI 由 ``_win32``
的坐标合同统一处理。
"""

from __future__ import annotations

import time
from typing import Any, Iterable

import numpy as np

from AutoScriptor.control.DesktopControl import inputs as host_input
from AutoScriptor.control.DesktopControl.screen import capture, save_frame, virtual_screen_box
from AutoScriptor.control.DesktopControl.windows import (
    WindowInfo,
    activate,
    find_windows,
    foreground_window,
    list_windows,
)
from AutoScriptor.control.DesktopControl._win32 import ensure_dpi_awareness
from AutoScriptor.core.box import Box
from AutoScriptor.logging.logger import logger


# T() / I() 没有显式指定区域时带的是模拟器默认帧。主机屏幕通常比它大，
# 照抄这个区域会把识别裁在屏幕左上角，右侧和下方的控件永远找不到。
_EMULATOR_DEFAULT_FRAME = (1280, 720)


def _clip_box_to_frame(box: Box | None, frame_size: tuple[int, int], *, what: str = "识别区域") -> Box:
    """把区域裁剪到截图范围内；完全落在截图外的区域直接报错。"""
    width, height = int(frame_size[0]), int(frame_size[1])
    if box is None:
        return Box(0, 0, width, height)
    if box.width <= 0 or box.height <= 0:
        raise ValueError(f"{what}的宽高必须为正：{box!r}")
    left, top = int(box.left), int(box.top)
    right, bottom = left + int(box.width), top + int(box.height)
    if right <= 0 or bottom <= 0 or left >= width or top >= height:
        raise ValueError(f"{what}完全落在截图之外：{box!r}，截图尺寸 {(width, height)}")
    return Box(
        max(0, left),
        max(0, top),
        min(width, right) - max(0, left),
        min(height, bottom) - max(0, top),
    )


def _adapt_preferred_box(preferred: Box | None, frame_size: tuple[int, int]) -> Box:
    """把目标自带的搜索区域适配到当前截图尺寸。"""
    if preferred is None:
        return Box(0, 0, *frame_size)
    if (preferred.left, preferred.top, preferred.width, preferred.height) == (
        0,
        0,
        *_EMULATOR_DEFAULT_FRAME,
    ):
        # 默认 ROI 只是「全屏」的另一种写法，换成真实的屏幕尺寸。
        return Box(0, 0, *frame_size)
    return _clip_box_to_frame(preferred, frame_size)


def _target_parts(target: Any, frame_size: tuple[int, int]) -> tuple[Any, Box, str | None]:
    """把一个目标拆成 ``locate_on_screen`` 需要的 ``(来源, 搜索区域, 颜色)``。

    支持项目既有目标（``T`` / ``I`` / ``B`` 产出的 ``Target``）以及裸文本、裸
    ``Box``、裸图片数组——主机上临时找一块区域时不必先去注册 UI 模板。
    """
    if isinstance(target, str):
        return target, Box(0, 0, *frame_size), None
    if isinstance(target, Box):
        return target, _clip_box_to_frame(target, frame_size), None
    if isinstance(target, np.ndarray):
        return target, Box(0, 0, *frame_size), None

    get_source = getattr(target, "get_source", None)
    if get_source is None:
        raise TypeError(
            f"不支持的目标类型 {type(target).__name__}；"
            f"可用 T('文字') / I(图片) / B(x, y, w, h) / 裸 str / 裸 Box / ndarray"
        )
    ui_entry = getattr(target, "ui", None)
    preferred = getattr(ui_entry, "box", None) if ui_entry is not None else None
    color = getattr(ui_entry, "color", None) if ui_entry is not None else None
    return get_source(), _adapt_preferred_box(preferred, frame_size), color


class DesktopControl:
    """Windows 主机（桌面）的截屏、键鼠与目标定位。

    坐标系全类统一：物理像素、虚拟桌面左上角为原点。``screenshot()`` 的数组下标
    与 ``click(x, y)`` 的坐标一致，``Box`` 也是屏幕坐标。

    只控制主机上的普通程序（浏览器、PC 客户端）；模拟器/游戏请继续用
    ``MixControl``（NemuIpc / ADB）。
    """

    def __init__(self, *, dpi_aware: bool = True, default_confidence: float = 0.8):
        self.default_confidence = float(default_confidence)
        # DPI 感知必须在使用任何坐标之前确定：它是一次性的进程级设置。
        self.dpi_awareness = ensure_dpi_awareness() if dpi_aware else "unchanged"
        logger.info(
            f"DesktopControl 就绪：DPI 感知={self.dpi_awareness}，"
            f"虚拟桌面={self.screen_box}，置信度={self.default_confidence}"
        )

    # ------------------------------------------------------------ 屏幕

    @property
    def screen_box(self) -> Box:
        """整个虚拟桌面（所有显示器）的范围。"""
        return virtual_screen_box()

    @property
    def frame_size(self) -> tuple[int, int]:
        """虚拟桌面的 ``(宽, 高)``。"""
        box = self.screen_box
        return box.width, box.height

    def screenshot(self, box: Box | None = None) -> np.ndarray:
        """抓取主机屏幕（BGR）。``box`` 用屏幕坐标，不传则抓整个虚拟桌面。"""
        return capture(box)

    def save_screenshot(self, path: str, box: Box | None = None) -> str:
        """截一帧并保存（取证用），返回写入路径。"""
        return save_frame(self.screenshot(box), path)

    # ------------------------------------------------------------ 键鼠

    def move_to(self, x: int, y: int) -> None:
        host_input.move_to(x, y)

    def cursor_position(self) -> tuple[int, int]:
        return host_input.cursor_position()

    def click(
        self,
        x: int | None = None,
        y: int | None = None,
        *,
        button: str = "left",
        clicks: int = 1,
        hold_s: float = host_input.DEFAULT_HOLD_S,
    ) -> tuple[int, int]:
        """在屏幕坐标 ``(x, y)`` 点击；省略坐标则点当前光标位置。"""
        position = host_input.click(x, y, button=button, clicks=clicks, hold_s=hold_s)
        logger.debug(f"主机点击 {button} x{clicks} @ {position}")
        return position

    def click_box(
        self,
        box: Box,
        *,
        offset: tuple[int, int] = (0, 0),
        button: str = "left",
        clicks: int = 1,
    ) -> tuple[int, int]:
        """点一个 ``Box`` 的中心（可加偏移）。

        用精确中心而不是 ``b2p`` 的随机抖动：抖动是为游戏反检测设计的，桌面控件
        需要的是确定性——点偏一点点就可能落到相邻按钮上。
        """
        center_x, center_y = box.center()
        return self.click(center_x + offset[0], center_y + offset[1], button=button, clicks=clicks)

    def drag(
        self,
        start: tuple[int, int],
        end: tuple[int, int],
        *,
        button: str = "left",
        duration_s: float = 0.3,
    ) -> None:
        host_input.drag(start, end, button=button, duration_s=duration_s)

    def scroll(
        self,
        clicks: int,
        *,
        x: int | None = None,
        y: int | None = None,
        horizontal: bool = False,
    ) -> None:
        host_input.scroll(clicks, x=x, y=y, horizontal=horizontal)

    def type_text(self, text: str, *, interval_s: float = 0.01) -> int:
        """向当前焦点输入文本（Unicode 注入，中文与网址都可用）。"""
        typed = host_input.type_text(text, interval_s=interval_s)
        logger.info(f"主机输入文本 {typed} 个字符")
        return typed

    def press(self, key: str | int) -> None:
        host_input.press(key)

    def hotkey(self, *keys: str | int) -> None:
        host_input.hotkey(*keys)

    def set_clipboard_text(self, text: str) -> None:
        host_input.set_clipboard_text(text)

    # ------------------------------------------------------------ 识别

    def locate(
        self,
        target: Any,
        *,
        confidence: float | None = None,
        screenshot: np.ndarray | None = None,
        box: Box | None = None,
    ) -> Box | None:
        """在主机屏幕上定位一个目标，返回第一个命中的 ``Box``（没找到返回 None）。

        ``screenshot`` 允许复用同一帧做多次识别（省一次截屏）；``box`` 覆盖目标的
        搜索区域（屏幕坐标）。
        """
        hits = self.locate_all(target, confidence=confidence, screenshot=screenshot, box=box)
        return hits[0] if hits else None

    def locate_all(
        self,
        target: Any,
        *,
        confidence: float | None = None,
        screenshot: np.ndarray | None = None,
        box: Box | None = None,
    ) -> list[Box]:
        """定位目标的所有命中区域（屏幕坐标）。"""
        # 延迟导入：识别模块会拉起 OCR 引擎，不能让「导入 DesktopControl」顺带启动它。
        from AutoScriptor.recognition.locate import locate_on_screen

        frame = screenshot if screenshot is not None else self.screenshot()
        if frame is None or frame.size == 0:
            raise ValueError("识别用的截图是空的")
        frame_size = (int(frame.shape[1]), int(frame.shape[0]))
        source, preferred, color = _target_parts(target, frame_size)
        if box is not None:
            preferred = _clip_box_to_frame(box, frame_size)
        threshold = self.default_confidence if confidence is None else float(confidence)

        result = locate_on_screen(frame, [source], threshold, [preferred], [color])
        boxes = result[0] if result else None
        return list(boxes) if boxes else []

    def locate_any(
        self,
        targets: Iterable[Any],
        *,
        confidence: float | None = None,
        screenshot: np.ndarray | None = None,
        box: Box | None = None,
    ) -> Box | None:
        """在多个目标里找第一个出现的（按给定顺序优先）。"""
        for target in targets:
            found = self.locate(target, confidence=confidence, screenshot=screenshot, box=box)
            if found is not None:
                return found
        return None

    def wait_for_text(
        self,
        target: Any,
        *,
        timeout: float = 10.0,
        interval: float = 0.5,
        confidence: float | None = None,
        box: Box | None = None,
    ) -> bool:
        """等目标出现（轮询截图识别），超时返回 False。"""
        deadline = time.monotonic() + max(0.0, float(timeout))
        describe = getattr(target, "get_source", None)
        label = describe() if describe is not None else target
        while True:
            if self.locate(target, confidence=confidence, box=box) is not None:
                logger.info(f"主机屏幕上已出现：{label}")
                return True
            if time.monotonic() >= deadline:
                logger.warning(f"主机屏幕上等待超时（{timeout}s）：{label}")
                return False
            time.sleep(max(0.05, float(interval)))

    def click_text(
        self,
        target: Any,
        *,
        timeout: float = 5.0,
        interval: float = 0.5,
        confidence: float | None = None,
        box: Box | None = None,
        button: str = "left",
        clicks: int = 1,
    ) -> Box | None:
        """定位并点击目标，返回被点击的 ``Box``；超时没找到返回 None。

        这是主机上的主入口：坐标完全来自识别结果，不做硬编码；找不到就按
        ``timeout`` 重试，绝不盲点一下了事。
        """
        deadline = time.monotonic() + max(0.0, float(timeout))
        while True:
            hits = self.locate_all(target, confidence=confidence, box=box)
            if hits:
                if len(hits) > 1:
                    # 文字是子串匹配：「执行所有」既可能命中按钮，也可能命中页面上的
                    # 提示句子（「点击「执行所有」启动总调度」）。命中多处时如实告警，
                    # 让调用方用 box 收紧搜索区域，而不是默默点错地方。
                    logger.warning(
                        f"目标命中 {len(hits)} 处，点第一处：{[str(item) for item in hits]}；"
                        f"可用 box 缩小搜索区域"
                    )
                found = hits[0]
                position = self.click_box(found, button=button, clicks=clicks)
                logger.info(f"主机点击目标 {found} @ {position}")
                return found
            if time.monotonic() >= deadline:
                describe = getattr(target, "get_source", None)
                label = describe() if describe is not None else target
                logger.warning(f"主机屏幕上没找到目标（{timeout}s）：{label}")
                return None
            time.sleep(max(0.05, float(interval)))

    # ------------------------------------------------------------ 窗口

    def windows(self, **kwargs: Any) -> list[WindowInfo]:
        """当前顶层窗口列表（默认只含可见、有标题、未被隐藏的窗口）。"""
        return list_windows(**kwargs)

    def find_window(
        self,
        *,
        title_contains: str | None = None,
        process_name: str | None = None,
        class_name: str | None = None,
    ) -> WindowInfo | None:
        """找一个窗口；多个候选时优先返回未最小化的那个。"""
        matched = find_windows(
            title_contains=title_contains,
            process_name=process_name,
            class_name=class_name,
        )
        if not matched:
            return None
        matched.sort(key=lambda info: (info.minimized, -info.rect.area))
        return matched[0]

    def activate_window(self, window: WindowInfo | int | str) -> bool:
        """把窗口提到前台。

        直接传 ``WindowInfo`` / 句柄，或传一个字符串：``"msedge.exe"`` 这类以
        ``.exe`` 结尾的按进程名找，其余按标题子串找。
        """
        if isinstance(window, WindowInfo):
            info = window
        elif isinstance(window, int):
            found = find_windows(process_name=None, visible_only=False)
            info = next((item for item in found if item.handle == window), None)
            if info is None:
                logger.warning(f"窗口句柄 {window} 不存在")
                return False
        else:
            text = str(window or "").strip()
            if not text:
                raise ValueError("窗口标识不能为空")
            if text.lower().endswith(".exe"):
                info = self.find_window(process_name=text)
            else:
                info = self.find_window(title_contains=text)
            if info is None:
                logger.warning(f"没找到窗口：{text}")
                return False
        return activate(info.handle)

    def foreground_window(self) -> WindowInfo | None:
        return foreground_window()


_desktop_instance: DesktopControl | None = None


def get_desktop() -> DesktopControl:
    """取共享的 ``DesktopControl``（进程内一个就够，DPI 设置也只做一次）。"""
    global _desktop_instance
    if _desktop_instance is None:
        _desktop_instance = DesktopControl()
    return _desktop_instance
