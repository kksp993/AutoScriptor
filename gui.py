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

import os
import time

_BOOT_T0 = time.perf_counter()


def _boot_log(message: str) -> None:
    if "--electron" not in sys.argv and not os.environ.get("AUTOSCRIPTOR_ELECTRON_PIPE"):
        return
    elapsed = time.perf_counter() - _BOOT_T0
    print(f"[启动] {message}（Python {elapsed:.1f}s）", flush=True)


_boot_log("Python 进程已启动，正在初始化运行时")


def _windows_current_executable_path() -> str:
    if os.name != "nt":
        return ""
    try:
        import ctypes

        buffer = ctypes.create_unicode_buffer(32768)
        length = ctypes.windll.kernel32.GetModuleFileNameW(None, buffer, len(buffer))
        if length:
            return buffer.value
    except Exception:
        return ""
    return ""


def _configure_packaged_multiprocessing_spawn() -> None:
    if not _COMPILED or os.name != "nt":
        return
    try:
        setattr(sys, "frozen", True)
    except Exception:
        pass

    executable = _windows_current_executable_path()
    if executable and executable.lower().endswith(".exe"):
        sys.executable = executable


try:
    from importlib.util import module_from_spec as _PACKAGED_STDLIB_MODULE_FROM_SPEC
    from importlib.util import spec_from_file_location as _PACKAGED_STDLIB_SPEC_FROM_FILE_LOCATION
except Exception:
    _PACKAGED_STDLIB_MODULE_FROM_SPEC = None
    _PACKAGED_STDLIB_SPEC_FROM_FILE_LOCATION = None

try:
    import _frozen_importlib as _PACKAGED_STDLIB_BOOTSTRAP
    import _frozen_importlib_external as _PACKAGED_STDLIB_BOOTSTRAP_EXTERNAL

    _PACKAGED_STDLIB_MODULE_SPEC = getattr(_PACKAGED_STDLIB_BOOTSTRAP, "ModuleSpec", None)
    _PACKAGED_STDLIB_SOURCE_FILE_LOADER = getattr(
        _PACKAGED_STDLIB_BOOTSTRAP_EXTERNAL,
        "SourceFileLoader",
        None,
    )
except Exception:
    _PACKAGED_STDLIB_MODULE_SPEC = None
    _PACKAGED_STDLIB_SOURCE_FILE_LOADER = None

# Nuitka 编译后 sys.path 由编译器自动管理，无需手动插入；
# 开发模式下仍需将项目根加入 sys.path 以支持 import AutoScriptor / ZmxyOL
_COMPILED = "__compiled__" in dir()
if _COMPILED:
    _configure_packaged_multiprocessing_spawn()
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


def _packaged_stdlib_module_from_source_loader(
    name: str,
    path: str,
    *,
    package_dir: str | None = None,
):
    """Build a module with frozen importlib loader primitives."""
    if _PACKAGED_STDLIB_SOURCE_FILE_LOADER is None:
        return None
    try:
        loader = _PACKAGED_STDLIB_SOURCE_FILE_LOADER(name, path)
    except Exception:
        return None

    spec = None
    if _PACKAGED_STDLIB_MODULE_SPEC is not None:
        try:
            spec = _PACKAGED_STDLIB_MODULE_SPEC(
                name,
                loader,
                origin=path,
                is_package=package_dir is not None,
            )
        except TypeError:
            try:
                spec = _PACKAGED_STDLIB_MODULE_SPEC(name, loader)
            except Exception:
                spec = None
        except Exception:
            spec = None
        if spec is not None and package_dir is not None:
            try:
                spec.submodule_search_locations = [package_dir]
            except Exception:
                pass

    module = type(sys)(name)
    module.__loader__ = loader
    module.__file__ = path
    module.__package__ = name if package_dir is not None else name.rpartition(".")[0]
    if spec is not None:
        module.__spec__ = spec
    if package_dir is not None:
        module.__path__ = [package_dir]
    return module, loader


