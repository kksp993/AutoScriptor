"""
自动更新检查器
==============
后台定时检查 Git 仓库更新，提供检查/执行更新的 API。
借鉴 StarRailCopilot 的 fetch → stash → pull --ff-only → stash pop 流程。
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
from typing import Optional

from AutoScriptor.utils.logger import logger


class Updater:
    """管理 Git 仓库的更新检查与执行。"""

    state: str = "idle"
    changelog: str = ""
    current_version: str = ""
    remote_version: str = ""
    last_error: str = ""

    _check_thread: Optional[threading.Thread] = None
    _stop_event = threading.Event()
    _restart_event = None  # multiprocessing.Event, 由 gui.py 传入

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

    def _run_git(self, *args, timeout: int = 30, allow_failure: bool = False) -> str:
        cmd = [self._git] + list(args)
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                cwd=self._root, timeout=timeout
            )
            if result.returncode != 0 and not allow_failure:
                logger.debug(f"Git 命令非零退出: {cmd} -> {result.stderr.strip()}")
            return result.stdout.strip()
        except Exception as e:
            logger.debug(f"Git 命令失败: {cmd} -> {e}")
            return ""

    def _run_git_ok(self, *args, timeout: int = 30) -> bool:
        cmd = [self._git] + list(args)
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                cwd=self._root, timeout=timeout
            )
            return result.returncode == 0
        except Exception:
            return False

    def get_current_commit(self) -> str:
        return self._run_git("rev-parse", "--short", "HEAD")

    def get_current_branch(self) -> str:
        return self._run_git("rev-parse", "--abbrev-ref", "HEAD")

    def _get_remote_branch(self) -> str:
        branch = self.get_current_branch()
        return branch if branch else "feat/launcher"

    # ── 检查更新 ──

    def check_update(self) -> bool:
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
                return False

            # 检查本地是否有远程不存在的提交（开发分支保护）
            local_only = self._run_git(
                "log", "--not", f"--remotes=origin/*",
                "-1", "--oneline", allow_failure=True
            )
            if local_only:
                logger.info(f"本地有未推送提交 {local_only.split()[0]}，跳过更新")
                self.state = "idle"
                return False

            self.current_version = local[:8]
            self.remote_version = remote[:8]
            self.changelog = self._run_git(
                "log", "--oneline", "--no-merges",
                f"HEAD..origin/{branch}", "--max-count=20"
            )
            self.state = "available"
            logger.info(f"发现更新: {self.current_version} -> {self.remote_version}")
            return True

        except Exception as e:
            logger.error(f"检查更新失败: {e}")
            self.state = "failed"
            self.last_error = str(e)
            return False

    # ── 执行更新 ──

    def run_update(self) -> bool:
        if self.state not in ("available", "failed", "idle"):
            return False

        self.state = "updating"
        self.last_error = ""
        try:
            branch = self._get_remote_branch()

            self._run_git_ok("fetch", "origin", branch, timeout=60)

            # 清除 git 锁文件
            for lock in [".git/index.lock", ".git/HEAD.lock"]:
                lock_path = os.path.join(self._root, lock)
                if os.path.exists(lock_path):
                    logger.info(f"移除锁文件: {lock}")
                    os.remove(lock_path)

            # stash 保护本地修改
            stashed = self._run_git_ok("stash", "--quiet")

            # 先尝试 fast-forward pull
            if not self._run_git_ok("pull", "--ff-only", "origin", branch, timeout=120):
                logger.warning("pull --ff-only 失败，尝试 reset --hard")
                self._run_git_ok("reset", "--hard", f"origin/{branch}")

            # 恢复本地修改
            if stashed:
                self._run_git_ok("stash", "pop", "--quiet", timeout=10)

            # 更新依赖
            self._pip_install()

            self.current_version = self.get_current_commit()

            if self._restart_event is not None:
                self.state = "restarting"
                logger.info(f"更新完成: {self.current_version}，即将重启后端")
                self._trigger_restart()
            else:
                self.state = "done"
                logger.info(f"更新完成: {self.current_version}")
            return True

        except Exception as e:
            logger.error(f"更新执行失败: {e}")
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
                cwd=self._root, timeout=300,
                capture_output=True
            )
        except Exception as e:
            logger.warning(f"依赖安装失败: {e}")

    # ── 定时检查 ──

    def start_scheduled_check(self, interval_minutes: int = 30):
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
        return {
            "state": self.state,
            "current_version": self.get_current_commit(),
            "branch": self.get_current_branch(),
            "remote_version": self.remote_version,
            "changelog": self.changelog,
            "last_error": self.last_error,
        }


updater = Updater()
