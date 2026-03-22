"""
自动更新检查器
==============
后台定时检查 Git 仓库更新，提供检查/执行更新的 API。
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from typing import Optional

from AutoScriptor.utils.logger import logger


class Updater:
    """管理 Git 仓库的更新检查与执行。"""

    # 状态: idle / checking / available / updating / done / failed
    state: str = "idle"
    changelog: str = ""
    current_version: str = ""
    remote_version: str = ""

    _check_thread: Optional[threading.Thread] = None
    _stop_event = threading.Event()

    def __init__(self):
        self._root = os.getcwd()
        self._git = self._find_git()

    def _find_git(self) -> str:
        for candidate in ["git", "git.exe"]:
            try:
                subprocess.run(
                    [candidate, "--version"],
                    capture_output=True, timeout=5
                )
                return candidate
            except Exception:
                continue
        return "git"

    def _run_git(self, *args, timeout: int = 30) -> str:
        cmd = [self._git] + list(args)
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                cwd=self._root, timeout=timeout
            )
            return result.stdout.strip()
        except Exception as e:
            logger.debug(f"Git 命令失败: {cmd} -> {e}")
            return ""

    def get_current_commit(self) -> str:
        return self._run_git("rev-parse", "--short", "HEAD")

    def get_current_branch(self) -> str:
        return self._run_git("rev-parse", "--abbrev-ref", "HEAD")

    def check_update(self) -> bool:
        """
        检查远程是否有更新。

        Returns:
            bool: True 表示有更新可用
        """
        if self.state == "checking":
            return False

        self.state = "checking"
        try:
            self._run_git("fetch", "--quiet", timeout=60)

            branch = self.get_current_branch() or "master"
            local = self._run_git("rev-parse", "HEAD")
            remote = self._run_git("rev-parse", f"origin/{branch}")

            if not local or not remote:
                self.state = "failed"
                return False

            if local == remote:
                self.state = "idle"
                self.changelog = ""
                return False

            self.current_version = local[:8]
            self.remote_version = remote[:8]
            self.changelog = self._run_git(
                "log", "--oneline", f"HEAD..origin/{branch}", "--max-count=20"
            )
            self.state = "available"
            logger.info(f"发现更新: {self.current_version} -> {self.remote_version}")
            return True

        except Exception as e:
            logger.error(f"检查更新失败: {e}")
            self.state = "failed"
            return False

    def run_update(self) -> bool:
        """执行 git pull 更新"""
        self.state = "updating"
        try:
            branch = self.get_current_branch() or "master"
            output = self._run_git("pull", "origin", branch, timeout=120)
            if "Already up to date" in output or "Fast-forward" in output or output:
                logger.info(f"更新完成: {output[:200]}")
                self._pip_install()
                self.state = "done"
                return True
            else:
                self.state = "failed"
                return False
        except Exception as e:
            logger.error(f"更新执行失败: {e}")
            self.state = "failed"
            return False

    def _pip_install(self):
        """更新后自动安装新依赖"""
        req_file = os.path.join(self._root, "requirements.txt")
        if not os.path.exists(req_file):
            return
        try:
            import sys
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "-r", req_file, "--quiet"],
                cwd=self._root, timeout=300,
                capture_output=True
            )
        except Exception as e:
            logger.warning(f"依赖安装失败: {e}")

    def start_scheduled_check(self, interval_minutes: int = 30):
        """启动后台定时检查线程"""
        if self._check_thread and self._check_thread.is_alive():
            return

        self._stop_event.clear()

        def _loop():
            while not self._stop_event.is_set():
                self._stop_event.wait(interval_minutes * 60)
                if self._stop_event.is_set():
                    break
                try:
                    self.check_update()
                except Exception as e:
                    logger.debug(f"定时更新检查异常: {e}")

        self._check_thread = threading.Thread(target=_loop, daemon=True, name="updater")
        self._check_thread.start()
        logger.info(f"自动更新检查已启动，间隔 {interval_minutes} 分钟")

    def stop(self):
        self._stop_event.set()

    def get_status(self) -> dict:
        return {
            "state": self.state,
            "current_version": self.get_current_commit(),
            "branch": self.get_current_branch(),
            "remote_version": self.remote_version,
            "changelog": self.changelog,
        }


updater = Updater()