_PACKAGED_IMPORTLIB_METADATA_HELPERS = (
    "_functools",
    "_text",
    "_adapters",
    "_collections",
    "_itertools",
    "_meta",
)


def _preload_packaged_importlib_metadata_helpers(name: str, package_dir: str | None) -> None:
    if name != "importlib.metadata" or package_dir is None:
        return
    for helper in _PACKAGED_IMPORTLIB_METADATA_HELPERS:
        submodule_name = f"{name}.{helper}"
        existing = sys.modules.get(submodule_name)
        has_location = bool(getattr(existing, "__file__", None)) if existing is not None else False
        if has_location:
            continue
        sys.modules.pop(submodule_name, None)
        path = os.path.join(package_dir, f"{helper}.py")
        loaded = _load_packaged_stdlib_module(submodule_name, path)
        if not loaded:
            loaded = _load_packaged_stdlib_module(submodule_name, path + "c")
        if not loaded:
            raise ImportError(f"cannot preload {submodule_name}")


def _load_packaged_stdlib_module(
    name: str,
    path: str,
    *,
    package_dir: str | None = None,
    prefer_source_loader: bool = False,
) -> bool:
    """Load a copied CPython stdlib module before a Nuitka namespace shell wins."""
    if not os.path.isfile(path):
        return False
    module = None
    loader = None
    if prefer_source_loader:
        fallback = _packaged_stdlib_module_from_source_loader(name, path, package_dir=package_dir)
        if fallback is not None:
            module, loader = fallback
    if _PACKAGED_STDLIB_MODULE_FROM_SPEC is not None and _PACKAGED_STDLIB_SPEC_FROM_FILE_LOCATION is not None:
        if module is None or loader is None:
            try:
                spec = _PACKAGED_STDLIB_SPEC_FROM_FILE_LOCATION(
                    name,
                    path,
                    submodule_search_locations=([package_dir] if package_dir is not None else None),
                )
                if spec is not None and spec.loader is not None:
                    module = _PACKAGED_STDLIB_MODULE_FROM_SPEC(spec)
                    loader = spec.loader
            except Exception:
                module = None
                loader = None
    if module is None or loader is None:
        fallback = _packaged_stdlib_module_from_source_loader(name, path, package_dir=package_dir)
        if fallback is None:
            return False
        module, loader = fallback
    sys.modules[name] = module
    parent_name, _, child_name = name.rpartition(".")
    parent = sys.modules.get(parent_name) if parent_name else None
    if parent is not None:
        try:
            setattr(parent, child_name, module)
        except Exception:
            pass
    try:
        _preload_packaged_importlib_metadata_helpers(name, package_dir)
        loader.exec_module(module)
    except Exception:
        sys.modules.pop(name, None)
        if package_dir is not None:
            for mod_name in [key for key in sys.modules if key.startswith(name + ".")]:
                sys.modules.pop(mod_name, None)
        if parent is not None and getattr(parent, child_name, None) is module:
            try:
                delattr(parent, child_name)
            except Exception:
                pass
        raise
    return True


def _prepend_package_search_path(module, package_dir: str) -> None:
    paths = list(getattr(module, "__path__", []) or [])
    if package_dir not in paths:
        try:
            module.__path__ = [package_dir, *paths]
        except Exception:
            pass
    spec = getattr(module, "__spec__", None)
    if spec is None:
        return
    try:
        locations = getattr(spec, "submodule_search_locations", None)
        if locations is None:
            spec.submodule_search_locations = [package_dir]
        else:
            spec_paths = list(locations)
            if package_dir not in spec_paths:
                spec.submodule_search_locations = [package_dir, *spec_paths]
    except Exception:
        pass


def _drop_module_tree(name: str) -> None:
    for mod_name in [key for key in sys.modules if key == name or key.startswith(name + ".")]:
        sys.modules.pop(mod_name, None)


