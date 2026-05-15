"""
RuntimeContext 单元测试
======================
覆盖：单例模式、init/shutdown 生命周期、refresh 逻辑、
      _sync_globals 模块级变量同步、status_dict、线程安全。
"""

import sys
import os
import threading
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


def import_runtime_context_for_test():
    autoscriptor = types.ModuleType("AutoScriptor")
    autoscriptor.__path__ = [os.path.join(os.path.dirname(__file__), "..", "..", "AutoScriptor")]
    autoscriptor.mixctrl = None
    autoscriptor.mumu = None
    utils = types.ModuleType("AutoScriptor.utils")
    utils.__path__ = [os.path.join(os.path.dirname(__file__), "..", "..", "AutoScriptor", "utils")]
    cancel_module = types.ModuleType("AutoScriptor.utils.cancel")
    cancel_module.check_cancel_raise = lambda: None
    logger_module = types.ModuleType("AutoScriptor.utils.logger")
    logger_module.logger = SimpleNamespace(
        debug=lambda *args, **kwargs: None,
        info=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
        error=lambda *args, **kwargs: None,
    )
    with patch.dict(sys.modules, {
        "AutoScriptor": autoscriptor,
        "AutoScriptor.utils": utils,
        "AutoScriptor.utils.cancel": cancel_module,
        "AutoScriptor.utils.logger": logger_module,
    }):
        sys.modules.pop("services.core.runtime_context", None)
        import services.core.runtime_context as module
    return module


def app_config_stub(get_value=False):
    autoscriptor = types.ModuleType("AutoScriptor")
    autoscriptor.__path__ = [os.path.join(os.path.dirname(__file__), "..", "..", "AutoScriptor")]
    utils = types.ModuleType("AutoScriptor.utils")
    utils.__path__ = [os.path.join(os.path.dirname(__file__), "..", "..", "AutoScriptor", "utils")]
    app_config = types.ModuleType("AutoScriptor.utils.app_config")
    app_config.cfg = SimpleNamespace(get=lambda *args, **kwargs: get_value)
    return {
        "AutoScriptor": autoscriptor,
        "AutoScriptor.utils": utils,
        "AutoScriptor.utils.app_config": app_config,
    }


runtime_context_module = import_runtime_context_for_test()
RuntimeContext = runtime_context_module.RuntimeContext
runtime_ctx = runtime_context_module.runtime_ctx


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
        with patch.object(runtime_ctx, "_sync_globals"):
            runtime_ctx.init(mock_mix, mock_mumu)
        self.assertIs(runtime_ctx.mixctrl, mock_mix)
        self.assertIs(runtime_ctx.mumu, mock_mumu)
        self.assertTrue(runtime_ctx.is_initialized)

    def test_init_with_empty_controls_is_not_initialized(self):
        with patch.object(runtime_ctx, "_sync_globals"):
            runtime_ctx.init(None, None)
        self.assertFalse(runtime_ctx.is_initialized)

    def test_shutdown_clears(self):
        with patch.object(runtime_ctx, "_sync_globals"):
            runtime_ctx.init(object(), object())
        runtime_ctx.vlm_client = object()
        runtime_ctx.shutdown()
        self.assertIsNone(runtime_ctx.mixctrl)
        self.assertIsNone(runtime_ctx.mumu)
        self.assertIsNone(runtime_ctx.vlm_client)
        self.assertFalse(runtime_ctx.is_initialized)

    def test_shutdown_does_not_import_autoscriptor(self):
        ctx = RuntimeContext()
        sentinel = sys.modules.pop("AutoScriptor", None)
        try:
            ctx.shutdown()
            self.assertNotIn("AutoScriptor", sys.modules)
        finally:
            if sentinel is not None:
                sys.modules["AutoScriptor"] = sentinel


