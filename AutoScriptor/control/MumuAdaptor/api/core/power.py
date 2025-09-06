#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time : 2024/7/29 下午3:05
# @Author : wlkjyy
# @File : power.py
# @Software: PyCharm

from AutoScriptor.logger import logger


class Power:

    def __init__(self, utils):
        self.utils = utils

    def start(self, package: str = None) -> bool:
        """
            启动模拟器(start)
        :param package: 启动时自动启动应用的应用包名
        :return:
        """
        logger.info(f"正在启动模拟器 {self.utils.get_vm_id()}")
        if package:
            logger.info(f"将自动启动应用: {package}")

        try:
            self.utils.set_operate('control')
            args = ['launch']
            if package is not None:
                args.extend(['-pkg', package])

            ret_code, retval = self.utils.run_command(args)
            if ret_code == 0:
                logger.info(f"模拟器 {self.utils.get_vm_id()} 启动成功")
                return True

            raise RuntimeError(retval)
        except Exception as e:
            logger.error(f"模拟器启动失败: {str(e)}")
            raise

    def shutdown(self):
        """
            关闭模拟器(shutdown)
        :return:
        """
        self.utils.set_operate('control')
        ret_code, retval = self.utils.run_command(['shutdown'])
        if ret_code == 0:
            return True

        raise RuntimeError(retval)

    def restart(self):
        """
            重启模拟器(restart)
        :return:
        """
        self.utils.set_operate('control')
        ret_code, retval = self.utils.run_command(['restart'])
        if ret_code == 0:
            return True

        raise RuntimeError(retval)

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
