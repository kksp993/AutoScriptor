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
import json
import os

# Nuitka 编译后 sys.path 由编译器自动管理，无需手动插入；
# 开发模式下仍需将项目根加入 sys.path 以支持 import AutoScriptor / ZmxyOL
_COMPILED = "__compiled__" in dir()
if _COMPILED:
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(sys.executable)))
    # Keep a stable user base without importing site; site pulls pip/ensurepip into Nuitka.
    _exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    _user_base = os.path.join(_exe_dir, ".user_site")
    os.environ.setdefault("PYTHONUSERBASE", _user_base)
    try:
        os.makedirs(_user_base, exist_ok=True)
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
parser.add_argument('--runtime-import-smoke', action='store_true',
                    help='Run packaged-runtime import checks and exit')
parser.add_argument('--mumu-runtime-probe', action='store_true',
                    help='Run MuMu runtime acceptance probe and exit')
parser.add_argument('--probe-out', default='', help='Write smoke/probe JSON report to this path')
parser.add_argument('--mumu-probe-require-app', action='store_true',
                    help='Require the configured app package during the MuMu probe')
parser.add_argument('--mumu-probe-start', action='store_true',
                    help='Create a live device session during the MuMu probe')
parser.add_argument('--mumu-probe-power-cycle', action='store_true',
                    help='Shut down MuMu first, then prove AutoScriptor can start it')
parser.add_argument('--mumu-probe-screenshot', action='store_true',
                    help='Capture a NemuIpc screenshot during the MuMu probe')
parser.add_argument('--mumu-probe-shutdown-after', action='store_true',
                    help='Shut down MuMu after the MuMu probe')
parser.add_argument('--mumu-probe-timeout', type=int, default=120,
                    help='Timeout budget in seconds for MuMu probe shutdown/start operations')
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


