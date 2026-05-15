#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time : 2024/7/29 下午3:26
# @Author : wlkjyy
# @File : app.py
# @Software: PyCharm
import json
import os.path
from AutoScriptor.control.MumuAdaptor.api.adb.direct import run_adb
from AutoScriptor.utils.logger import logger


def _manager_failed(ret_code: int, retval) -> bool:
    return ret_code != 0 or _is_not_handle_cmd(retval)


def _is_not_handle_cmd(retval) -> bool:
    """MuMu 6 的 MuMuManager 不支持 control app 命令时会返回 not handle cmd"""
    if not retval:
        return False
    s = retval if isinstance(retval, str) else str(retval)
    return "not handle cmd" in s


def _adb_app_close(package: str) -> bool:
    """ADB 回退：强制关闭应用（MuMu 6 等不支持 MuMuManager app close 时使用）"""
    r = run_adb(["shell", "am", "force-stop", package], timeout=10)
    return r.returncode == 0


def _adb_app_launch(package: str) -> bool:
    """ADB 回退：通过 monkey 启动应用（MuMu 6 等不支持 MuMuManager app launch 时使用）"""
    r = run_adb(["shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"], timeout=15)
    return r.returncode == 0


def _adb_app_state(package: str) -> str:
    """ADB 回退：通过 pidof 判断应用是否在运行"""
    r = run_adb(["shell", "pidof", package], timeout=5)
    return "running" if (r.returncode == 0 and r.stdout.strip()) else "stopped"


def _adb_list_packages() -> list[dict[str, str]]:
    """ADB 回退：列出已安装包。app_name/version 留空，调用方只依赖 package。"""
    r = run_adb(["shell", "pm", "list", "packages"], timeout=15)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip())
    installed = []
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line.startswith("package:"):
            continue
        package = line.split("package:", 1)[1].strip()
        if package:
            installed.append({"package": package, "app_name": "", "version": ""})
    return installed


def _adb_app_exists(package: str) -> bool:
    r = run_adb(["shell", "pm", "path", package], timeout=5)
    return r.returncode == 0 and bool(r.stdout.strip())


class App:

    def __init__(self, utils):
        self.utils = utils

    def install(self, apk_path: str = None) -> bool:
        """
            安装应用到模拟器里(install)
        :param apk_path: 选择要安装的应用apk文件路径（支持apk/xapk/apks后缀）
        :return:
        """
        logger.info(f"正在安装应用: {apk_path}")

        try:
            if not os.path.exists(apk_path):
                raise FileNotFoundError(f"apk文件不存在: {apk_path}")

            if not os.path.isfile(apk_path):
                raise FileNotFoundError(f"指定路径不是文件: {apk_path}")

            self.utils.set_operate('control')
            ret_code, retval = self.utils.run_command(['app', 'install', '-apk', apk_path])

            if ret_code == 0:
                logger.info(f"应用安装成功: {apk_path}")
                return True

            raise RuntimeError(retval)
        except Exception as e:
            logger.error(f"应用安装失败: {str(e)}")
            raise

    def uninstall(self, package: str) -> bool:
        """
            卸载应用(uninstall)
        :param package: 选择要卸载的应用包名
        :return:
        """
        self.utils.set_operate('control')
        ret_code, retval = self.utils.run_command(['app', 'uninstall', '-pkg', package])

        if ret_code == 0:
            return True

        raise RuntimeError(retval)

    def launch(self, package: str) -> bool:
        """
            启动应用(launch)
        :param package: 选择要启动的应用包名
        :return:
        """
        self.utils.set_operate('control')
        ret_code, retval = self.utils.run_command(['app', 'launch', '-pkg', package])

        if ret_code == 0:
            return True
        if _manager_failed(ret_code, retval):
            logger.debug("MuMuManager app launch 失败，回退至 ADB monkey: ret=%s, out=%s", ret_code, retval)
            return _adb_app_launch(package)
        raise RuntimeError(retval)

    def close(self, package: str) -> bool:
        """
            关闭应用(close)
        :param package: 选择要关闭的应用包名
        :return:
        """
        self.utils.set_operate('control')
        ret_code, retval = self.utils.run_command(['app', 'close', '-pkg', package])

        if ret_code == 0:
            return True
        if _manager_failed(ret_code, retval):
            logger.debug("MuMuManager app close 失败，回退至 ADB force-stop: ret=%s, out=%s", ret_code, retval)
            return _adb_app_close(package)
        raise RuntimeError(retval)

    def get_installed(self):
        """
            获取已安装的应用(get_installed)
        :return:
        """
        self.utils.set_operate('control')
        ret_code, retval = self.utils.run_command(['app', 'info', '-i'])

        if ret_code != 0:
            logger.debug("MuMuManager app info -i 失败，回退至 ADB pm list packages: ret=%s, out=%s", ret_code, retval)
            return _adb_list_packages()

        data = json.loads(retval)
        installed = []

        for key in data.keys():
            if key != "active":
                installed.append({
                    "package": key,
                    "app_name": data[key]['app_name'],
                    "version": data[key]['version']
                })

        return installed

    def exists(self, package: str) -> bool:
        """
            判断应用是否存在(exists)
        :param package: 选择要判断的应用包名
        :return:
        """
        self.utils.set_operate('control')
        ret_code, retval = self.utils.run_command(['app', 'info', '-pkg', package])

        if ret_code != 0:
            logger.debug("MuMuManager app exists 失败，回退至 ADB pm path: ret=%s, out=%s", ret_code, retval)
            return _adb_app_exists(package)

        data = json.loads(retval)

        return data['state'] != 'not_installed'

    def doesntExists(self, package: str) -> bool:
        """
            判断应用是否不存在(doesntExists)
        :param package: 选择要判断的应用包名
        :return:
        """
        return not self.exists(package)

    def state(self, package: str) -> str:
        """
            获取应用状态(state)
        :param package: 选择要获取的应用包名
        :return:
        """
        self.utils.set_operate('control')
        ret_code, retval = self.utils.run_command(['app', 'info', '-pkg', package])

        if ret_code == 0:
            data = json.loads(retval)
            return data['state']
        if _manager_failed(ret_code, retval):
            logger.debug("MuMuManager app info 失败，回退至 ADB pidof: ret=%s, out=%s", ret_code, retval)
            return _adb_app_state(package)
        raise RuntimeError(retval)
