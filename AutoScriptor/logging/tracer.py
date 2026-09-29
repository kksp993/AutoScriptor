"""Debug screenshots: annotated decision frames plus the run's rolling history.

Two producers write into ``logs/debug_screenshot/``:

- ``save_debug_screenshot()`` annotates one frame at a decision point -- a
  click, a failed locate, an OCR read -- so the frame explains itself.
- ``capture_run_frame()`` stores one routine frame per interval while a
  debug-enabled run is active, so an error archive carries the minutes leading
  up to a failure instead of only the frames taken after it.

The directory is cleared when a task starts and drained into the error archive
when one fails, so whatever it holds always belongs to the run just finished.
It is also the single owner of that path: the archiver asks here rather than
recomputing it.
"""
from __future__ import annotations

import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from AutoScriptor.core.box import Box
from AutoScriptor.core.targets import Target
from AutoScriptor.logging.logger import logger
from AutoScriptor.utils.paths import get_logs_root

try:
    from PIL import Image, ImageDraw, ImageFont
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False


_DEBUG_DIR_NAME = "debug_screenshot"

# Directory name the error archive uses for the run's screenshots.
RUN_SCREENSHOT_DIR_NAME = "debug_screenshots"

# One routine frame per interval while a debug-enabled run is active. Five
# seconds is fine enough to follow a task's steps and coarse enough that the
# capture never competes with recognition for the screenshot lane.
CAPTURE_INTERVAL_S = 5.0

# Per-prefix retention, newest first. The run history gets the largest budget:
# at the interval above it covers about five minutes, and older frames of a long
# task are exactly the ones a failure timeline needs least.
_KEEP_PER_PREFIX = {
    "c": 30,   # annotated clicks
    "s": 10,   # failed locate / click / stuck until
    "e": 5,    # OCR and extract
    "r": 60,   # routine run frames
}

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}

_run_capture_enabled = False
_last_capture_at = 0.0


def debug_screenshot_dir() -> Path:
    """Where debug screenshots live. Created on first use, not on import."""
    path = get_logs_root() / _DEBUG_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


# ── Run capture ──

def set_run_capture(enabled: bool) -> None:
    """Turn routine frame capture on or off for the run that is starting.

    The task executor owns this flag: it is the layer that knows whether the
    current task runs in debug mode, either from the app-wide setting or from
    the task's own registration metadata. Without it the control layer would
    have to guess from global config and would miss task-level debug runs.
    """
    global _run_capture_enabled, _last_capture_at
    _run_capture_enabled = bool(enabled)
    _last_capture_at = 0.0


def is_run_capture_enabled() -> bool:
    return _run_capture_enabled


def capture_run_frame(frame, *, interval_s: float = CAPTURE_INTERVAL_S) -> bool:
    """Store one routine frame when a debug run is active and the interval elapsed.

    Returns whether a frame was written. Called from every screenshot, so the
    disabled path returns before touching the frame.
    """
    global _last_capture_at
    if not _run_capture_enabled or frame is None:
        return False
    now = time.monotonic()
    if now - _last_capture_at < interval_s:
        return False
    _last_capture_at = now
    return _write_frame(frame, prefix="r")


# ── Annotation helpers ──

def _draw_text_with_bg(img, text: str, position: tuple[int, int], font_scale: float = 0.6, thickness: int = 2):
    """在图片上绘制带背景的文字（支持中文）"""
    text_x, text_y = position
    text_color, bg_color = (255, 255, 255), (0, 0, 0)
    text = text[:40] + "..." if len(text) > 40 else text
    if any('\u4e00' <= c <= '\u9fff' for c in text) and _HAS_PIL:
        try:
            img_pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
            draw = ImageDraw.Draw(img_pil)
            font_path = Path("C:/Windows/Fonts/msyh.ttc")
            font = ImageFont.truetype(str(font_path), int(20 * font_scale)) if font_path.exists() else ImageFont.load_default()
            bbox = draw.textbbox((0, 0), text, font=font)
            w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
            draw.rectangle([(text_x - 2, text_y - h - 2), (text_x + w + 2, text_y + 2)], fill=bg_color)
            draw.text((text_x, text_y - h), text, fill=text_color, font=font)
            img[:] = cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)
            return h + 4
        except (OSError, ValueError, RuntimeError):
            logger.debug("PIL text drawing failed; using OpenCV text renderer")
    font = cv2.FONT_HERSHEY_SIMPLEX
    (text_width, text_height), baseline = cv2.getTextSize(text, font, font_scale, thickness)
    cv2.rectangle(img, (text_x - 2, text_y - text_height - 2), (text_x + text_width + 2, text_y + baseline + 2), bg_color, -1)
    cv2.putText(img, text, (text_x, text_y), font, font_scale, text_color, thickness)
    return text_height + baseline + 4


