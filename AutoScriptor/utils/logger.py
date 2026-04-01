"""
统一日志模块 — 基于 rich
========================
对外提供与旧 logzero 完全兼容的 ``logger`` 实例（标准 logging.Logger），
同时使用 rich.logging.RichHandler 处理控制台输出，天然支持 UTF-8 & 终端颜色。

公共 API
--------
- ``logger``               — 全局 Logger（INFO 级别）
- ``set_current_task(name)`` — 注入当前线程的任务名
- ``setup_task_aware_logging()`` — 应用任务感知的日志格式
- ``setup_logfile(path)``  — 添加 / 切换文件 handler（UTF-8）
- ``log_flush(msg)``       — 单行覆写式控制台输出（进度用）
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import inspect

# Nuitka standalone 下 Rich 测量单元格宽度会动态 import「unicode17-0-0」等子模块，
# 与冻结导入不兼容；编译产物改用标准 StreamHandler。
_COMPILED = "__compiled__" in dir()

if not _COMPILED:
    # ── rich console: 统一 UTF-8；Electron 管道禁用 legacy Windows 路径 ──
    from rich.console import Console
    from rich.logging import RichHandler
    from rich.text import Text

    _force_terminal = not os.environ.get("NO_COLOR")
    _electron_pipe = os.environ.get("AUTOSCRIPTOR_ELECTRON_PIPE") == "1"
    _kw = dict(
        file=sys.stderr,
        stderr=False,
        force_terminal=_force_terminal,
        force_jupyter=False,
        color_system="auto" if _force_terminal else None,
        legacy_windows=False,
    )
    if _electron_pipe:
        _kw["width"] = 120
    _console = Console(**_kw)
else:
    Text = None  # type: ignore[misc, assignment]
    _electron_pipe = os.environ.get("AUTOSCRIPTOR_ELECTRON_PIPE") == "1"
    _console = None

# ── 任务名注入 ──────────────────────────────────────────────────
_task_ctx = threading.local()


def set_current_task(name: str | None):
    """设置当前线程正在执行的任务名称（None 表示清除）"""
    _task_ctx.name = name


class _TaskFilter(logging.Filter):
    """在 LogRecord 上附加 task_prefix 字段，供 Formatter 使用。"""
    def filter(self, record: logging.LogRecord) -> bool:
        task_name = getattr(_task_ctx, "name", None)
        record.task_prefix = f"[{task_name}] " if task_name else ""
        return True


# ── 文件 handler 使用的纯文本 Formatter ─────────────────────────
_FILE_FMT = "%(task_prefix)s[%(levelname)1.1s %(asctime)s %(module)s:%(lineno)d] %(message)s"
_FILE_DATEFMT = "%y%m%d %H:%M:%S"

# Nuitka 下控制台与文件格式一致（无 Rich 竖线/路径列）
_CONSOLE_PLAIN_FMT = "%(task_prefix)s[%(levelname)1.1s %(asctime)s] %(message)s"
_CONSOLE_DATEFMT = "%H:%M:%S"

# ── 构建全局 logger ─────────────────────────────────────────────
logger = logging.getLogger("AutoScriptor")
logger.setLevel(logging.DEBUG)
logger.propagate = False

if not _COMPILED:

    class _ElectronRichHandler(RichHandler):
        """Electron 管道下：不显示源码路径，级别列不 ljust(8) 以免与竖线之间空一大截。"""

        def get_level_text(self, record: logging.LogRecord) -> Text:
            level_name = record.levelname
            return Text.styled(level_name, f"logging.level.{level_name.lower()}")


# 防止重复添加 handler（热重载场景）
if not logger.handlers:
    if _COMPILED:
        _plain = logging.StreamHandler(stream=sys.stderr)
        _plain.setLevel(logging.DEBUG)
        _plain.setFormatter(
            logging.Formatter(_CONSOLE_PLAIN_FMT, datefmt=_CONSOLE_DATEFMT)
        )
        _plain.addFilter(_TaskFilter())
        logger.addHandler(_plain)
    else:
        _rh_kw = dict(
            console=_console,
            show_time=True,
            show_path=not _electron_pipe,
            rich_tracebacks=True,
            tracebacks_show_locals=False,
            markup=False,
            log_time_format="%H:%M:%S",
        )
        _rich_handler = (_ElectronRichHandler if _electron_pipe else RichHandler)(
            **_rh_kw
        )
        _rich_handler.setLevel(logging.DEBUG)
        _rich_handler.addFilter(_TaskFilter())
        logger.addHandler(_rich_handler)

_file_handler: logging.FileHandler | None = None


def setup_task_aware_logging():
    """兼容旧调用——rich handler 已自带任务感知 filter，此处为空操作。"""
    pass


def setup_logfile(path: str, encoding: str = "utf-8"):
    """添加 / 切换文件日志 handler（UTF-8），替代 logzero.logfile()。"""
    global _file_handler
    if _file_handler is not None:
        logger.removeHandler(_file_handler)
        try:
            _file_handler.close()
        except Exception:
            pass

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    _file_handler = logging.FileHandler(path, encoding=encoding, errors="replace")
    _file_handler.setLevel(logging.DEBUG)
    _file_handler.setFormatter(logging.Formatter(_FILE_FMT, datefmt=_FILE_DATEFMT))
    _file_handler.addFilter(_TaskFilter())
    logger.addHandler(_file_handler)


# ── log_flush: 单行覆写式控制台输出 ─────────────────────────────
_last_flush_msg = ""


def log_flush(msg: str):
    """在控制台以 \\r 覆写方式打印进度信息，不写入文件。"""
    global _last_flush_msg
    if msg == _last_flush_msg:
        return
    _last_flush_msg = msg
    if _COMPILED:
        print(msg, end="\r", flush=True)
        return
    try:
        _console.print(msg, end="\r", highlight=False)
    except Exception:
        print(msg, end="\r", flush=True)
