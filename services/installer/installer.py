import sys
import os
import subprocess
from pathlib import Path
import json

_THIS_FILE = Path(__file__).resolve()
_PROJECT_ROOT = _THIS_FILE.parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Deferred import - run_target will be imported when needed
def _import_run_target():
    from entry import run_target
    return run_target
try:
    import questionary  # type: ignore
except Exception:
    questionary = None  # type: ignore
from typing import Any
try:
    import questionary  # type: ignore
except Exception:
    questionary = None  # type: ignore

# 运行环境下既支持包内相对导入，也尽量兼容以脚本方式直接运行
try:
    from .git_service import GitService  # type: ignore
    from .env_config import EnvConfig  # type: ignore
except Exception:
    try:
        from services.installer.git_service import GitService  # type: ignore
        from services.installer.env_config import EnvConfig  # type: ignore
    except Exception:
        GitService = None  # type: ignore
        EnvConfig = None  # type: ignore

try:
    import winreg  # type: ignore
except Exception:
    winreg = None  # 非 Windows 环境兼容

COMMON_MUMU_PORTS =[
    16384,16416,16448,16480,16512,16544,16576,16608
]


def _path_ok_for_emulator_key(key: str, val: str) -> bool:
    """与 Electron installer 路径校验一致：目录/可执行文件须真实存在且类型正确。"""
    try:
        s = (val or "").strip()
        if not s:
            return False
        p = Path(s)
        if not p.exists():
            return False
        if key == "mumu_folder":
            return p.is_dir()
        if key in ("emu_path", "adb_path"):
            return p.is_file()
        return True
    except OSError:
        return False


def _emulator_paths_need_detect(emulator: dict) -> bool:
    for key in ("mumu_folder", "emu_path", "adb_path"):
        val = str(emulator.get(key, "")).strip()
        if not val or val.startswith("YOUR_"):
            return True
        if not _path_ok_for_emulator_key(key, val):
            return True
    return False


def _detect_security_software() -> list[str]:
    """Detect running security software that may slow down venv file operations."""
    known = {
        "360tray.exe": "360\u5b89\u5168\u536b\u58eb",
        "360safe.exe": "360\u5b89\u5168\u536b\u58eb",
        "360sd.exe": "360\u6740\u6bd2",
        "zhudongfangyu.exe": "360\u4e3b\u52a8\u9632\u5fa1",
        "hipstray.exe": "\u706b\u7ed2\u5b89\u5168",
        "wsctrlsvc.exe": "\u706b\u7ed2\u5b89\u5168",
        "qqpctray.exe": "\u817e\u8baf\u7535\u8111\u7ba1\u5bb6",
        "kxetray.exe": "\u91d1\u5c71\u6bd2\u9738",
        "avp.exe": "\u5361\u5df4\u65af\u57fa",
    }
    found: list[str] = []
    try:
        out = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=10,
        )
        for line in out.stdout.splitlines():
            if not line.strip():
                continue
            name = line.split(",")[0].strip('"').lower()
            if name in known and known[name] not in found:
                found.append(known[name])
    except Exception:
        pass
    return found


def _try_add_defender_exclusion(target_path: str) -> bool:
    """Best-effort: add Windows Defender real-time scan exclusion."""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f'Add-MpPreference -ExclusionPath "{target_path}" -ErrorAction SilentlyContinue'],
            capture_output=True, text=True, timeout=15,
        )
        return r.returncode == 0
    except Exception:
        return False


def _prompt_text(message: str, default: str | None = None) -> str | None:
    """Prompt helper tolerant to missing questionary or non-interactive sessions."""
    try:
        if questionary is not None:
            ans = questionary.text(message, default=(default or "")).ask()  # type: ignore[attr-defined]
            if isinstance(ans, str) and ans.strip():
                return ans
    except Exception:
        pass
    return default


def find_project_root(start: Path) -> Path:
    """Locate project root by looking for requirements.txt at or above start."""
    cur = start.resolve()
    for p in [cur, *cur.parents]:
        if (p / "requirements.txt").exists() and (p / "services").exists():
            return p
    # Fallback: two levels up from this file (AutoScriptor/installer → repo root)
    return start.resolve().parents[2]


def get_venv_python(project_root: Path) -> Path:
    return project_root / ".venv" / "Scripts" / "python.exe"


def _fresh_install_requested(argv: list[str]) -> bool:
    ev = os.environ.get("AUTOSCRIPTOR_FRESH_INSTALL", "").strip().lower()
    if ev in ("1", "true", "yes", "on"):
        return True
    for a in argv[1:]:
        if a.strip().lower() in ("--fresh-install", "--fresh"):
            return True
    return False


