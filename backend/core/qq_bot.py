"""Opt-in, project-local NapCat deployment. No game or global config imports."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import secrets
import shutil
import socket
import subprocess
import tempfile
import time
from urllib.request import Request, urlopen
import zipfile


# Reviewed upstream layout and config schema; upgrades must update this pair together.
VERSION = "v4.18.9"
ARCHIVE_NAME = "NapCat.Shell.Windows.Node.zip"
ARCHIVE_SHA256 = "234f2b9341d355d107881ce486d6699f529300d644282e25af452717d00a50da"
DOWNLOAD_URL = f"https://github.com/NapNeko/NapCatQQ/releases/download/{VERSION}/{ARCHIVE_NAME}"
BOT_ROOT = Path(__file__).resolve().parents[2] / ".autoscriptor" / "qq-bot"
REQUIRED_FILES = ("node.exe", "index.js", "wrapper.node", "QQNT.dll", "napcat/napcat.mjs")

# Where a QQ session and an access token must never live. A synced folder copies
# them to a server the user does not control, and a shared folder lets other
# accounts on the machine read them. Same-machine programs are out of scope:
# NapCat keeps its own session in plaintext by design, so locking only our copies
# would protect nothing that matters.
_UNSAFE_LOCATION_MARKERS = (
    "onedrive",
    "dropbox",
    "google drive",
    "googledrive",
    "icloud",
    "\\users\\public",
    "\\public\\",
)


def assert_private_location(root: Path | None = None) -> None:
    """Refuse a data root that other accounts or a cloud service can read."""
    root = root or BOT_ROOT
    text = str(root).lower()
    if text.startswith("\\\\"):
        raise OSError(f"机器人目录不能放在网络路径上：{root}")
    for marker in _UNSAFE_LOCATION_MARKERS:
        if marker in text:
            raise OSError(
                f"机器人目录位于同步盘或公共目录，QQ 登录态可能被复制出去：{root}\n"
                f"请把项目移动到本地普通目录（例如 D:\\Projects\\AutoScriptor-s）后重试。"
            )


def read_document(path: Path) -> dict:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"Expected a JSON object: {path.name}")
    return document


def write_document(path: Path, document: dict) -> None:
    path.write_text(json.dumps(document, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def load_local_settings(root: Path | None = None) -> dict | None:
    root = root or BOT_ROOT
    if not root.exists():
        return None
    if not all((root / filename).is_file() for filename in REQUIRED_FILES):
        raise ValueError("Local NapCat installation is incomplete; rerun scripts\\install.bat qq")
    settings = read_document(root / "autoscriptor.json")
    port = settings.get("http_port")
    web_port = settings.get("web_port")
    token = settings.get("access_token")
    if (
        not isinstance(settings.get("version"), str) or not settings["version"]
        or type(port) is not int or not 1024 <= port <= 65535
        or type(web_port) is not int or not 1024 <= web_port <= 65535 or port == web_port
        or not isinstance(token, str) or len(token) < 32
        or not token.isascii() or not token.isalnum()
    ):
        raise ValueError("Invalid local NapCat connection settings; refusing to expose the service")
    return settings


def cached_accounts(root: Path | None = None) -> list[str]:
    """QQ numbers that have logged in here before, so they can skip the QR code.

    NapCat writes ``napcat_<QQ>.json`` next to its shared config once a session
    exists. That file is the reliable signal -- far better than remembering what
    we last started, because it also reflects logins done through the panel.
    """
    root = root or BOT_ROOT
    config_directory = root / "napcat" / "config"
    if not config_directory.is_dir():
        return []
    accounts: list[str] = []
    for path in config_directory.glob("napcat_*.json"):
        number = path.stem[len("napcat_"):]
        # ``napcat_protocol_<QQ>.json`` shares the prefix; a session file is digits only.
        if number.isdigit():
            accounts.append(number)
    return sorted(accounts)


def remember_account(account: str, root: Path | None = None) -> None:
    """Record the account to quick-login next time."""
    root = root or BOT_ROOT
    settings = load_local_settings(root)
    if settings is None:
        raise ValueError("NapCat 尚未安装，无法记录账号")
    settings["account"] = str(account or "").strip()
    write_document(root / "autoscriptor.json", settings)


def remembered_account(root: Path | None = None) -> str:
    settings = load_local_settings(root)
    if settings is None:
        return ""
    return str(settings.get("account") or "").strip()


def webui_login_url(root: Path | None = None) -> str:
    """The panel URL that shows the login QR code."""
    root = root or BOT_ROOT
    settings = load_local_settings(root)
    if settings is None:
        raise ValueError("NapCat 尚未安装")
    document = read_document(root / "napcat" / "config" / "webui.json")
    return f"http://127.0.0.1:{settings['web_port']}/webui?token={document['token']}"


def _pid_file(root: Path) -> Path:
    return root / ".bot.pid"


def _bot_log(root: Path) -> Path:
    """Where the bot's own output goes, since it runs without a console."""
    return root / "bot.log"


