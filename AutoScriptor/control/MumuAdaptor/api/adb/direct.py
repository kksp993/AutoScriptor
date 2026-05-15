import subprocess


def adb_base_args() -> list[str]:
    from AutoScriptor.utils.app_config import cfg

    emulator = cfg["emulator"]
    args = [emulator["adb_path"]]
    addr = str(emulator.get("adb_addr", "") or "").strip()
    if addr:
        args.extend(["-s", addr])
    return args


def run_adb(args: list[str], timeout: int = 10):
    return subprocess.run(
        adb_base_args() + args,
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
    )


def adb_device_ready() -> bool:
    try:
        state = run_adb(["get-state"], timeout=5)
        if state.returncode != 0 or state.stdout.strip() != "device":
            return False
        booted = run_adb(["shell", "getprop", "sys.boot_completed"], timeout=5)
        return booted.returncode == 0 and booted.stdout.strip() == "1"
    except (OSError, subprocess.SubprocessError):
        return False


def configured_adb_host_port() -> tuple[str, str] | None:
    from AutoScriptor.utils.app_config import cfg

    addr = str(cfg["emulator"].get("adb_addr", "") or "").strip()
    if ":" not in addr:
        return None
    host, port = addr.rsplit(":", 1)
    if not host or not port:
        return None
    return host, port