def _apply_fresh_install_prep(project_root: Path) -> None:
    """清除依赖完成标记与 wheelhouse 中的 Python 安装包缓存，便于重新下载。"""
    stamp = project_root / ".venv" / ".deps_installed.stamp"
    stamp.unlink(missing_ok=True)
    py_cache = project_root / "wheelhouse" / "python"
    if py_cache.is_dir():
        for p in py_cache.glob("*.exe"):
            try:
                p.unlink()
            except OSError:
                pass


def _pip_cache_purge(venv_python: Path) -> None:
    try:
        subprocess.run(
            [str(venv_python), "-m", "pip", "cache", "purge"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except Exception:
        pass


def ensure_venv(project_root: Path) -> Path:
    """Create .venv if missing. Returns venv python path."""
    venv_python = get_venv_python(project_root)
    if venv_python.exists():
        return venv_python
    # Create venv using the current interpreter
    subprocess.check_call([sys.executable, "-m", "venv", str(project_root / ".venv")])
    return venv_python


def reinstall_pip_and_install(project_root: Path, extra_index: str | None = None, fresh: bool = False) -> None:
    venv_python = get_venv_python(project_root)
    # 若已安装依赖的标记文件存在，则跳过重复安装以缩短启动时间
    stamp = project_root / ".venv" / ".deps_installed.stamp"
    if stamp.exists():
        return

    # Check if pip is available, if not install it using portable get-pip.py
    pip_available = False
    try:
        subprocess.check_call([str(venv_python), "-c", "import pip"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        pip_available = True
    except subprocess.CalledProcessError:
        # Pip not available, install using get-pip.py
        get_pip_script = project_root / "services" / "installer" / "get-pip.py"
        if get_pip_script.exists():
            print("Installing pip using portable get-pip.py...")
            subprocess.check_call([str(venv_python), str(get_pip_script)])

    # Upgrade pip first (use python -m pip to avoid self-modify issues)
    if fresh:
        up = [str(venv_python), "-m", "pip", "install", "--no-cache-dir", "--upgrade", "pip", "setuptools", "wheel"]
    else:
        up = [str(venv_python), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"]
    subprocess.check_call(up)
    # 标准在线安装；不再优先 wheelhouse
    req = project_root / "requirements.txt"
    args = [str(venv_python), "-m", "pip", "install"]
    if fresh:
        args += ["--no-cache-dir", "--upgrade", "--force-reinstall"]
    args += ["-r", str(req)]
    if extra_index:
        args += ["-i", extra_index]
    subprocess.check_call(args)
    try:
        stamp.write_text("ok", encoding="utf-8")
    except Exception:
        pass


def _read_registry_mu_mu_paths() -> list[Path]:
    paths: list[Path] = []
    if winreg is None:
        return paths
    uninstall_roots = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    keywords = ["MuMu", "MuMu Player", "网易 MuMu"]
    for root, sub in uninstall_roots:
        try:
            with winreg.OpenKey(root, sub) as h:  # type: ignore[attr-defined]
                for i in range(0, 4096):
                    try:
                        name = winreg.EnumKey(h, i)
                        with winreg.OpenKey(h, name) as appkey:
                            display_name = ""
                            install_loc = ""
                            try:
                                display_name, _ = winreg.QueryValueEx(appkey, "DisplayName")
                            except Exception:
                                pass
                            try:
                                install_loc, _ = winreg.QueryValueEx(appkey, "InstallLocation")
                            except Exception:
                                pass
                            text = f"{display_name} {install_loc}".lower()
                            if any(k.lower() in text for k in keywords):
                                if install_loc and os.path.isdir(install_loc):
                                    paths.append(Path(install_loc))
                    except OSError:
                        break
        except Exception:
            continue
    return paths


_SKIP_ROOT_DIRS = frozenset({
    "$recycle.bin", "system volume information", "windows", "recovery",
    "perflogs", "$winreagent", "$sysreset", "config.msi",
    "documents and settings", "msocache",
})


def _search_common_mu_mu_paths() -> list[Path]:
    candidates: list[Path] = []
    seen: set[str] = set()

    pf = os.environ.get("ProgramFiles", r"C:\\Program Files")
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\\Program Files (x86)")

    common_names = [
        "Netease\\MuMu",
        "Netease\\MuMu Player 12",
        "MuMu",
        "MuMu Player 12",
        "Netease\\MuMu Player",
        "Netease\\MuMuPlayer",
    ]

    base_dirs: list[Path] = [Path(pf), Path(pf86)]

    for code in range(ord('A'), ord('Z') + 1):
        root = f"{chr(code)}:\\"
        if not os.path.exists(root):
            continue
        root_path = Path(root)
        base_dirs.append(root_path)
        base_dirs.append(root_path / "Program Files")
        base_dirs.append(root_path / "Program Files (x86)")
        # 枚举盘符下的一级子目录，覆盖 X:\任意目录\Netease\MuMu 这类非标路径
        try:
            for entry in os.scandir(root):
                if not entry.is_dir():
                    continue
                if entry.name.lower() in _SKIP_ROOT_DIRS:
                    continue
                base_dirs.append(root_path / entry.name)
        except OSError:
            pass

    for base_dir in base_dirs:
        for name in common_names:
            p = base_dir / name
            try:
                if p.exists():
                    norm_key = os.path.normcase(os.path.normpath(str(p)))
                    if norm_key not in seen:
                        candidates.append(p)
                        seen.add(norm_key)
            except Exception:
                continue

    return candidates


def _derive_paths_from_mumu_folder(folder: Path) -> dict:
    # 兼容老版（nx_main）与 12 版（shell）
    nx_main = folder / "nx_main"
    shell = folder / "shell"
    emu_path = None
    adb_path = None
    if nx_main.exists():
        ep = nx_main / "MuMuManager.exe"
        ap = nx_main / "adb.exe"
        if ep.is_file():
            emu_path = ep
        if ap.is_file():
            adb_path = ap
    if (emu_path is None or adb_path is None) and shell.exists():
        ep = shell / "MuMuPlayer.exe"
        ap = shell / "adb.exe"
        if emu_path is None and ep.is_file():
            emu_path = ep
        if adb_path is None and ap.is_file():
            adb_path = ap
    return {
        "mumu_folder": str(folder),
        "emu_path": str(emu_path) if emu_path else "",
        "adb_path": str(adb_path) if adb_path else "",
    }


def _format_subprocess_exit_code(code: int | None) -> str:
    """将 Windows 上常见的无符号退出码（如 4294967295）显示为有符号整数，便于理解。"""
    if code is None:
        return "?"
    c = int(code)
    if c > 0x7FFFFFFF:
        c -= 0x100000000
    return str(c)


def _parse_mumu_manager_version_stdout(text: str) -> str:
    """解析 MuMuManager version 子命令输出的 JSON。"""
    if not (text or "").strip():
        return ""
    try:
        data = json.loads(text.strip())
        if isinstance(data, dict) and data.get("version"):
            return str(data["version"])
    except Exception:
        pass
    return ""


def _adb_detect_serial(adb_path: str) -> str | None:
    try:
        # 启动 ADB 服务并读取设备
        subprocess.run([adb_path, "start-server"], capture_output=True, text=True, timeout=5)
        out = subprocess.run([adb_path, "devices"], capture_output=True, text=True, timeout=5)
        lines = (out.stdout or "").splitlines()
        # 过滤 header 行
        pairs = [ln.split("\t")[0] for ln in lines if "\tdevice" in ln]
        for serial in pairs:
            if serial.startswith("127.0.0.1:"):
                return serial
        return pairs[0] if pairs else None
    except Exception:
        return None


def _adb_device_rows(adb_path: str) -> list[tuple[str, str]]:
    try:
        subprocess.run([adb_path, "start-server"], capture_output=True, text=True, timeout=5)
        out = subprocess.run([adb_path, "devices"], capture_output=True, text=True, timeout=5)
        rows: list[tuple[str, str]] = []
        for line in (out.stdout or "").splitlines():
            line = line.strip()
            if not line or line.lower().startswith("list of devices"):
                continue
            parts = line.split()
            if len(parts) >= 2:
                rows.append((parts[0], parts[1]))
        return rows
    except Exception:
        return []


def _parse_mumu_info_payload(text: str) -> list[dict]:
    try:
        data = json.loads((text or "").strip() or "{}")
    except Exception:
        return []
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        if "index" in data:
            return [data]
        return [item for item in data.values() if isinstance(item, dict) and "index" in item]
    return []


def _mumu_info_rows(emu_path: str) -> list[dict]:
    p = str(emu_path or "").strip()
    if not p or not Path(p).is_file():
        return []
    try:
        r = subprocess.run(
            [p, "info", "-v", "all"],
            capture_output=True,
            text=True,
            timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if r.returncode == 0:
            return _parse_mumu_info_payload(r.stdout or "")
    except Exception:
        pass
    return []


def _normalize_serial_host(host: str) -> str:
    h = str(host or "").strip().lower()
    if not h or h in {"localhost", "::1"}:
        return "127.0.0.1"
    return h


def _split_adb_serial(serial: str) -> tuple[str, str] | None:
    s = str(serial or "").strip()
    if ":" not in s:
        return None
    host, port = s.rsplit(":", 1)
    if not host or not port.isdigit():
        return None
    return _normalize_serial_host(host), port


def _player_serial(player: dict) -> str:
    port = str(player.get("adb_port", "") or "").strip()
    if not port:
        return ""
    host = _normalize_serial_host(str(player.get("adb_host_ip", "127.0.0.1") or "127.0.0.1"))
    return f"{host}:{port}"


def _player_is_running(player: dict) -> bool:
    if player.get("is_process_started") is True or player.get("is_android_started") is True:
        return True
    state = str(player.get("player_state", "") or "").lower()
    return "start" in state or "running" in state


def _sort_players_for_selection(players: list[dict]) -> list[dict]:
    def key(player: dict):
        running = 0 if _player_is_running(player) else 1
        main = 0 if player.get("is_main") is True else 1
        try:
            index = int(player.get("index", 0))
        except Exception:
            index = 0
        return running, main, index

    return sorted(players, key=key)


def _find_player_by_serial(players: list[dict], serial: str) -> dict | None:
    target = _split_adb_serial(serial)
    if target is None:
        return None
    target_host, target_port = target
    for player in players:
        current = _split_adb_serial(_player_serial(player))
        if current is None:
            continue
        host, port = current
        if port != target_port:
            continue
        if host == target_host or host == "127.0.0.1" or target_host == "127.0.0.1":
            return player
    return None


def _coerce_player_index(player: dict | None):
    if not player or player.get("index") is None:
        return None
    try:
        return int(player.get("index"))
    except Exception:
        return str(player.get("index"))


def _reconnect_mumu_player_ports(adb_path: str, players: list[dict]) -> None:
    for player in _sort_players_for_selection(players):
        if not _player_is_running(player):
            continue
        serial = _player_serial(player)
        if serial:
            _adb_reconnect_serial(adb_path, serial)


def _choose_adb_device(adb_path: str, emu_path: str, preferred_serial: str, allow_fallback: bool = True) -> dict:
    players = _mumu_info_rows(emu_path)
    preferred = str(preferred_serial or "").strip()
    if preferred and not preferred.startswith("YOUR_") and not preferred.endswith(":0"):
        ok, detail = _adb_state(adb_path, preferred)
        if not ok and ":" in preferred:
            _adb_reconnect_serial(adb_path, preferred)
            ok, detail = _adb_state(adb_path, preferred)
        player = _find_player_by_serial(players, preferred)
        if ok:
            return {
                "connected": True,
                "serial": preferred,
                "detail": f"配置设备已连接 {preferred}",
                "fallback_serial": "",
                "player": player,
                "index": _coerce_player_index(player),
            }
        if not allow_fallback:
            usable = [(s, st) for s, st in _adb_device_rows(adb_path) if st == "device"]
            fallback = next(((s, st) for s, st in usable if s.startswith("127.0.0.1:")), usable[0] if usable else None)
            extra = f"；另检测到 {fallback[0]} 可用，但运行时会优先使用配置地址" if fallback else ""
            return {
                "connected": False,
                "serial": preferred,
                "detail": f"配置设备 {preferred} 未连接{extra}。{detail}".strip(),
                "fallback_serial": fallback[0] if fallback else "",
                "player": player,
                "index": _coerce_player_index(player),
            }

    _reconnect_mumu_player_ports(adb_path, players)
    rows = [(s, st) for s, st in _adb_device_rows(adb_path) if st == "device"]
    chosen: tuple[str, str] | None = None
    player: dict | None = None
    for candidate in _sort_players_for_selection(players):
        for row in rows:
            if _find_player_by_serial([candidate], row[0]):
                chosen = row
                player = candidate
                break
        if chosen:
            break
    if chosen is None:
        chosen = next(((s, st) for s, st in rows if s.startswith("127.0.0.1:")), rows[0] if rows else None)
        if chosen:
            player = _find_player_by_serial(players, chosen[0])
    if chosen:
        return {
            "connected": True,
            "serial": chosen[0],
            "detail": f"已连接设备 {chosen[0]}",
            "fallback_serial": "",
            "player": player,
            "index": _coerce_player_index(player),
        }
    return {
        "connected": False,
        "serial": preferred,
        "detail": "未检测到已连接设备（模拟器可能未运行）",
        "fallback_serial": "",
        "player": _find_player_by_serial(players, preferred) if preferred else None,
        "index": None,
    }


def _adb_state(adb_path: str, serial: str) -> tuple[bool, str]:
    s = str(serial or "").strip()
    if not s or s.startswith("YOUR_") or s.endswith(":0"):
        return False, "未配置 ADB 设备地址"
    try:
        r = subprocess.run(
            [adb_path, "-s", s, "get-state"],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        state = (r.stdout or "").strip()
        if r.returncode == 0 and state == "device":
            return True, "state=device"
        detail = (r.stderr or r.stdout or "").strip()
        return False, detail or f"state={state or '?'}"
    except Exception as exc:
        return False, str(exc)


def _adb_reconnect_serial(adb_path: str, serial: str) -> None:
    s = str(serial or "").strip()
    if not s or ":" not in s or s.startswith("YOUR_") or s.endswith(":0"):
        return
    try:
        subprocess.run([adb_path, "disconnect", s], capture_output=True, text=True, timeout=5)
    except Exception:
        pass
    try:
        subprocess.run([adb_path, "connect", s], capture_output=True, text=True, timeout=8)
    except Exception:
        pass


def _check_configured_adb_device(adb_path: str, preferred_serial: str) -> dict:
    serial = str(preferred_serial or "").strip()
    rows = _adb_device_rows(adb_path)
    usable = [(s, st) for s, st in rows if st == "device"]
    fallback = next(((s, st) for s, st in usable if s.startswith("127.0.0.1:")), usable[0] if usable else None)
    if not serial or serial.startswith("YOUR_") or serial.endswith(":0"):
        if fallback:
            return {"connected": True, "serial": fallback[0], "detail": f"已连接设备 {fallback[0]}", "fallback_serial": ""}
        return {"connected": False, "serial": "", "detail": "未检测到已连接设备（模拟器可能未运行）", "fallback_serial": ""}

    ok, detail = _adb_state(adb_path, serial)
    if not ok and ":" in serial:
        _adb_reconnect_serial(adb_path, serial)
        ok, detail = _adb_state(adb_path, serial)
    if ok:
        return {"connected": True, "serial": serial, "detail": f"配置设备已连接 {serial}", "fallback_serial": ""}

    row_state = next((st for s, st in rows if s == serial), "")
    base = f"配置设备 {serial} 状态为 {row_state}" if row_state else f"配置设备 {serial} 未连接"
    extra = f"；另检测到 {fallback[0]} 可用，但运行时会优先使用配置地址" if fallback else ""
    return {
        "connected": False,
        "serial": serial,
        "detail": f"{base}{extra}。{detail}".strip(),
        "fallback_serial": fallback[0] if fallback else "",
    }


def validate_mumu_setup(emulator: dict) -> dict:
    """对 emulator 配置做功能性验证，返回结构化检测报告。"""
    results: dict = {
        "mumu_folder": {"exists": False, "detail": ""},
        "emu_path": {"exists": False, "runnable": False, "detail": ""},
        "adb_path": {"exists": False, "runnable": False, "version": "", "detail": ""},
        "adb_device": {"connected": False, "serial": "", "detail": ""},
        "emulator_index": {"configured": emulator.get("index"), "detected": None, "match": None, "detail": ""},
        "overall": False,
        "operationReady": False,
        "needsRunningDevice": False,
    }

    folder = str(emulator.get("mumu_folder", "") or "").strip()
    if folder:
        p = Path(folder)
        if p.exists() and p.is_dir():
            results["mumu_folder"]["exists"] = True
            has_nx = (p / "nx_main").exists()
            has_shell = (p / "shell").exists()
            if has_nx or has_shell:
                parts = []
                if has_nx:
                    parts.append("nx_main")
                if has_shell:
                    parts.append("shell")
                results["mumu_folder"]["detail"] = f"目录结构正常 ({', '.join(parts)})"
            else:
                results["mumu_folder"]["detail"] = "目录存在但未找到 nx_main 或 shell 子目录"
        else:
            results["mumu_folder"]["detail"] = "路径不存在" if folder else "未配置"
    else:
        results["mumu_folder"]["detail"] = "未配置"

    emu_path = str(emulator.get("emu_path", "") or "").strip()
    if emu_path and Path(emu_path).is_file():
        results["emu_path"]["exists"] = True
        try:
            # 新版 MuMu（nx_main\MuMuManager.exe）：`version` 返回 0 且 stdout 为 JSON。
            # 旧安装器使用的 `-v 0 player -ld` 在新 CLI 下会打印帮助并以 -1（显示为 4294967295）退出，易误判。
            r = subprocess.run(
                [emu_path, "version"],
                capture_output=True, text=True, timeout=8,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            rc_disp = _format_subprocess_exit_code(r.returncode)
            ver = _parse_mumu_manager_version_stdout(r.stdout or "")
            if r.returncode == 0:
                results["emu_path"]["runnable"] = True
                if ver:
                    results["emu_path"]["detail"] = (
                        f"可执行（MuMuManager {ver}，返回码 {rc_disp}）"
                    )
                else:
                    results["emu_path"]["detail"] = f"可执行（返回码 {rc_disp}）"
            else:
                results["emu_path"]["runnable"] = False
                tail = (r.stderr or r.stdout or "").strip().splitlines()
                hint = tail[0][:120] if tail else ""
                extra = f" {hint}" if hint else ""
                results["emu_path"]["detail"] = (
                    f"MuMuManager version 失败（返回码 {rc_disp}）。"
                    f"请确认路径为 nx_main\\MuMuManager.exe 或 shell\\MuMuPlayer.exe，且 MuMu 为较新版本。{extra}"
                )
        except subprocess.TimeoutExpired:
            results["emu_path"]["runnable"] = False
            results["emu_path"]["detail"] = "执行 version 超时，请检查 MuMu 是否卡死或路径错误"
        except Exception as e:
            results["emu_path"]["detail"] = f"执行失败: {e}"
    else:
        results["emu_path"]["detail"] = "文件不存在" if emu_path else "未配置"

    adb_path = str(emulator.get("adb_path", "") or "").strip()
    if adb_path and Path(adb_path).is_file():
        results["adb_path"]["exists"] = True
        try:
            r = subprocess.run(
                [adb_path, "version"],
                capture_output=True, text=True, timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            results["adb_path"]["runnable"] = True
            import re
            m = re.search(r"Android Debug Bridge version ([\d.]+)", r.stdout or "")
            ver = m.group(1) if m else ""
            results["adb_path"]["version"] = ver
            results["adb_path"]["detail"] = f"ADB {ver}" if ver else "可执行，版本未知"
        except Exception as e:
            results["adb_path"]["detail"] = f"执行失败: {e}"
    else:
        results["adb_path"]["detail"] = "文件不存在" if adb_path else "未配置"

    if results["adb_path"]["runnable"]:
        addr = str(emulator.get("adb_addr", "") or "")
        needs_addr = not addr or addr.startswith("YOUR_") or addr.endswith(":0")
        device = _choose_adb_device(adb_path, emu_path, addr, allow_fallback=needs_addr)
        results["adb_device"]["connected"] = device["connected"]
        results["adb_device"]["serial"] = device["serial"]
        results["adb_device"]["detail"] = device["detail"]
        if device.get("fallback_serial"):
            results["adb_device"]["fallback_serial"] = device["fallback_serial"]
        results["emulator_index"]["detected"] = device.get("index")
        configured = "" if emulator.get("index") is None else str(emulator.get("index"))
        detected = "" if device.get("index") is None else str(device.get("index"))
        if detected:
            results["emulator_index"]["match"] = (not configured) or configured == detected
            if results["emulator_index"]["match"]:
                results["emulator_index"]["detail"] = f"ADB 地址对应 MuMu 实例 {detected}"
            else:
                results["emulator_index"]["detail"] = (
                    f"配置 index={configured}，但 ADB 地址 {device['serial']} 对应 MuMu 实例 {detected}"
                )
        else:
            results["emulator_index"]["detail"] = "未能从 MuMuManager info 反查 ADB 地址对应的实例序号"
    else:
        results["adb_device"]["detail"] = "ADB 不可用，跳过设备检测"

    if (
        results["emu_path"]["exists"]
        and not results["emu_path"]["runnable"]
    ):
        if results["adb_device"]["connected"]:
            results["emu_path"]["detail"] += " 已检测到 ADB 设备可用，安装器将把 MuMuManager 异常视为警告。"
        elif results["adb_path"]["runnable"]:
            results["emu_path"]["detail"] += " ADB 可执行文件可用，安装器将把 MuMuManager 异常视为警告。"

    results["overall"] = (
        results["mumu_folder"]["exists"]
        and results["emu_path"]["exists"]
        and results["adb_path"]["exists"] and results["adb_path"]["runnable"]
    )
    results["operationReady"] = bool(results["overall"] and results["adb_device"]["connected"])
    if results["operationReady"] and results["emulator_index"]["match"] is False:
        results["operationReady"] = False
        results["adb_device"]["detail"] += "；MuMu 实例序号与 ADB 地址不一致，请重新运行安装器配置或在设置中修正 index"
    results["needsRunningDevice"] = bool(results["overall"] and not results["adb_device"]["connected"])
    return results


def ensure_config_with_mumu(project_root: Path) -> None:
    """确保存在 config.json，并尽量自动填写 MuMu 相关字段。"""
    cfg_tmpl = project_root / "config template.json"
    cfg_path = project_root / "config.json"
    if not cfg_path.exists():
        if cfg_tmpl.exists():
            cfg_path.write_text(cfg_tmpl.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            cfg_path.write_text(json.dumps({
                "app": {"name": "ZmxyOL","max_retry": 3,"app_to_start": "org.yjmobile.zmxy", "restart_on_error": True, "run_in_background": True, "auto_start": True},
                "emulator": {"index": 1, "adb_addr": "127.0.0.1:16416", "max_retry": 3,"mumu_folder": "", "emu_path": "", "adb_path": ""},
                "ocr": {"use_gpu": False},
                "current_account": "default"
            }, ensure_ascii=False, indent=2), encoding="utf-8")

    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
    except Exception:
        return

    emulator = data.setdefault("emulator", {})

    # 若缺省、占位符，或配置里写了默认路径但本机磁盘上不存在/类型不对，则尝试自动探测
    need_detect = _emulator_paths_need_detect(emulator)

    if need_detect:
        candidates = []
        candidates.extend(_read_registry_mu_mu_paths())
        candidates.extend(_search_common_mu_mu_paths())
        chosen = None
        # 排除 Global 版
        for c in candidates:
            if "global" in str(c).lower():
                continue
            chosen = c
            break
        if chosen is not None:
            paths = _derive_paths_from_mumu_folder(chosen)
            for k, v in paths.items():
                if not v:
                    continue
                cur = str(emulator.get(k, "") or "").strip()
                cur_ok = cur and not cur.startswith("YOUR_") and _path_ok_for_emulator_key(k, cur)
                if not cur_ok:
                    emulator[k] = v

    # 自动检测 adb 设备地址，并同步 MuMu 多开 index，避免 ADB 操作与生命周期控制落到不同实例。
    adb_addr = str(emulator.get("adb_addr", ""))
    needs_addr = not adb_addr or adb_addr.startswith("YOUR_") or adb_addr.endswith(":0")
    if emulator.get("adb_path"):
        device = _choose_adb_device(
            emulator["adb_path"],
            str(emulator.get("emu_path", "") or ""),
            adb_addr,
            allow_fallback=needs_addr,
        )
        if device.get("connected") and (needs_addr or device.get("serial") == adb_addr):
            emulator["adb_addr"] = device["serial"]
            if device.get("index") is not None:
                emulator["index"] = device["index"]
        elif device.get("index") is not None and adb_addr and not adb_addr.startswith("YOUR_"):
            emulator["index"] = device["index"]
        elif needs_addr:
            serial = _adb_detect_serial(emulator["adb_path"]) or ""
            if serial:
                emulator["adb_addr"] = serial
                player = _find_player_by_serial(_mumu_info_rows(str(emulator.get("emu_path", "") or "")), serial)
                index = _coerce_player_index(player)
                if index is not None:
                    emulator["index"] = index
            else:
                index_text = _prompt_text("请输入 MuMu 实例序号 (0-7，默认 0):", default="0")
                try:
                    index = int(index_text) if index_text else 0
                except Exception:
                    index = 0
                if 0 <= index < len(COMMON_MUMU_PORTS):
                    emulator["index"] = index
                    emulator["adb_addr"] = f"127.0.0.1:{COMMON_MUMU_PORTS[index]}"
                else:
                    emulator["index"] = 0
                    emulator["adb_addr"] = f"127.0.0.1:{COMMON_MUMU_PORTS[0]}"

    # 回写
    try:
        cfg_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def relaunch_in_venv_if_needed(project_root: Path, argv: list[str]) -> None:
    """If not running inside the target .venv, relaunch inside it."""
    venv_python = get_venv_python(project_root)
    # Heuristic: compare current executable path to venv path
    if Path(sys.executable).resolve() != venv_python.resolve():
        if not venv_python.exists():
            ensure_venv(project_root)
        # Relaunch inside venv
        os.execv(str(venv_python), [str(venv_python), *argv])


def main() -> int:
    # Resolve project root from this file location
    this_file = Path(__file__).resolve()
    project_root = find_project_root(this_file.parent)

    # First phase: if not already in the target .venv, relaunch into it
    # (This also creates venv when missing.)
    relaunch_in_venv_if_needed(project_root, sys.argv)

    # 解析命令行参数
    no_git_update = False
    try:
        for a in sys.argv[1:]:
            if a.strip().lower() in {"--no-git-update", "--no_git_update", "--no-git", "-l"}:
                no_git_update = True
    except Exception:
        no_git_update = False

    # 安全更新：将本地 deploy 分支同步到 origin/main，并在运行结束后恢复原始分支与工作区状态
    git_state: dict[str, Any] = {}
    git_helper = None
    try:
        if (not no_git_update) and GitService is not None and EnvConfig is not None:
            git_helper = GitService(EnvConfig(), None, None)
            # 若系统没有 git，则跳过安全更新（不影响后续运行）
            try:
                has_git = bool(git_helper.get_os_git() or git_helper.get_git_version())
            except Exception:
                has_git = False
            if has_git and (not no_git_update):
                DEFAULT_UPSTREAM_REF = "origin/main"
                DEFAULT_UPSTREAM_REF = "origin/feat/launcher"
                upstream_ref = os.environ.get("AUTOSCRIPTOR_UPSTREAM_REF", DEFAULT_UPSTREAM_REF).strip() or DEFAULT_UPSTREAM_REF
                git_state = git_helper.begin_deploy_update(project_root, upstream_ref=upstream_ref) or {}
    except Exception:
        # 更新失败不影响主流程
        git_state = {}

    # Inside venv now
    # Optional pip index from environment variable AUTOSCRIPTOR_PIP_INDEX
    extra_index = os.environ.get("AUTOSCRIPTOR_PIP_INDEX", None)
    fresh = _fresh_install_requested(sys.argv)
    if fresh:
        _apply_fresh_install_prep(project_root)

    # Ensure venv present (no-op if already)
    ensure_venv(project_root)

    if fresh:
        _pip_cache_purge(get_venv_python(project_root))

    # Antivirus check
    av_list = _detect_security_software()
    _try_add_defender_exclusion(str(project_root / ".venv"))
    _try_add_defender_exclusion(str(project_root))
    if av_list:
        names = "\u3001".join(av_list)
        print(f"\n{'='*60}")
        print(f"  \u26a0 \u68c0\u6d4b\u5230\u5b89\u5168\u8f6f\u4ef6: {names}")
        print(f"  \u5176\u5b9e\u65f6\u626b\u63cf\u53ef\u80fd\u663e\u8457\u62d6\u6162\u5b89\u88c5\u548c\u8fd0\u884c\u901f\u5ea6\u3002")
        print(f"  \u5efa\u8bae\u5c06\u4ee5\u4e0b\u76ee\u5f55\u6dfb\u52a0\u5230\u5b89\u5168\u8f6f\u4ef6\u7684\u767d\u540d\u5355/\u4fe1\u4efb\u533a:")
        print(f"  \u2192 {project_root}")
        print(f"{'='*60}\n")

    # Install dependencies
    reinstall_pip_and_install(project_root, extra_index=extra_index, fresh=fresh)

    # 根据 README 约定自动配置 MuMu（仅 Windows 有效，忽略失败）
    try:
        ensure_config_with_mumu(project_root)
    except Exception:
        pass

    # Decide run target（与 --fresh-install 等标志共存，任意位置可写 webui|cli|install-only）
    target = "webui"
    for a in sys.argv[1:]:
        t = a.strip().lower()
        if t in {"webui", "cli", "install-only"}:
            target = t
            break

    try:
        run_target_func = _import_run_target()
        return run_target_func(get_venv_python(project_root), project_root, target)
    finally:
        # 尝试恢复原始分支/提交与工作区状态
        try:
            from services.webui.server import shutdown_webui
            shutdown_webui()
            if git_helper and git_state:
                git_helper.end_deploy_update(project_root, git_state)
        except Exception:
            pass


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as e:
        print(f"安装/运行失败，退出码: {e.returncode}")
        sys.exit(e.returncode or 1)
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as e:
        print(f"未预期错误: {e}")
        sys.exit(1)