def running_bot_pid(root: Path | None = None) -> int | None:
    """PID recorded in the pid file, or ``None`` if that process is gone.

    Only covers the detached path (``launch_bot``). The console path used to
    leave no record at all, so use :func:`bot_process_pid` when the question is
    "is a bot serving this installation".
    """
    root = root or BOT_ROOT
    path = _pid_file(root)
    if not path.is_file():
        return None
    try:
        pid = int(path.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return None
    # ``os.kill(pid, 0)`` is not a portable existence check: on Windows it raises
    # SystemError for a signal it does not implement. Opening the process and
    # closing the handle asks the same question without sending anything.
    import ctypes

    SYNCHRONIZE = 0x00100000
    handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
    if not handle:
        path.unlink(missing_ok=True)
        return None
    ctypes.windll.kernel32.CloseHandle(handle)
    return pid


def _listening_pid(port: int) -> int | None:
    """PID listening on ``127.0.0.1:<port>``, or ``None``.

    Parses ``netstat`` rather than importing ``psutil``: that package is only
    present as somebody else's dependency, and a bot that cannot be stopped when
    a transitive requirement moves is worse than a slightly ugly parse.
    """
    try:
        completed = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    suffix = f":{port}"
    for line in (completed.stdout or "").splitlines():
        parts = line.split()
        # TCP  127.0.0.1:3000  0.0.0.0:0  LISTENING  30836
        if len(parts) < 5 or parts[0].upper() != "TCP" or parts[3].upper() != "LISTENING":
            continue
        if not parts[1].endswith(suffix):
            continue
        if not parts[4].isdigit():
            continue
        return int(parts[4])
    return None


def _is_our_node_process(pid: int) -> bool:
    """Whether ``pid`` is a ``node.exe``.

    The bot is always ``<root>/node.exe``, so anything else holding our port is
    somebody else's program and must not be terminated on our behalf.
    """
    try:
        completed = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return "node.exe" in (completed.stdout or "").lower()


def listening_bot_pid(root: Path | None = None) -> int | None:
    """PID holding the bot's HTTP port, however the bot was started.

    The pid file is not enough on its own: a bot started from the console had no
    record, and a detached one leaves a stale file once the machine reboots. The
    listener is the fact both paths share.
    """
    settings = load_local_settings(root)
    if settings is None:
        return None
    pid = _listening_pid(settings["http_port"])
    if pid is None or not _is_our_node_process(pid):
        return None
    return pid


def bot_process_pid(root: Path | None = None) -> int | None:
    """PID of the bot serving this installation, or ``None``.

    Covers both start paths: the recorded pid first, then whoever holds the port.
    """
    return running_bot_pid(root) or listening_bot_pid(root)


def bot_is_running(root: Path | None = None) -> bool:
    """Whether the bot process is up.

    Process liveness only. This says nothing about whether QQ is logged in, and
    must not be presented as if it did: NapCat answers its own port before any
    account is through the QR flow.
    """
    return bot_process_pid(root) is not None


def launch_bot(
    root: Path | None = None,
    account: str = "",
    *,
    visible: bool = False,
) -> int:
    """Start the bot in its own process and return immediately.

    ``account`` selects NapCat's ``-q`` quick login, which is what makes the
    second and later starts need no QR code at all.
    """
    root = root or BOT_ROOT
    settings = load_local_settings(root)
    if settings is None:
        raise ValueError("NapCat 尚未安装，先运行一键设置")
    if running_bot_pid(root) is not None:
        raise OSError("机器人已经在运行")
    for port in (settings["http_port"], settings["web_port"]):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                raise OSError(f"端口 {port} 被占用，机器人可能已在运行") from None

    command = [str(root / "node.exe"), str(root / "index.js")]
    if account.strip():
        command += ["-q", account.strip()]
    environment = os.environ.copy()
    # The upstream fork branch passes Electron-only --no-sandbox to Node.
    environment["NAPCAT_DISABLE_MULTI_PROCESS"] = "1"

    creation_flags = subprocess.CREATE_NEW_CONSOLE if visible else subprocess.CREATE_NO_WINDOW
    log_path = _bot_log(root)
    # Without a console the output needs somewhere to go: an inherited pipe would
    # fill up and block the bot, and printing to the caller's terminal makes the
    # setup output unreadable. Truncate rather than append so it stays one run.
    with open(log_path, "wb") as log:
        process = subprocess.Popen(  # noqa: S603 - fixed executable, fixed arguments
            command, cwd=root, env=environment, creationflags=creation_flags,
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
        )
    _pid_file(root).write_text(str(process.pid), encoding="ascii")
    return process.pid


def ensure_bot_running(root: Path | None = None) -> bool:
    """Start the local bot with its cached QQ session when it is not running."""
    root = root or BOT_ROOT
    if load_local_settings(root) is None or bot_is_running(root):
        return False
    account = remembered_account(root) or next(iter(cached_accounts(root)), "")
    if not account:
        return False
    launch_bot(root, account=account)
    return True


def stop_bot(root: Path | None = None) -> bool:
    """Terminate the bot serving this installation. Returns whether it stopped.

    Both start paths and the orphan case are covered. Relying on the pid file
    alone made this a silent no-op for a console-started bot: it reported "not
    running", left the port held, and every later start failed with "端口被占用"
    -- a loop the user cannot get out of.
    """
    root = root or BOT_ROOT
    pid = bot_process_pid(root)
    if pid is None:
        return False
    # /T so the QQ runtime child process goes with it; /F because the bot has no
    # shutdown channel of its own.
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                   capture_output=True, text=True, encoding="utf-8", errors="replace")
    _pid_file(root).unlink(missing_ok=True)
    return True


