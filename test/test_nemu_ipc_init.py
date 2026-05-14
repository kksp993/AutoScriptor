"""
验证 NemuIpcImpl.__init__ 在各种 DLL 加载失败场景下的行为。

原始 bug: `for ipc_dll in list_dll` 循环结束后 `if not ipc_dll` 永远为 False，
导致 DLL 全部加载失败时 self.lib 未赋值且不抛异常，后续访问报
AttributeError: 'NemuIpcImpl' object has no attribute 'lib'。
"""

import ctypes
import importlib
import importlib.util
import os
import sys
import types
import unittest
from unittest.mock import patch, MagicMock

# ---------- 绕过 AutoScriptor.__init__ 的重量级导入链 ----------
# 先注册一系列 stub 模块，防止 nemu_ipc.py 的 import 触发整包初始化
_STUBS = {
    "AutoScriptor": types.ModuleType("AutoScriptor"),
    "AutoScriptor.control": types.ModuleType("AutoScriptor.control"),
    "AutoScriptor.control.NemuIpc": types.ModuleType("AutoScriptor.control.NemuIpc"),
    "AutoScriptor.control.NemuIpc.base": types.ModuleType("AutoScriptor.control.NemuIpc.base"),
    "AutoScriptor.control.NemuIpc.device": types.ModuleType("AutoScriptor.control.NemuIpc.device"),
    "AutoScriptor.control.NemuIpc.device.method": types.ModuleType("AutoScriptor.control.NemuIpc.device.method"),
    "AutoScriptor.control.NemuIpc.config": types.ModuleType("AutoScriptor.control.NemuIpc.config"),
    "AutoScriptor.utils": types.ModuleType("AutoScriptor.utils"),
}

# 需要提供真实的子模块（nemu_ipc.py 实际 import 的）
_BASE = os.path.join(os.path.dirname(__file__), os.pardir)

