"""
后台监控改革 单元测试
====================
覆盖：DEFAULT_INTERVAL=1.0、_check_concurrent 接受 screenshot、
      ui_T/locate screenshot 参数透传、BackgroundMonitor 基本增删。
"""

import sys
import os
import inspect
import threading
import unittest
from unittest.mock import patch, MagicMock

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from AutoScriptor.core import background
from AutoScriptor.core.background import BackgroundMonitor


# ---------------------------------------------------------------------------
# 默认间隔
# ---------------------------------------------------------------------------

class TestDefaultInterval(unittest.TestCase):

    def test_module_constant(self):
        self.assertEqual(background.DEFAULT_INTERVAL, 1.0)

    @patch.object(BackgroundMonitor, "start")
    def test_monitor_uses_default(self, _):
        mon = BackgroundMonitor()
        self.assertEqual(mon._interval, 1.0)


# ---------------------------------------------------------------------------
# _check_concurrent 签名
# ---------------------------------------------------------------------------

class TestCheckConcurrentSignature(unittest.TestCase):

    def test_accepts_screenshot_param(self):
        sig = inspect.signature(BackgroundMonitor._check_concurrent)
        self.assertIn("screenshot", sig.parameters)
        self.assertIsNone(sig.parameters["screenshot"].default)


# ---------------------------------------------------------------------------
# ui_T / locate 签名
# ---------------------------------------------------------------------------

class TestUiTSignature(unittest.TestCase):

    def test_has_screenshot_kwarg(self):
        from AutoScriptor.core.api import ui_T

        sig = inspect.signature(ui_T)
        self.assertIn("screenshot", sig.parameters)
        self.assertEqual(
            sig.parameters["screenshot"].kind,
            inspect.Parameter.KEYWORD_ONLY,
        )
        self.assertIsNone(sig.parameters["screenshot"].default)


class TestLocateSignature(unittest.TestCase):

    def test_has_screenshot_param(self):
        from AutoScriptor.core.api import locate

        sig = inspect.signature(locate)
        self.assertIn("screenshot", sig.parameters)
        self.assertIsNone(sig.parameters["screenshot"].default)


# ---------------------------------------------------------------------------
# screenshot 透传
# ---------------------------------------------------------------------------

class TestLocatePassthrough(unittest.TestCase):
    """验证 screenshot 经由 locate → _locate_all → mixctrl.locate 完整透传"""

    @patch("AutoScriptor.core.api._ensure_boosted")
    @patch("AutoScriptor.core.api.mixctrl")
    def test_screenshot_reaches_mixctrl(self, mock_ctrl, _mock_boost):
        mock_ctrl.locate.return_value = [None]

        from AutoScriptor.core.api import locate
        from AutoScriptor.core.targets import T

        fake = np.zeros((720, 1280, 3), dtype=np.uint8)
        locate((T("test"),), timeout=0, assure_stable=False, screenshot=fake)

        _, kwargs = mock_ctrl.locate.call_args
        self.assertIs(kwargs.get("screenshot"), fake)

    @patch("AutoScriptor.core.api._ensure_boosted")
    @patch("AutoScriptor.core.api.mixctrl")
    def test_none_screenshot_default(self, mock_ctrl, _mock_boost):
        mock_ctrl.locate.return_value = [None]

        from AutoScriptor.core.api import locate
        from AutoScriptor.core.targets import T

        locate((T("test"),), timeout=0, assure_stable=False)

        _, kwargs = mock_ctrl.locate.call_args
        self.assertIsNone(kwargs.get("screenshot"))


# ---------------------------------------------------------------------------
# BackgroundMonitor 回调 CRUD（不启动线程）
# ---------------------------------------------------------------------------

