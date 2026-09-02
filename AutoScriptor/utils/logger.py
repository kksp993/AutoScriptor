"""Source runtime logging utilities."""
from __future__ import annotations

import inspect
import logging
import os
import sys
import threading

from rich.console import Console
from rich.logging import RichHandler
from rich.text import Text

logging.raiseExceptions = False

_devnull_stream = None
_console_lock = threading.RLock()


def _is_closed_stream_error(exc: BaseException | None) -> bool:
    if isinstance(exc, ValueError) and "closed file" in str(exc).lower():
        return True
    if isinstance(exc, OSError) and getattr(exc, "errno", None) in {9, 22}:
        return True
    return False


def _stream_is_closed(stream) -> bool:
    if stream is None:
        return True
    try:
        return bool(getattr(stream, "closed", False))
    except (OSError, ValueError, AttributeError):
        return True


def _safe_stderr():
    global _devnull_stream
    for stream in (getattr(sys, "stderr", None), getattr(sys, "__stderr__", None)):
        if not _stream_is_closed(stream):
            return stream
    if _devnull_stream is None or _stream_is_closed(_devnull_stream):
        _devnull_stream = open(os.devnull, "w", encoding="utf-8", errors="replace")
    return _devnull_stream


class _SafeStreamHandler(logging.StreamHandler):
    def _refresh_stream(self) -> None:
        self.acquire()
        try:
            self.stream = _safe_stderr()
        finally:
            self.release()

    def emit(self, record: logging.LogRecord) -> None:
        if _stream_is_closed(getattr(self, "stream", None)):
            self._refresh_stream()
        super().emit(record)

    def handleError(self, record: logging.LogRecord) -> None:
        if _is_closed_stream_error(sys.exc_info()[1]):
            self._refresh_stream()
            return
        super().handleError(record)


_force_terminal = not os.environ.get("NO_COLOR")
_electron_pipe = os.environ.get("AUTOSCRIPTOR_ELECTRON_PIPE") == "1"
_console_kwargs = {
    "stderr": False,
    "force_terminal": _force_terminal,
    "force_jupyter": False,
    "color_system": "auto" if _force_terminal else None,
    "legacy_windows": False,
}
if _electron_pipe:
    _console_kwargs["width"] = 120


def _make_console() -> Console:
    return Console(file=_safe_stderr(), **_console_kwargs)


_console = _make_console()
_task_ctx = threading.local()
_AUTOSCRIPTOR_PACKAGE_ROOT = os.path.normcase(
    os.path.realpath(os.path.join(os.path.dirname(__file__), os.pardir))
)
_PROJECT_ROOT = os.path.normcase(
    os.path.realpath(os.path.join(_AUTOSCRIPTOR_PACKAGE_ROOT, os.pardir))
)


def _normalize_source_path(path: str) -> str:
    return os.path.normcase(os.path.realpath(path))


def _is_path_within(path: str, parent: str) -> bool:
    try:
        return os.path.commonpath((_normalize_source_path(path), parent)) == parent
    except (OSError, ValueError):
        return False


def _find_external_project_caller():
    """Return the first project caller outside the AutoScriptor package."""
    current_frame = inspect.currentframe()
    try:
        current_frame = current_frame.f_back if current_frame is not None else None
        while current_frame is not None:
            source_path = current_frame.f_code.co_filename
            is_project_source = _is_path_within(source_path, _PROJECT_ROOT)
            is_autoscriptor_source = _is_path_within(source_path, _AUTOSCRIPTOR_PACKAGE_ROOT)
            if is_project_source and not is_autoscriptor_source:
                return source_path, current_frame.f_lineno, current_frame.f_code.co_name
            current_frame = current_frame.f_back
    finally:
        del current_frame
    return None


def set_current_task(name: str | None):
    """Set the task name attached to current-thread log records."""
    _task_ctx.name = name


class _TaskFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        task_name = getattr(_task_ctx, "name", None)
        record.task_prefix = f"[{task_name}] " if task_name else ""
        return True


