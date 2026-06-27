"""Source Git updater.

This channel is intentionally limited to source checkouts: fetch origin/main,
compare it with HEAD, then fast-forward by pulling origin main. Dependency
installation stays explicit in scripts/install.*.
"""
from __future__ import annotations

import os
import subprocess
import threading

from AutoScriptor.utils.logger import logger
from AutoScriptor.utils.paths import get_app_root


UPDATE_REMOTE = "origin"
UPDATE_BRANCH = "main"


class GitCommandError(RuntimeError):
    pass


class Updater:
    """管理源码 Git 仓库的更新检查与执行。"""

    def __init__(self):
        self._root = str(get_app_root())
        self._git = self._find_git()
        self._unavailable_reason = ""
        self.state = "idle"
        self.changelog = ""
        self.current_version = ""
        self.remote_version = ""
        self.remote_branch = UPDATE_BRANCH
        self.ahead_count = 0
        self.behind_count = 0
        self.last_error = ""
        self._restart_event = None  # multiprocessing.Event，由 services/webui/gui.py 传入

    def _find_git(self) -> str:
        for candidate in ["git.exe", "git"]:
            try:
                result = subprocess.run(
                    [candidate, "--version"],
                    capture_output=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    return candidate
            except (OSError, subprocess.SubprocessError):
                continue
        return ""

    def _git_cmd(self, *args) -> list[str]:
        if not self._git:
            raise GitCommandError("git not found. Install Git for Windows first.")
        safe_root = os.path.abspath(self._root).replace("\\", "/")
        return [self._git, "-c", f"safe.directory={safe_root}", *args]

    @staticmethod
    def _git_failure_text(args, result) -> str:
        detail = (result.stderr or result.stdout or "").strip()
        suffix = f": {detail}" if detail else ""
        return f"git {' '.join(args)} failed with exit code {result.returncode}{suffix}"

    def _run_git(self, *args, timeout: int = 30) -> str:
        cmd = self._git_cmd(*args)
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=self._root,
                timeout=timeout,
            )
            if result.returncode != 0:
                raise GitCommandError(self._git_failure_text(args, result))
            return result.stdout.strip()
        except subprocess.TimeoutExpired as e:
            raise GitCommandError(f"git {' '.join(args)} timed out after {timeout}s") from e
        except OSError as e:
            raise GitCommandError(f"git {' '.join(args)} failed to start: {e}") from e

    def _git_update_available(self) -> bool:
        """当前运行目录是否真的可执行源码 Git 更新。"""
        self._unavailable_reason = ""
        if not self._git:
            self._unavailable_reason = "git not found. Install Git for Windows first."
            return False
        if not os.path.isdir(self._root):
            self._unavailable_reason = f"项目根目录不存在: {self._root}"
            return False
        if not os.path.isdir(os.path.join(self._root, ".git")):
            self._unavailable_reason = "当前目录不是 Git 工作区，源码更新不可用。"
            return False
        try:
            self._run_git("rev-parse", "--is-inside-work-tree", timeout=5)
        except GitCommandError as e:
            self._unavailable_reason = str(e)
            return False
        return True

    def _current_commit(self) -> str:
        return self._run_git("rev-parse", "--short", "HEAD")

    def _current_branch(self) -> str:
        return self._run_git("rev-parse", "--abbrev-ref", "HEAD")

    def get_current_commit(self) -> str:
        if not self._git_update_available():
            return ""
        return self._current_commit()

    def get_current_branch(self) -> str:
        if not self._git_update_available():
            return ""
        return self._current_branch()

    def _ensure_attached_branch(self) -> str:
        branch = self._current_branch().strip()
        if not branch or branch == "HEAD":
            raise GitCommandError("Detached HEAD is not supported by source Git updater.")
        return branch

    def _target_ref(self) -> str:
        return f"{UPDATE_REMOTE}/{UPDATE_BRANCH}"

    def _fetch_target(self) -> None:
        self._run_git("fetch", UPDATE_REMOTE, UPDATE_BRANCH, timeout=60)

    def _ahead_behind(self, target_ref: str) -> tuple[int, int]:
        output = self._run_git(
            "rev-list",
            "--left-right",
            "--count",
            f"HEAD...{target_ref}",
            timeout=10,
        )
        parts = output.replace("\t", " ").split()
        if len(parts) != 2:
            raise GitCommandError(f"git rev-list returned unexpected ahead/behind output: {output}")
        try:
            return int(parts[0]), int(parts[1])
        except ValueError as e:
            raise GitCommandError(f"git rev-list returned invalid ahead/behind output: {output}") from e

    @staticmethod
    def _diverged_message(branch: str, target_ref: str, ahead: int, behind: int) -> str:
        return (
            f"Local branch {branch} and {target_ref} have diverged: "
            f"local ahead {ahead} commit(s), behind {behind}. Resolve with Git manually."
        )

    # ── 检查更新 ──

    def check_update(self) -> bool:
        if not self._git_update_available():
            self.state = "disabled"
            self.last_error = self._unavailable_reason
            self.remote_version = ""
            self.changelog = ""
            self.ahead_count = 0
            self.behind_count = 0
            return False

        if self.state == "checking":
            return False

        self.state = "checking"
        self.last_error = ""
        self.changelog = ""
        self.ahead_count = 0
        self.behind_count = 0
        try:
            branch = self._ensure_attached_branch()
        except GitCommandError as e:
            self.state = "failed"
            self.last_error = str(e)
            return False

        try:
            self._fetch_target()
        except GitCommandError as e:
            self.state = "failed"
            self.last_error = str(e)
            logger.warning(f"git fetch 失败: {self.last_error}")
            return False

        target_ref = self._target_ref()
        try:
            local = self._run_git("rev-parse", "HEAD")
            remote = self._run_git("rev-parse", target_ref)
            ahead, behind = self._ahead_behind(target_ref)
        except GitCommandError as e:
            self.state = "failed"
            self.last_error = str(e)
            return False

        self.current_version = local[:8]
        self.remote_version = remote[:8]
        self.ahead_count = ahead
        self.behind_count = behind

        if local == remote or behind == 0:
            self.state = "idle"
            self.changelog = ""
            return False

        if ahead > 0 and behind > 0:
            self.state = "failed"
            self.changelog = ""
            self.last_error = self._diverged_message(branch, target_ref, ahead, behind)
            return False

        try:
            self.changelog = self._run_git(
                "log",
                "--oneline",
                "--no-merges",
                f"HEAD..{target_ref}",
                "--max-count=20",
            )
        except GitCommandError as e:
            self.state = "failed"
            self.last_error = str(e)
            return False
        self.state = "available"
        logger.info(f"发现源码更新: {self.current_version} -> {self.remote_version}")
        return True

    # ── 执行更新 ──

    def run_update(self) -> bool:
        if not self._git_update_available():
            self.state = "disabled"
            self.last_error = self._unavailable_reason
            return False

        if self.state not in ("available", "failed", "idle"):
            return False

        self.state = "updating"
        self.last_error = ""
        self.changelog = ""
        try:
            branch = self._ensure_attached_branch()
        except GitCommandError as e:
            self.state = "failed"
            self.last_error = str(e)
            return False

        try:
            status = self._run_git("status", "--porcelain", timeout=10)
        except GitCommandError as e:
            self.state = "failed"
            self.last_error = str(e)
            return False
        if status.strip():
            self.state = "failed"
            self.last_error = "Working tree has local changes. Commit or clean them before updating."
            return False

        try:
            self._fetch_target()
        except GitCommandError as e:
            self.state = "failed"
            self.last_error = str(e)
            return False

        target_ref = self._target_ref()
        try:
            local = self._run_git("rev-parse", "HEAD")
            remote = self._run_git("rev-parse", target_ref)
            ahead, behind = self._ahead_behind(target_ref)
        except GitCommandError as e:
            self.state = "failed"
            self.last_error = str(e)
            return False

        self.current_version = local[:8]
        self.remote_version = remote[:8]
        self.ahead_count = ahead
        self.behind_count = behind

        if ahead > 0 and behind > 0:
            self.state = "failed"
            self.last_error = self._diverged_message(branch, target_ref, ahead, behind)
            return False

        if local == remote or behind == 0:
            self.state = "done"
            return True

        try:
            self._run_git("pull", "--ff-only", UPDATE_REMOTE, UPDATE_BRANCH, timeout=120)
            local = self._run_git("rev-parse", "HEAD")
            remote = self._run_git("rev-parse", target_ref)
        except GitCommandError as e:
            self.state = "failed"
            self.last_error = str(e)
            return False
        self.current_version = local[:8]
        self.remote_version = remote[:8]
        self.ahead_count = 0
        self.behind_count = 0

        if self._restart_event is not None:
            self.state = "restarting"
            logger.info(f"源码更新完成: {self.current_version}，即将重启后端")
            self._trigger_restart()
        else:
            self.state = "done"
            logger.info(f"源码更新完成: {self.current_version}")
        return True

    def set_restart_event(self, event):
        """设置重启事件（multiprocessing.Event），由 services/webui/gui.py 子进程传入。"""
        self._restart_event = event

    def _trigger_restart(self, delay: float = 2.0):
        """延迟触发后端重启，给 API 响应留出返回时间。"""
        def _fire():
            logger.info("触发后端重启...")
            self._restart_event.set()

        timer = threading.Timer(delay, _fire)
        timer.daemon = True
        timer.start()

    def get_status(self) -> dict:
        available = self._git_update_available()
        state = self.state
        reason = self._unavailable_reason
        current_version = ""
        branch = ""
        if not available:
            state = "disabled"
        else:
            try:
                current_version = self._run_git("rev-parse", "HEAD")[:8]
                branch = self._ensure_attached_branch()
            except GitCommandError as e:
                state = "failed"
                self.last_error = str(e)
        return {
            "kind": "source-git",
            "available": available,
            "unavailable_reason": reason,
            "state": state,
            "has_update": available and state == "available",
            "current_version": current_version,
            "branch": branch,
            "remote_branch": self.remote_branch,
            "remote_version": self.remote_version if available else "",
            "ahead_count": self.ahead_count if available else 0,
            "behind_count": self.behind_count if available else 0,
            "changelog": self.changelog if available else "",
            "last_error": self.last_error if available else reason,
        }


updater = Updater()
