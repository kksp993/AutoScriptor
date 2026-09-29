"""4399 悬浮窗（贴边推广浮窗）检测与移除。

4399 渠道登录后会在屏幕边缘弹出绿色推广浮窗，遮挡游戏 UI。本模块在四边窄条
内按绿色连通域定位它，再滑到屏幕中央触发设置面板并隐藏。

这是 4399 平台业务，因此属于 ZmxyOL，而不是通用识别层，也不占用 AutoScriptor。
调用方：登录流程（``ZmxyOL.nav.envs.login``）。
"""

from __future__ import annotations

import cv2
import numpy as np

import AutoScriptor.core.api as core_api
from AutoScriptor import B, click, swipe
from AutoScriptor.core.box import Box
from AutoScriptor.utils.cancel import cancellable_sleep, check_cancel_raise
from AutoScriptor.logging.logger import logger


def detect_floating_window_on_frame(
    screenshot: np.ndarray,
    edge_width: int = 40,
    min_area: int = 150,
    max_area: int = 3000,
    green_range: tuple = ((35, 60, 60), (90, 255, 255)),
    debug: bool = False,
) -> dict:
    """
    在给定帧上检测屏幕边缘的 4399 悬浮窗。

    在屏幕四边各取 edge_width 像素宽的窄条，转 HSV 后提取绿色像素，
    对绿色连通区域做面积 + 长宽比过滤，返回第一个命中结果。

    Args:
        screenshot: 屏幕截图 numpy 数组 (RGB 或 BGR 格式均可，绿色通道不受影响)
        edge_width: 边缘扫描宽度，默认 40 像素
        min_area: 连通区域最小面积（像素²），低于此值忽略
        max_area: 连通区域最大面积（像素²），高于此值忽略
        green_range: HSV 绿色范围 ((H_low, S_low, V_low), (H_high, S_high, V_high))
        debug: 若为 True，保存调试图像到 logs/debug/

    Returns:
        dict: {
            'found': bool,
            'edge': str - '上'/'下'/'左'/'右',
            'box': Box(left, top, width, height) - 全图坐标下的位置,
            'center': (x, y) - 全图坐标下的中心点,
            'area': int - 连通区域面积,
        }
        未找到时返回 {'found': False}
    """
    h, w = screenshot.shape[:2]

    # 定义四条边缘扫描区域: (name, x_offset, y_offset, strip_w, strip_h)
    edges = [
        ("上", 0, 0, w, min(edge_width, h)),
        ("下", 0, max(0, h - edge_width), w, min(edge_width, h)),
        ("左", 0, 0, min(edge_width, w), h),
        ("右", max(0, w - edge_width), 0, min(edge_width, w), h),
    ]

    lower_green = np.array(green_range[0], dtype=np.uint8)
    upper_green = np.array(green_range[1], dtype=np.uint8)

    # 形态学核
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))

    results = []

    for edge_name, ox, oy, sw, sh in edges:
        # 裁剪边缘条
        strip = screenshot[oy : oy + sh, ox : ox + sw]
        if strip.size == 0:
            continue

        # 同时尝试 RGB2HSV 和 BGR2HSV，取并集（兼容两种颜色空间）
        hsv_rgb = cv2.cvtColor(strip, cv2.COLOR_RGB2HSV)
        hsv_bgr = cv2.cvtColor(strip, cv2.COLOR_BGR2HSV)
        mask_rgb = cv2.inRange(hsv_rgb, lower_green, upper_green)
        mask_bgr = cv2.inRange(hsv_bgr, lower_green, upper_green)
        mask = cv2.bitwise_or(mask_rgb, mask_bgr)

        # 形态学：先闭合小缝隙，再开运算去噪点
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)

        if debug:
            _save_debug(edge_name, strip, mask)

        # 查找连通区域
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        for cnt in contours:
            area = cv2.contourArea(cnt)
            if not (min_area <= area <= max_area):
                continue

            bx, by, bw, bh = cv2.boundingRect(cnt)
            if not _touches_screen_edge(edge_name, bx, by, bw, bh, sw, sh):
                continue

            # 长宽比过滤：悬浮窗是扁平矩形（水平或垂直方向），排除正方形噪声
            aspect = max(bw, bh) / max(min(bw, bh), 1)
            if aspect < 1.5:
                continue

            # 绿色像素占比过滤：区域内绿色像素应占 boundingRect 的较大比例
            roi_mask = mask[by : by + bh, bx : bx + bw]
            green_ratio = cv2.countNonZero(roi_mask) / max(bw * bh, 1)
            if green_ratio < 0.25:
                continue

            # 转换为全图坐标
            abs_x = bx + ox
            abs_y = by + oy
            cx = abs_x + bw // 2
            cy = abs_y + bh // 2

            results.append({
                "found": True,
                "edge": edge_name,
                "box": Box(abs_x, abs_y, bw, bh),
                "center": (cx, cy),
                "area": area,
                "green_ratio": round(green_ratio, 3),
            })

    if not results:
        return {"found": False}

    # 返回绿色像素占比最高的结果（最可能是悬浮窗）
    best = max(results, key=lambda r: r["green_ratio"])
    return best