def _write_probe_report(report: dict, out_path: str = "") -> None:
    text = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    if out_path:
        parent = os.path.dirname(os.path.abspath(out_path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(text)
            f.write("\n")
    print(text, flush=True)


def _run_runtime_import_smoke(out_path: str = "") -> bool:
    """Import runtime modules that commonly differ between dev and packaged builds."""
    import importlib
    import time
    import traceback

    modules = [
        "AutoScriptor",
        "AutoScriptor.core.api",
        "AutoScriptor.core.control",
        "AutoScriptor.control.MumuAdaptor.mumu",
        "AutoScriptor.control.MumuAdaptor.device_facade",
        "AutoScriptor.control.NemuIpc.device.method.nemu_ipc",
        "AutoScriptor.control.NemuIpc.device.method.pool",
        "AutoScriptor.control.NemuIpc.device.method.utils",
        "AutoScriptor.recognition.digit_rec",
        "AutoScriptor.utils.box_grid",
        "services.core.runtime_context",
        "services.webui.server",
        "services.webui.routes.editor",
        "services.webui.routes.canvas",
    ]
    report = {
        "mode": "runtime-import-smoke",
        "time": time.time(),
        "compiled": _COMPILED,
        "executable": sys.executable,
        "checks": [],
        "errors": [],
    }
    for name in modules:
        t0 = time.perf_counter()
        try:
            module = importlib.import_module(name)
            report["checks"].append({
                "module": name,
                "ok": True,
                "file": getattr(module, "__file__", ""),
                "elapsed_ms": int((time.perf_counter() - t0) * 1000),
            })
        except Exception as exc:
            report["checks"].append({
                "module": name,
                "ok": False,
                "error": str(exc),
                "traceback": traceback.format_exc(),
                "elapsed_ms": int((time.perf_counter() - t0) * 1000),
            })
            report["errors"].append(f"{name}: {exc}")

    try:
        from AutoScriptor.core.control import MixControl
        from AutoScriptor.core.api import ensure_app_running, extract_info
        from AutoScriptor.core.targets import B
        from AutoScriptor.utils.box_grid import indexof, make_box_grid
        from services.webui.routes import editor as editor_routes

        imported_grid = editor_routes._editor_safe_import(
            "AutoScriptor.utils.box_grid",
            fromlist=("make_box_grid", "indexof"),
        )
        grid_validation = editor_routes._validate_editor_snippet(
            "counts = extract_info("
            "make_box_grid(B(1, 2, 3, 4), B(1, 2, 30, 40), row=2, col=3), "
            "digital=True)"
        )

        report["symbol_checks"] = {
            "MixControl": MixControl.__name__,
            "ensure_app_running": ensure_app_running.__name__,
            "extract_info": extract_info.__name__,
            "B": B.__name__,
            "make_box_grid": make_box_grid.__name__,
            "indexof": indexof.__name__,
            "editor_safe_import_box_grid": getattr(imported_grid, "__name__", ""),
            "editor_grid_extract_validation": grid_validation,
        }
    except Exception as exc:
        report["errors"].append(f"symbol check failed: {exc}")
        report["symbol_checks"] = {"error": str(exc), "traceback": traceback.format_exc()}

    report["ok"] = not report["errors"]
    _write_probe_report(report, out_path)
    return bool(report["ok"])


def _run_step(report: dict, name: str, fn, *, required: bool = True):
    import time
    import traceback

    t0 = time.perf_counter()
    try:
        result = fn()
        report["checks"][name] = {
            "ok": True,
            "elapsed_ms": int((time.perf_counter() - t0) * 1000),
            "result": result,
        }
        return result
    except Exception as exc:
        report["checks"][name] = {
            "ok": False,
            "elapsed_ms": int((time.perf_counter() - t0) * 1000),
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
        if required:
            report["errors"].append(f"{name}: {exc}")
        return None


def _run_mumu_runtime_probe(probe_args) -> bool:
    """Exercise the real configured MuMu path from inside the packaged engine."""
    import time

    report = {
        "mode": "mumu-runtime-probe",
        "time": time.time(),
        "compiled": _COMPILED,
        "executable": sys.executable,
        "data_dir": os.environ.get("AUTOSCRIPTOR_DATA_DIR", ""),
        "require_app": bool(probe_args.mumu_probe_require_app),
        "checks": {},
        "errors": [],
    }
    state = {"mixctrl": None, "mumu": None}

    try:
        from AutoScriptor.utils.app_config import cfg

        report["config"] = {
            "config_path": getattr(cfg, "CONFIG_PATH", ""),
            "emulator": {
                "index": cfg["emulator"].get("index"),
                "adb_addr": cfg["emulator"].get("adb_addr"),
                "mumu_folder": cfg["emulator"].get("mumu_folder"),
                "emu_path": cfg["emulator"].get("emu_path"),
                "adb_path": cfg["emulator"].get("adb_path"),
            },
            "app_to_start": cfg["app"].get("app_to_start"),
        }

        def diagnostics(include_screenshot=False):
            from AutoScriptor.control.MumuAdaptor.device_facade import get_device_facade

            data = get_device_facade().diagnostics(
                include_screenshot=include_screenshot,
                require_app=bool(probe_args.mumu_probe_require_app),
            )
            status = (data.get("overall") or {}).get("status")
            if status == "error":
                raise RuntimeError((data.get("overall") or {}).get("message") or "diagnostics failed")
            return data

        _run_step(report, "diagnostics_before", lambda: diagnostics(False), required=False)

        def shutdown_before():
            from AutoScriptor.control.MumuAdaptor.mumu import Mumu

            mumu = Mumu().select(cfg["emulator"]["index"])
            running = bool(mumu.power.is_running())
            ok = True
            if running:
                ok = bool(mumu.power.shutdown(wait=True, timeout=min(90, probe_args.mumu_probe_timeout)))
            if not ok:
                raise RuntimeError("MuMu shutdown did not complete")
            return {"was_running": running, "shutdown_ok": ok}

        if probe_args.mumu_probe_power_cycle:
            _run_step(report, "shutdown_before_start", shutdown_before)

        def ensure_runtime():
            from AutoScriptor.core.api import ensure_app_running

            mixctrl, mumu = ensure_app_running(
                cfg["emulator"]["index"],
                cfg["emulator"]["adb_addr"],
                cfg["app"]["app_to_start"],
                start_emulator=True,
                launch_app=bool(probe_args.mumu_probe_require_app),
            )
            state["mixctrl"] = mixctrl
            state["mumu"] = mumu
            return {
                "mixctrl_class": mixctrl.__class__.__name__,
                "mumu_class": mumu.__class__.__name__,
                "launch_app": bool(probe_args.mumu_probe_require_app),
            }

        if (
            probe_args.mumu_probe_start
            or probe_args.mumu_probe_power_cycle
            or probe_args.mumu_probe_screenshot
        ):
            _run_step(report, "ensure_device_session", ensure_runtime)

        def screenshot():
            mixctrl = state.get("mixctrl")
            if mixctrl is None:
                ensure_runtime()
                mixctrl = state["mixctrl"]
            image = mixctrl.screenshot()
            shape = tuple(int(v) for v in getattr(image, "shape", ())[:3])
            if len(shape) < 2 or shape[0] <= 0 or shape[1] <= 0:
                raise RuntimeError(f"invalid screenshot shape: {shape}")
            return {"shape": shape}

        if probe_args.mumu_probe_screenshot:
            _run_step(report, "nemu_screenshot", screenshot)

        _run_step(
            report,
            "diagnostics_after",
            lambda: diagnostics(bool(probe_args.mumu_probe_screenshot)),
            required=(
                probe_args.mumu_probe_start
                or probe_args.mumu_probe_power_cycle
                or probe_args.mumu_probe_screenshot
            ),
        )

        def shutdown_after():
            mumu = state.get("mumu")
            if mumu is None:
                from AutoScriptor.control.MumuAdaptor.mumu import Mumu

                mumu = Mumu().select(cfg["emulator"]["index"])
            ok = bool(mumu.power.shutdown(wait=True, timeout=min(90, probe_args.mumu_probe_timeout)))
            if not ok:
                raise RuntimeError("MuMu shutdown did not complete")
            return {"shutdown_ok": ok}

        if probe_args.mumu_probe_shutdown_after:
            _run_step(report, "shutdown_after", shutdown_after)

    except Exception as exc:
        import traceback

        report["errors"].append(str(exc))
        report["fatal_traceback"] = traceback.format_exc()

    report["ok"] = not report["errors"]
    _write_probe_report(report, probe_args.probe_out)
    return bool(report["ok"])


if __name__ == '__main__':
    if args.runtime_import_smoke:
        sys.exit(0 if _run_runtime_import_smoke(args.probe_out) else 1)
    if args.mumu_runtime_probe:
        sys.exit(0 if _run_mumu_runtime_probe(args) else 1)

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
