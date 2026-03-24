#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time : 2024/7/29 下午3:05
# @Author : wlkjyy
# @File : power.py
# @Software: PyCharm

import time
from AutoScriptor.utils.logger import logger


class Power:

    def __init__(self, utils):
        self.utils = utils

    def is_running(self) -> bool:
        """检测模拟器是否正在运行。"""
        try:
            self.utils.set_operate('control')
            ret_code, retval = self.utils.run_command(['info'])
            return ret_code == 0 and 'running' in (retval or '').lower()
        except Exception:
            return False

    def start(self, package: str = None, max_retries: int = 2) -> bool:
        """
            启动模拟器(start)
        :param package: 启动时自动启动应用的应用包名
        :param max_retries: 启动失败时最大重试次数
        :return:
        """
        logger.info(f"正在启动模拟器 {self.utils.get_vm_id()}")
        if package:
            logger.info(f"将自动启动应用: {package}")

        last_error = None
        for attempt in range(max_retries + 1):
            try:
                self.utils.set_operate('control')
                args = ['launch']
                if package is not None:
                    args.extend(['-pkg', package])

                ret_code, retval = self.utils.run_command(args)
                if ret_code == 0:
                    logger.info(f"模拟器 {self.utils.get_vm_id()} 启动成功")
                    return True

                last_error = RuntimeError(retval)
                if attempt < max_retries:
                    logger.warning(f"模拟器启动失败 (尝试 {attempt+1}/{max_retries+1}): {retval}")
                    time.sleep(5)
            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    logger.warning(f"模拟器启动异常 (尝试 {attempt+1}/{max_retries+1}): {e}")
                    time.sleep(5)

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

        logger.warning(f"等待模拟器关闭超时 ({timeout}s)，尝试强制关闭")
        self._force_kill()
        time.sleep(3)
        return not self.is_running()

    def _force_kill(self):
        """强制终止 MuMu 模拟器进程（最后手段）。"""
        import subprocess
        mumu_processes = [
            "MuMuVMMHeadless.exe", "MuMuVMMSVC.exe", "MuMuPlayer.exe",
        ]
        for proc in mumu_processes:
            try:
                subprocess.run(
                    ["taskkill", "/F", "/IM", proc],
                    shell=False,
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
                )
            except Exception:
                pass

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