def detect_floating_window(debug: bool = False) -> dict:
    """
    截取当前画面并检测 4399 悬浮窗。

    Returns:
        dict: 见 detect_floating_window_on_frame
    """
    return detect_floating_window_on_frame(core_api.mixctrl.screenshot(), debug=debug)


def dismiss_floating_window(max_retries: int = 1, debug: bool = False) -> bool:
    """
    检测并移除 4399 悬浮窗：检测到后将其滑动到屏幕中央触发设置面板，然后隐藏。

    Args:
        max_retries: 最大重试次数（悬浮窗可能需要多次截图才能稳定检测到）
        debug: 保存调试图像

    Returns:
        bool: True 表示检测到并处理了悬浮窗，False 表示未检测到
    """
    for attempt in range(max_retries):
        check_cancel_raise()
        screenshot = core_api.mixctrl.screenshot()
        result = detect_floating_window_on_frame(screenshot, debug=debug)
        if not result["found"]:
            cancellable_sleep(0.3)
            continue

        logger.info(f"🔍 检测到悬浮窗: {result['edge']}边 {result['box']} (第{attempt+1}次)")

        # 从悬浮窗位置滑到屏幕中央，触发悬浮窗设置面板
        cx, cy = result["center"]
        swipe(B(cx, cy, 10, 10), B(640, 650, 10, 10), duration_s=1)
        cancellable_sleep(1)
        click(B(740, 555, 10, 10))
        cancellable_sleep(0.5)

        verify = detect_floating_window_on_frame(core_api.mixctrl.screenshot(), debug=debug)
        if not verify["found"]:
            logger.info("✅ 悬浮窗已隐藏")
            return True

        logger.warning(f"⚠️ 悬浮窗关闭后仍检测到: {verify['edge']}边 {verify['box']}")

    return False


def _touches_screen_edge(edge_name: str, bx: int, by: int, bw: int, bh: int, sw: int, sh: int, margin: int = 2) -> bool:
    """Require the candidate to touch the real screen boundary for that edge."""
    if edge_name == "上":
        return by <= margin
    if edge_name == "下":
        return by + bh >= sh - margin
    if edge_name == "左":
        return bx <= margin
    if edge_name == "右":
        return bx + bw >= sw - margin
    return False


def _save_debug(edge_name: str, strip: np.ndarray, mask: np.ndarray):
    """保存调试图像"""
    import os
    debug_dir = os.path.join(os.getcwd(), "logs", "debug", "floating_window")
    os.makedirs(debug_dir, exist_ok=True)
    cv2.imwrite(os.path.join(debug_dir, f"strip_{edge_name}.png"), strip)
    cv2.imwrite(os.path.join(debug_dir, f"mask_{edge_name}.png"), mask)
