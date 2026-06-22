"""Unified device checks and direct-control fallbacks for MuMu.

The project still uses three low-level channels:

* MuMuManager for official lifecycle commands when it is healthy.
* ADB for click/app fallbacks and package state checks.
* NemuIpc for screenshots and high fidelity touch when available.

This facade keeps the health checks and fallback primitives in one place so
adapter classes do not each invent their own "is the device usable?" logic.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0


def _text(result: subprocess.CompletedProcess[str]) -> str:
    return (result.stderr or result.stdout or "").strip()


def _status(status: str, message: str = "", **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"status": status, "message": message}
    payload.update(extra)
    return payload


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


def _parse_mumu_info_payload(text: str) -> list[dict[str, Any]]:
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


def _player_serial(player: dict[str, Any] | None) -> str:
    if not player:
        return ""
    port = str(player.get("adb_port", "") or "").strip()
    if not port:
        return ""
    host = _normalize_serial_host(str(player.get("adb_host_ip", "127.0.0.1") or "127.0.0.1"))
    return f"{host}:{port}"


def _player_is_running(player: dict[str, Any] | None) -> bool:
    if not player:
        return False
    if player.get("is_process_started") is True or player.get("is_android_started") is True:
        return True
    state = str(player.get("player_state", "") or "").lower()
    return "start" in state or "running" in state


def _find_player_by_serial(players: list[dict[str, Any]], serial: str) -> dict[str, Any] | None:
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


def _coerce_player_index(player: dict[str, Any] | None) -> str | int | None:
    if not player or player.get("index") is None:
        return None
    try:
        return int(player.get("index"))
    except Exception:
        return str(player.get("index"))


class DeviceFacade:
    """Small facade around configured MuMuManager, ADB and NemuIpc paths."""

    def __init__(
        self,
        *,
        emulator: dict[str, Any] | None = None,
        app: dict[str, Any] | None = None,
        vm_index: str | int | None = None,
    ):
        if emulator is None or app is None:
            from AutoScriptor.utils.app_config import cfg

            emulator = emulator if emulator is not None else cfg["emulator"]
            app = app if app is not None else cfg["app"]
        self.emulator = emulator
        self.app = app
        self.vm_index = str(vm_index if vm_index is not None else emulator.get("index", ""))

    @classmethod
    def from_config(cls, *, vm_index: str | int | None = None) -> "DeviceFacade":
        return cls(vm_index=vm_index)

    @property
    def adb_addr(self) -> str:
        return str(self.emulator.get("adb_addr", "") or "").strip()

    @property
    def app_package(self) -> str:
        return str(self.app.get("app_to_start", "") or "").strip()

    def adb_base_args(self) -> list[str]:
        adb_path = str(self.emulator.get("adb_path", "") or "").strip()
        args = [adb_path]
        if self.adb_addr:
            args.extend(["-s", self.adb_addr])
        return args

    def manager_base_args(self, operate: str | list[str] | None = None) -> list[str]:
        emu_path = str(self.emulator.get("emu_path", "") or "").strip()
        args = [emu_path]
        if operate:
            args.extend(operate if isinstance(operate, list) else [operate])
        if self.vm_index:
            args.extend(["-v", self.vm_index])
        return args

    def run_adb(self, args: list[str], timeout: int = 10) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            self.adb_base_args() + args,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
        )

    def run_manager(
        self,
        args: list[str],
        *,
        operate: str | list[str] | None = None,
        timeout: int = 10,
    ) -> subprocess.CompletedProcess[str]:
        from AutoScriptor.utils.perf import mumu_safe_subprocess

        with mumu_safe_subprocess():
            return subprocess.run(
                self.manager_base_args(operate) + args,
                capture_output=True,
                text=True,
                timeout=timeout,
                creationflags=CREATE_NO_WINDOW,
            )

    def configured_adb_host_port(self) -> tuple[str, str] | None:
        if ":" not in self.adb_addr:
            return None
        host, port = self.adb_addr.rsplit(":", 1)
        if not host or not port:
            return None
        return host, port

    def adb_device_ready(self) -> bool:
        try:
            state = self.run_adb(["get-state"], timeout=5)
            if state.returncode != 0 or state.stdout.strip() != "device":
                if ":" not in self.adb_addr:
                    return False
                self._adb_connect_serial(self.adb_addr)
                state = self.run_adb(["get-state"], timeout=5)
                if state.returncode != 0 or state.stdout.strip() != "device":
                    return False
            booted = self.run_adb(["shell", "getprop", "sys.boot_completed"], timeout=5)
            return booted.returncode == 0 and booted.stdout.strip() == "1"
        except (OSError, subprocess.SubprocessError):
            return False

    def adb_shell(self, args: list[str], timeout: int = 10) -> bool:
        result = self.run_adb(["shell", *args], timeout=timeout)
        if result.returncode == 0:
            return True
        raise RuntimeError(_text(result))

    def adb_tap(self, x: int, y: int) -> bool:
        return self.adb_shell(["input", "tap", str(x), str(y)])

    def adb_swipe(self, from_x: int, from_y: int, to_x: int, to_y: int, duration: int = 500) -> bool:
        return self.adb_shell([
            "input", "swipe", str(from_x), str(from_y), str(to_x), str(to_y), str(duration)
        ])

    def adb_input_text(self, text: str) -> bool:
        return self.adb_shell(["input", "text", text])

    def adb_key_event(self, key: int | str) -> bool:
        return self.adb_shell(["input", "keyevent", str(key)])

    def adb_force_stop_app(self, package: str) -> bool:
        return self.adb_shell(["am", "force-stop", package])

    def adb_launch_app(self, package: str) -> bool:
        result = self.run_adb(
            ["shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"],
            timeout=15,
        )
        return result.returncode == 0

    def adb_app_state(self, package: str) -> str:
        result = self.run_adb(["shell", "pidof", package], timeout=5)
        return "running" if (result.returncode == 0 and result.stdout.strip()) else "stopped"

    def adb_app_exists(self, package: str) -> bool:
        result = self.run_adb(["shell", "pm", "path", package], timeout=5)
        return result.returncode == 0 and bool(result.stdout.strip())

    def adb_list_packages(self) -> list[dict[str, str]]:
        result = self.run_adb(["shell", "pm", "list", "packages"], timeout=15)
        if result.returncode != 0:
            raise RuntimeError(_text(result))
        installed = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line.startswith("package:"):
                continue
            package = line.split("package:", 1)[1].strip()
            if package:
                installed.append({"package": package, "app_name": "", "version": ""})
        return installed

    def _manager_version_check(self) -> dict[str, Any]:
        path = str(self.emulator.get("emu_path", "") or "").strip()
        exists = bool(path and Path(path).is_file())
        if not exists:
            return _status("error", "MuMuManager path is missing", path=path, exists=False)
        try:
            from AutoScriptor.utils.perf import mumu_safe_subprocess

            with mumu_safe_subprocess():
                result = subprocess.run(
                    [path, "version"],
                    capture_output=True,
                    text=True,
                    timeout=8,
                    creationflags=CREATE_NO_WINDOW,
                )
            version = ""
            try:
                data = json.loads(result.stdout or "{}")
                version = str(data.get("version") or "")
            except Exception:
                pass
            if result.returncode == 0:
                return _status("ok", "MuMuManager version command succeeded", path=path, exists=True, version=version)
            return _status(
                "warn",
                "MuMuManager version command failed; ADB fallback may still be usable",
                path=path,
                exists=True,
                returncode=result.returncode,
                detail=_text(result),
            )
        except subprocess.TimeoutExpired:
            return _status("warn", "MuMuManager version command timed out", path=path, exists=True)
        except Exception as exc:
            return _status("warn", f"MuMuManager check failed: {exc}", path=path, exists=True)

    def _adb_check(self) -> dict[str, Any]:
        path = str(self.emulator.get("adb_path", "") or "").strip()
        exists = bool(path and Path(path).is_file())
        if not exists:
            return _status("error", "ADB path is missing", path=path, exists=False)
        try:
            result = subprocess.run(
                [path, "version"],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=CREATE_NO_WINDOW,
            )
            if result.returncode != 0:
                return _status("error", "ADB version command failed", path=path, exists=True, detail=_text(result))
            match = re.search(r"Android Debug Bridge version ([\d.]+)", result.stdout or "")
            return _status("ok", "ADB executable is available", path=path, exists=True, version=match.group(1) if match else "")
        except Exception as exc:
            return _status("error", f"ADB check failed: {exc}", path=path, exists=True)

    def _manager_info_rows(self) -> list[dict[str, Any]]:
        path = str(self.emulator.get("emu_path", "") or "").strip()
        if not path or not Path(path).is_file():
            return []
        try:
            from AutoScriptor.utils.perf import mumu_safe_subprocess

            with mumu_safe_subprocess():
                result = subprocess.run(
                    [path, "info", "-v", "all"],
                    capture_output=True,
                    text=True,
                    timeout=8,
                    creationflags=CREATE_NO_WINDOW,
                )
            if result.returncode == 0:
                return _parse_mumu_info_payload(result.stdout or "")
        except Exception:
            pass
        return []

    def _adb_device_rows(self) -> list[tuple[str, str]]:
        path = str(self.emulator.get("adb_path", "") or "").strip()
        if not path or not Path(path).is_file():
            return []
        try:
            subprocess.run([path, "start-server"], capture_output=True, text=True, timeout=5, creationflags=CREATE_NO_WINDOW)
            out = subprocess.run([path, "devices"], capture_output=True, text=True, timeout=5, creationflags=CREATE_NO_WINDOW)
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

    def _adb_connect_serial(self, serial: str) -> str:
        path = str(self.emulator.get("adb_path", "") or "").strip()
        s = str(serial or "").strip()
        if not path or not Path(path).is_file() or ":" not in s:
            return ""
        try:
            result = subprocess.run(
                [path, "connect", s],
                capture_output=True,
                text=True,
                timeout=8,
                creationflags=CREATE_NO_WINDOW,
            )
            return (result.stdout or result.stderr or "").strip()
        except Exception as exc:
            return str(exc)

    def _adb_mismatch_detail(
        self,
        *,
        configured: str,
        raw_detail: str,
        rows: list[tuple[str, str]],
        players: list[dict[str, Any]],
    ) -> dict[str, Any]:
        usable = [(serial, state) for serial, state in rows if state == "device"]
        configured_player = _find_player_by_serial(players, configured)
        running_players = [player for player in players if _player_is_running(player) and _player_serial(player)]

        fallback_serial = ""
        fallback_player: dict[str, Any] | None = None
        for player in running_players:
            serial = _player_serial(player)
            if any(row_serial == serial and state == "device" for row_serial, state in rows):
                fallback_serial = serial
                fallback_player = player
                break
        if not fallback_serial and usable:
            fallback_serial = usable[0][0]
            fallback_player = _find_player_by_serial(players, fallback_serial)
        if not fallback_serial and running_players:
            fallback_player = running_players[0]
            fallback_serial = _player_serial(fallback_player)

        extra: dict[str, Any] = {
            "serial": configured,
            "detail": raw_detail,
            "connected_devices": [serial for serial, state in rows if state == "device"],
        }
        if configured_player:
            extra["configured_index"] = _coerce_player_index(configured_player)
            extra["configured_running"] = _player_is_running(configured_player)
        else:
            extra["configured_index"] = self.vm_index
        if fallback_serial:
            extra["fallback_serial"] = fallback_serial
            extra["suggested_adb_addr"] = fallback_serial
        if fallback_player:
            extra["detected_index"] = _coerce_player_index(fallback_player)
            extra["detected_running"] = _player_is_running(fallback_player)

        if fallback_serial:
            msg = f"Configured ADB device is not connected; detected usable MuMu ADB at {fallback_serial}"
            if extra.get("detected_index") is not None:
                msg += f" (index {extra['detected_index']})"
            return _status("error", msg, **extra)
        return _status("error", "ADB device is not connected", **extra)

    def _adb_device_check(self) -> dict[str, Any]:
        try:
            connect_detail = ""
            state = self.run_adb(["get-state"], timeout=5)
            if state.returncode != 0:
                if ":" in self.adb_addr:
                    connect_detail = self._adb_connect_serial(self.adb_addr)
                    state = self.run_adb(["get-state"], timeout=5)
                    if state.returncode == 0 and state.stdout.strip() == "device":
                        booted = self.run_adb(["shell", "getprop", "sys.boot_completed"], timeout=5)
                        if booted.returncode == 0 and booted.stdout.strip() == "1":
                            return _status(
                                "ok",
                                "ADB device is ready after reconnect",
                                serial=self.adb_addr,
                                boot_completed=True,
                                reconnect=connect_detail,
                            )
                        return _status(
                            "warn",
                            "ADB device connected after reconnect but Android boot is not complete",
                            serial=self.adb_addr,
                            reconnect=connect_detail,
                        )
                rows = self._adb_device_rows()
                players = self._manager_info_rows()
                detail = _text(state)
                if connect_detail:
                    detail = f"{detail}; adb connect: {connect_detail}".strip("; ")
                return self._adb_mismatch_detail(
                    configured=self.adb_addr,
                    raw_detail=detail,
                    rows=rows,
                    players=players,
                )
            if state.stdout.strip() != "device":
                return _status("warn", f"ADB device state is {state.stdout.strip()!r}", serial=self.adb_addr)
            booted = self.run_adb(["shell", "getprop", "sys.boot_completed"], timeout=5)
            if booted.returncode == 0 and booted.stdout.strip() == "1":
                return _status("ok", "ADB device is ready", serial=self.adb_addr, boot_completed=True)
            return _status("warn", "ADB device connected but Android boot is not complete", serial=self.adb_addr)
        except Exception as exc:
            return _status("error", f"ADB device check failed: {exc}", serial=self.adb_addr)

    def _app_check(self) -> dict[str, Any]:
        package = self.app_package
        if not package:
            return _status("skipped", "No app package configured")
        if not self.adb_device_ready():
            return _status("skipped", "ADB device is not ready", package=package)
        if not self.adb_app_exists(package):
            return _status("error", "Configured app package is not installed", package=package)
        state = self.adb_app_state(package)
        return _status("ok" if state == "running" else "warn", f"App is {state}", package=package, running=state == "running")

    def _nemu_ipc_check(self, include_screenshot: bool) -> dict[str, Any]:
        if not include_screenshot:
            return _status("skipped", "Screenshot probe not requested")
        start = time.monotonic()
        try:
            from AutoScriptor.control.NemuIpc.device.method.nemu_ipc import NemuIpc

            nemu = NemuIpc(self.adb_addr)
            image = nemu.screenshot_nemu_ipc()
            nemu.nemu_ipc_release()
            shape = tuple(int(x) for x in getattr(image, "shape", ())[:2])
            return _status("ok", "NemuIpc screenshot succeeded", elapsed_ms=int((time.monotonic() - start) * 1000), shape=shape)
        except Exception as exc:
            return _status("error", f"NemuIpc screenshot failed: {exc}", elapsed_ms=int((time.monotonic() - start) * 1000))

    def _ocr_check(self) -> dict[str, Any]:
        module = sys.modules.get("AutoScriptor.recognition.ocr_rec")
        if module is None:
            return _status("skipped", "OCR module has not been loaded")

        try:
            manager = module.ocr_manager
            thread = getattr(manager, "_init_thread", None)
            ready = bool(manager.is_ready())
            initializing = bool(thread and thread.is_alive())
            if ready:
                return _status("ok", "OCR engine is ready", use_gpu=bool(module.ocr_config.get("use_gpu")))
            if initializing:
                return _status("warn", "OCR engine is still initializing", use_gpu=bool(module.ocr_config.get("use_gpu")))
            return _status("error", "OCR engine is not ready", use_gpu=bool(module.ocr_config.get("use_gpu")))
        except Exception as exc:
            return _status("error", f"OCR status check failed: {exc}")

    def _ui_map_check(self) -> dict[str, Any]:
        module = sys.modules.get("AutoScriptor.utils.ui_map")
        if module is None:
            return _status("skipped", "UI Map module has not been loaded")

        try:
            ui_manager = module.ui_manager
            thread = getattr(ui_manager, "_init_thread", None)
            initializing = bool(thread and thread.is_alive())
            count = len(getattr(ui_manager, "_ui", {}) or {})
            if count:
                return _status("ok", "UI Map is loaded", entries=count)
            if initializing:
                return _status("warn", "UI Map is still initializing", entries=count)
            return _status("error", "UI Map is empty", entries=count)
        except Exception as exc:
            return _status("error", f"UI Map status check failed: {exc}")

    @staticmethod
    def _overall(
        checks: dict[str, dict[str, Any]],
        include_screenshot: bool,
        *,
        require_app: bool,
    ) -> dict[str, Any]:
        blocking = ["adb", "adb_device"]
        if require_app:
            blocking.append("app")
        if include_screenshot:
            blocking.append("nemu_ipc")
        states = [checks.get(name, {}).get("status") for name in blocking]
        if "error" in states:
            return _status(
                "error",
                "Device is not ready for task execution" if require_app else "Device is not ready",
            )
        if "warn" in states:
            return _status("warn", "Device can be reached, but one or more layers need attention")
        return _status(
            "ok",
            "Device diagnostics passed" if not require_app else "Task execution diagnostics passed",
        )

    def diagnostics(self, *, include_screenshot: bool = False, require_app: bool = False) -> dict[str, Any]:
        checks = {
            "manager": self._manager_version_check(),
            "adb": self._adb_check(),
            "adb_device": self._adb_device_check(),
            "app": self._app_check(),
            "nemu_ipc": self._nemu_ipc_check(include_screenshot),
            "ocr": self._ocr_check(),
            "ui_map": self._ui_map_check(),
        }
        device_overall = self._overall(checks, include_screenshot, require_app=False)
        task_overall = self._overall(checks, include_screenshot, require_app=True)
        return {
            "generated_at": time.time(),
            "adb_addr": self.adb_addr,
            "emulator_index": self.vm_index,
            "require_app": bool(require_app),
            "checks": checks,
            "device_overall": device_overall,
            "task_overall": task_overall,
            "overall": task_overall if require_app else device_overall,
        }


def get_device_facade(*, vm_index: str | int | None = None) -> DeviceFacade:
    """Return a fresh facade so config changes are picked up immediately."""
    return DeviceFacade.from_config(vm_index=vm_index)
