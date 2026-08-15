"""AutoScriptor source WebUI entry point.

Electron starts this file with ``--electron``. Direct source use can run:

    .venv\\Scripts\\python.exe -X utf8 services\\webui\\gui.py
"""
from __future__ import annotations

import argparse
import os
import signal
import sys
import time
from pathlib import Path


def _force_electron_utf8_stdio() -> None:
    """Keep Electron's pipe output UTF-8 before later imports can write logs."""
    if "--electron" not in sys.argv and not os.environ.get("AUTOSCRIPTOR_ELECTRON_PIPE"):
        return

    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("AUTOSCRIPTOR_ELECTRON_PIPE", "1")

    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is not None:
            stream.reconfigure(
                encoding="utf-8",
                errors="replace",
                line_buffering=(name == "stderr"),
                write_through=True,
            )


_force_electron_utf8_stdio()

_BOOT_T0 = time.perf_counter()


def _boot_log(message: str) -> None:
    if "--electron" not in sys.argv and not os.environ.get("AUTOSCRIPTOR_ELECTRON_PIPE"):
        return
    elapsed = time.perf_counter() - _BOOT_T0
    print(f"[startup] {message} (Python {elapsed:.1f}s)", flush=True)


_boot_log("Python 进程已启动，正在初始化源码运行环境")

ROOT = str(Path(__file__).resolve().parents[2])
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

parser = argparse.ArgumentParser(description="AutoScriptor WebUI source service")
parser.add_argument(
    "--electron",
    action="store_true",
    help="Running inside Electron shell; suppress browser auto-open",
)
args, _ = parser.parse_known_args()

if args.electron:
    import webbrowser as _webbrowser

    _webbrowser.open = lambda *a, **kw: None


def _webui_worker(restart_event):
    """Child process entry: start WebUI and signal parent restart after updates."""
    _force_electron_utf8_stdio()

    if os.environ.get("AUTOSCRIPTOR_ELECTRON"):
        import webbrowser as _webbrowser

        _webbrowser.open = lambda *a, **kw: None

    _boot_log("正在导入 WebUI 服务模块")
    from services.webui.server import run_webui

    _boot_log("WebUI 服务模块已导入，正在启动 HTTP 服务")
    run_webui(restart_event=restart_event)


def main() -> int:
    _boot_log("正在准备多进程运行环境")
    import multiprocessing

    multiprocessing.set_executable(sys.executable)
    multiprocessing.freeze_support()

    _boot_log("正在检查单实例锁")
    from services.single_instance import ensure_single_instance

    ensure_single_instance()

    if args.electron:
        os.environ["UVICORN_LOG_LEVEL"] = "info"
        os.environ["AUTOSCRIPTOR_ELECTRON"] = "1"

    _boot_log("正在准备 WebUI 子进程")
    from multiprocessing import Event, Process

    mp_state = {"should_exit": False, "process": None}

    def terminate_webui_worker(timeout: float = 10) -> None:
        process = mp_state["process"]
        if process is None or not process.is_alive():
            return
        process.terminate()
        process.join(timeout=timeout)
        if process.is_alive():
            process.kill()
            process.join(timeout=timeout)

    def stop_webui_worker(_signum=None, _frame=None):
        terminate_webui_worker()
        mp_state["should_exit"] = True

    for sig_name in ("SIGTERM", "SIGINT", "SIGBREAK"):
        sig = getattr(signal, sig_name, None)
        if sig is not None:
            signal.signal(sig, stop_webui_worker)

    should_exit = False
    while not should_exit:
        mp_state["should_exit"] = False
        event = Event()
        process = Process(target=_webui_worker, args=(event,))
        mp_state["process"] = process
        _boot_log("正在启动 WebUI 子进程")
        process.start()
        _boot_log(f"WebUI 子进程已启动 pid={process.pid}")

        while not should_exit:
            if mp_state["should_exit"]:
                should_exit = True
                break
            try:
                signaled = event.wait(1)
            except KeyboardInterrupt:
                stop_webui_worker()
                should_exit = True
                break

            if signaled:
                print("[AutoScriptor] Update complete; restarting backend...", flush=True)
                process.kill()
                process.join(timeout=10)
                break
            if process.is_alive():
                continue
            should_exit = True

        if should_exit and process.is_alive():
            terminate_webui_worker(timeout=2)
        mp_state["process"] = None

    return 0


if __name__ == "__main__":
    sys.exit(main())
