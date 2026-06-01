"""
源码仓库更新器
==============
只用于开发/源码部署形态：fetch -> stash -> pull/reset -> pip install -> restart。

发行版安装包没有 .git，也不应该在「检查更新」里走这个通道；发行版更新由
content_delta_update 或 Electron 的 backend_incremental.zip 机制负责。
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
from typing import Optional

from AutoScriptor.utils.logger import logger

try:
    from AutoScriptor.utils.paths import get_app_root, is_compiled
except Exception:  # pragma: no cover - 部分契约测试会替换 AutoScriptor.utils
    def get_app_root():
        return os.getcwd()

    def is_compiled() -> bool:
        return False


class Updater:
    """管理源码 Git 仓库的更新检查与执行。"""

    state: str = "idle"
    changelog: str = ""
    current_version: str = ""
    remote_version: str = ""
    last_error: str = ""

    _check_thread: Optional[threading.Thread] = None
    _stop_event = threading.Event()
    _restart_event = None  # multiprocessing.Event，由 gui.py 传入

    def __init__(self):
        self._root = str(get_app_root())
        self._git = self._find_git()
        self._unavailable_reason = ""

    def _find_git(self) -> str:
        for candidate in ["git", "git.exe"]:
            try:
                result = subprocess.run(
                    [candidate, "--version"],
                    capture_output=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    return candidate
            except Exception:
                continue
        return "git"

    def _git_cmd(self, *args) -> list[str]:
        safe_root = os.path.abspath(self._root).replace("\\", "/")
        return [self._git, "-c", f"safe.directory={safe_root}", *args]

    def _run_git(self, *args, timeout: int = 30, allow_failure: bool = False) -> str:
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
            if result.returncode != 0 and not allow_failure:
                logger.debug(f"Git 命令非零退出: {cmd} -> {result.stderr.strip()}")
            return result.stdout.strip()
        except Exception as e:
            logger.debug(f"Git 命令失败: {cmd} -> {e}")
            return ""

    def _run_git_ok(self, *args, timeout: int = 30) -> bool:
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
            return result.returncode == 0
        except Exception:
            return False

    def _git_update_available(self) -> bool:
        """当前运行目录是否真的可执行源码 Git 更新。"""
        self._unavailable_reason = ""
        if is_compiled():
            self._unavailable_reason = "当前是发行版运行环境，发行版不使用 Git 更新通道。"
            return False
        if not os.path.isdir(self._root):
            self._unavailable_reason = f"项目根目录不存在: {self._root}"
            return False
        if not os.path.isdir(os.path.join(self._root, ".git")):
            self._unavailable_reason = "当前目录不是 Git 工作区，源码更新不可用。"
            return False
        if not self._run_git_ok("rev-parse", "--is-inside-work-tree", timeout=5):
            self._unavailable_reason = "Git 不可用或当前目录不是有效工作区。"
            return False
        return True

    def get_current_commit(self) -> str:
        if not self._git_update_available():
            return ""
        return self._run_git("rev-parse", "--short", "HEAD")

    def get_current_branch(self) -> str:
        if not self._git_update_available():
            return ""
        return self._run_git("rev-parse", "--abbrev-ref", "HEAD")

    def _get_remote_branch(self) -> str:
        branch = self.get_current_branch()
        return branch if branch else "main"

    # ── 检查更新 ──

    def check_update(self) -> bool:
        if not self._git_update_available():
            self.state = "disabled"
            self.last_error = self._unavailable_reason
            self.remote_version = ""
            self.changelog = ""
            return False

        if self.state == "checking":
            return False

        self.state = "checking"
        self.last_error = ""
        try:
            branch = self._get_remote_branch()

            for attempt in range(3):
                if self._run_git_ok("fetch", "origin", branch, timeout=60):
                    break
                logger.warning(f"git fetch 失败 (第 {attempt + 1} 次)")
                time.sleep(2)
            else:
                self.state = "failed"
                self.last_error = "git fetch 连续失败"
                return False

            local = self._run_git("rev-parse", "HEAD")
            remote = self._run_git("rev-parse", f"origin/{branch}")

            if not local or not remote:
                self.state = "failed"
                self.last_error = "无法获取 commit"
                return False

            if local == remote:
                self.state = "idle"
                self.changelog = ""
                self.current_version = local[:8]
                self.remote_version = ""
                return False

            # 开发分支保护：有本地未推送提交时不自动覆盖。
            local_only = self._run_git(
                "log",
                "--not",
                "--remotes=origin/*",
                "-1",
                "--oneline",
                allow_failure=True,
            )
            if local_only:
                logger.info(f"本地有未推送提交 {local_only.split()[0]}，跳过更新")
                self.state = "idle"
                self.current_version = local[:8]
                self.remote_version = ""
                return False

            self.current_version = local[:8]
            self.remote_version = remote[:8]
            self.changelog = self._run_git(
                "log",
                "--oneline",
                "--no-merges",
                f"HEAD..origin/{branch}",
                "--max-count=20",
            )
            self.state = "available"
            logger.info(f"发现源码更新: {self.current_version} -> {self.remote_version}")
            return True

        except Exception as e:
            logger.error(f"检查源码更新失败: {e}")
            self.state = "failed"
            self.last_error = str(e)
            return False

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
        try:
            branch = self._get_remote_branch()

            self._run_git_ok("fetch", "origin", branch, timeout=60)

            for lock in [".git/index.lock", ".git/HEAD.lock"]:
                lock_path = os.path.join(self._root, lock)
                if os.path.exists(lock_path):
                    logger.info(f"移除 Git 锁文件: {lock}")
                    os.remove(lock_path)

            stashed = self._run_git_ok("stash", "--quiet")

            if not self._run_git_ok("pull", "--ff-only", "origin", branch, timeout=120):
                logger.warning("pull --ff-only 失败，尝试 reset --hard")
                self._run_git_ok("reset", "--hard", f"origin/{branch}")

            if stashed:
                self._run_git_ok("stash", "pop", "--quiet", timeout=10)

            self._pip_install()

            self.current_version = self.get_current_commit()

            if self._restart_event is not None:
                self.state = "restarting"
                logger.info(f"源码更新完成: {self.current_version}，即将重启后端")
                self._trigger_restart()
            else:
                self.state = "done"
                logger.info(f"源码更新完成: {self.current_version}")
            return True

        except Exception as e:
            logger.error(f"源码更新执行失败: {e}")
            self.state = "failed"
            self.last_error = str(e)
            return False

    def _pip_install(self):
        req_file = os.path.join(self._root, "requirements.txt")
        if not os.path.exists(req_file):
            return
        try:
            import sys

            logger.info("更新 Python 依赖...")
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "-r", req_file, "--quiet"],
                cwd=self._root,
                timeout=300,
                capture_output=True,
            )
        except Exception as e:
            logger.warning(f"依赖安装失败: {e}")

    def set_restart_event(self, event):
        """设置重启事件（multiprocessing.Event），由 gui.py 子进程传入。"""
        self._restart_event = event

    def _trigger_restart(self, delay: float = 2.0):
        """延迟触发后端重启，给 API 响应留出返回时间。"""
        def _fire():
            logger.info("触发后端重启...")
            self._restart_event.set()

        timer = threading.Timer(delay, _fire)
        timer.daemon = True
        timer.start()

    def stop(self):
        self._stop_event.set()

    def get_status(self) -> dict:
        available = self._git_update_available()
        state = self.state
        reason = self._unavailable_reason
        if not available:
            state = "disabled"
        return {
            "kind": "source-git",
            "available": available,
            "unavailable_reason": reason,
            "state": state,
            "current_version": self.get_current_commit() if available else "",
            "branch": self.get_current_branch() if available else "",
            "remote_version": self.remote_version if available else "",
            "changelog": self.changelog if available else "",
            "last_error": self.last_error if available else reason,
        }


updater = Updater()