def _drop_broken_package_shell(name: str) -> None:
    """Remove a Nuitka namespace shell when copied stdlib source should load."""
    module = sys.modules.get(name)
    if module is None:
        return
    has_location = bool(getattr(module, "__file__", None) or getattr(module, "__path__", None))
    if has_location:
        return
    _drop_module_tree(name)


def _create_packaged_package_shell(name: str, package_dir: str, init_path: str):
    """Create a package object without executing its copied __init__.py."""
    fallback = _packaged_stdlib_module_from_source_loader(name, init_path, package_dir=package_dir)
    if fallback is not None:
        module, _loader = fallback
    else:
        module = type(sys)(name)
        module.__file__ = init_path
        module.__package__ = name
        module.__path__ = [package_dir]
    sys.modules[name] = module
    parent_name, _, child_name = name.rpartition(".")
    parent = sys.modules.get(parent_name) if parent_name else None
    if parent is not None:
        try:
            setattr(parent, child_name, module)
        except Exception:
            pass
    _prepend_package_search_path(module, package_dir)
    return module


def _export_multiprocessing_context_api(package, context_module) -> None:
    default_context = getattr(context_module, "_default_context", None)
    if default_context is None:
        raise ImportError("multiprocessing.context has no _default_context")
    exported = [name for name in dir(default_context) if not name.startswith("_")]
    package.__all__ = exported
    for name in exported:
        setattr(package, name, getattr(default_context, name))
    package.SUBDEBUG = 5
    package.SUBWARNING = 25
    if "__main__" in sys.modules:
        sys.modules["__mp_main__"] = sys.modules["__main__"]


def _load_packaged_multiprocessing_child(package_dir: str, child: str) -> bool:
    module_name = f"multiprocessing.{child}"
    source_path = os.path.join(package_dir, f"{child}.py")
    bytecode_path = source_path + "c"
    return _load_packaged_stdlib_module(
        module_name,
        source_path,
        prefer_source_loader=True,
    ) or _load_packaged_stdlib_module(
        module_name,
        bytecode_path,
        prefer_source_loader=True,
    )


def _bootstrap_packaged_multiprocessing(exe_dir: str) -> None:
    package_dir = os.path.join(exe_dir, "multiprocessing")
    if not os.path.isdir(package_dir):
        return
    existing = sys.modules.get("multiprocessing")
    if existing is not None and getattr(existing, "__file__", None) and hasattr(existing, "Manager"):
        return
    _drop_module_tree("multiprocessing")
    parent = _create_packaged_package_shell(
        "multiprocessing",
        package_dir,
        os.path.join(package_dir, "__init__.py"),
    )
    if not _load_packaged_multiprocessing_child(package_dir, "process"):
        raise ImportError("cannot preload multiprocessing.process")
    if not _load_packaged_multiprocessing_child(package_dir, "util"):
        raise ImportError("cannot preload multiprocessing.util")
    if not _load_packaged_multiprocessing_child(package_dir, "context"):
        raise ImportError("cannot preload multiprocessing.context")
    context_module = sys.modules.get("multiprocessing.context")
    if context_module is None:
        raise ImportError("multiprocessing.context was not registered")
    try:
        setattr(parent, "context", context_module)
    except Exception:
        pass
    _export_multiprocessing_context_api(parent, context_module)
    if not _load_packaged_multiprocessing_child(package_dir, "reduction"):
        raise ImportError("cannot preload multiprocessing.reduction")
    if not _load_packaged_multiprocessing_child(package_dir, "connection"):
        raise ImportError("cannot preload multiprocessing.connection")
    if not _load_packaged_multiprocessing_child(package_dir, "synchronize"):
        raise ImportError("cannot preload multiprocessing.synchronize")
    if not _load_packaged_multiprocessing_child(package_dir, "spawn"):
        raise ImportError("cannot preload multiprocessing.spawn")
    if not _load_packaged_multiprocessing_child(package_dir, "popen_spawn_win32"):
        raise ImportError("cannot preload multiprocessing.popen_spawn_win32")


