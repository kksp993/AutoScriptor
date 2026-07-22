"""Task error archive helpers for source runtime."""
from __future__ import annotations

import shutil
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import cv2

from AutoScriptor.utils.logger import logger
from AutoScriptor.utils.paths import get_error_archives_dir, get_logs_root


_DEFAULT_CONTEXT_CONFIG = {
    "mm_current_region": True,
    "locate_region_result": True,
    "bg_active_callbacks": True,
    "bg_signals": True,
    "bg_event_history": True,
    "recognition_trace": True,
    "python_version": True,
    "timestamp": True,
}


def _imwrite_unicode(path: str, img) -> bool:
    """Write an image to paths that may contain non-ASCII characters."""
    try:
        success, buf = cv2.imencode(".png", img)
        if not success:
            return False
        buf.tofile(path)
        return True
    except (cv2.error, OSError, AttributeError, TypeError, ValueError):
        return False


def _format_variable_value(value: Any, max_length: int = 200) -> str:
    try:
        if value is None:
            return "None"
        if isinstance(value, (str, int, float, bool)):
            text = str(value)
            return text[:max_length] + "..." if len(text) > max_length else text
        if isinstance(value, (list, tuple)):
            if not value:
                return f"{type(value).__name__}([])"
            if len(value) > 10:
                items = ", ".join(_format_variable_value(v, 50) for v in value[:5])
                return f"{type(value).__name__}([{items}...], len={len(value)})"
            items = ", ".join(_format_variable_value(v, 50) for v in value)
            return f"{type(value).__name__}([{items}])"
        if isinstance(value, dict):
            if not value:
                return "dict({})"
            items_iter = list(value.items())
            clipped = len(items_iter) > 10
            shown = items_iter[:5] if clipped else items_iter
            items = ", ".join(
                f"{k!r}: {_format_variable_value(v, 50)}" for k, v in shown
            )
            suffix = f"...}}, len={len(value)})" if clipped else "})"
            return f"dict({{{items}{suffix}"
        text = repr(value)
        return text[:max_length] + "..." if len(text) > max_length else text
    except Exception:
        return f"<unformattable {type(value).__name__}>"


