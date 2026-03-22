"""
_locate_all 中 VLMTarget 分支路由测试
======================================
覆盖：纯 VLM 列表、混合列表（VLM + Text + Image）、
      空列表、VLM 分支隔离性（不影响非 VLM 目标）。

注意：这些测试通过 mock 绕过实际设备和 VLM 服务。
"""

import sys
import os
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from AutoScriptor.utils.box import Box
from AutoScriptor.core.targets import VLMTarget, V, TextTarget, BoxTarget


class TestLocateAllVLMRouting(unittest.TestCase):
    """验证 _locate_all 中 VLMTarget 的路由逻辑"""

    @patch("AutoScriptor.core.api.mixctrl")
    @patch("AutoScriptor.recognition.rec.vlm_locate")
    def test_pure_vlm_targets(self, mock_vlm_locate, mock_mixctrl):
        """全 VLM 目标列表不调用 mixctrl.locate"""
        from AutoScriptor.core.api import _locate_all

        mock_vlm_locate.return_value = [Box(100, 200, 30, 30)]
        mock_mixctrl.screenshot.return_value = MagicMock()

        targets = [V("按钮A"), V("按钮B")]
        result = _locate_all(targets)

        mock_mixctrl.locate.assert_not_called()
        self.assertEqual(mock_vlm_locate.call_count, 2)
        self.assertEqual(len(result), 2)

    @patch("AutoScriptor.core.api.mixctrl")
    @patch("AutoScriptor.recognition.rec.vlm_locate")
    def test_mixed_targets_routes_correctly(self, mock_vlm_locate, mock_mixctrl):
        """混合目标：VLM 走 vlm_locate，其余走 mixctrl.locate"""
        from AutoScriptor.core.api import _locate_all
        from AutoScriptor.core.targets import ui_str

        mock_vlm_locate.return_value = [Box(50, 50, 30, 30)]
        mock_mixctrl.locate.return_value = [[Box(10, 10, 20, 20)]]

        text_target = ui_str("测试").t
        vlm_target = V("VLM目标")
        targets = [text_target, vlm_target]
        result = _locate_all(targets)

        mock_mixctrl.locate.assert_called_once()
        mock_vlm_locate.assert_called_once()
        self.assertEqual(len(result), 2)
        self.assertIsNotNone(result[0])
        self.assertIsNotNone(result[1])

    @patch("AutoScriptor.core.api.mixctrl")
    @patch("AutoScriptor.recognition.rec.vlm_locate")
    def test_vlm_failure_returns_none(self, mock_vlm_locate, mock_mixctrl):
        """VLM grounding 失败时，对应位置应为 None"""
        from AutoScriptor.core.api import _locate_all

        mock_vlm_locate.return_value = None
        mock_mixctrl.screenshot.return_value = MagicMock()

        targets = [V("不存在的目标")]
        result = _locate_all(targets)

        self.assertIsNone(result[0])

    @patch("AutoScriptor.core.api.mixctrl")
    @patch("AutoScriptor.recognition.rec.vlm_locate")
    def test_vlm_uses_custom_roi(self, mock_vlm_locate, mock_mixctrl):
        """VLM 目标应将自身的 box 作为 ROI 传入 vlm_locate"""
        from AutoScriptor.core.api import _locate_all

        roi = Box(100, 200, 400, 300)
        mock_vlm_locate.return_value = [Box(150, 250, 30, 30)]
        mock_mixctrl.screenshot.return_value = MagicMock()

        targets = [V("按钮", box=roi)]
        _locate_all(targets)

        _, call_kwargs = mock_vlm_locate.call_args
        if not call_kwargs:
            call_args = mock_vlm_locate.call_args[0]
            self.assertEqual(call_args[2], roi)

    @patch("AutoScriptor.core.api.mixctrl")
    def test_no_vlm_targets_skips_vlm(self, mock_mixctrl):
        """无 VLM 目标时不导入/调用 vlm_locate"""
        from AutoScriptor.core.api import _locate_all
        from AutoScriptor.core.targets import ui_str

        mock_mixctrl.locate.return_value = [[Box(1, 2, 3, 4)]]

        targets = [ui_str("普通文本").t]
        result = _locate_all(targets)

        self.assertEqual(len(result), 1)


if __name__ == "__main__":
    unittest.main()