def local_notification_settings(root: Path | None = None) -> dict:
    settings = load_local_settings(root)
    if settings is None:
        raise ValueError("Local NapCat is not installed; run scripts\\install.bat qq")
    return {
        "endpoint": f"http://127.0.0.1:{settings['http_port']}",
        "access_token": settings["access_token"],
    }


def local_installation_status(root: Path | None = None) -> dict:
    """What the WebUI may show about the managed install.

    ``running`` is process liveness only -- whether a bot is serving the
    configured port. It deliberately says nothing about the QQ login, because
    NapCat answers that port before anyone is through the QR flow, and claiming
    "logged in" from it would be a guess. Never includes either token.
    """
    settings = load_local_settings(root)
    if settings is None:
        return {"installed": False}
    return {
        "installed": True,
        "version": settings["version"],
        "running": bot_is_running(root),
        "login_url": f"http://127.0.0.1:{settings['web_port']}",
    }


def choose_port(preferred: int, excluded: set[int]) -> int:
    for port in range(preferred, preferred + 100):
        if port in excluded:
            continue
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
        return port
    raise OSError(f"No free loopback port near {preferred}")


def verify_archive(archive: Path, expected_digest: str = ARCHIVE_SHA256) -> None:
    digest = hashlib.sha256()
    with archive.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected_digest:
        raise ValueError("NapCat SHA256 mismatch; download will not be installed or executed")


def extract_archive(archive: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive) as package:
        if sum(member.file_size for member in package.infolist()) > 2 * 1024**3:
            raise ValueError("Unexpectedly large NapCat archive")
        for member in package.infolist():
            normalized = member.filename.replace("\\", "/")
            path = PurePosixPath(normalized)
            if path.is_absolute() or ".." in path.parts or ":" in normalized:
                raise ValueError("Unsafe path in NapCat archive")
            if (member.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("Symbolic links are not allowed in NapCat archive")
        package.extractall(destination)


def prepare_configuration(root: Path, http_port: int, web_port: int) -> None:
    config_directory = root / "napcat" / "config"
    config_directory.mkdir(parents=True, exist_ok=True)
    access_token = secrets.token_hex(32)
    write_document(config_directory / "onebot11.json", {
        "network": {
            "httpServers": [{
                "name": "AutoScriptor", "enable": True,
                "host": "127.0.0.1", "port": http_port,
                "token": access_token, "enableCors": False,
                "enableWebsocket": False, "messagePostFormat": "array", "debug": False,
            }],
            "httpSseServers": [], "httpClients": [], "websocketServers": [],
            "websocketClients": [], "plugins": [],
        },
    })
    write_document(config_directory / "webui.json", {
        "host": "127.0.0.1", "port": web_port,
        "token": secrets.token_hex(32), "autoLoginAccount": "",
        "disableWebUI": False, "enableXForwardedFor": False,
    })
    write_document(root / "autoscriptor.json", {
        "version": VERSION, "http_port": http_port, "web_port": web_port,
        "access_token": access_token,
    })


def install_bot(root: Path | None = None) -> None:
    root = root or BOT_ROOT
    if load_local_settings(root) is not None:
        print("NapCat already installed; preserving ports, tokens and login data.")
        return
    if os.name != "nt" or os.environ.get("PROCESSOR_ARCHITECTURE", "").lower() != "amd64":
        raise OSError("This NapCat package requires Windows x64")
    root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="qq-install-", dir=root.parent) as temporary:
        staging = Path(temporary)
        archive = staging / ARCHIVE_NAME
        print(f"Downloading official NapCat {VERSION} (about 112 MiB)...", flush=True)
        request = Request(DOWNLOAD_URL, headers={"User-Agent": "AutoScriptor-QQ-Setup"})
        with urlopen(request, timeout=60) as response, archive.open("wb") as output:
            shutil.copyfileobj(response, output)
        verify_archive(archive)
        extracted = staging / "unpacked"
        extract_archive(archive, extracted)
        # Official archives can wrap the runtime in one top-level directory.
        candidates = [extracted] + [entry for entry in extracted.iterdir() if entry.is_dir()]
        runtime = next((entry for entry in candidates if all(
            (entry / filename).is_file() for filename in REQUIRED_FILES
        )), None)
        if runtime is None:
            raise ValueError("NapCat archive layout changed; refusing partial installation")
        validate_native_runtime(runtime)
        http_port = choose_port(3000, set())
        web_port = choose_port(6099, {http_port})
        prepare_configuration(runtime, http_port, web_port)
        # No existing runtime is replaced. A failed download never becomes an installation.
        publish_runtime(runtime, root)
    print("NapCat installed. Start with scripts\\run.bat qq, then scan the login QR code.")
    print("In WebUI > QQ notifications, use the local robot and enter your recipient.")


