"""
远程访问模块
============
通过 SSH 反向隧道实现外网访问 WebUI。
"""
from __future__ import annotations

import json
import subprocess
import threading
import time
from typing import Optional

from AutoScriptor.utils.logger import logger


class RemoteAccess:
    """管理 SSH 反向隧道，实现远程访问 WebUI。"""

    _process: Optional[subprocess.Popen] = None
    _thread: Optional[threading.Thread] = None
    _address: Optional[str] = None
    _lock = threading.Lock()

    @classmethod
    def start(
        cls,
        local_port: int = 5000,
        ssh_server: str = "",
        ssh_user: str = "",
        ssh_executable: str = "ssh",
        setup_timeout: int = 60,
    ):
        """启动 SSH 反向隧道"""
        if cls.is_alive():
            logger.info("远程访问已在运行中")
            return

        if not ssh_server:
            logger.warning("未配置 SSH 服务器，无法启动远程访问")
            return

        def _run():
            try:
                host_port = ssh_server.split(":")
                host = host_port[0]
                port = int(host_port[1]) if len(host_port) > 1 else 22

                user = ssh_user or "nokey"
                cmd = [
                    ssh_executable,
                    "-o", "StrictHostKeyChecking=accept-new",
                    "-o", "ServerAliveInterval=60",
                    "-R", f"0:127.0.0.1:{local_port}",
                    "-p", str(port),
                    f"{user}@{host}",
                    "--", "--output", "json",
                ]

                logger.info(f"正在建立远程访问隧道: {host}:{port}")

                with cls._lock:
                    cls._process = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                    )

                deadline = time.time() + setup_timeout
                while time.time() < deadline:
                    if cls._process.poll() is not None:
                        break
                    line = cls._process.stdout.readline().strip()
                    if not line:
                        time.sleep(0.5)
                        continue
                    try:
                        data = json.loads(line)
                        if "address" in data:
                            cls._address = data["address"]
                            logger.info(f"远程访问已建立: {cls._address}")
                            return
                    except json.JSONDecodeError:
                        continue

                logger.warning("远程访问建立超时")
            except FileNotFoundError:
                logger.error(f"SSH 可执行文件未找到: {ssh_executable}")
            except Exception as e:
                logger.error(f"远程访问启动失败: {e}")

        cls._thread = threading.Thread(target=_run, daemon=True, name="remote-access")
        cls._thread.start()

    @classmethod
    def stop(cls):
        """停止 SSH 隧道"""
        with cls._lock:
            if cls._process and cls._process.poll() is None:
                cls._process.kill()
                cls._process = None
            cls._address = None
        logger.info("远程访问已停止")

    @classmethod
    def is_alive(cls) -> bool:
        return (
            cls._thread is not None
            and cls._thread.is_alive()
            and cls._process is not None
            and cls._process.poll() is None
        )

    @classmethod
    def get_status(cls) -> dict:
        if cls.is_alive() and cls._address:
            return {"state": "connected", "address": cls._address}
        elif cls._thread and cls._thread.is_alive():
            return {"state": "connecting", "address": None}
        else:
            return {"state": "stopped", "address": None}