class TestBackgroundMonitorCallbacks(unittest.TestCase):

    @patch.object(BackgroundMonitor, "start")
    def test_add_and_retrieve(self, _):
        mon = BackgroundMonitor()
        cb = MagicMock()
        idf = (MagicMock(),)
        mon.add("evt", idf, cb)

        self.assertIn("evt", mon._callbacks)
        self.assertIs(mon._callbacks["evt"]["cb"], cb)

    @patch.object(BackgroundMonitor, "start")
    def test_remove(self, _):
        mon = BackgroundMonitor()
        mon.add("evt", (MagicMock(),), MagicMock())
        mon.remove("evt")

        self.assertNotIn("evt", mon._callbacks)

    @patch.object(BackgroundMonitor, "start")
    def test_clear_callbacks(self, _):
        mon = BackgroundMonitor()
        mon.add("a", (MagicMock(),), MagicMock())
        mon.add("b", (MagicMock(),), MagicMock())
        mon.clear()

        self.assertEqual(len(mon._callbacks), 0)

    @patch.object(BackgroundMonitor, "start")
    def test_clear_preserves_signals_by_default(self, _):
        mon = BackgroundMonitor()
        mon.set_signal("key", "val")
        mon.clear(clear_signals=False)

        self.assertEqual(mon.signal("key"), "val")

    @patch.object(BackgroundMonitor, "start")
    def test_clear_with_signals(self, _):
        mon = BackgroundMonitor()
        mon.set_signal("key", "val")
        mon.clear(clear_signals=True)

        self.assertIsNone(mon.signal("key"))

    @patch.object(BackgroundMonitor, "start")
    def test_stale_snapshot_callback_is_not_current_after_clear(self, _):
        mon = BackgroundMonitor()
        cb = MagicMock()
        mon.add("evt", (MagicMock(),), cb)
        old_info = mon._callbacks["evt"]

        mon.clear()

        self.assertFalse(mon._callback_is_current("evt", old_info))

    @patch.object(BackgroundMonitor, "start")
    def test_remove_with_expected_info_does_not_remove_replaced_callback(self, _):
        mon = BackgroundMonitor()
        old_cb = MagicMock()
        new_cb = MagicMock()
        mon.add("evt", (MagicMock(),), old_cb)
        old_info = mon._callbacks["evt"]
        mon.add("evt", (MagicMock(),), new_cb)

        mon.remove("evt", expected_info=old_info)

        self.assertIn("evt", mon._callbacks)
        self.assertIs(mon._callbacks["evt"]["cb"], new_cb)

    @patch.object(BackgroundMonitor, "start")
    def test_scope_removes_callbacks_on_exit(self, _):
        mon = BackgroundMonitor()
        with mon.scope("battle") as scope:
            name = scope.add("end", (MagicMock(),), MagicMock())
            self.assertEqual(name, "battle:end")
            self.assertIn("battle:end", mon._callbacks)

        self.assertNotIn("battle:end", mon._callbacks)

    @patch.object(BackgroundMonitor, "start")
    def test_scope_removes_callbacks_on_exception(self, _):
        mon = BackgroundMonitor()
        with self.assertRaises(RuntimeError):
            with mon.scope("battle") as scope:
                scope.add("end", (MagicMock(),), MagicMock())
                raise RuntimeError("boom")

        self.assertEqual(mon.get_idfs(), set())

    @patch.object(BackgroundMonitor, "start")
    def test_scope_does_not_remove_replaced_callback(self, _):
        mon = BackgroundMonitor()
        replacement = MagicMock()
        with mon.scope("battle") as scope:
            scope.add("end", (MagicMock(),), MagicMock())
            mon.add("battle:end", (MagicMock(),), replacement)

        self.assertIn("battle:end", mon._callbacks)
        self.assertIs(mon._callbacks["battle:end"]["cb"], replacement)

    @patch.object(BackgroundMonitor, "start")
    def test_protect_clear_ignores_external_clear(self, _):
        mon = BackgroundMonitor()
        mon.add("evt", (MagicMock(),), MagicMock())

        with mon.protect_clear():
            done = threading.Event()
            t = threading.Thread(target=lambda: (mon.clear(clear_signals=True), done.set()))
            t.start()
            done.wait(1)
            t.join(1)

        self.assertIn("evt", mon._callbacks)

    @patch.object(BackgroundMonitor, "start")
    def test_protect_clear_allows_monitor_thread_clear(self, _):
        mon = BackgroundMonitor()
        mon.add("evt", (MagicMock(),), MagicMock())

        with mon.protect_clear():
            mon._enter_callback_thread()
            try:
                mon.clear()
            finally:
                mon._exit_callback_thread()

        self.assertEqual(mon.get_idfs(), set())


