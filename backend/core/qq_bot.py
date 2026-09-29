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


def local_notification_settings(root: Path | None = None) -> dict:
    settings = load_local_settings(root)
    if settings is None:
        raise ValueError("Local NapCat is not installed; run scripts\\install.bat qq")
    return {
        "endpoint": f"http://127.0.0.1:{settings['http_port']}",
        "access_token": settings["access_token"],
    }


def local_installation_status(root: Path | None = None) -> dict:
    settings = load_local_settings(root)
    if settings is None:
        return {"installed": False}
    return {
        "installed": True,
        "version": settings["version"],
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
    with lock_bot(root):
        for port in (settings["http_port"], settings["web_port"]):
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", port))
        print(f"NapCat login: http://127.0.0.1:{settings['web_port']}", flush=True)
        print("Use the token in napcat/config/webui.json if prompted. Keep this window open.", flush=True)
        environment = os.environ.copy()
        # The upstream fork branch passes Electron-only --no-sandbox to Node.
        environment["NAPCAT_DISABLE_MULTI_PROCESS"] = "1"
        return subprocess.call(
            [str(root / "node.exe"), str(root / "index.js")], cwd=root, env=environment,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "start", "status"))
    arguments = parser.parse_args()
    try:
        if arguments.action == "install":
            install_bot()
        elif arguments.action == "start":
            return start_bot()
        else:
            print(json.dumps(local_installation_status()))
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        print(f"QQ robot setup failed: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
