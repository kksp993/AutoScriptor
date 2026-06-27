#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time : 2024/7/29 下午3:05
# @Author : wlkjyy
# @File : power.py
# @Software: PyCharm

import time
import json
import subprocess
from typing import Callable

from AutoScriptor.control.MumuAdaptor.device_facade import get_device_facade
from AutoScriptor.utils.cancel import TaskCancelled, check_cancel_raise, sleep_with_cancel
from AutoScriptor.utils.logger import logger


class Power:

    def __init__(self, utils):
        self.utils = utils

    def _wait_until_android_ready(
        self,
        timeout: float = 90.0,
        interval: float = 2.0,
        cancel_check: Callable[[], None] | None = None,
    ) -> bool:
        cancel_check = cancel_check or check_cancel_raise
        deadline = time.monotonic() + timeout
        facade = get_device_facade(vm_index=self.utils.get_vm_id())
        while time.monotonic() < deadline:
            cancel_check()
            if facade.adb_device_ready():
                return True
            sleep_with_cancel(interval, cancel_check)
        return False

    def is_running(self) -> bool:
        """检测模拟器是否正在运行。"""
        try:
            self.utils.set_operate('info')
            ret_code, retval = self.utils.run_command([])
            if ret_code == 0:
                try:
                    data = json.loads(retval or "{}")
                    if isinstance(data, dict):
                        return bool(
                            data.get("is_process_started")
                            or data.get("is_android_started")
                            or "start" in str(data.get("player_state", "")).lower()
                            or "running" in str(data.get("player_state", "")).lower()
                        )
                except json.JSONDecodeError:
                    pass
                return 'running' in (retval or '').lower() or 'start_finished' in (retval or '').lower()
            logger.debug("MuMuManager info 失败，回退 ADB 检测: ret=%s, out=%s", ret_code, retval)
        except (OSError, RuntimeError, subprocess.SubprocessError):
            logger.debug("MuMuManager info 异常，回退 ADB 检测", exc_info=True)
        return get_device_facade(vm_index=self.utils.get_vm_id()).adb_device_ready()

    def start(
        self,
        package: str = None,
        max_retries: int = 2,
        cancel_check: Callable[[], None] | None = None,
    ) -> bool:
        """
            启动模拟器(start)
        :param package: 启动时自动启动应用的应用包名
        :param max_retries: 启动失败时最大重试次数
        :return:
        """
        logger.info(f"正在启动模拟器 {self.utils.get_vm_id()}")
        if package:
            logger.info(f"将自动启动应用: {package}")

        cancel_check = cancel_check or check_cancel_raise
        last_error = None
        for attempt in range(max_retries + 1):
            cancel_check()
            try:
                self.utils.set_operate('control')
                args = ['launch']
                if package is not None:
                    args.extend(['-pkg', package])

                ret_code, retval = self.utils.run_command(args)
                if ret_code == 0:
                    if not self._wait_until_android_ready(cancel_check=cancel_check):
                        raise RuntimeError("MuMuManager launch code succeeded, but device did not become ready")
                    logger.info(f"模拟器 {self.utils.get_vm_id()} 启动成功")
                    return True
                if get_device_facade(vm_index=self.utils.get_vm_id()).adb_device_ready():
                    logger.warning("MuMuManager launch 失败，但 ADB 已可用，视为模拟器已启动: %s", retval)
                    return True

                last_error = RuntimeError(retval)
                if attempt < max_retries:
                    logger.warning(f"模拟器启动失败 (尝试 {attempt+1}/{max_retries+1}): {retval}")
                    sleep_with_cancel(5, cancel_check)
            except TaskCancelled:
                raise
            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    logger.warning(f"模拟器启动异常 (尝试 {attempt+1}/{max_retries+1}): {e}")
                    sleep_with_cancel(5, cancel_check)

        logger.error(f"模拟器启动失败 (已重试 {max_retries} 次): {last_error}")
        raise last_error

    def shutdown(self, wait: bool = True, timeout: int = 30) -> bool:
        """
            关闭模拟器(shutdown)
        :param wait: 是否等待模拟器完全关闭
        :param timeout: 等待关闭的超时秒数
        :return:
        """
        logger.info(f"正在关闭模拟器 {self.utils.get_vm_id()}")
        self.utils.set_operate('control')
        ret_code, retval = self.utils.run_command(['shutdown'])
        if ret_code != 0:
            logger.warning(f"shutdown 命令返回非零: {ret_code}, {retval}")

        if not wait:
            return ret_code == 0

        deadline = time.time() + timeout
        while time.time() < deadline:
            if not self.is_running():
                logger.info(f"模拟器 {self.utils.get_vm_id()} 已完全关闭")
                return True
            sleep_with_cancel(2)

        logger.warning(f"等待模拟器 {self.utils.get_vm_id()} 关闭超时 ({timeout}s)，不执行全局 taskkill 以免影响其他 MuMu 实例")
        return False

    def restart(self):
        """
            重启模拟器(restart)：先安全关闭再启动。
        :return:
        """
        self.shutdown(wait=True, timeout=30)
        sleep_with_cancel(3)
        return self.start()

    def stop(self):
        """
            关闭一个模拟器
        :return:
        """
        return self.shutdown()

    def reboot(self):
        """
            重启一个模拟器
        :return:
        """
        return self.restart()
