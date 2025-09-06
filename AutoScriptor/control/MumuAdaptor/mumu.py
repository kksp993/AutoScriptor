#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time : 2024/7/28 下午9:36
# @Author : wlkjyy
# @File : mumu.py
# @Software: PyCharm
import os.path
from typing import Union

from AutoScriptor.control.MumuAdaptor.api.adb.Adb import Adb
from AutoScriptor.control.MumuAdaptor.api.core.Core import Core
from AutoScriptor.control.MumuAdaptor.api.core.app import App
from AutoScriptor.control.MumuAdaptor.api.core.performance import Performance
from AutoScriptor.control.MumuAdaptor.api.core.power import Power
from AutoScriptor.control.MumuAdaptor.api.core.shortcut import Shortcut
from AutoScriptor.control.MumuAdaptor.api.core.simulation import Simulation
from AutoScriptor.control.MumuAdaptor.api.core.window import Window
from AutoScriptor.control.MumuAdaptor.api.develop.androidevent import AndroidEvent
from AutoScriptor.control.MumuAdaptor.api.driver.Driver import Driver
from AutoScriptor.control.MumuAdaptor.api.network.Network import Network
from AutoScriptor.control.MumuAdaptor.api.permission.Permission import Permission
from AutoScriptor.control.MumuAdaptor.api.screen.gui import Gui
from AutoScriptor.control.MumuAdaptor.api.setting.setting import Setting
from AutoScriptor.control.MumuAdaptor.utils import utils
from AutoScriptor.control.MumuAdaptor.api.screen.screen import Screen
from AutoScriptor.control.MumuAdaptor.api.screen.gui import Gui

global gui
gui = None


class Mumu:
    def __init__(self):
        from AutoScriptor.utils.constant import cfg
        if not os.path.exists(cfg["emulator"]["emu_path"]):
            raise RuntimeError(f"MuMuManager.exe not found in {cfg['emulator']['emu_path']}")
        if not os.path.exists(cfg["emulator"]["adb_path"]):
            raise RuntimeError(f"adb.exe not found in {cfg['emulator']['adb_path']}")

    def select(self, vm_index: Union[int, list, tuple] = None, *args):
        """
            选择要操作的模拟器索引
        :param vm_index: 模拟器索引
        :param args: 更多的模拟器索引
        :return:

        Example:
            Mumu().select(1)
            Mumu().select(1, 2, 3)
            Mumu().select([1, 2, 3])
            Mumu().select((1, 2, 3))
        """

        if len(args) > 0:
            if isinstance(vm_index, int):
                vm_index = [vm_index]
            else:
                vm_index = list(vm_index)

            vm_index.extend(args)

        if isinstance(vm_index, int):
            self.__vm_index = str(vm_index)
        else:
            vm_index = list(set(vm_index))
            self.__vm_index = ",".join([str(i) for i in vm_index])

        return self

    def generate_utils(self) -> utils:
        return utils().set_vm_index(self.__vm_index).set_mumu_root_object(self)

    def all(self):
        """
            选择所有模拟器
        :return:
        """
        self.__vm_index = 'all'
        return self

    @property
    def core(self) -> Core:
        """
            模拟器类
        :return:
        """
        return Core(self.generate_utils())

    @property
    def driver(self) -> Driver:
        """
            驱动类

            已完成
        :return:
        """

        return Driver(self.generate_utils())

    @property
    def permission(self) -> Permission:
        """
            权限类

            已完成
        :return:
        """
        return Permission(self.generate_utils())

    @property
    def power(self):
        """
            电源类

            已完成
        :return:
        """
        return Power(self.generate_utils())

    @property
    def window(self) -> Window:
        """
            窗口类

            已完成
        :return:
        """

        return Window(self.generate_utils())

    @property
    def app(self) -> App:
        """
            app类

            已完成
        :return:
        """

        return App(self.generate_utils())

    @property
    def androidEvent(self) -> AndroidEvent:
        """
            安卓事件类

            已完成
        :return:
        """
        return AndroidEvent(self.generate_utils())

    @property
    def shortcut(self) -> Shortcut:
        """
            快捷方式类

            已完成
        :return:
        """
        return Shortcut(self.generate_utils())

    @property
    def simulation(self) -> Simulation:
        """
            机型类（这玩意很鸡肋，没什么用）

            已完成
        :return:
        """
        return Simulation(self.generate_utils())

    @property
    def setting(self) -> Setting:
        """
            配置类
        :return:
        """

        return Setting(self.generate_utils())

    @property
    def screen(self) -> Screen:
        """
            屏幕类
        :return:
        """
        return Screen(self.generate_utils())

    @property
    def performance(self) -> Performance:
        """
            性能类
        :return:
        """
        return Performance(self.generate_utils())

    @property
    def network(self):
        """
            网路操作类
        :return:
        """

        return Network(self.generate_utils())

    @property
    def adb(self) -> Adb:
        """
            ADB类
        :return:
        """
        return Adb(self.generate_utils())

    @property
    def auto(self) -> Gui:
        """
            GUI自动化类
        :return:
        """
        try:
            import cv2
            import pyscrcpy
        except ImportError:
            raise ImportError("if you want to use autoGui class, you should install opencv-python")

        return Gui(self.generate_utils())
