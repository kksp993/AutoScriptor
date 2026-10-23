"""MuMu 多版本目录自适应：布局解析与 NemuIpc 动态库定位。

MuMu 累计版本很多、目录不一致（调研见
``docs/AutoScriptor/reference/mumu-realtime-control-research.md`` §1.4）：

- MuMu 6.0（Android 15）：``nx_device/15.0/shell/sdk/external_renderer_ipc.dll``
- MuMu 5.0 / MuMu 12（Android 12）：``nx_device/12.0/shell/sdk/...``
- MaaFramework 使用的副本：``nx_main/sdk/external_renderer_ipc.dll``
- MuMu 12 早期及更早：``shell/sdk/...``

``nx_device`` 下的序号是 Android 大版本，会随新版本继续增加，所以实现按通配 +
版本排序探测。这里固化「新版本优先」「子目录上溯到安装根」「旧布局仍可用」三条
行为，避免以后又退回写死 ``nx_device/12.0``。
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from AutoScriptor.utils.mumu_discovery import (
    candidate_nemu_dll_paths,
    derive_paths_from_folder,
    resolve_mumu_layout,
)

MUMU_MANAGER_NAME = "MuMuManager.exe"
MUMU_ADB_NAME = "adb.exe"
NEMU_DLL_NAME = "external_renderer_ipc.dll"


def write_file(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    return path


class FakeMumuInstall:
    """按版本布局搭一个假的 MuMu 安装目录。"""

    def __init__(self, root: Path):
        self.root = root

    def add_android_series_dll(self, series: str) -> Path:
        """MuMu 5.0/6.0 布局：nx_device/<android 大版本>/shell/sdk/。"""
        return write_file(self.root / "nx_device" / series / "shell" / "sdk" / NEMU_DLL_NAME)

    def add_nx_main_sdk_dll(self) -> Path:
        return write_file(self.root / "nx_main" / "sdk" / NEMU_DLL_NAME)

    def add_legacy_shell_sdk_dll(self) -> Path:
        return write_file(self.root / "shell" / "sdk" / NEMU_DLL_NAME)

    def add_manager(self, folder: str = "nx_main") -> Path:
        return write_file(self.root / folder / MUMU_MANAGER_NAME)

    def add_adb(self, folder: str = "nx_main") -> Path:
        return write_file(self.root / folder / MUMU_ADB_NAME)


class TestMumuLayoutResolution(unittest.TestCase):
    def test_mumu_6_0_android_15_layout_is_resolved(self):
        """MuMu 6.0 把库放在 nx_device/15.0；写死 12.0 的旧实现会找不到。"""
        with tempfile.TemporaryDirectory() as tmp:
            install = FakeMumuInstall(Path(tmp) / "MuMu")
            dll = install.add_android_series_dll("15.0")
            manager = install.add_manager()
            adb = install.add_adb()

            layout = resolve_mumu_layout(install.root)

            self.assertEqual(layout["root"], str(install.root))
            self.assertEqual(layout["nemu_dll"], str(dll))
            self.assertEqual(layout["manager"], str(manager))
            self.assertEqual(layout["adb"], str(adb))

            paths = derive_paths_from_folder(install.root)
            self.assertEqual(paths["mumu_folder"], str(install.root))
            self.assertEqual(paths["emu_path"], str(manager))
            self.assertEqual(paths["adb_path"], str(adb))

    def test_newest_android_series_wins(self):
        """升级后可能同时留着多个 nx_device/<版本>，要用运行中的那个（最新的）。"""
        with tempfile.TemporaryDirectory() as tmp:
            install = FakeMumuInstall(Path(tmp) / "MuMu")
            install.add_android_series_dll("12.0")
            newest = install.add_android_series_dll("15.0")

            candidates = candidate_nemu_dll_paths(install.root)

            self.assertEqual(candidates[0], newest)
            self.assertEqual(resolve_mumu_layout(install.root)["nemu_dll"], str(newest))

    def test_nx_main_sdk_dll_is_a_candidate(self):
        """没有版本目录时用 nx_main/sdk 副本（MaaFramework 也优先探它）。"""
        with tempfile.TemporaryDirectory() as tmp:
            install = FakeMumuInstall(Path(tmp) / "MuMu")
            dll = install.add_nx_main_sdk_dll()
            install.add_manager()
            install.add_adb()

            self.assertEqual(resolve_mumu_layout(install.root)["nemu_dll"], str(dll))

    def test_legacy_shell_sdk_layout_still_works(self):
        """MuMu 12 早期把库放在 shell/sdk；不能因为加了新版本就不认旧目录。"""
        with tempfile.TemporaryDirectory() as tmp:
            install = FakeMumuInstall(Path(tmp) / "MuMuPlayer-12.0")
            dll = install.add_legacy_shell_sdk_dll()
            manager = install.add_manager(folder="shell")
            adb = install.add_adb(folder="shell")

            layout = resolve_mumu_layout(install.root)

            self.assertEqual(layout["nemu_dll"], str(dll))
            self.assertEqual(layout["manager"], str(manager))
            self.assertEqual(layout["adb"], str(adb))

    def test_subfolder_config_walks_up_to_install_root(self):
        """用户把 mumu_folder 配成 nx_main 之类的子目录时，要上溯到安装根。

        nemu_connect 需要的是包含 nx_device / shell 的那一级；把子目录原样传下去
        会连接失败。旧实现只按配置值拼相对路径，配错子目录就彻底找不到库。
        """
        with tempfile.TemporaryDirectory() as tmp:
            install = FakeMumuInstall(Path(tmp) / "MuMu")
            dll = install.add_android_series_dll("12.0")
            install.add_manager()
            install.add_adb()

            layout = resolve_mumu_layout(install.root / "nx_main")

            self.assertEqual(layout["root"], str(install.root))
            self.assertEqual(layout["nemu_dll"], str(dll))

    def test_parent_of_install_root_is_corrected_by_dll_location(self):
        """配置指到安装根的上一级时，用库的位置反推回真正的安装根。

        真实场景：`C:\\Program Files\\Netease` 这种「里面还有一层 MuMu」的配法。
        只靠目录内容排名会停在上级目录，把错路径交给 ``nemu_connect``；而库只有
        ``<root>[/nx_device/<系列>]/shell/sdk/`` 与 ``<root>/nx_main/sdk/`` 两种放法，
        按它反推是确定的。
        """
        with tempfile.TemporaryDirectory() as tmp:
            install = FakeMumuInstall(Path(tmp) / "Netease" / "MuMu")
            dll = install.add_android_series_dll("12.0")
            adb = install.add_adb()
            install.add_manager()

            layout = resolve_mumu_layout(install.root.parent)

            self.assertEqual(layout["root"], str(install.root))
            self.assertEqual(layout["nemu_dll"], str(dll))
            self.assertEqual(layout["adb"], str(adb))

    def test_nested_sdk_copy_does_not_promote_subfolder_to_root(self):
        """MuMu 5.30 真实布局：``nx_main/sdk`` 里也有一份同名 DLL。

        配成 ``nx_main`` 时，这份副本会让子目录看起来「库和可执行文件都齐了」，
        从而被误判成安装根（真机验证时踩到过）。安装根必须认 ``nx_device`` /
        ``nx_main`` 子目录，并且库里要选版本目录那一份。
        """
        with tempfile.TemporaryDirectory() as tmp:
            install = FakeMumuInstall(Path(tmp) / "MuMu")
            versioned_dll = install.add_android_series_dll("12.0")
            install.add_nx_main_sdk_dll()
            install.add_manager()
            install.add_adb()

            layout = resolve_mumu_layout(install.root / "nx_main")

            self.assertEqual(layout["root"], str(install.root))
            self.assertEqual(layout["nemu_dll"], str(versioned_dll))

    def test_missing_install_returns_start_and_empty_paths(self):
        from AutoScriptor.utils import mumu_discovery

        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "nope"

            # 关掉限深查找：它会沿着上级目录扫，而测试机的 %TEMP% 里可能留着被中断的
            # 运行建过的假 MuMu 目录。这里只验证「哪里都找不到」时的回落契约。
            with patch.object(mumu_discovery, "_bounded_find", return_value=[]):
                layout = mumu_discovery.resolve_mumu_layout(missing)
                paths = mumu_discovery.derive_paths_from_folder(missing)

            self.assertEqual(layout["root"], str(missing))
            self.assertEqual(layout["nemu_dll"], "")
            self.assertEqual(paths["emu_path"], "")
            self.assertEqual(paths["adb_path"], "")


class TestNemuIpcImplLayoutUse(unittest.TestCase):
    """NemuIpcImpl 要加载探测到的库，并把安装根传给 nemu_connect。"""

    def _build(self, nemu_folder: Path, install: FakeMumuInstall):
        from AutoScriptor.control.NemuIpc.device.method import nemu_ipc

        loaded_paths = []
        fake_lib = MagicMock()

        def record_load(path):
            loaded_paths.append(path)
            return fake_lib

        with patch.object(nemu_ipc.ctypes, "CDLL", side_effect=record_load):
            impl = nemu_ipc.NemuIpcImpl(str(nemu_folder), instance_id=0)
        return impl, loaded_paths

    def test_loads_newest_series_dll_and_connects_with_install_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            install = FakeMumuInstall(Path(tmp) / "MuMu")
            install.add_android_series_dll("12.0")
            newest = install.add_android_series_dll("15.0")
            install.add_manager()
            install.add_adb()

            impl, loaded_paths = self._build(install.root / "nx_main", install)

            self.assertEqual(loaded_paths, [str(newest)])
            self.assertEqual(impl.nemu_folder, str(install.root))

    def test_legacy_shell_sdk_dll_is_loaded_without_version_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            install = FakeMumuInstall(Path(tmp) / "MuMuPlayer-12.0")
            dll = install.add_legacy_shell_sdk_dll()

            impl, loaded_paths = self._build(install.root, install)

            self.assertEqual(loaded_paths, [str(dll)])
            self.assertEqual(impl.nemu_folder, str(install.root))


if __name__ == "__main__":
    unittest.main()
