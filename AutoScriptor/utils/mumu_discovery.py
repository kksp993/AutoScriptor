"""MuMu installation discovery helpers for source WebUI setup.

This module borrows the proven search strategy from the old Electron installer,
but keeps it as a small Python utility so source WebUI and diagnostics can reuse
it without restoring the old installer surface.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0

COMMON_NAMES = (
    "Netease\\MuMu",
    "Netease\\MuMuPlayer",
    "Netease\\MuMuPlayer-12.0",
    "Netease\\MuMu Player 12",
    "Netease\\MuMu Player",
    "MuMu",
    "MuMuPlayer",
    "MuMuPlayer-12.0",
    "MuMu Player 12",
)

SKIP_ROOT_DIRS = {
    "$recycle.bin", "system volume information", "windows", "recovery",
    "perflogs", "$winreagent", "$sysreset", "config.msi",
    "documents and settings", "msocache",
}

# 限深查找时跳过的目录：vms 里是虚拟机磁盘镜像，config 里是用户数据，
# 都不会放模拟器可执行文件，但体积和层级都很大。
_SEARCH_SKIP_DIRS = {
    "vms", "log", "logs", "config", "configs", "overlay", "plugins",
    "temp", "tmp", "__pycache__", "$recycle.bin", "system volume information",
}

PATH_KEYS = ("mumu_folder", "emu_path", "adb_path")

# MuMu 按实例号分配 ADB 端口：实例 0 是 16384，每多开一个加 32。
MUMU_ADB_BASE_PORT = 16384
MUMU_ADB_PORT_STEP = 32

# MuMu 各版本的目录布局（调研：docs/AutoScriptor/reference/mumu-realtime-control-research.md §1.4）。
# 版本史：
#   - MuMu 12 早期 / 更老的 MuMu：NemuIpc 库在 ``shell/sdk/``；
#   - MuMu 5.0（即常说的 MuMu 12）：改到 ``nx_device/12.0/shell/sdk/``；
#   - MuMu 6.0（Android 15）：``nx_device/15.0/shell/sdk/``（MAA PR #16994）。
# ``nx_device`` 下的数字是模拟器的 Android 大版本，会随新版本继续增加，所以
# 用通配 + 版本号排序而不是枚举；``nx_main/sdk/`` 是 MaaFramework 使用的副本
# （本机实测与 nx_device 副本导出集合一致）。
MUMU_MANAGER_RELATIVE_CANDIDATES = (
    ("nx_main", "MuMuManager.exe"),   # MuMu v5+（12 5.0 / 6.0）
    ("shell", "MuMuManager.exe"),     # MuMu v4 及更早
    ("MuMuManager.exe",),
)

MUMU_ADB_RELATIVE_CANDIDATES = (
    ("nx_main", "adb.exe"),                                  # MuMu v5+
    ("shell", "adb.exe"),                                    # MuMu 12 早期
    ("vmonitor", "bin", "adb_server.exe"),                   # MuMu 6 时代
    ("emulator", "nemu", "vmonitor", "bin", "adb_server.exe"),
    ("adb.exe",),
)


def default_mumu_adb_addr(index: Any) -> str:
    """实例号对应的默认 ADB 地址。"""
    try:
        n = int(index)
    except (TypeError, ValueError):
        n = 0
    if n < 0:
        n = 0
    return f"127.0.0.1:{MUMU_ADB_BASE_PORT + n * MUMU_ADB_PORT_STEP}"


def is_placeholder_adb_addr(adb_addr: Any) -> bool:
    """True 表示这不是一个真实地址：空值、模板占位或 ``:0`` 结尾的残值。"""
    text = str(adb_addr or "").strip()
    return not text or text.startswith("YOUR_") or text.endswith(":0")


def is_derived_adb_addr(adb_addr: Any, index: Any) -> bool:
    """True 表示该地址恰好是 ``index`` 推导出来的那一个。

    这种地址本身不携带信息，只是实例号的镜像，所以可以跟着真正连上的设备走。
    手填的地址（局域网主机、自定义端口、``localhost`` 写法）与推导结果永不相
    等，因此会被完整保留。
    """
    return str(adb_addr or "").strip() == default_mumu_adb_addr(index)


def _is_windows() -> bool:
    return os.name == "nt"


def _norm_key(path: Path | str) -> str:
    return str(Path(path)).replace("/", "\\").lower()


def _path_is_valid(key: str, value: Any) -> bool:
    text = str(value or "").strip()
    if not text or text.startswith("YOUR_"):
        return False
    p = Path(text)
    if key == "mumu_folder":
        return p.is_dir()
    if key in {"emu_path", "adb_path"}:
        return p.is_file()
    return p.exists()


def _read_registry_mumu_paths() -> list[Path]:
    if not _is_windows():
        return []
    roots = (
        r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
        r"HKLM\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
    )
    keywords = ("mumu", "mumu player", "网易 mumu")
    results: list[Path] = []
    for root in roots:
        try:
            out = subprocess.run(
                ["reg", "query", root],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                creationflags=CREATE_NO_WINDOW,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if out.returncode != 0:
            continue
        for line in (out.stdout or "").splitlines():
            subkey = line.strip()
            if not subkey.upper().startswith("HKLM"):
                continue
            try:
                name = subprocess.run(
                    ["reg", "query", subkey, "/v", "DisplayName"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=5,
                    creationflags=CREATE_NO_WINDOW,
                )
            except (OSError, subprocess.SubprocessError):
                continue
            if not any(keyword in (name.stdout or "").lower() for keyword in keywords):
                continue
            try:
                loc = subprocess.run(
                    ["reg", "query", subkey, "/v", "InstallLocation"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=5,
                    creationflags=CREATE_NO_WINDOW,
                )
            except (OSError, subprocess.SubprocessError):
                continue
            if loc.returncode != 0:
                continue
            for part in (loc.stdout or "").splitlines():
                if "InstallLocation" not in part or "REG_SZ" not in part:
                    continue
                candidate = part.split("REG_SZ", 1)[1].strip()
                p = Path(candidate)
                if p.is_dir():
                    results.append(p)
    return results


def _program_files_bases() -> list[Path]:
    bases: list[Path] = []
    for raw in (
        os.environ.get("ProgramFiles", r"C:\Program Files"),
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        os.environ.get("LOCALAPPDATA", ""),
    ):
        if raw:
            bases.append(Path(raw))
    if _is_windows():
        for code in range(ord("A"), ord("Z") + 1):
            root = Path(f"{chr(code)}:\\")
            if not root.exists():
                continue
            bases.extend([root, root / "Program Files", root / "Program Files (x86)"])
            try:
                for entry in root.iterdir():
                    if entry.is_dir() and entry.name.lower() not in SKIP_ROOT_DIRS:
                        bases.append(entry)
            except OSError:
                pass
    seen: set[str] = set()
    result: list[Path] = []
    for base in bases:
        key = _norm_key(base)
        if key not in seen:
            seen.add(key)
            result.append(base)
    return result


def search_mumu_folders() -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []

    def add(path: Path) -> None:
        try:
            key = _norm_key(path.resolve())
        except OSError:
            key = _norm_key(path)
        if key in seen or not path.exists():
            return
        seen.add(key)
        result.append(path)

    for path in _read_registry_mumu_paths():
        add(path)
    for base in _program_files_bases():
        for name in COMMON_NAMES:
            add(base / name)
    return result


def _android_series_sort_key(name: str) -> tuple[int, ...]:
    """把 ``nx_device`` 下的版本目录名（``"12.0"`` / ``"15.0"`` / 未来的 ``"16.0"``）
    转成可排序元组；认不出数字的排最后。"""
    digits = re.findall(r"\d+", str(name or ""))
    if not digits:
        return (0,)
    return tuple(int(part) for part in digits[:2])


def _bounded_find(root: Path, filename: str, *, max_depth: int) -> list[Path]:
    """限深查找文件名（大小写不敏感），跳过 vms/log/config 等重目录。"""
    matches: list[Path] = []
    lowered = filename.lower()
    for current_dir, dir_names, file_names in os.walk(root):
        current_path = Path(current_dir)
        try:
            depth = len(current_path.relative_to(root).parts)
        except ValueError:
            dir_names[:] = []
            continue
        if depth >= max_depth:
            dir_names[:] = []
        else:
            dir_names[:] = [name for name in dir_names if name.lower() not in _SEARCH_SKIP_DIRS]
        for name in file_names:
            if name.lower() == lowered:
                matches.append(current_path / name)
    return sorted(matches)


def _bounded_find_one(root: Path, filename: str, *, max_depth: int) -> str:
    found = _bounded_find(root, filename, max_depth=max_depth)
    return str(found[0]) if found else ""


def _first_existing_file(root: Path, candidates: tuple[tuple[str, ...], ...]) -> str:
    for parts in candidates:
        path = root.joinpath(*parts)
        if path.is_file():
            return str(path)
    return ""


def _looks_like_install_root(path: Path) -> bool:
    """True 表示这个目录本身就是 MuMu 安装根。

    认 ``nx_main`` / ``nx_device`` 两个子目录：它们只出现在安装根下。刻意不认
    ``shell``——``nx_device/<系列>/shell`` 也有 ``shell``，会让版本目录冒充安装
    根，把错误的路径传给 ``nemu_connect``。
    """
    return (path / "nx_main").is_dir() or (path / "nx_device").is_dir()


def _looks_like_mumu_related(path: Path) -> bool:
    """True 表示这个目录值得做限深查找。

    配置指错时要沿上级找安装根，但不能一路扫到 ``C:\\``：那里既没有 MuMu 安装，
    深度 5 的通配又会走遍整棵树。判据是「名字带 mumu / 有 MuMu 命名的子目录 /
    有已知的布局子目录」，误配到子目录（nx_main、nx_device/12.0/shell）时靠
    上级的安装根命中，不依赖起点自己满足这一条。
    """
    if "mumu" in path.name.lower():
        return True
    if any((path / marker).is_dir() for marker in ("nx_main", "nx_device", "shell")):
        return True
    try:
        return any(
            entry.is_dir() and "mumu" in entry.name.lower() for entry in path.iterdir()
        )
    except OSError:
        return False


def candidate_nemu_dll_paths(root: Path | str, *, include_search: bool | None = None) -> list[Path]:
    """NemuIpc 动态库候选路径，按版本从新到旧。

    ``nx_device/<series>/`` 的序号是 Android 大版本（12.0 / 15.0 / …），随
    MuMu 升级会继续增加，所以对目录通配并按版本号从大到小排，而不是枚举。
    顺序参考 MAA ``MumuExtras.cpp``（nx_device/15.0 → nx_device/12.0 →
    shell/sdk）并补上 MaaFramework 使用的 ``nx_main/sdk/``。
    """
    base = Path(root)
    candidates: list[Path] = []
    nx_device = base / "nx_device"
    if nx_device.is_dir():
        version_dirs = sorted(
            (entry for entry in nx_device.iterdir() if entry.is_dir()),
            key=lambda entry: _android_series_sort_key(entry.name),
            reverse=True,
        )
        candidates.extend(
            version_dir / "shell" / "sdk" / "external_renderer_ipc.dll"
            for version_dir in version_dirs
        )
    candidates.append(base / "nx_main" / "sdk" / "external_renderer_ipc.dll")
    candidates.append(base / "shell" / "sdk" / "external_renderer_ipc.dll")

    if include_search is None:
        # 只有已知路径全落空时才做限深搜索，避免每次初始化都扫目录树。
        include_search = not any(path.is_file() for path in candidates)
    if include_search:
        candidates.extend(_bounded_find(base, "external_renderer_ipc.dll", max_depth=5))

    seen: set[str] = set()
    result: list[Path] = []
    for path in candidates:
        key = _norm_key(path)
        if key not in seen:
            seen.add(key)
            result.append(path)
    return result


def _root_from_dll_path(dll_path: Path) -> Path | None:
    """按 NemuIpc 库的位置反推安装根。

    库只有两种放法：``<root>[/nx_device/<Android 系列>]/shell/sdk/`` 与
    ``<root>/nx_main/sdk/``。反推比按目录内容排名的猜测更硬——尤其当配置指到
    安装根的上一级时，排名只会看到上级目录，反推能直接落回真正的安装根。
    """
    sdk_dir = dll_path.parent
    if sdk_dir.name.lower() != "sdk":
        return None
    layout_dir = sdk_dir.parent                     # .../shell 或 .../nx_main
    if layout_dir.name.lower() == "nx_main":
        return layout_dir.parent
    if layout_dir.name.lower() != "shell":
        return None
    version_holder = layout_dir.parent               # <root> 或 <root>/nx_device/<系列>
    if version_holder.parent.name.lower() == "nx_device":
        return version_holder.parent.parent
    return version_holder


def _promote_root_from_dll(layout: dict[str, Any]) -> dict[str, Any]:
    """把已经找到的库位置换算成安装根；一致时原样返回。"""
    dll_text = str(layout.get("nemu_dll") or "").strip()
    if not dll_text:
        return layout
    derived_root = _root_from_dll_path(Path(dll_text))
    if derived_root is None or not derived_root.is_dir():
        return layout
    if _norm_key(derived_root) == _norm_key(str(layout.get("root") or "")):
        return layout

    promoted = dict(layout)
    promoted["root"] = str(derived_root)
    promoted_candidates = [
        str(path) for path in candidate_nemu_dll_paths(derived_root)
    ]
    promoted["nemu_dll_candidates"] = promoted_candidates
    first_existing = next((path for path in promoted_candidates if Path(path).is_file()), "")
    if first_existing:
        # 换到真正的安装根之后，首选库也要跟着换成新根下的那一份（版本目录优先），
        # 否则「根」和「库」会各说各的版本。
        promoted["nemu_dll"] = first_existing
    manager = _first_existing_file(derived_root, MUMU_MANAGER_RELATIVE_CANDIDATES)
    if not manager:
        manager = _bounded_find_one(derived_root, "MuMuManager.exe", max_depth=3)
    adb = _first_existing_file(derived_root, MUMU_ADB_RELATIVE_CANDIDATES)
    if not adb:
        adb = _bounded_find_one(derived_root, "adb.exe", max_depth=3)
    if not adb:
        adb = _bounded_find_one(derived_root, "adb_server.exe", max_depth=4)
    promoted["manager"] = manager
    promoted["adb"] = adb
    return promoted


def resolve_mumu_layout(folder: Path | str) -> dict[str, Any]:
    """从任意起点自适应解析 MuMu 安装布局。

    起跳点既可能是安装根，也可能是用户误配的子目录（``nx_main``、``shell``、
    ``nx_device/12.0/shell`` 等）。NemuIpc 的 ``nemu_connect`` 需要的是包含
    ``nx_device`` / ``shell`` 的安装根，所以返回的 ``root`` 才是该传给 DLL 的
    路径。逐级向上至多 3 层找「像安装根」的目录（能解析出 NemuIpc 库、
    MuMuManager 或 adb 的），优先选内容最全的一级。

    返回 ``root`` / ``nemu_dll`` / ``nemu_dll_candidates`` / ``manager`` /
    ``adb``；全部找不到时 ``root`` 回落为起点、其余为空。
    """
    raw = str(folder or "").strip()
    start = Path(raw) if raw else Path(".")
    roots: list[Path] = []
    probe = start
    for _ in range(4):
        roots.append(probe)
        if probe.parent == probe:
            break
        probe = probe.parent

    best_rank: tuple[int, int, int, int] | None = None
    best: dict[str, Any] | None = None
    for index, candidate_root in enumerate(roots):
        # 限深查找只在这个目录确实与 MuMu 有关时才做（见 _looks_like_mumu_related）。
        allow_search = _looks_like_mumu_related(candidate_root)
        dll_candidates = candidate_nemu_dll_paths(
            candidate_root, include_search=None if allow_search else False
        )
        nemu_dll = next((path for path in dll_candidates if path.is_file()), None)
        manager = _first_existing_file(candidate_root, MUMU_MANAGER_RELATIVE_CANDIDATES)
        if not manager and allow_search:
            manager = _bounded_find_one(candidate_root, "MuMuManager.exe", max_depth=3)
        adb = _first_existing_file(candidate_root, MUMU_ADB_RELATIVE_CANDIDATES)
        if not adb and allow_search:
            adb = _bounded_find_one(candidate_root, "adb.exe", max_depth=3)
        if not adb and allow_search:
            adb = _bounded_find_one(candidate_root, "adb_server.exe", max_depth=4)
        if nemu_dll is None and not manager and not adb:
            continue
        # 先认「这是安装根」的目录：子目录（nx_main、nx_device/<系列>/shell 等）
        # 里也可能碰巧搜到库和可执行文件，但 nemu_connect 只接受安装根。
        # 再比 NemuIpc 库、manager+adb 的齐全度；同分时靠近起点的那一级优先。
        rank = (
            1 if _looks_like_install_root(candidate_root) else 0,
            1 if nemu_dll else 0,
            (1 if manager else 0) + (1 if adb else 0),
            -index,
        )
        if best_rank is None or rank > best_rank:
            best_rank = rank
            best = {
                "root": str(candidate_root),
                "nemu_dll": str(nemu_dll) if nemu_dll else "",
                "nemu_dll_candidates": [str(path) for path in dll_candidates],
                "manager": manager,
                "adb": adb,
            }
        if rank[:3] == (1, 1, 2):
            break

    if best is not None:
        return _promote_root_from_dll(best)
    return {
        "root": str(start),
        "nemu_dll": "",
        "nemu_dll_candidates": [
            str(path) for path in candidate_nemu_dll_paths(start, include_search=True)
        ],
        "manager": "",
        "adb": "",
    }


def derive_paths_from_folder(folder: Path | str) -> dict[str, str]:
    """从安装根（或误配的子目录）推导三个配置路径。

    多版本自适应：候选相对路径 + 限深查找；布局知识全部来自
    ``resolve_mumu_layout`` / ``candidate_nemu_dll_paths``。返回结构与配置字段
    ``mumu_folder`` / ``emu_path`` / ``adb_path`` 一一对应。
    """
    layout = resolve_mumu_layout(folder)
    return {
        "mumu_folder": str(layout.get("root") or folder),
        "emu_path": str(layout.get("manager") or ""),
        "adb_path": str(layout.get("adb") or ""),
    }


def _adb_device_rows(adb_path: str) -> list[dict[str, str]]:
    path = str(adb_path or "").strip()
    if not path or not Path(path).is_file():
        return []
    try:
        subprocess.run([path, "start-server"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=8, creationflags=CREATE_NO_WINDOW)
        out = subprocess.run([path, "devices"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=8, creationflags=CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return []
    rows = []
    for line in (out.stdout or "").splitlines():
        text = line.strip()
        if not text or text.lower().startswith("list of devices"):
            continue
        parts = text.split()
        if parts:
            rows.append({"serial": parts[0], "state": parts[1] if len(parts) > 1 else "", "raw": text})
    return rows


def _parse_mumu_info_payload(text: str) -> list[dict[str, Any]]:
    try:
        data = json.loads((text or "").strip() or "{}")
    except json.JSONDecodeError:
        return []
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        if "index" in data:
            return [data]
        return [item for item in data.values() if isinstance(item, dict) and "index" in item]
    return []


def _mumu_info_rows(emu_path: str) -> list[dict[str, Any]]:
    path = str(emu_path or "").strip()
    if not path or not Path(path).is_file():
        return []
    try:
        out = subprocess.run(
            [path, "info", "-v", "all"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if out.returncode != 0:
        return []
    return _parse_mumu_info_payload(out.stdout or "")


def _normalize_host(host: str) -> str:
    text = str(host or "").strip().lower()
    return "127.0.0.1" if text in {"", "localhost", "::1"} else text


def _player_serial(player: dict[str, Any] | None) -> str:
    if not player:
        return ""
    port = str(player.get("adb_port") or "").strip()
    if not port:
        return ""
    return f"{_normalize_host(str(player.get('adb_host_ip') or '127.0.0.1'))}:{port}"


def _player_running(player: dict[str, Any] | None) -> bool:
    if not player:
        return False
    if player.get("is_process_started") is True or player.get("is_android_started") is True:
        return True
    return "start" in str(player.get("player_state") or "").lower() or "running" in str(player.get("player_state") or "").lower()


def _coerce_index(player: dict[str, Any] | None) -> int | str | None:
    if not player or player.get("index") is None:
        return None
    try:
        return int(player.get("index"))
    except (TypeError, ValueError):
        return str(player.get("index"))


def choose_adb_device(adb_path: str, emu_path: str, preferred_serial: str = "") -> dict[str, Any]:
    players = sorted(_mumu_info_rows(emu_path), key=lambda p: (not _player_running(p), not bool(p.get("is_main")), int(p.get("index") or 0)))
    rows = [row for row in _adb_device_rows(adb_path) if row.get("state") == "device"]
    preferred = str(preferred_serial or "").strip()
    if preferred and not preferred.startswith("YOUR_") and not preferred.endswith(":0"):
        for row in rows:
            if row["serial"] == preferred:
                player = next((p for p in players if _player_serial(p) == preferred), None)
                return {"connected": True, "serial": preferred, "index": _coerce_index(player), "detail": "配置设备已连接"}
    for player in players:
        serial = _player_serial(player)
        if serial and _player_running(player) and any(row["serial"] == serial for row in rows):
            return {"connected": True, "serial": serial, "index": _coerce_index(player), "detail": "已连接 MuMu 设备"}
    fallback = next((row for row in rows if row["serial"].startswith("127.0.0.1:")), rows[0] if rows else None)
    if fallback:
        return {"connected": True, "serial": fallback["serial"], "index": None, "detail": "已连接 ADB 设备"}
    return {"connected": False, "serial": preferred, "index": None, "detail": "未检测到已连接设备（模拟器可能未运行）"}


def discover_mumu_setup(emulator: dict[str, Any] | None = None, *, probe_adb: bool = True) -> dict[str, Any]:
    source = dict(emulator or {})
    result_emulator = dict(source)
    before = {key: str(result_emulator.get(key, "") or "") for key in (*PATH_KEYS, "adb_addr")}
    candidates = []
    chosen = ""

    need_paths = any(not _path_is_valid(key, result_emulator.get(key)) for key in PATH_KEYS)
    if need_paths:
        for folder in search_mumu_folders():
            if "global" in str(folder).lower():
                continue
            paths = derive_paths_from_folder(folder)
            valid = {key: _path_is_valid(key, value) for key, value in paths.items()}
            candidates.append({"folder": str(folder), "paths": paths, "valid": valid})
            if not chosen and (valid.get("emu_path") or valid.get("adb_path")):
                chosen = str(folder)
                for key, value in paths.items():
                    if value and not _path_is_valid(key, result_emulator.get(key)):
                        result_emulator[key] = value
                if all(_path_is_valid(key, result_emulator.get(key)) for key in PATH_KEYS):
                    break

    device = {"connected": False, "serial": "", "index": None, "detail": "未探测 ADB"}
    if probe_adb and _path_is_valid("adb_path", result_emulator.get("adb_path")):
        configured_addr = str(result_emulator.get("adb_addr") or "").strip()
        # 占位值没有信息量，镜像值只是实例号的另一份写法：两者都该跟着真实设备走。
        # 手填的地址（局域网主机、自定义端口）不满足等值判断，保持原样。
        addr_follows_device = is_placeholder_adb_addr(configured_addr) or is_derived_adb_addr(
            configured_addr, result_emulator.get("index", 0)
        )
        device = choose_adb_device(
            str(result_emulator.get("adb_path") or ""),
            str(result_emulator.get("emu_path") or ""),
            configured_addr,
        )
        if device.get("index") is not None:
            result_emulator["index"] = device["index"]
        # 先落实例号再写地址：两者必须说同一个实例，否则配置自相矛盾。
        if device.get("connected") and (addr_follows_device or device.get("serial") == configured_addr):
            result_emulator["adb_addr"] = device.get("serial") or configured_addr

    path_status = {key: _path_is_valid(key, result_emulator.get(key)) for key in PATH_KEYS}
    after = {key: str(result_emulator.get(key, "") or "") for key in (*PATH_KEYS, "adb_addr")}
    return {
        "changed": before != after,
        "chosen": chosen,
        "candidates": candidates[:12],
        "candidate_count": len(candidates),
        "emulator": result_emulator,
        "path_status": path_status,
        "adb_device": device,
        "needs_manual_paths": not all(path_status.values()),
        "needs_running_device": not bool(device.get("connected")),
    }
