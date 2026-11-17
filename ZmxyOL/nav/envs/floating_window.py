"""4399 floating ball, expanded panel and hide-confirmation lifecycle.

Logo templates distinguish the movable control from green game buttons. Docked
logos rotate and clip against all four edges; a full logo may be anywhere.
"""

from __future__ import annotations

import cv2
import numpy as np
from functools import lru_cache
from time import monotonic

import AutoScriptor.core.api as core_api
from AutoScriptor import B, T, click, ctrl_mumu, locate, swipe
from AutoScriptor.core.box import Box
from AutoScriptor.utils.paths import get_assets_dir, get_logs_root
from AutoScriptor.utils.cancel import cancellable_sleep, check_cancel_raise
from AutoScriptor.logging.logger import logger


@lru_cache(maxsize=32)
def _load_template(path):
    image = cv2.imdecode(np.frombuffer(path.read_bytes(), np.uint8), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise ValueError(f"Invalid floating-ball template: {path}")
    return image


def _match_template(gray, name, region):
    template = _load_template(get_assets_dir() / 'pic' / f'floating-ball-{name}.png')
    left, top, width, height = region
    cropped = gray[top:top + height, left:left + width]
    template_height, template_width = template.shape
    if cropped.shape[0] < template_height or cropped.shape[1] < template_width:
        return None
    scores = cv2.matchTemplate(cropped, template, cv2.TM_CCOEFF_NORMED)
    _minimum, confidence, _minimum_location, location = cv2.minMaxLoc(scores)
    if confidence < 0.80:
        return None
    return Box(left + location[0], top + location[1], template_width, template_height), confidence


def detect_floating_window_on_frame(
    screenshot: np.ndarray,
    edge_width: int = 40,
    min_area: int = 150,
    max_area: int = 3000,
    green_range: tuple = ((35, 60, 60), (90, 255, 255)),
    debug: bool = False,
) -> dict:
    """Find the 4399 logo in one BGR frame, not merely a green connected area.

    Existing area/color arguments remain optional candidate filters. ``edge``
    is ``内部`` for a complete logo; clipped templates must touch a real edge.
    """
    height, width = screenshot.shape[:2]
    gray = cv2.cvtColor(screenshot, cv2.COLOR_BGR2GRAY)
    strip_width = min(edge_width, width, height)
    regions = (
        ('full', '内部', Box(0, 0, width, height)),
        ('left', '左', Box(0, 0, strip_width, height)),
        ('right', '右', Box(width - strip_width, 0, strip_width, height)),
        ('top', '上', Box(0, 0, width, strip_width)),
        ('bottom', '下', Box(0, height - strip_width, width, strip_width)),
    )
    candidates = []
    for template_name, edge_name, region in regions:
        match = _match_template(gray, template_name, region)
        if match is None:
            continue
        box, confidence = match
        area = box.width * box.height
        if not min_area <= area <= max_area:
            continue
        if template_name != 'full' and not _touches_screen_edge(
                edge_name, box.left, box.top, box.width, box.height, width, height):
            continue
        crop = screenshot[box.top:box.top + box.height, box.left:box.left + box.width]
        mask = cv2.inRange(cv2.cvtColor(crop, cv2.COLOR_BGR2HSV),
                           np.array(green_range[0], np.uint8), np.array(green_range[1], np.uint8))
        green_ratio = cv2.countNonZero(mask) / area
        if green_ratio < 0.10:
            continue
        horizontal, vertical = box.center()
        # The outermost Android pixels may intercept a drag as a system gesture.
        if edge_name == '右':
            horizontal = width - 14
        elif edge_name == '左':
            horizontal = 8
        elif edge_name == '上':
            vertical = 8
        elif edge_name == '下':
            vertical = height - 8
        candidates.append(dict(found=True, edge=edge_name, box=box,
                               center=(int(horizontal), int(vertical)), area=area,
                               confidence=round(confidence, 4), green_ratio=round(green_ratio, 3)))
    result = max(candidates, key=lambda candidate: candidate['confidence']) if candidates else {'found': False}
    if debug:
        directory = get_logs_root() / 'debug' / 'floating_window'
        directory.mkdir(parents=True, exist_ok=True)
        success, encoded = cv2.imencode('.png', screenshot)
        if success:
            (directory / f'{monotonic():.6f}.png').write_bytes(encoded.tobytes())
    return result


def detect_floating_window(debug: bool = False) -> dict:
    """
    截取当前画面并检测 4399 悬浮窗。

    Returns:
        dict: 见 detect_floating_window_on_frame
    """
    return detect_floating_window_on_frame(core_api.mixctrl.screenshot(), debug=debug)


def inspect_floating_overlay_on_frame(screenshot, debug=False):
    """The expanded panel and hide dialog are not an absent floating ball."""
    gray = cv2.cvtColor(screenshot, cv2.COLOR_BGR2GRAY)
    if _match_template(gray, 'hide', Box(400, 110, 480, 90)):
        return {'kind': 'hide_dialog'}
    if _match_template(gray, 'panel', Box(0, 70, 440, 100)):
        return {'kind': 'panel'}
    result = detect_floating_window_on_frame(screenshot, debug=debug)
    return {**result, 'kind': 'ball' if result['found'] else 'absent'}


def _wait_for_overlay(expected, timeout=4, debug=False):
    deadline = monotonic() + timeout
    while True:
        check_cancel_raise()
        frame = core_api.mixctrl.screenshot()
        state = inspect_floating_overlay_on_frame(frame, debug)
        if state['kind'] == expected:
            return frame, state
        if monotonic() >= deadline:
            raise TimeoutError(f'4399 悬浮窗等待 {expected} 超时，当前状态 {state["kind"]}')
        cancellable_sleep(0.25)


def _confirm_hide(frame):
    matches = locate((
        T('不获取设备传感器信息', box=Box(445, 415, 385, 90)),
        T('隐藏', box=Box(650, 525, 200, 65)),
    ), screenshot=frame, assure_stable=False, is_simplify=False)
    if not matches or not all(matches):
        raise RuntimeError('4399 隐藏悬浮球对话框控件不完整，拒绝盲点')
    click(B(matches[0][0]))
    deadline = monotonic() + 2
    while monotonic() < deadline:
        check_cancel_raise()
        cancellable_sleep(0.2)
        selected_frame = core_api.mixctrl.screenshot()
        if inspect_floating_overlay_on_frame(selected_frame)['kind'] != 'hide_dialog':
            raise RuntimeError('4399 隐藏对话框在确认选项前消失')
        # The lower radio button must turn green before submitting the dialog.
        indicator = cv2.cvtColor(selected_frame[438:463, 791:816], cv2.COLOR_BGR2HSV)
        selected_pixels = cv2.countNonZero(cv2.inRange(indicator, (40, 70, 70), (95, 255, 255)))
        if selected_pixels >= 30:
            click(B(matches[1][0]))
            return
    raise RuntimeError('未确认选择“不获取设备传感器信息”，拒绝提交隐藏设置')


def _dismiss_floating_window(max_retries, debug):
    handled = False
    for attempt in range(max_retries):
        check_cancel_raise()
        frame = core_api.mixctrl.screenshot()
        state = inspect_floating_overlay_on_frame(frame, debug)
        if state['kind'] == 'absent':
            cancellable_sleep(0.3)
            if inspect_floating_overlay_on_frame(core_api.mixctrl.screenshot(), debug)['kind'] == 'absent':
                return handled
            continue
        handled = True
        logger.info('处理4399悬浮窗: %s，尝试 %d/%d', state, attempt + 1, max_retries)
        try:
            if state['kind'] == 'panel':
                click(B(963, 330, 16, 60))
                frame, state = _wait_for_overlay('ball', debug=debug)
            if state['kind'] == 'ball':
                horizontal, vertical = state['center']
                swipe(B(horizontal, vertical), B(640, 650), duration_s=1,
                      ensure_stable_after_swipe=False)
                frame, state = _wait_for_overlay('hide_dialog', debug=debug)
            _confirm_hide(frame)
            _wait_for_overlay('absent', debug=debug)
            cancellable_sleep(0.5)
            if inspect_floating_overlay_on_frame(core_api.mixctrl.screenshot(), debug)['kind'] == 'absent':
                logger.info('4399悬浮球、展开面板及隐藏对话框均已消失')
                return True
        except TimeoutError:
            if attempt + 1 == max_retries:
                raise
    raise RuntimeError('4399 悬浮窗未能确认隐藏，停止后续登录操作')


def dismiss_floating_window(max_retries: int = 3, debug: bool = False) -> bool:
    """Return False only for verified absence; detected-but-not-hidden raises.

    Native Android overlays use ADB input and restore the previous mode. Hiding
    selects the no-sensor option; it never grants sensor access implicitly.
    """
    if max_retries < 1:
        raise ValueError('max_retries must be positive')
    return ctrl_mumu(_dismiss_floating_window)(max_retries, debug)


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