def validate_native_runtime(root: Path) -> None:
    """Load the QQ native addon without creating a QQ session or logging in."""
    # Loading QQ's addon can keep native handles alive even without a login session.
    probe = "process.dlopen({exports: {}}, process.argv[1]); console.log('Native runtime ready'); process.exit(0)"
    try:
        result = subprocess.run(
            [str(root / "node.exe"), "-e", probe, str(root / "wrapper.node")],
            cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
        )
    except subprocess.TimeoutExpired:
        raise OSError("NapCat native runtime validation timed out; installation was not accepted") from None
    if result.returncode != 0:
        raise OSError(f"NapCat native runtime validation failed: {result.stderr.strip()[:1500]}")
    print("NapCat native runtime validated (no QQ login).", flush=True)


def publish_runtime(staging: Path, destination: Path) -> None:
    # Windows scanners can briefly hold newly extracted executables/directories.
    for attempt in range(5):
        try:
            staging.rename(destination)
            return
        except PermissionError as error:
            if getattr(error, "winerror", None) != 5 or attempt == 4 or destination.exists():
                raise
            time.sleep(0.25 * 2**attempt)


@contextmanager
def lock_bot(root: Path):
    import msvcrt

    with (root / ".run.lock").open("a+b") as lock_file:
        lock_file.seek(0)
        try:
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise OSError("Local NapCat is already starting or running; use its existing window") from None
        try:
            yield
        finally:
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)


def start_bot(root: Path | None = None) -> int:
    root = root or BOT_ROOT
    settings = load_local_settings(root)
    if settings is None:
        raise ValueError("Run scripts\\install.bat qq first")
    account = remembered_account(root)
    with lock_bot(root):
        for port in (settings["http_port"], settings["web_port"]):
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", port))
        if account:
            print(f"Quick login as {account}; no QR code needed.", flush=True)
        else:
            print(f"No remembered account. Scan at {webui_login_url(root)}", flush=True)
        print("Keep this window open. Close it to stop the robot.", flush=True)
        environment = os.environ.copy()
        # The upstream fork branch passes Electron-only --no-sandbox to Node.
        environment["NAPCAT_DISABLE_MULTI_PROCESS"] = "1"
        command = [str(root / "node.exe"), str(root / "index.js")]
        if account:
            command += ["-q", account]
        # Popen rather than call: this window has to keep running anyway, and
        # recording the child pid is what makes "stop" able to find the bot this
        # path started. Without it, stop reported "not running" while the port
        # stayed held, and every later start failed as occupied.
        process = subprocess.Popen(command, cwd=root, env=environment)  # noqa: S603
        _pid_file(root).write_text(str(process.pid), encoding="ascii")
        try:
            return process.wait()
        finally:
            # The child is gone, so the record would only mislead the next caller.
            _pid_file(root).unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "start", "stop", "status", "accounts"))
    arguments = parser.parse_args()
    try:
        if arguments.action == "install":
            install_bot()
        elif arguments.action == "start":
            return start_bot()
        elif arguments.action == "stop":
            print("stopped" if stop_bot() else "not running")
        elif arguments.action == "accounts":
            print(json.dumps({
                "cached": cached_accounts(),
                "remembered": remembered_account(),
                "running_pid": running_bot_pid(),
            }, ensure_ascii=False))
        else:
            print(json.dumps(local_installation_status()))
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        print(f"QQ robot setup failed: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