def _load_real(dotted: str, file_rel: str):
    """从文件加载真实模块，挂到 sys.modules"""
    fpath = os.path.normpath(os.path.join(_BASE, file_rel))
    spec = importlib.util.spec_from_file_location(dotted, fpath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[dotted] = mod
    spec.loader.exec_module(mod)
    return mod

# 注入 stubs
for name, mod in _STUBS.items():
    sys.modules.setdefault(name, mod)

# 提供 logger stub
_logger_mod = types.ModuleType("AutoScriptor.utils.logger")
_logger_mod.logger = MagicMock()
sys.modules["AutoScriptor.utils.logger"] = _logger_mod

# 提供 cfg stub
_const_mod = types.ModuleType("AutoScriptor.utils.app_config")
_const_mod.cfg = {"emulator": {"mumu_folder": "C:/FakeNemu"}}
sys.modules["AutoScriptor.utils.app_config"] = _const_mod

# 加载真实依赖子模块
_load_real("AutoScriptor.control.NemuIpc.base.decorator",
           "AutoScriptor/control/NemuIpc/base/decorator.py")
_load_real("AutoScriptor.control.NemuIpc.base.timer",
           "AutoScriptor/control/NemuIpc/base/timer.py")

# base.utils 可能有子包
_bu = types.ModuleType("AutoScriptor.control.NemuIpc.base.utils")
sys.modules["AutoScriptor.control.NemuIpc.base.utils"] = _bu

_load_real("AutoScriptor.control.NemuIpc.base.utils.utils",
           "AutoScriptor/control/NemuIpc/base/utils/utils.py")
_bu_utils = sys.modules["AutoScriptor.control.NemuIpc.base.utils.utils"]
for attr in ("ensure_time", "random_rectangle_point"):
    if hasattr(_bu_utils, attr):
        setattr(_bu, attr, getattr(_bu_utils, attr))

_load_real("AutoScriptor.control.NemuIpc.config.deep",
           "AutoScriptor/control/NemuIpc/config/deep.py")

# pool / utils stubs
_pool_mod = types.ModuleType("AutoScriptor.control.NemuIpc.device.method.pool")
_pool_mod.WORKER_POOL = MagicMock()
sys.modules["AutoScriptor.control.NemuIpc.device.method.pool"] = _pool_mod

_utils_mod = types.ModuleType("AutoScriptor.control.NemuIpc.device.method.utils")
_utils_mod.RETRY_TRIES = 3
_utils_mod.retry_sleep = lambda i: 0
sys.modules["AutoScriptor.control.NemuIpc.device.method.utils"] = _utils_mod

# 最终加载目标模块
_nemu = _load_real(
    "AutoScriptor.control.NemuIpc.device.method.nemu_ipc",
    "AutoScriptor/control/NemuIpc/device/method/nemu_ipc.py",
)
NemuIpcImpl = _nemu.NemuIpcImpl
NemuIpcIncompatible = _nemu.NemuIpcIncompatible

# ---------- 测试 ----------

FAKE_FOLDER = "C:/FakeNemu"
CANDIDATE_PATHS = [
    os.path.abspath(os.path.join(FAKE_FOLDER, "./shell/sdk/external_renderer_ipc.dll")),
    os.path.abspath(os.path.join(FAKE_FOLDER, "./nx_device/12.0/shell/sdk/external_renderer_ipc.dll")),
]


class TestNemuIpcImplInit(unittest.TestCase):
    """NemuIpcImpl.__init__ DLL 加载场景测试"""

    @patch("AutoScriptor.control.NemuIpc.device.method.nemu_ipc.ctypes")
    @patch("AutoScriptor.control.NemuIpc.device.method.nemu_ipc.os.path.exists",
           return_value=False)
    def test_a_no_dll_exists_raises_incompatible(self, mock_exists, mock_ctypes):
        """两个候选路径都不存在时，必须抛出 NemuIpcIncompatible"""
        with self.assertRaises(NemuIpcIncompatible) as ctx:
            NemuIpcImpl(FAKE_FOLDER, instance_id=0)
        self.assertIn("external_renderer_ipc.dll", str(ctx.exception))
        mock_ctypes.CDLL.assert_not_called()

    @patch("AutoScriptor.control.NemuIpc.device.method.nemu_ipc.ctypes")
    @patch("AutoScriptor.control.NemuIpc.device.method.nemu_ipc.os.path.exists",
           return_value=True)
    def test_b_dll_exists_but_load_fails(self, mock_exists, mock_ctypes):
        """文件存在但 CDLL 加载失败时，必须抛出 NemuIpcIncompatible"""
        mock_ctypes.CDLL.side_effect = OSError("dependency missing")
        with self.assertRaises(NemuIpcIncompatible):
            NemuIpcImpl(FAKE_FOLDER, instance_id=0)

    @patch("AutoScriptor.control.NemuIpc.device.method.nemu_ipc.ctypes")
    def test_c_first_missing_second_load_fails(self, mock_ctypes):
        """第一路径不存在、第二路径加载失败 → NemuIpcIncompatible"""
        mock_ctypes.CDLL.side_effect = OSError("bad dll")

        def exists_side(path):
            return path == CANDIDATE_PATHS[1]

        with patch("AutoScriptor.control.NemuIpc.device.method.nemu_ipc.os.path.exists",
                    side_effect=exists_side):
            with self.assertRaises(NemuIpcIncompatible):
                NemuIpcImpl(FAKE_FOLDER, instance_id=0)

    @patch("AutoScriptor.control.NemuIpc.device.method.nemu_ipc.ctypes")
    def test_d_second_path_loads_successfully(self, mock_ctypes):
        """第一路径不存在、第二路径加载成功 → self.lib 正确赋值"""
        fake_lib = MagicMock()
        mock_ctypes.CDLL.return_value = fake_lib

        def exists_side(path):
            return path == CANDIDATE_PATHS[1]

        with patch("AutoScriptor.control.NemuIpc.device.method.nemu_ipc.os.path.exists",
                    side_effect=exists_side):
            impl = NemuIpcImpl(FAKE_FOLDER, instance_id=0)

        self.assertIs(impl.lib, fake_lib)
        self.assertEqual(impl.connect_id, 0)

    @patch("AutoScriptor.control.NemuIpc.device.method.nemu_ipc.ctypes")
    @patch("AutoScriptor.control.NemuIpc.device.method.nemu_ipc.os.path.exists",
           return_value=True)
    def test_e_first_path_loads_stops_early(self, mock_exists, mock_ctypes):
        """第一路径加载成功时，不再尝试第二路径"""
        fake_lib = MagicMock()
        mock_ctypes.CDLL.return_value = fake_lib

        impl = NemuIpcImpl(FAKE_FOLDER, instance_id=0)

        mock_ctypes.CDLL.assert_called_once()
        self.assertIs(impl.lib, fake_lib)

    @patch("AutoScriptor.control.NemuIpc.device.method.nemu_ipc.ctypes")
    @patch("AutoScriptor.control.NemuIpc.device.method.nemu_ipc.os.path.exists",
           return_value=True)
    def test_f_no_half_initialized_object(self, mock_exists, mock_ctypes):
        """失败时不产生缺少 lib 属性的半初始化对象"""
        mock_ctypes.CDLL.side_effect = OSError("fail")
        with self.assertRaises(NemuIpcIncompatible):
            NemuIpcImpl(FAKE_FOLDER, instance_id=0)


if __name__ == "__main__":
    unittest.main()
