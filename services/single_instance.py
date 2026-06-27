"""
跨进程单例：保证 AutoScriptor 源码 WebUI / Electron 主入口全局只运行一个实例。

放在 services/ 下，避免 import AutoScriptor 包时执行其 __init__ 拉起重依赖。

- Windows：命名互斥体（Local\\AutoScriptor_<name>）
- 其他平台：临时目录下锁文件 + fcntl 非阻塞排他锁

开发调试可设置环境变量 AUTOSCRIPTOR_ALLOW_MULTI_INSTANCE=1 跳过检查。
"""

from __future__ import annotations

import atexit
import os
import re
import sys
import tempfile
from pathlib import Path

_ERROR_ALREADY_EXISTS = 183
_state: dict[str, object] = {"kind": None, "handle": None, "fp": None}


def _sanitize(lock_name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]+", "_", lock_name.strip())
    return s or "default"


def _release() -> None:
    kind = _state.get("kind")
    if kind == "win32":
        h = _state.get("handle")
        if h:
            try:
                import ctypes

                ctypes.windll.kernel32.CloseHandle(h)
            except (AttributeError, OSError, ValueError):
                pass
        _state["handle"] = None
    elif kind == "posix":
        fp = _state.get("fp")
        if fp:
            try:
                import fcntl

                fcntl.flock(fp.fileno(), fcntl.LOCK_UN)
            except (ImportError, OSError, ValueError):
                pass
            try:
                fp.close()
            except OSError:
                pass
        _state["fp"] = None
    _state["kind"] = None


def ensure_single_instance(lock_name: str = "autoscriptor", *, exit_code: int = 1) -> None:
    """
    若已有其它进程持有同名锁，打印说明并 sys.exit(exit_code)。

    在进程退出时通过 atexit 释放锁（Windows 关闭互斥体句柄，POSIX 解锁并关闭文件）。
    """
    raw = os.environ.get("AUTOSCRIPTOR_ALLOW_MULTI_INSTANCE", "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return

    key = _sanitize(lock_name)

    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        mutex_name = f"Local\\AutoScriptor_{key}"
        handle = kernel32.CreateMutexW(None, True, mutex_name)
        if not handle:
            print("无法创建单例互斥量，请稍后重试。", file=sys.stderr, flush=True)
            sys.exit(exit_code)
        err = ctypes.get_last_error()
        if err == _ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            print(
                "AutoScriptor 已在运行，请勿重复启动。\n"
                "若确认无其它实例，可结束残留进程，或设置环境变量 "
                "AUTOSCRIPTOR_ALLOW_MULTI_INSTANCE=1（仅开发调试）。",
                file=sys.stderr,
                flush=True,
            )
            sys.exit(exit_code)
        _state["kind"] = "win32"
        _state["handle"] = handle
    else:
        import fcntl

        lock_path = Path(tempfile.gettempdir()) / f"autoscriptor_{key}.lock"
        try:
            fp = open(lock_path, "a+b")
        except OSError as e:
            print(f"无法打开单例锁文件: {e}", file=sys.stderr, flush=True)
            sys.exit(exit_code)
        try:
            fcntl.flock(fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            try:
                fp.close()
            except OSError:
                pass
            print(
                "AutoScriptor 已在运行，请勿重复启动。\n"
                "若确认无其它实例，可结束残留进程，或设置环境变量 "
                "AUTOSCRIPTOR_ALLOW_MULTI_INSTANCE=1（仅开发调试）。",
                file=sys.stderr,
                flush=True,
            )
            sys.exit(exit_code)
        _state["kind"] = "posix"
        _state["fp"] = fp

    atexit.register(_release)