# ---------------------------------------------------------------------------
# signal 读写
# ---------------------------------------------------------------------------

class TestBackgroundMonitorSignals(unittest.TestCase):

    @patch.object(BackgroundMonitor, "start")
    def test_set_get(self, _):
        mon = BackgroundMonitor()
        mon.set_signal("flag", True)
        self.assertTrue(mon.signal("flag"))

    @patch.object(BackgroundMonitor, "start")
    def test_default_value(self, _):
        mon = BackgroundMonitor()
        self.assertIsNone(mon.signal("missing"))
        self.assertEqual(mon.signal("missing", 42), 42)

    @patch.object(BackgroundMonitor, "start")
    def test_clear_signals(self, _):
        mon = BackgroundMonitor()
        mon.set_signal("a", 1)
        mon.set_signal("b", 2)
        mon.clear_signals()

        self.assertIsNone(mon.signal("a"))
        self.assertIsNone(mon.signal("b"))

    @patch.object(BackgroundMonitor, "start")
    def test_wait_signal_returns_when_expected_matches(self, _):
        mon = BackgroundMonitor()
        mon.set_signal("ready", True)

        self.assertTrue(mon.wait_signal("ready", timeout=0.1))

    @patch.object(BackgroundMonitor, "start")
    def test_wait_signal_times_out(self, _):
        mon = BackgroundMonitor()

        with self.assertRaises(TimeoutError):
            mon.wait_signal("ready", timeout=0.01, interval=0.001)


# ---------------------------------------------------------------------------
# set_interval
# ---------------------------------------------------------------------------

class TestBackgroundMonitorInterval(unittest.TestCase):

    @patch.object(BackgroundMonitor, "start")
    def test_set_interval(self, _):
        mon = BackgroundMonitor()
        mon.set_interval(2.0)
        self.assertEqual(mon._interval, 2.0)

    @patch.object(BackgroundMonitor, "start")
    def test_set_interval_below_default(self, _):
        mon = BackgroundMonitor()
        mon.set_interval(0.5)
        self.assertEqual(mon._interval, 0.5)


class TestMonitorDecorator(unittest.TestCase):

    @patch.object(BackgroundMonitor, "start")
    def test_monitor_decorator_registers_and_cleans_legacy_pairs(self, _):
        mon = BackgroundMonitor()
        cb = MagicMock()
        idf = (MagicMock(),)

        with patch.object(background, "bg", mon):
            @background.monitor([(idf, cb)])
            def run():
                self.assertIn("run:0", mon._callbacks)
                return "ok"

            self.assertEqual(run(), "ok")

        self.assertEqual(mon.get_idfs(), set())

    @patch.object(BackgroundMonitor, "start")
    def test_monitor_decorator_cleans_on_exception(self, _):
        mon = BackgroundMonitor()

        with patch.object(background, "bg", mon):
            @background.monitor([("named", (MagicMock(),), MagicMock())])
            def run():
                self.assertIn("named", mon._callbacks)
                raise RuntimeError("boom")

            with self.assertRaises(RuntimeError):
                run()

        self.assertEqual(mon.get_idfs(), set())

    @patch.object(BackgroundMonitor, "start")
    def test_monitor_decorator_accepts_dict_pairs(self, _):
        mon = BackgroundMonitor()
        cb = MagicMock()

        with patch.object(background, "bg", mon):
            @background.monitor([{
                "name": "dict_evt",
                "identifier": (MagicMock(),),
                "callback": cb,
                "once": False,
            }])
            def run():
                self.assertIn("dict_evt", mon._callbacks)
                self.assertFalse(mon._callbacks["dict_evt"]["once"])

            run()

        self.assertEqual(mon.get_idfs(), set())

    @patch.object(BackgroundMonitor, "start")
    def test_monitor_decorator_does_not_remove_replaced_callback(self, _):
        mon = BackgroundMonitor()
        replacement = MagicMock()

        with patch.object(background, "bg", mon):
            @background.monitor([("named", (MagicMock(),), MagicMock())])
            def run():
                mon.add("named", (MagicMock(),), replacement)

            run()

        self.assertIn("named", mon._callbacks)
        self.assertIs(mon._callbacks["named"]["cb"], replacement)


if __name__ == "__main__":
    unittest.main()