def _bootstrap_packaged_encodings(exe_dir: str) -> None:
    package_dir = os.path.join(exe_dir, "encodings")
    if not os.path.isdir(package_dir):
        return
    parent = sys.modules.get("encodings")
    if parent is not None:
        _prepend_package_search_path(parent, package_dir)
    else:
        _load_packaged_stdlib_module(
            "encodings",
            os.path.join(package_dir, "__init__.py"),
            package_dir=package_dir,
        ) or _load_packaged_stdlib_module(
            "encodings",
            os.path.join(package_dir, "__init__.pyc"),
            package_dir=package_dir,
        )
    idna_path = os.path.join(package_dir, "idna.py")
    existing = sys.modules.get("encodings.idna")
    existing_file = getattr(existing, "__file__", "") if existing is not None else ""
    if existing_file and os.path.abspath(existing_file).startswith(os.path.abspath(package_dir)):
        return
    sys.modules.pop("encodings.idna", None)
    _load_packaged_stdlib_module("encodings.idna", idna_path) or _load_packaged_stdlib_module(
        "encodings.idna",
        idna_path + "c",
    )


def _patch_packaged_typing_protocol_allowlist() -> None:
    try:
        import typing
    except Exception:
        return
    allowlist = getattr(typing, "_PROTO_ALLOWLIST", None)
    if not isinstance(allowlist, dict):
        return
    names = (
        "Awaitable",
        "AsyncIterator",
        "AsyncIterable",
        "Coroutine",
        "Generator",
        "Iterable",
        "Iterator",
        "Reversible",
        "Sized",
        "Container",
        "Collection",
        "Callable",
        "ContextManager",
        "AsyncContextManager",
        "Hashable",
    )
    for module_name in ("collections.abc", "_collections_abc"):
        existing = allowlist.get(module_name)
        if isinstance(existing, set):
            existing.update(names)
        elif isinstance(existing, list):
            for name in names:
                if name not in existing:
                    existing.append(name)
        elif isinstance(existing, tuple):
            allowlist[module_name] = tuple(dict.fromkeys([*existing, *names]))
        else:
            allowlist[module_name] = list(names)


def _bootstrap_packaged_importlib(exe_dir: str) -> None:
    package_dir = os.path.join(exe_dir, "importlib")
    if not os.path.isdir(package_dir):
        return
    parent = sys.modules.get("importlib")
    if parent is not None:
        _prepend_package_search_path(parent, package_dir)
    for submodule in (
        "importlib.abc",
        "importlib.resources",
        "importlib.readers",
        "importlib.metadata",
        "importlib._adapters",
        "importlib._common",
        "importlib.metadata._adapters",
        "importlib.metadata._collections",
        "importlib.metadata._functools",
        "importlib.metadata._itertools",
        "importlib.metadata._meta",
        "importlib.metadata._text",
    ):
        _drop_broken_package_shell(submodule)
    if "importlib._abc" not in sys.modules:
        _load_packaged_stdlib_module(
            "importlib._abc",
            os.path.join(package_dir, "_abc.py"),
        ) or _load_packaged_stdlib_module(
            "importlib._abc",
            os.path.join(package_dir, "_abc.pyc"),
        )
    for name, rel_path, package_path in (
        ("importlib.abc", "abc.py", None),
        ("importlib._adapters", "_adapters.py", None),
        ("importlib._common", "_common.py", None),
        ("importlib.readers", "readers.py", None),
        ("importlib.resources", "resources.py", None),
        ("importlib.metadata", os.path.join("metadata", "__init__.py"), os.path.join(package_dir, "metadata")),
    ):
        if name in sys.modules:
            continue
        _load_packaged_stdlib_module(
            name,
            os.path.join(package_dir, rel_path),
            package_dir=package_path,
        ) or _load_packaged_stdlib_module(
            name,
            os.path.join(package_dir, rel_path + "c"),
            package_dir=package_path,
        )


