"""
后台监控改革 单元测试
====================
覆盖：DEFAULT_INTERVAL=1.0、_check_concurrent 接受 screenshot、
      ui_T/locate screenshot 参数透传、BackgroundMonitor 基本增删。
"""

import sys
import os
import inspect
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


if __name__ == "__main__":
    unittest.main()