class TestRefresh(unittest.TestCase):
    """refresh 设备生命周期"""

    def setUp(self):
        self.ctx = RuntimeContext()

    def test_refresh_for_execution_always_starts_emulator_and_app(self):
        calls = []
        fake_cfg = {
            "emulator": {"index": 3, "adb_addr": "127.0.0.1:16480"},
            "app": {"app_to_start": "pkg", "auto_start": False},
        }

        def ensure_app_running(*args, **kwargs):
            calls.append((args, kwargs))
            return "mix", "mumu"

        autoscriptor = types.ModuleType("AutoScriptor")
        autoscriptor.__path__ = [os.path.join(os.path.dirname(__file__), "..", "..", "AutoScriptor")]
        autoscriptor.ensure_app_running = ensure_app_running
        autoscriptor.mixctrl = None
        autoscriptor.mumu = None
        core_pkg = types.ModuleType("AutoScriptor.core")
        core_pkg.__path__ = [os.path.join(os.path.dirname(__file__), "..", "..", "AutoScriptor", "core")]
        core_api = types.ModuleType("AutoScriptor.core.api")
        core_api.mixctrl = None
        core_api.mumu = None
        app_config = types.ModuleType("AutoScriptor.utils.app_config")
        app_config.cfg = fake_cfg

        with patch.dict(sys.modules, {
            "AutoScriptor": autoscriptor,
            "AutoScriptor.core": core_pkg,
            "AutoScriptor.core.api": core_api,
            "AutoScriptor.utils.app_config": app_config,
        }):
            self.ctx.refresh(cancel_check=lambda: None)

        args, kwargs = calls[0]
        self.assertEqual(args, (3, "127.0.0.1:16480", "pkg"))
        self.assertTrue(kwargs["start_emulator"])
        self.assertTrue(kwargs["launch_app"])
        self.assertTrue(callable(kwargs["cancel_check"]))
        self.assertTrue(self.ctx.is_initialized)
        self.assertEqual(core_api.mixctrl, "mix")
        self.assertEqual(autoscriptor.mumu, "mumu")

    def test_refresh_is_serialized(self):
        started = threading.Event()
        release = threading.Event()
        second_entered = threading.Event()
        calls = []
        fake_cfg = {
            "emulator": {"index": 1, "adb_addr": "addr"},
            "app": {"app_to_start": "pkg", "auto_start": False},
        }

        def ensure_app_running(*args, **kwargs):
            calls.append(threading.current_thread().name)
            if len(calls) == 1:
                started.set()
                release.wait(1)
            else:
                second_entered.set()
            return object(), object()

        autoscriptor = types.ModuleType("AutoScriptor")
        autoscriptor.__path__ = [os.path.join(os.path.dirname(__file__), "..", "..", "AutoScriptor")]
        autoscriptor.ensure_app_running = ensure_app_running
        core_pkg = types.ModuleType("AutoScriptor.core")
        core_pkg.__path__ = [os.path.join(os.path.dirname(__file__), "..", "..", "AutoScriptor", "core")]
        core_api = types.ModuleType("AutoScriptor.core.api")
        app_config = types.ModuleType("AutoScriptor.utils.app_config")
        app_config.cfg = fake_cfg

        with patch.dict(sys.modules, {
            "AutoScriptor": autoscriptor,
            "AutoScriptor.core": core_pkg,
            "AutoScriptor.core.api": core_api,
            "AutoScriptor.utils.app_config": app_config,
        }):
            t1 = threading.Thread(target=self.ctx.refresh, kwargs={"cancel_check": lambda: None}, name="r1")
            t2 = threading.Thread(target=self.ctx.refresh, kwargs={"cancel_check": lambda: None}, name="r2")
            t1.start()
            started.wait(1)
            t2.start()
            self.assertFalse(second_entered.wait(0.1))
            release.set()
            t1.join(1)
            t2.join(1)

        self.assertEqual(calls, ["r1", "r2"])


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
        with patch.object(runtime_ctx, "_sync_globals"):
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
        with patch.dict(sys.modules, app_config_stub(get_value=False)):
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
