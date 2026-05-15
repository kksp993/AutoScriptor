#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time : 2024/7/29 下午3:05
# @Author : wlkjyy
# @File : power.py
# @Software: PyCharm

import time
from typing import Callable

from AutoScriptor.control.MumuAdaptor.api.adb.direct import adb_device_ready
from AutoScriptor.utils.cancel import TaskCancelled, check_cancel_raise, sleep_with_cancel
from AutoScriptor.utils.logger import logger


class Power:

    def __init__(self, utils):
        self.utils = utils

    def is_running(self) -> bool:
        """检测模拟器是否正在运行。"""
        try:
            self.utils.set_operate('control')
            ret_code, retval = self.utils.run_command(['info'])
            if ret_code == 0:
                return 'running' in (retval or '').lower()
            logger.debug("MuMuManager info 失败，回退 ADB 检测: ret=%s, out=%s", ret_code, retval)
        except Exception:
            logger.debug("MuMuManager info 异常，回退 ADB 检测", exc_info=True)
        return adb_device_ready()

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
                    logger.info(f"模拟器 {self.utils.get_vm_id()} 启动成功")
                    return True
                if adb_device_ready():
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
            time.sleep(2)

        logger.warning(f"等待模拟器 {self.utils.get_vm_id()} 关闭超时 ({timeout}s)，不执行全局 taskkill 以免影响其他 MuMu 实例")
        return False

    def restart(self):
        """
            重启模拟器(restart)：先安全关闭再启动。
        :return:
        """
        self.shutdown(wait=True, timeout=30)
        time.sleep(3)
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