def _draw_prior_clicks(img, prior_clicks: list[tuple[int, int]], final_color: tuple[int, int, int] = (0, 0, 255)):
    """绘制累积的 BoxTarget 点击轨迹，编号 1..N，颜色从浅红渐变到深红"""
    n = len(prior_clicks)
    if n == 0:
        return
    for i, pt in enumerate(prior_clicks):
        ratio = i / n  # 0 → 最浅, (n-1)/n → 次深 (最深留给当前 click)
        b = int(200 * (1 - ratio))
        g = int(200 * (1 - ratio))
        color = (b, g, 255)  # BGR: 浅红 (200,200,255) → 深红 (0,0,255)
        cv2.circle(img, pt, 8, color, -1)
        cv2.circle(img, pt, 8, (0, 0, 0), 1)
        label = str(i + 1)
        font = cv2.FONT_HERSHEY_SIMPLEX
        (tw, th), _ = cv2.getTextSize(label, font, 0.4, 1)
        cv2.putText(img, label, (pt[0] - tw // 2, pt[1] + th // 2), font, 0.4, (255, 255, 255), 1)


def _draw_info_bar(img, extra_info: dict):
    """在图像顶部绘制诊断信息条。click_mode 与 screenshot_src 不一致时显示红色警告。"""
    if not extra_info:
        return
    parts = [f"{k}:{v}" for k, v in extra_info.items()]
    click_mode = extra_info.get("click", "")
    src = extra_info.get("src", "")
    has_mismatch = click_mode and src and click_mode != src
    if has_mismatch:
        parts.insert(0, "MISMATCH!")
    info_text = "  ".join(parts)
    h, w = img.shape[:2]
    bar_h = 24
    bar_color = (0, 0, 200) if has_mismatch else (50, 50, 50)
    cv2.rectangle(img, (0, 0), (w, bar_h), bar_color, -1)
    cv2.putText(img, info_text, (4, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.48,
                (255, 255, 255), 1, cv2.LINE_AA)


# ── Writing ──

def _write_frame(img, prefix: str) -> bool:
    """Write one frame and trim the directory back to its retention budgets."""
    try:
        directory = debug_screenshot_dir()
        ts = datetime.now().strftime('%y%m%d_%H%M%S_%f')
        output_path = directory / f'{ts}_{prefix}.png'
        if not _imwrite(img, output_path):
            logger.warning("failed to write debug screenshot: %s", output_path)
            return False
        _prune(directory)
        return True
    except (OSError, cv2.error, AttributeError, TypeError, ValueError) as e:
        logger.warning(f"保存调试截图失败: {e}")
        return False


def _imwrite(img, path: Path) -> bool:
    """Write via imencode so paths outside the ASCII range still work.

    ``cv2.imwrite`` reports failure with a False return and no exception, which
    used to leave the directory silently empty whenever the repository lived
    under a non-ASCII path.
    """
    try:
        success, buffer = cv2.imencode(".png", img)
        if not success:
            return False
        buffer.tofile(str(path))
        return True
    except (cv2.error, OSError, AttributeError, TypeError, ValueError):
        return False


def _prune(directory: Path) -> None:
    """Keep the newest frames per prefix so the directory stays bounded."""
    try:
        files = sorted(
            (p for p in directory.iterdir() if p.is_file()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        keep: set[Path] = set()
        for prefix, limit in _KEEP_PER_PREFIX.items():
            keep.update(_frames_of_prefix(files, prefix)[:limit])
        for path in files:
            if path not in keep:
                path.unlink()
    except OSError as e:
        logger.debug(f"清理调试截图失败: {e}")


def _frames_of_prefix(files: list[Path], prefix: str) -> list[Path]:
    """Frames named ``<ts>_<prefix>.png``, plus the older ``<prefix>_`` spelling."""
    suffix = f"_{prefix}.png"
    legacy_prefix = f"{prefix}_"
    return [
        p for p in files
        if p.name.endswith(suffix) or (p.name.startswith(legacy_prefix) and p.name.endswith(".png"))
    ]


def save_debug_screenshot(
    target: Target|tuple[Target, ...],
    screenshot,  # numpy array (cv2 image format)
    box: Optional[Box] = None, 
    pt: Optional[tuple[int, int]] = None,
    ocr_text: Optional[str] = None,
    prefix: str = "c",
    prior_clicks: Optional[list[tuple[int, int]]] = None,
    extra_info: Optional[dict] = None
):
    """
    保存调试截图，支持多种标注方式
    
    Args:
        target: 目标对象或目标对象元组，用于标注目标信息
        screenshot: 截图底板（numpy array，cv2 格式）
        box: 用于标注框选区域（可选）
        pt: 点击位置 (x, y)，当点击或长按时有效（可选）
        ocr_text: OCR 结果文字，格式为 "ocr:{识别结果}"（可选）
        prior_clicks: 两次截图保存之间累积的 BoxTarget 点击位置列表（可选）
    
    Examples:
        from AutoScriptor.logging.tracer import save_debug_screenshot
        from AutoScriptor.core.box import Box
        
        # 点击截图
        save_debug_screenshot(target=T("确定"), screenshot=img, box=box, pt=(100, 200))
        
        # OCR 截图
        save_debug_screenshot(target=BoxTarget(Box(100, 100, 200, 50)), screenshot=img, box=Box(100, 100, 200, 50), ocr_text="ocr:购买")
        
        # 带诊断信息的截图（extra_info 会渲染到顶部信息条，click/src 不一致时红色高亮）
        save_debug_screenshot(target=T("确定"), screenshot=img, prefix="s",
                              extra_info={"click": "mumu", "src": "nemu", "until": "<lambda>", "elapsed": "30.1s"})
    """
    try:
        img = screenshot.copy()

        # 0-A. 绘制诊断信息条（mode/mismatch/until 等）
        if extra_info:
            _draw_info_bar(img, extra_info)

        # 0-B. 绘制累积的 BoxTarget 点击轨迹（浅红→深红，编号 1,2,3...）
        if prior_clicks:
            _draw_prior_clicks(img, prior_clicks)

        # 1. 绘制 Target 相关的标注（红色框和点击位置）
        if box is not None:
            right = box.left + box.width
            bottom = box.top + box.height
            cv2.rectangle(img, (box.left, box.top), (right, bottom), (0, 0, 255), 3)

            # 绘制 Target 信息文字（简化显示）
            if target is not None:
                t = target[0] if isinstance(target, tuple) else target
                target_str = f"T('{t.ui.text}')" if hasattr(t, 'ui') and hasattr(t.ui, 'text') and t.ui.text else f"Box[{box.left},{box.top}]"
                _draw_text_with_bg(img, target_str, (box.left, max(box.top - 10, 20)))

        # 2. 绘制点击位置（最深红，当前 click）
        if pt is not None:
            cv2.circle(img, pt, 5, (0, 0, 255), -1)

        # 3. 绘制 OCR 结果文字（格式：ocr:{识别结果}）
        if ocr_text is not None:
            # 如果传入的不是 "None" 字符串，格式化为 ocr:{res}
            if ocr_text != "None":
                ocr_display_text = f"ocr:{ocr_text}"
            else:
                ocr_display_text = "ocr:None"

            if box is not None:
                # 在 box 上方显示 OCR 文字
                _draw_text_with_bg(img, ocr_display_text, (box.left, max(box.top - 10, 20)))
            else:
                # 如果没有 box，在图片左上角显示
                _draw_text_with_bg(img, ocr_display_text, (10, 30))

        _write_frame(img, prefix)
    except (OSError, cv2.error, AttributeError, TypeError, ValueError) as e:
        logger.debug(f"保存调试截图失败: {e}")


def clear_debug_screenshots():
    """清空调试截图目录，在每个任务开始前调用，确保截图都属于当前任务"""
    try:
        directory = debug_screenshot_dir()
        for path in directory.iterdir():
            if path.is_file():
                path.unlink()
    except OSError as e:
        logger.debug(f"清理调试截图目录失败: {e}")


def take_debug_screenshots(destination: Path) -> int:
    """Move the run's screenshots into ``destination`` and empty the directory.

    Sorted by filename, which starts with the timestamp, so the archive keeps
    the run in chronological order. Returns how many files moved.
    """
    try:
        source = debug_screenshot_dir()
        frames = sorted(
            (
                p for p in source.iterdir()
                if p.is_file() and p.suffix.lower() in _IMAGE_SUFFIXES
            ),
            key=lambda p: p.name,
        )
    except OSError as e:
        logger.warning("read debug screenshots failed: %s", e)
        return 0

    if not frames:
        return 0

    destination.mkdir(parents=True, exist_ok=True)
    moved = 0
    for frame in frames:
        try:
            shutil.move(str(frame), str(destination / frame.name))
            moved += 1
        except OSError as e:
            logger.warning("move debug screenshot failed: %s (%s)", frame, e)
    return moved