def collect_default_context(config: Optional[Dict[str, bool]] = None) -> Dict[str, Any]:
    """Collect lightweight runtime context for error archives."""
    merged = _DEFAULT_CONTEXT_CONFIG.copy()
    if config:
        merged.update(config)
    context: Dict[str, Any] = {}

    if merged.get("mm_current_region"):
        try:
            from ZmxyOL.nav.map_manager import mm

            cur_env, cur_loc = mm.get_region()
            context["mm_current_region"] = {"env": cur_env, "loc": cur_loc}
        except Exception as exc:
            context["mm_current_region"] = f"failed: {exc}"

    if merged.get("locate_region_result"):
        try:
            from ZmxyOL.nav.api import locate_region

            result = locate_region(cnt=0, check_only=True)
            if isinstance(result, tuple) and len(result) == 2:
                detected_env, detected_loc = result
                context["locate_region_result"] = {
                    "env": detected_env,
                    "loc": detected_loc,
                }
            else:
                context["locate_region_result"] = f"unresolved: {result}"
        except Exception as exc:
            context["locate_region_result"] = f"failed: {exc}"

    if merged.get("bg_active_callbacks"):
        try:
            from AutoScriptor.core.background import bg

            if hasattr(bg, "get_idfs"):
                context["bg_active_callbacks"] = list(bg.get_idfs())
            elif hasattr(bg, "_callbacks"):
                context["bg_active_callbacks"] = list(bg._callbacks.keys())
            else:
                context["bg_active_callbacks"] = []
        except Exception as exc:
            context["bg_active_callbacks"] = f"failed: {exc}"

    if merged.get("bg_signals"):
        try:
            from AutoScriptor.core.background import bg

            if hasattr(bg, "_signals"):
                context["bg_signals"] = {
                    key: _format_variable_value(value, max_length=100)
                    for key, value in bg._signals.items()
                }
            else:
                context["bg_signals"] = "unavailable"
        except Exception as exc:
            context["bg_signals"] = f"failed: {exc}"

    if merged.get("bg_event_history"):
        try:
            from AutoScriptor.core.background import bg

            if hasattr(bg, "get_event_history"):
                history = bg.get_event_history()
                context["bg_event_history"] = (
                    "\n    " + "\n    ".join(history) if history else "(empty)"
                )
            else:
                context["bg_event_history"] = "(unsupported)"
        except Exception as exc:
            context["bg_event_history"] = f"failed: {exc}"

    if merged.get("recognition_trace"):
        try:
            from AutoScriptor.recognition.recognition_trace import (
                get_recent_recognition_results,
                serialize_recognition_results,
            )

            context["recognition_trace"] = serialize_recognition_results(
                get_recent_recognition_results(limit=16)
            )
        except Exception as exc:
            context["recognition_trace"] = f"failed: {exc}"

    if merged.get("python_version"):
        context["python_version"] = sys.version.split()[0]
    if merged.get("timestamp"):
        context["error_timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return context


def _safe_archive_name(error_name: str) -> str:
    return (
        error_name.replace("/", "_")
        .replace("\\", "_")
        .replace(" -> ", "_")
        .strip()
        or "error"
    )


def _current_log_file() -> Optional[Path]:
    for handler in logger.handlers:
        filename = getattr(handler, "baseFilename", None)
        if filename and Path(filename).exists():
            return Path(filename)

    log_dir = get_logs_root() / "log"
    if not log_dir.is_dir():
        return None
    candidates = [p for p in log_dir.iterdir() if p.suffix.lower() == ".log"]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _recent_log_lines(limit: int = 100) -> list[str]:
    try:
        log_file = _current_log_file()
        if not log_file:
            return []
        with log_file.open("r", encoding="utf-8", errors="ignore") as handle:
            lines = handle.readlines()
        return lines[-limit:]
    except (OSError, ValueError) as exc:
        logger.warning("read recent log failed: %s", exc)
        return []


def _write_error_log(
    archive_dir: Path,
    ts: str,
    error_name: str,
    exc: Exception,
    extra_context: Optional[Dict[str, Any]],
) -> None:
    recent_lines = _recent_log_lines()
    context = collect_default_context()
    if extra_context:
        context.update(extra_context)

    with (archive_dir / "error.log").open("w", encoding="utf-8") as handle:
        if recent_lines:
            handle.write("=" * 80 + "\n")
            handle.write("Recent log lines:\n")
            handle.write("=" * 80 + "\n")
            handle.writelines(recent_lines)
            handle.write("\n")

        handle.write("=" * 80 + "\n")
        handle.write("Error:\n")
        handle.write("=" * 80 + "\n")
        handle.write(f"[{ts}] {error_name}: {exc}\n")
        handle.write(f"type: {type(exc).__name__}\n")
        handle.write(f"message: {exc}\n\n")

        if context:
            handle.write("=" * 80 + "\n")
            handle.write("Context:\n")
            handle.write("=" * 80 + "\n")
            for key, value in sorted(context.items()):
                handle.write(f"  {key} = {_format_variable_value(value)}\n")
            handle.write("\n")

        handle.write("=" * 80 + "\n")
        handle.write("Traceback:\n")
        handle.write("=" * 80 + "\n")
        if exc.__traceback__ is not None:
            tb = traceback.TracebackException.from_exception(
                exc,
                capture_locals=False,
                lookup_lines=True,
            )
            handle.write("".join(tb.format()))
        else:
            handle.write("".join(traceback.format_exception_only(type(exc), exc)))


def _save_screenshots(archive_dir: Path, mixctrl) -> None:
    if mixctrl is None:
        return
    try:
        img = mixctrl.screenshot()
        if img is not None:
            _imwrite_unicode(str(archive_dir / "current_screenshot.png"), img)
    except Exception as exc:
        logger.warning("save current screenshot failed: %s", exc)

    for idx in range(1, 4):
        time.sleep(1)
        try:
            img = mixctrl.screenshot()
            if img is not None:
                _imwrite_unicode(str(archive_dir / f"timed_screenshot_{idx}.png"), img)
        except Exception as exc:
            logger.warning("save timed screenshot %s failed: %s", idx, exc)


def _copy_click_screenshots(archive_dir: Path) -> None:
    click_dir = get_logs_root() / "debug_screenshot"
    if not click_dir.is_dir():
        return

    destination = archive_dir / "click_screenshots"
    destination.mkdir(parents=True, exist_ok=True)
    copied = 0
    for src in click_dir.iterdir():
        if src.is_file() and src.suffix.lower() in {".png", ".jpg", ".jpeg"}:
            try:
                shutil.copy2(src, destination / src.name)
                copied += 1
            except OSError as exc:
                logger.warning("copy click screenshot failed: %s (%s)", src, exc)

    if copied == 0:
        try:
            destination.rmdir()
        except OSError:
            pass
        return

    for src in click_dir.iterdir():
        if src.is_file() and src.suffix.lower() in {".png", ".jpg", ".jpeg"}:
            try:
                src.unlink()
            except OSError as exc:
                logger.warning("clear click screenshot failed: %s (%s)", src, exc)


def archive_error(
    error_name: str,
    exc: Exception,
    mixctrl=None,
    include_click_screenshots: bool = True,
    extra_context: Optional[Dict[str, Any]] = None,
    video_path: str | Path | None = None,
) -> Optional[str]:
    """Archive a task error with recent logs, context and screenshots."""
    try:
        ts = datetime.now().strftime("%y%m%d_%H%M%S")
        archive_dir = get_error_archives_dir() / f"{ts}_{_safe_archive_name(error_name)}"
        archive_dir.mkdir(parents=True, exist_ok=True)

        _write_error_log(archive_dir, ts, error_name, exc, extra_context)
        _save_screenshots(archive_dir, mixctrl)
        if include_click_screenshots:
            _copy_click_screenshots(archive_dir)
        if video_path:
            from AutoScriptor.utils.task_video_recorder import copy_video_to_archive

            copy_video_to_archive(video_path, archive_dir)

        logger.info("error archived: %s", archive_dir)
        return str(archive_dir)
    except Exception as archive_exc:
        logger.error("archive error failed: %s", archive_exc)
        logger.error(traceback.format_exc())
        return None
