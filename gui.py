"""
AutoScriptor GUI Entry Point
============================
Launched by Electron (or directly) to start the FastAPI WebUI server.
Pass --electron to suppress the browser auto-open.
"""
from __future__ import annotations

import io
import sys

# Electron 管道 UTF-8：须在任意会写 stderr 的 import 之前执行。
# Windows 上 stderr 常为 cp936，按 GBK 写管道；main.js 按 UTF-8 解码会乱码。
# 在二进制 buffer 上套 UTF-8 TextIOWrapper，与 spawn + PYTHONIOENCODING 一致。
def _electron_force_utf8_stdio() -> None:
    if "--electron" not in sys.argv:
        return
    import os

    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("AUTOSCRIPTOR_ELECTRON_PIPE", "1")
    # 一律在二进制 buffer 上套 UTF-8：仅 reconfigure 在部分 Windows 版本上仍会写 cp936
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        buf = getattr(stream, "buffer", None) if stream is not None else None
        if buf is None:
            continue
        try:
            # detach() 先将旧 wrapper 与底层 buffer 分离，
            # 防止旧 wrapper 被 GC 时 __del__ -> close() 关闭共享的 buffer，
            # 否则 Rich / colorama 等后续写入会报 "I/O operation on closed file"。
            stream.flush()
            stream.detach()
            setattr(
                sys,
                name,
                io.TextIOWrapper(
                    buf,
                    encoding="utf-8",
                    errors="replace",
                    line_buffering=(name == "stderr"),
                    write_through=True,
                ),
            )
        except Exception:
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


_electron_force_utf8_stdio()

import argparse
import os
import site

# Nuitka 编译后 sys.path 由编译器自动管理，无需手动插入；
# 开发模式下仍需将项目根加入 sys.path 以支持 import AutoScriptor / ZmxyOL
_COMPILED = "__compiled__" in dir()
if _COMPILED:
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(sys.executable)))
    # standalone 下 site.USER_SITE 常为 None，Paddle 在 set_paddle_lib_path 等处会拼接失败
    _exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    if getattr(site, "USER_SITE", None) is None:
        site.USER_SITE = os.path.join(_exe_dir, ".user_site")
        try:
            os.makedirs(site.USER_SITE, exist_ok=True)
        except OSError:
            pass
else:
    ROOT = os.path.dirname(os.path.abspath(__file__))
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)

parser = argparse.ArgumentParser(description='AutoScriptor web service')
parser.add_argument('--host', default='127.0.0.1')
parser.add_argument('-p', '--port', type=int, default=5000)
parser.add_argument('--electron', action='store_true',
                    help='Running inside Electron shell — suppress browser open')
parser.add_argument('--ssl-key', default=None, help='SSL key file path')
parser.add_argument('--ssl-cert', default=None, help='SSL certificate file path')
args, _ = parser.parse_known_args()

if args.electron:
    import webbrowser as _wb
    _wb.open = lambda *a, **kw: None


def _webui_worker(restart_event):
    """子进程入口：启动 WebUI 并支持更新后重启。"""
    # 子进程继承了父进程的 env，PYTHONIOENCODING/PYTHONUTF8 已由解释器启动时生效。
    # 针对 Electron 管道额外套 UTF-8 TextIOWrapper（与父进程行为一致）。
    if os.environ.get("AUTOSCRIPTOR_ELECTRON_PIPE"):
        for name in ("stdout", "stderr"):
            stream = getattr(sys, name, None)
            buf = getattr(stream, "buffer", None) if stream else None
            if buf is None:
                continue
            try:
                stream.flush()
                stream.detach()
                setattr(
                    sys,
                    name,
                    io.TextIOWrapper(
                        buf,
                        encoding="utf-8",
                        errors="replace",
                        line_buffering=(name == "stderr"),
                        write_through=True,
                    ),
                )
            except Exception:
                try:
                    stream.reconfigure(encoding="utf-8", errors="replace")
                except Exception:
                    pass

    if os.environ.get("AUTOSCRIPTOR_ELECTRON"):
        import webbrowser as _wb
        _wb.open = lambda *a, **kw: None

    from services.webui.server import run_webui
    run_webui(restart_event=restart_event)


if __name__ == '__main__':
    from services.single_instance import ensure_single_instance

    ensure_single_instance()

    import multiprocessing
    import signal

    multiprocessing.freeze_support()

    if args.electron:
        os.environ['UVICORN_LOG_LEVEL'] = 'info'
        os.environ['AUTOSCRIPTOR_ELECTRON'] = '1'

    from multiprocessing import Event, Process

    _mp_state = {"should_exit": False, "process": None}

    def _stop_webui_worker(_signum=None, _frame=None):
        """父进程收到终止信号时先结束子进程，避免 Windows 上仅父进程退出、uvicorn 子进程残留。"""
        p = _mp_state["process"]
        if p is not None and p.is_alive():
            p.terminate()
            try:
                p.join(timeout=10)
            except Exception:
                pass
            if p.is_alive():
                try:
                    p.kill()
                except Exception:
                    pass
        _mp_state["should_exit"] = True

    for _sig in ("SIGTERM", "SIGINT"):
        if hasattr(signal, _sig):
            try:
                signal.signal(getattr(signal, _sig), _stop_webui_worker)
            except Exception:
                pass
    if hasattr(signal, "SIGBREAK"):
        try:
            signal.signal(signal.SIGBREAK, _stop_webui_worker)
        except Exception:
            pass

    should_exit = False
    while not should_exit:
        _mp_state["should_exit"] = False
        event = Event()
        process = Process(target=_webui_worker, args=(event,))
        _mp_state["process"] = process
        process.start()
        while not should_exit:
            if _mp_state["should_exit"]:
                should_exit = True
                break
            try:
                signaled = event.wait(1)
            except KeyboardInterrupt:
                _stop_webui_worker()
                should_exit = True
                break
            if signaled:
                print("[AutoScriptor] 更新完成，正在重启后端...", flush=True)
                process.kill()
                process.join(timeout=10)
                break
            elif process.is_alive():
                continue
            else:
                should_exit = True
        if should_exit and process.is_alive():
            _stop_webui_worker()
            try:
                process.join(timeout=2)
            except Exception:
                pass
        _mp_state["process"] = None
