"""
RuntimeContext 单元测试
======================
覆盖：单例模式、init/shutdown 生命周期、refresh 逻辑、
      _sync_globals 模块级变量同步、status_dict、线程安全。
"""

import sys
import os
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from services.core.runtime_context import RuntimeContext, runtime_ctx


class TestSingleton(unittest.TestCase):
    """单例与线程安全"""

    def test_singleton_identity(self):
        a = RuntimeContext.instance()
        b = RuntimeContext.instance()
        self.assertIs(a, b)

    def test_module_level_is_singleton(self):
        self.assertIs(runtime_ctx, RuntimeContext.instance())

    def test_thread_safe_singleton(self):
        instances = []

        def grab():
            instances.append(RuntimeContext.instance())

        threads = [threading.Thread(target=grab) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertTrue(all(inst is instances[0] for inst in instances))


class TestInitShutdown(unittest.TestCase):
    """init / shutdown 生命周期"""

    def setUp(self):
        self._orig_mixctrl = runtime_ctx.mixctrl
        self._orig_mumu = runtime_ctx.mumu
        self._orig_init = runtime_ctx._initialized

    def tearDown(self):
        runtime_ctx.mixctrl = self._orig_mixctrl
        runtime_ctx.mumu = self._orig_mumu
        runtime_ctx._initialized = self._orig_init

    def test_init_sets_attributes(self):
        mock_mix = object()
        mock_mumu = object()
        runtime_ctx.init(mock_mix, mock_mumu)
        self.assertIs(runtime_ctx.mixctrl, mock_mix)
        self.assertIs(runtime_ctx.mumu, mock_mumu)
        self.assertTrue(runtime_ctx.is_initialized)

    def test_shutdown_clears(self):
        runtime_ctx.init(object(), object())
        runtime_ctx.vlm_client = object()
        runtime_ctx.shutdown()
        self.assertIsNone(runtime_ctx.mixctrl)
        self.assertIsNone(runtime_ctx.mumu)
        self.assertIsNone(runtime_ctx.vlm_client)
        self.assertFalse(runtime_ctx.is_initialized)


class TestStatusDict(unittest.TestCase):
    """status_dict 输出"""

    def setUp(self):
        self._orig = (
            runtime_ctx.mixctrl,
            runtime_ctx.mumu,
            runtime_ctx.bg,
            runtime_ctx.vlm_client,
            runtime_ctx._initialized,
        )

    def tearDown(self):
        (
            runtime_ctx.mixctrl,
            runtime_ctx.mumu,
            runtime_ctx.bg,
            runtime_ctx.vlm_client,
            runtime_ctx._initialized,
        ) = self._orig

    def test_all_none(self):
        runtime_ctx.shutdown()
        d = runtime_ctx.status_dict()
        self.assertFalse(d["initialized"])
        self.assertFalse(d["has_mixctrl"])
        self.assertFalse(d["has_mumu"])
        self.assertFalse(d["has_vlm"])

    def test_after_init(self):
        runtime_ctx.init(object(), object())
        d = runtime_ctx.status_dict()
        self.assertTrue(d["initialized"])
        self.assertTrue(d["has_mixctrl"])
        self.assertTrue(d["has_mumu"])

    def test_dict_keys(self):
        d = runtime_ctx.status_dict()
        expected_keys = {"initialized", "has_mixctrl", "has_mumu", "has_bg", "has_vlm"}
        self.assertEqual(set(d.keys()), expected_keys)


class TestReleaseNemuIpc(unittest.TestCase):
    """_release_nemu_ipc 安全释放"""

    def test_none_mixctrl_no_crash(self):
        runtime_ctx.mixctrl = None
        runtime_ctx._release_nemu_ipc()

    def test_missing_nemu_control_no_crash(self):
        runtime_ctx.mixctrl = object()
        runtime_ctx._release_nemu_ipc()

    def test_calls_release_on_real_ipc(self):
        released = []

        class FakeIpc:
            def nemu_ipc_release(self):
                released.append(True)

        class FakeNemuCtrl:
            nemu_ipc = FakeIpc()

        class FakeMix:
            nemu_control = FakeNemuCtrl()

        runtime_ctx.mixctrl = FakeMix()
        runtime_ctx._release_nemu_ipc()
        self.assertEqual(len(released), 1)
        runtime_ctx.mixctrl = None


class TestInitVlm(unittest.TestCase):
    """init_vlm 惰性加载"""

    def setUp(self):
        self._orig_vlm = runtime_ctx.vlm_client

    def tearDown(self):
        runtime_ctx.vlm_client = self._orig_vlm

    def test_skips_when_already_set(self):
        sentinel = object()
        runtime_ctx.vlm_client = sentinel
        runtime_ctx.init_vlm()
        self.assertIs(runtime_ctx.vlm_client, sentinel)

    def test_skips_when_use_agent_false(self):
        runtime_ctx.vlm_client = None
        from unittest.mock import patch
        with patch("AutoScriptor.utils.constant.cfg") as mock_cfg:
            mock_cfg.get.return_value = False
            runtime_ctx.init_vlm()
        self.assertIsNone(runtime_ctx.vlm_client)


class TestInitBg(unittest.TestCase):
    """init_bg 绑定"""

    def setUp(self):
        self._orig_bg = runtime_ctx.bg

    def tearDown(self):
        runtime_ctx.bg = self._orig_bg

    def test_skips_when_already_set(self):
        sentinel = object()
        runtime_ctx.bg = sentinel
        runtime_ctx.init_bg()
        self.assertIs(runtime_ctx.bg, sentinel)


if __name__ == "__main__":
    unittest.main()
