"""MuMu installation discovery helpers for source WebUI setup.

This module borrows the proven search strategy from the old Electron installer,
but keeps it as a small Python utility so source WebUI and diagnostics can reuse
it without restoring the old installer surface.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0

COMMON_NAMES = (
    "Netease\\MuMu",
    "Netease\\MuMu Player 12",
    "MuMu",
    "MuMu Player 12",
    "Netease\\MuMu Player",
    "Netease\\MuMuPlayer",
)

SKIP_ROOT_DIRS = {
    "$recycle.bin", "system volume information", "windows", "recovery",
    "perflogs", "$winreagent", "$sysreset", "config.msi",
    "documents and settings", "msocache",
}

PATH_KEYS = ("mumu_folder", "emu_path", "adb_path")


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


def derive_paths_from_folder(folder: Path | str) -> dict[str, str]:
    root = Path(folder)
    paths = {"mumu_folder": str(root), "emu_path": "", "adb_path": ""}
    candidates = (
        (root / "nx_main" / "MuMuManager.exe", root / "nx_main" / "adb.exe"),
        (root / "shell" / "MuMuPlayer.exe", root / "shell" / "adb.exe"),
    )
    for manager, adb in candidates:
        if not paths["emu_path"] and manager.is_file():
            paths["emu_path"] = str(manager)
        if not paths["adb_path"] and adb.is_file():
            paths["adb_path"] = str(adb)
    return paths


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
        device = choose_adb_device(
            str(result_emulator.get("adb_path") or ""),
            str(result_emulator.get("emu_path") or ""),
            str(result_emulator.get("adb_addr") or ""),
        )
        needs_addr = not str(result_emulator.get("adb_addr") or "").strip() or str(result_emulator.get("adb_addr") or "").startswith("YOUR_") or str(result_emulator.get("adb_addr") or "").endswith(":0")
        if device.get("connected") and (needs_addr or device.get("serial") == result_emulator.get("adb_addr")):
            result_emulator["adb_addr"] = device.get("serial") or result_emulator.get("adb_addr")
        if device.get("index") is not None:
            result_emulator["index"] = device["index"]

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
