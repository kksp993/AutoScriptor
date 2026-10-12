"""主机屏幕截图。

坐标系与 ``_win32`` 完全一致：物理像素、虚拟桌面左上角为原点。截图数组和屏幕
坐标一一对应——``frame[y, x]`` 就是屏幕上的 ``(origin_x + x, origin_y + y)``，
所以在截图上量到的像素可以直接拿去点击。
"""

from __future__ import annotations

import numpy as np

from AutoScriptor.control.DesktopControl._win32 import ensure_dpi_awareness, virtual_screen_rect
from AutoScriptor.core.box import Box
from AutoScriptor.logging.logger import logger


def virtual_screen_box() -> Box:
    """整个虚拟桌面的范围（屏幕坐标，可能是负原点）。"""
    ensure_dpi_awareness()
    left, top, width, height = virtual_screen_rect()
    return Box(left, top, width, height)


def capture(box: Box | None = None) -> np.ndarray:
    """抓取主机屏幕，返回 BGR ndarray。

    ``box`` 使用屏幕坐标（虚拟桌面左上角为原点）；不传则抓整个虚拟桌面（多显示器
    时是拼接后的整块）。BGR 与项目其它截图通道（NemuIpc / ADB）保持一致，识别
    链路可以直接吃这个帧。
    """
    ensure_dpi_awareness()
    # 延迟导入：只有真的截屏时才需要 Pillow 的抓屏后端。
    from PIL import ImageGrab

    if box is None:
        image = ImageGrab.grab(all_screens=True)
    else:
        if box.width <= 0 or box.height <= 0:
            raise ValueError(f"截图区域必须是正宽高，收到 {box!r}")
        # Pillow 的 bbox 用屏幕坐标，内部自己减虚拟桌面原点，负坐标同样成立。
        image = ImageGrab.grab(
            bbox=(box.left, box.top, box.left + box.width, box.top + box.height),
            all_screens=True,
        )
    frame = np.asarray(image)
    if frame.ndim != 3 or frame.shape[2] < 3:
        raise RuntimeError(f"主机截图格式异常：shape={frame.shape!r}")
    return frame[:, :, ::-1].copy()      # RGB -> BGR


def save_frame(frame: np.ndarray, path: str) -> str:
    """把一帧写到磁盘（取证/复盘用）。返回实际写入的路径。"""
    import cv2

    if not cv2.imwrite(str(path), frame):
        raise OSError(f"写入截图失败：{path}")
    logger.debug(f"主机截图已保存：{path}")
    return str(path)