def _bootstrap_packaged_stdlib() -> None:
    if not _COMPILED:
        return
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    try:
        _bootstrap_packaged_importlib(exe_dir)
    except Exception as exc:
        print(f"[bootstrap] packaged stdlib importlib repair failed: {exc}", file=sys.stderr)
    try:
        _bootstrap_packaged_encodings(exe_dir)
    except Exception as exc:
        print(f"[bootstrap] packaged stdlib encodings repair failed: {exc}", file=sys.stderr)
    try:
        _bootstrap_packaged_multiprocessing(exe_dir)
    except Exception as exc:
        print(f"[bootstrap] packaged stdlib multiprocessing repair failed: {exc}", file=sys.stderr)
    try:
        collections_mod = sys.modules.get("collections")
        if collections_mod is not None and hasattr(collections_mod, "deque"):
            _patch_packaged_typing_protocol_allowlist()
            return
        sys.modules.pop("collections", None)
        abc_loaded = _load_packaged_stdlib_module(
            "_collections_abc",
            os.path.join(exe_dir, "_collections_abc.py"),
        ) or _load_packaged_stdlib_module(
            "_collections_abc",
            os.path.join(exe_dir, "_collections_abc.pyc"),
        )
        package_dir = os.path.join(exe_dir, "collections")
        loaded = _load_packaged_stdlib_module(
            "collections",
            os.path.join(package_dir, "__init__.py"),
            package_dir=package_dir,
        ) or _load_packaged_stdlib_module(
            "collections",
            os.path.join(package_dir, "__init__.pyc"),
            package_dir=package_dir,
        )
        if loaded and abc_loaded:
            collections_mod = sys.modules.get("collections")
            if collections_mod is not None and hasattr(collections_mod, "deque"):
                _patch_packaged_typing_protocol_allowlist()
                return
    except Exception as exc:
        print(f"[bootstrap] packaged stdlib collections repair failed: {exc}", file=sys.stderr)
    _patch_packaged_typing_protocol_allowlist()


_boot_log("正在检查打包运行时兼容层")
_bootstrap_packaged_stdlib()
_boot_log("运行时兼容层检查完成")

import argparse
import json

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

    _boot_log("正在导入 WebUI 服务模块")
    from services.webui.server import run_webui
    _boot_log("WebUI 服务模块导入完成，正在启动 HTTP 服务")
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
        from collections import defaultdict, deque
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
            "collections_deque": deque.__name__,
            "collections_defaultdict": defaultdict.__name__,
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


def main() -> int:
    _boot_log("正在解析启动参数")
    if args.runtime_import_smoke:
        return 0 if _run_runtime_import_smoke(args.probe_out) else 1
    if args.mumu_runtime_probe:
        return 0 if _run_mumu_runtime_probe(args) else 1

    _boot_log("正在初始化多进程运行环境")
    import multiprocessing
    import signal

    _configure_packaged_multiprocessing_spawn()
    try:
        multiprocessing.set_executable(sys.executable)
    except Exception:
        pass
    multiprocessing.freeze_support()

    _boot_log("正在检查单实例锁")
    from services.single_instance import ensure_single_instance

    ensure_single_instance()

    if args.electron:
        os.environ['UVICORN_LOG_LEVEL'] = 'info'
        os.environ['AUTOSCRIPTOR_ELECTRON'] = '1'

    _boot_log("正在准备 WebUI worker")
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
        _boot_log("正在创建 WebUI 子进程")
        process.start()
        _boot_log(f"WebUI 子进程已启动 pid={process.pid}")
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
    return 0


if __name__ == '__main__':
    sys.exit(main())
