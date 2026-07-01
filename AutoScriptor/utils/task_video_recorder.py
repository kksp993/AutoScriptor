"""Task-level debug video recording helper.

This helper is intentionally detachable: keep the hardcoded switch here and
mount it from TaskManager only. It uses ADB screenrecord so it does not compete
with the NemuIpc screenshot lane used by recognition and controls.
"""
from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

from AutoScriptor.control.MumuAdaptor.api.adb.direct import adb_base_args
from AutoScriptor.utils.logger import logger
from AutoScriptor.utils.paths import get_logs_root

ENABLE_TASK_VIDEO_RECORDING = True
_DEVICE_VIDEO_PATH = "/sdcard/autoscriptor_task_record.mp4"


class TaskVideoRecorder:
    def __init__(self, task_path: str, *, enabled: bool = ENABLE_TASK_VIDEO_RECORDING):
        self.task_path = task_path
        self.enabled = enabled
        self.proc: subprocess.Popen | None = None
        self.local_path: Path | None = None
        self.device_path = _DEVICE_VIDEO_PATH

    def start(self) -> "TaskVideoRecorder":
        if not self.enabled:
            return self
        try:
            self._adb(["shell", "rm", "-f", self.device_path], timeout=5)
            self.proc = subprocess.Popen(
                adb_base_args() + [
                    "shell", "screenrecord", "--size", "640x360", "--bit-rate", "500000", self.device_path,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            logger.info("debug video recording started: %s", self.task_path)
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("debug video recording start failed: %s", exc)
            self.proc = None
        return self

    def stop(self, *, keep: bool) -> Path | None:
        if not self.enabled:
            return None
        self._stop_process()
        if keep:
            self.local_path = self._pull_video()
        self.cleanup_device()
        if not keep:
            self.cleanup_local()
        return self.local_path

    def cleanup_local(self) -> None:
        if self.local_path and self.local_path.exists():
            try:
                self.local_path.unlink()
            except OSError as exc:
                logger.warning("debug video cleanup failed: %s", exc)
        self.local_path = None

    def cleanup_device(self) -> None:
        try:
            self._adb(["shell", "rm", "-f", self.device_path], timeout=5)
        except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
            logger.debug("debug video device cleanup failed: %s", exc)

    def _stop_process(self) -> None:
        if self.proc is None:
            return
        if self.proc.poll() is None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)
            except (OSError, subprocess.SubprocessError) as exc:
                logger.warning("debug video stop failed: %s", exc)
        self.proc = None
        time.sleep(0.2)

    def _pull_video(self) -> Path | None:
        out_dir = get_logs_root() / "task_video"
        out_dir.mkdir(parents=True, exist_ok=True)
        local = out_dir / f"{int(time.time())}_task_record.mp4"
        try:
            self._adb(["pull", self.device_path, str(local)], timeout=30)
            if local.is_file() and local.stat().st_size > 0:
                logger.info("debug video saved: %s", local)
                return local
        except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
            logger.warning("debug video pull failed: %s", exc)
        try:
            local.unlink()
        except OSError:
            pass
        return None

    @staticmethod
    def _adb(args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            adb_base_args() + args,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout or "").strip())
        return result


def new_task_video_recorder(task_path: str, enabled: bool) -> TaskVideoRecorder | None:
    if not enabled or not ENABLE_TASK_VIDEO_RECORDING:
        return None
    return TaskVideoRecorder(task_path).start()


def copy_video_to_archive(video_path: str | Path | None, archive_dir: Path) -> Path | None:
    if not video_path:
        return None
    src = Path(video_path)
    if not src.is_file():
        return None
    dst = archive_dir / "task_record.mp4"
    try:
        shutil.copy2(src, dst)
        return dst
    except OSError as exc:
        logger.warning("copy debug video failed: %s (%s)", src, exc)
        return None