class _ExternalCallerFilter(logging.Filter):
    """Show the business-script caller for logs emitted by AutoScriptor internals."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not _is_path_within(record.pathname, _AUTOSCRIPTOR_PACKAGE_ROOT):
            return True

        external_caller = _find_external_project_caller()
        if external_caller is None:
            return True

        source_path, line_number, function_name = external_caller
        record.pathname = source_path
        record.filename = os.path.basename(source_path)
        record.module = os.path.splitext(record.filename)[0]
        record.lineno = line_number
        record.funcName = function_name
        return True


_FILE_FMT = "%(task_prefix)s[%(levelname)1.1s %(asctime)s %(module)s:%(lineno)d] %(message)s"
_FILE_DATEFMT = "%y%m%d %H:%M:%S"
_CONSOLE_PLAIN_FMT = "%(task_prefix)s[%(levelname)1.1s %(asctime)s] %(message)s"
_CONSOLE_DATEFMT = "%H:%M:%S"

logger = logging.getLogger("AutoScriptor")
logger.setLevel(logging.DEBUG)
logger.propagate = False


class _SafeRichHandler(RichHandler):
    def _refresh_console(self) -> None:
        global _console
        with _console_lock:
            _console = _make_console()
            self.console = _console

    def emit(self, record: logging.LogRecord) -> None:
        if _stream_is_closed(getattr(self.console, "file", None)):
            self._refresh_console()
        super().emit(record)

    def handleError(self, record: logging.LogRecord) -> None:
        if _is_closed_stream_error(sys.exc_info()[1]):
            self._refresh_console()
            return
        super().handleError(record)


class _ElectronRichHandler(_SafeRichHandler):
    def get_level_text(self, record: logging.LogRecord) -> Text:
        level_name = record.levelname
        return Text.styled(level_name, f"logging.level.{level_name.lower()}")


if not logger.handlers:
    try:
        rich_handler = (_ElectronRichHandler if _electron_pipe else _SafeRichHandler)(
            console=_console,
            show_time=True,
            show_path=not _electron_pipe,
            rich_tracebacks=True,
            tracebacks_show_locals=False,
            markup=False,
            log_time_format="%H:%M:%S",
        )
        rich_handler.setLevel(logging.DEBUG)
        rich_handler.addFilter(_TaskFilter())
        rich_handler.addFilter(_ExternalCallerFilter())
        logger.addHandler(rich_handler)
    except (OSError, RuntimeError, TypeError, ValueError):
        plain_handler = _SafeStreamHandler(stream=_safe_stderr())
        plain_handler.setLevel(logging.DEBUG)
        plain_handler.setFormatter(
            logging.Formatter(_CONSOLE_PLAIN_FMT, datefmt=_CONSOLE_DATEFMT)
        )
        plain_handler.addFilter(_TaskFilter())
        plain_handler.addFilter(_ExternalCallerFilter())
        logger.addHandler(plain_handler)


_file_handler: logging.FileHandler | None = None


def setup_logfile(path: str, encoding: str = "utf-8"):
    """Add or switch the UTF-8 file log handler."""
    global _file_handler
    if _file_handler is not None:
        logger.removeHandler(_file_handler)
        try:
            _file_handler.close()
        except OSError:
            pass

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    _file_handler = logging.FileHandler(path, encoding=encoding, errors="replace")
    _file_handler.setLevel(logging.DEBUG)
    _file_handler.setFormatter(logging.Formatter(_FILE_FMT, datefmt=_FILE_DATEFMT))
    _file_handler.addFilter(_TaskFilter())
    _file_handler.addFilter(_ExternalCallerFilter())
    logger.addHandler(_file_handler)


_last_flush_msg = ""


def log_flush(msg: str):
    """Print a single-line progress message without writing to the file log."""
    global _last_flush_msg
    if msg == _last_flush_msg:
        return
    _last_flush_msg = msg
    try:
        _console.print(msg, end="\r", highlight=False)
    except (OSError, RuntimeError, ValueError):
        try:
            print(msg, end="\r", flush=True, file=_safe_stderr())
        except (OSError, RuntimeError, ValueError):
            pass
