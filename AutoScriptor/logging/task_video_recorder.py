"""Task-level debug video: rolling ADB screenrecord segments.

Why segments instead of one recording: Android's ``screenrecord`` caps a single
run at 180 seconds and *refuses to start at all* when ``--time-limit`` is
outside 1..180. One recording therefore only ever covers the opening minutes,
while a failure worth recording usually happens later. This recorder keeps a
short rolling window instead -- a new segment every ``segment_seconds``, only
the newest ``keep_segments`` retained -- so the archive carries the minutes
right before the failure.

Each segment is allowed to end on its own ``--time-limit`` so ``screenrecord``
finalises the MP4 before the next one starts; only the final segment is cut
short, and even then the device is given a grace period to finish writing
before anything is pulled. Pulled files are checked for decodability, because a
truncated MP4 is worse than no file: it looks like evidence and opens as none.

Capture goes through ADB, which keeps it off the Nemu IPC lane used by
recognition and input.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import cv2

from AutoScriptor.control.MumuAdaptor.api.adb.direct import adb_base_args
from AutoScriptor.logging.logger import logger
from AutoScriptor.utils.paths import get_logs_root

ENABLE_TASK_VIDEO_RECORDING = True

# Must stay strictly inside screenrecord's 1..180 window; the margin leaves the
# encoder room to finalise the file before the next segment starts.
_SEGMENT_SECONDS = 165
# Rotation wakes just after the device should have ended the segment on its
# own, so the gap between two segments stays around a second instead of four.
_ROTATE_MARGIN_S = 1
_KEEP_SEGMENTS = 3

_DEVICE_DIR = "/sdcard/autoscriptor_task_video"
_STARTUP_PROBE_S = 0.8
_DEVICE_IDLE_TIMEOUT_S = 6.0
_ADB_TIMEOUT_S = 30


class TaskVideoRecorder:
    """Records a task in rolling segments and keeps the newest few on failure."""

    def __init__(
        self,
        task_path: str,
        *,
        enabled: bool = ENABLE_TASK_VIDEO_RECORDING,
        segment_seconds: int = _SEGMENT_SECONDS,
        keep_segments: int = _KEEP_SEGMENTS,
    ):
        self.task_path = task_path
        self.enabled = bool(enabled) and ENABLE_TASK_VIDEO_RECORDING
        self.segment_seconds = min(180, max(1, int(segment_seconds)))
        self.keep_segments = max(1, int(keep_segments))
        # 设备端路径，旧→新。
        self.segments: list[str] = []
        self.local_dir: Path | None = None
        self._run_id = f"{int(time.time())}_{os.getpid()}"
        self._segment_index = 0
        self._proc: subprocess.Popen | None = None
        self._current_device_path: str | None = None
        self._lock = threading.RLock()
        self._stopped = threading.Event()
        self._rotate_thread: threading.Thread | None = None

    # ── Lifecycle ──

    def start(self) -> "TaskVideoRecorder":
        """Start the first segment synchronously, then rotate in the background."""
        if not self.enabled:
            return self
        self._reset_device_dir()
        if not self._start_segment():
            return self
        self._rotate_thread = threading.Thread(
            target=self._rotate_loop,
            name="task-video-rotate",
            daemon=True,
        )
        self._rotate_thread.start()
        logger.info(
            "debug video recording started: %s (%ss per segment, newest %s kept)",
            self.task_path,
            self.segment_seconds,
            self.keep_segments,
        )
        return self

    def stop(self, *, keep: bool) -> Path | None:
        """Stop recording; pull the retained segments when ``keep`` is set.

        Never raises. Failure paths call this while the task's own exception is
        in flight, so a broken recorder must not replace the real error, and the
        device-side cleanup has to run no matter where pulling fails.
        """
        if not self.enabled:
            return None
        self._stopped.set()
        try:
            if self._rotate_thread is not None:
                self._rotate_thread.join(timeout=self.segment_seconds + _ROTATE_MARGIN_S)
                self._rotate_thread = None
            self._finish_current_segment()
            if keep:
                self.local_dir = self._pull_segments()
        except Exception as exc:
            logger.warning("debug video stop failed: %s", exc)
        finally:
            self.cleanup_device()
            if not keep:
                self.cleanup_local()
        return self.local_dir

    def cleanup_local(self) -> None:
        """Drop the pulled copy; the archive keeps its own."""
        if self.local_dir and self.local_dir.exists():
            try:
                shutil.rmtree(self.local_dir)
            except OSError as exc:
                logger.warning("debug video cleanup failed: %s", exc)
        self.local_dir = None

    def cleanup_device(self) -> None:
        self._clear_device_dir()

    # ── Segments ──

    def _segment_device_path(self) -> str:
        self._segment_index += 1
        return f"{_DEVICE_DIR}/{self._run_id}_{self._segment_index:03d}.mp4"

    def _start_segment(self) -> bool:
        """Start one screenrecord segment; report why when it refuses to run."""
        device_path = self._segment_device_path()
        command = [
            "shell",
            "screenrecord",
            "--time-limit",
            str(self.segment_seconds),
            "--size",
            "640x360",
            "--bit-rate",
            "500000",
            device_path,
        ]
        try:
            process = subprocess.Popen(
                adb_base_args() + command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("debug video segment start failed: %s", exc)
            return False

        # screenrecord validates its arguments up front and exits immediately on
        # rejection, so an early exit here is the difference between "no video"
        # and a reason the user can act on.
        time.sleep(_STARTUP_PROBE_S)
        if process.poll() is not None:
            reason = ""
            try:
                reason = (process.stdout.read() or "").strip()
            except (OSError, ValueError):
                pass
            logger.warning(
                "debug video segment exited immediately (rc=%s): %s",
                process.returncode,
                reason or "screenrecord 未给出原因",
            )
            return False

        with self._lock:
            self._proc = process
            self._current_device_path = device_path
            self.segments.append(device_path)
        self._trim_device_segments()
        return True

    def _finish_current_segment(self) -> None:
        """End the running segment and wait for the device to finalise its MP4."""
        with self._lock:
            process = self._proc
            self._proc = None
            self._current_device_path = None
        if process is None:
            return
        if process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
            except (OSError, subprocess.SubprocessError) as exc:
                logger.warning("debug video stop failed: %s", exc)
        try:
            if process.stdout is not None:
                process.stdout.close()
        except (OSError, ValueError):
            pass
        self._wait_for_device_idle()

    def _rotate_loop(self) -> None:
        while not self._stopped.wait(self.segment_seconds + _ROTATE_MARGIN_S):
            self._finish_current_segment()
            if self._stopped.is_set():
                return
            if not self._start_segment():
                logger.warning("debug video rotation stopped: 无法启动新的分段")
                return

    def _trim_device_segments(self) -> None:
        """Delete older device segments so /sdcard keeps only the newest few."""
        stale = self.segments[: -self.keep_segments]
        if not stale:
            return
        self.segments = self.segments[-self.keep_segments :]
        for path in stale:
            try:
                self._adb(["shell", "rm", "-f", path], timeout=10)
            except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
                logger.debug("debug video segment cleanup failed: %s (%s)", path, exc)

    # ── Pulling ──

    def _pull_segments(self) -> Path | None:
        if not self.segments:
            logger.warning("debug video unavailable: 设备上没有任何分段")
            return None

        base_dir = get_logs_root() / "task_video"
        base_dir.mkdir(parents=True, exist_ok=True)
        # mkdtemp keeps a retry's pull from reusing the previous attempt's
        # directory when both happen within the same second.
        local_dir = Path(
            tempfile.mkdtemp(dir=base_dir, prefix=f"{int(time.time())}_task_record_")
        )
        pulled: list[Path] = []
        for index, device_path in enumerate(self.segments, start=1):
            local_path = local_dir / f"segment_{index:03d}.mp4"
            if not self._pull_one(device_path, local_path):
                continue
            if not _is_decodable(local_path):
                # Keep it: a damaged but present file still tells the user the
                # recording ran, and some players recover more than OpenCV does.
                logger.warning("debug video segment is not decodable: %s", local_path)
            pulled.append(local_path)

        if not pulled:
            try:
                local_dir.rmdir()
            except OSError:
                pass
            return None
        logger.info("debug video saved: %s (%s segment(s))", local_dir, len(pulled))
        return local_dir

    def _pull_one(self, device_path: str, local_path: Path) -> bool:
        try:
            self._adb(["pull", device_path, str(local_path)], timeout=_ADB_TIMEOUT_S)
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            logger.warning("debug video pull failed: %s (%s)", device_path, exc)
            return False
        try:
            return local_path.is_file() and local_path.stat().st_size > 0
        except OSError:
            return False

    # ── Device helpers ──

    def _reset_device_dir(self) -> None:
        """Clear leftovers, then recreate the directory screenrecord writes into.

        screenrecord does not create missing parent directories; without the
        mkdir it exits at once with "No such file or directory" and no video.
        """
        self._clear_device_dir()
        try:
            self._adb(["shell", "mkdir", "-p", _DEVICE_DIR], timeout=10)
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            logger.warning("debug video device dir unavailable: %s", exc)

    def _clear_device_dir(self) -> None:
        try:
            self._adb(["shell", "rm", "-rf", _DEVICE_DIR], timeout=10)
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            logger.debug("debug video device cleanup failed: %s", exc)

    def _wait_for_device_idle(self) -> None:
        """Give screenrecord time to finish writing before the file is pulled."""
        deadline = time.monotonic() + _DEVICE_IDLE_TIMEOUT_S
        while time.monotonic() < deadline:
            try:
                result = self._adb(["shell", "pidof", "screenrecord"], timeout=10)
            except (OSError, RuntimeError, subprocess.SubprocessError):
                return
            if not result.stdout.strip():
                return
            time.sleep(0.3)

    @staticmethod
    def _adb(args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            adb_base_args() + args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
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
    """Copy a pulled recording into the archive.

    ``video_path`` is either a segment directory (current layout) or a single
    file (older archives and manual captures).
    """
    if not video_path:
        return None
    source = Path(video_path)

    if source.is_dir():
        segments = sorted(p for p in source.glob("*.mp4") if p.is_file())
        if not segments:
            return None
        destination = archive_dir / "task_video"
        destination.mkdir(parents=True, exist_ok=True)
        for segment in segments:
            try:
                shutil.copy2(segment, destination / segment.name)
            except OSError as exc:
                logger.warning("copy debug video failed: %s (%s)", segment, exc)
        return destination if any(destination.iterdir()) else None

    if source.is_file():
        destination = archive_dir / "task_record.mp4"
        try:
            shutil.copy2(source, destination)
            return destination
        except OSError as exc:
            logger.warning("copy debug video failed: %s (%s)", source, exc)
    return None


def _is_decodable(path: Path) -> bool:
    """Whether OpenCV can open the file and read an actual frame from it."""
    capture = None
    try:
        capture = cv2.VideoCapture(str(path))
        if not capture.isOpened():
            return False
        ok, frame = capture.read()
        return bool(ok) and frame is not None
    except cv2.error:
        return False
    finally:
        if capture is not None:
            capture.release()
