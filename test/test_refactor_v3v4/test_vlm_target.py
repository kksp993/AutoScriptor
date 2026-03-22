"""
VLMTarget + V() 单元测试
========================
覆盖：VLMTarget 构建、repr、Box 默认值、V() 工厂函数、
      Target 继承关系、与 _locate_all 的集成路径。
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from AutoScriptor.utils.box import Box
from AutoScriptor.core.targets import (
    Target, ImageTarget, TextTarget, BoxTarget, VLMTarget, V, I, T, B,
)


class TestVLMTargetConstruction(unittest.TestCase):
    """VLMTarget 构建与属性"""

    def test_basic_creation(self):
        vt = VLMTarget("确认按钮")
        self.assertEqual(vt.description, "确认按钮")
        self.assertEqual(vt.box, Box(0, 0, 1280, 720))

    def test_custom_box(self):
        roi = Box(100, 200, 400, 300)
        vt = VLMTarget("关闭图标", box=roi)
        self.assertEqual(vt.box, roi)

    def test_none_box_fallback(self):
        vt = VLMTarget("test", box=None)
        self.assertEqual(vt.box, Box(0, 0, 1280, 720))


class TestVLMTargetRepr(unittest.TestCase):
    """VLMTarget __repr__ 格式"""

    def test_repr_default_box(self):
        vt = VLMTarget("开始游戏")
        self.assertEqual(repr(vt), "V('开始游戏')")

    def test_repr_custom_box(self):
        vt = VLMTarget("设置", box=Box(10, 20, 30, 40))
        self.assertIn("V('设置')", repr(vt))
        self.assertIn("@[", repr(vt))

    def test_repr_contains_description(self):
        desc = "一个很长的中文描述用于测试"
        vt = VLMTarget(desc)
        self.assertIn(desc, repr(vt))


class TestVFactory(unittest.TestCase):
    """V() 工厂函数"""

    def test_v_returns_vlm_target(self):
        result = V("搜索框")
        self.assertIsInstance(result, VLMTarget)
        self.assertEqual(result.description, "搜索框")

    def test_v_with_box_kwarg(self):
        roi = Box(50, 50, 200, 100)
        result = V("输入框", box=roi)
        self.assertEqual(result.box, roi)

    def test_v_default_box(self):
        result = V("按钮")
        self.assertEqual(result.box, Box(0, 0, 1280, 720))


class TestVLMTargetInheritance(unittest.TestCase):
    """继承关系与类型检查"""

    def test_is_target_subclass(self):
        self.assertTrue(issubclass(VLMTarget, Target))

    def test_isinstance_target(self):
        vt = V("test")
        self.assertIsInstance(vt, Target)

    def test_not_image_or_text_target(self):
        vt = V("test")
        self.assertNotIsInstance(vt, ImageTarget)
        self.assertNotIsInstance(vt, TextTarget)
        self.assertNotIsInstance(vt, BoxTarget)


class TestVLMTargetCoexistence(unittest.TestCase):
    """VLMTarget 与其他 Target 类型共存"""

    def test_mixed_tuple(self):
        targets = (V("确认按钮"), T("取消"), B(100, 200, 50, 50))
        self.assertEqual(len(targets), 3)
        self.assertIsInstance(targets[0], VLMTarget)
        self.assertIsInstance(targets[1], TextTarget)
        self.assertIsInstance(targets[2], BoxTarget)

    def test_in_list(self):
        targets = [V("搜索"), V("菜单")]
        self.assertTrue(all(isinstance(t, VLMTarget) for t in targets))


class TestVLMLocateIntegration(unittest.TestCase):
    """vlm_locate 函数的基本单元测试（不依赖 VLM 服务器）"""

    def test_vlm_locate_import(self):
        from AutoScriptor.recognition.rec import vlm_locate
        self.assertTrue(callable(vlm_locate))

    def test_vlm_locate_graceful_failure(self):
        """VLM 服务不可用时应返回 None 而非抛异常"""
        import numpy as np
        from AutoScriptor.recognition.rec import vlm_locate
        fake_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        result = vlm_locate(fake_frame, "不存在的目标")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
