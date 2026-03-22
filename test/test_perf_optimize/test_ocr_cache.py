"""
OCR 帧级缓存 + scale fallback 移除 单元测试
=============================================
覆盖：_frame_fingerprint 指纹一致性、_raw_ocr_cached 缓存命中/过期/
      失效、ocr() 默认 scale=1.0、无 fallback 递归。
"""

import sys
import os
import time
import inspect
import unittest
from unittest.mock import patch, MagicMock

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from AutoScriptor.recognition import ocr_rec


# ---------------------------------------------------------------------------
# _frame_fingerprint
# ---------------------------------------------------------------------------

class TestFrameFingerprint(unittest.TestCase):
    """_frame_fingerprint 指纹生成"""

    def test_consistent_for_same_array(self):
        img = np.zeros((100, 200, 3), dtype=np.uint8)
        self.assertEqual(
            ocr_rec._frame_fingerprint(img),
            ocr_rec._frame_fingerprint(img),
        )

    def test_equal_for_copy(self):
        img = np.random.randint(0, 255, (80, 120, 3), dtype=np.uint8)
        self.assertEqual(
            ocr_rec._frame_fingerprint(img),
            ocr_rec._frame_fingerprint(img.copy()),
        )

    def test_differs_for_different_content(self):
        a = np.zeros((100, 200, 3), dtype=np.uint8)
        b = np.full((100, 200, 3), 128, dtype=np.uint8)
        self.assertNotEqual(
            ocr_rec._frame_fingerprint(a),
            ocr_rec._frame_fingerprint(b),
        )

    def test_differs_for_different_shape(self):
        a = np.zeros((100, 200, 3), dtype=np.uint8)
        b = np.zeros((200, 100, 3), dtype=np.uint8)
        self.assertNotEqual(
            ocr_rec._frame_fingerprint(a),
            ocr_rec._frame_fingerprint(b),
        )

    def test_returns_tuple(self):
        img = np.zeros((50, 50, 3), dtype=np.uint8)
        self.assertIsInstance(ocr_rec._frame_fingerprint(img), tuple)

    def test_small_image(self):
        """1×1 图像不应崩溃"""
        img = np.zeros((1, 1, 3), dtype=np.uint8)
        fp = ocr_rec._frame_fingerprint(img)
        self.assertIsInstance(fp, tuple)


# ---------------------------------------------------------------------------
# _raw_ocr_cached
# ---------------------------------------------------------------------------

class TestRawOcrCached(unittest.TestCase):
    """_raw_ocr_cached 缓存行为"""

    def setUp(self):
        ocr_rec._frame_cache = None

    @patch("AutoScriptor.recognition.ocr_rec.get_ocr_engine")
    def test_first_call_invokes_engine(self, mock_get):
        engine = MagicMock()
        engine.ocr.return_value = [[]]
        mock_get.return_value = engine

        img = np.zeros((100, 200, 3), dtype=np.uint8)
        ocr_rec._raw_ocr_cached(img)
        engine.ocr.assert_called_once()

    @patch("AutoScriptor.recognition.ocr_rec.get_ocr_engine")
    def test_cache_hit_within_ttl(self, mock_get):
        engine = MagicMock()
        engine.ocr.return_value = [
            [([[0, 0], [100, 0], [100, 30], [0, 30]], ("缓存测试", 0.99))]
        ]
        mock_get.return_value = engine

        img = np.zeros((100, 200, 3), dtype=np.uint8)
        r1 = ocr_rec._raw_ocr_cached(img, ttl=5.0)
        r2 = ocr_rec._raw_ocr_cached(img, ttl=5.0)

        engine.ocr.assert_called_once()
        self.assertIs(r1, r2)

    @patch("AutoScriptor.recognition.ocr_rec.get_ocr_engine")
    def test_cache_miss_different_image(self, mock_get):
        engine = MagicMock()
        engine.ocr.return_value = [[]]
        mock_get.return_value = engine

        a = np.zeros((100, 200, 3), dtype=np.uint8)
        b = np.full((100, 200, 3), 255, dtype=np.uint8)
        ocr_rec._raw_ocr_cached(a)
        ocr_rec._raw_ocr_cached(b)
        self.assertEqual(engine.ocr.call_count, 2)

    @patch("AutoScriptor.recognition.ocr_rec.get_ocr_engine")
    def test_cache_expires_after_ttl(self, mock_get):
        engine = MagicMock()
        engine.ocr.return_value = [[]]
        mock_get.return_value = engine

        img = np.zeros((100, 200, 3), dtype=np.uint8)
        ocr_rec._raw_ocr_cached(img, ttl=0.01)
        time.sleep(0.03)
        ocr_rec._raw_ocr_cached(img, ttl=0.01)

        self.assertEqual(engine.ocr.call_count, 2)

    @patch("AutoScriptor.recognition.ocr_rec.get_ocr_engine")
    def test_returns_none_when_engine_unavailable(self, mock_get):
        mock_get.return_value = None

        img = np.zeros((100, 200, 3), dtype=np.uint8)
        self.assertIsNone(ocr_rec._raw_ocr_cached(img))


# ---------------------------------------------------------------------------
# ocr() 函数签名与 fallback 移除
# ---------------------------------------------------------------------------

class TestOcrFunctionSignature(unittest.TestCase):
    """ocr() 函数签名校验"""

    def test_default_scale_is_one(self):
        sig = inspect.signature(ocr_rec.ocr)
        self.assertEqual(sig.parameters["scale"].default, 1.0)

    def test_none_frame_returns_empty(self):
        self.assertEqual(ocr_rec.ocr(None, ["test"]), [])

    @patch("AutoScriptor.recognition.ocr_rec._raw_ocr_cached")
    def test_delegates_to_cached_ocr(self, mock_cached):
        mock_cached.return_value = [[]]
        img = np.zeros((100, 200, 3), dtype=np.uint8)
        ocr_rec.ocr(img, ["目标"])
        mock_cached.assert_called_once()

    @patch("AutoScriptor.recognition.ocr_rec._raw_ocr_cached")
    def test_no_recursive_fallback(self, mock_cached):
        """scale=0.5 找不到时不再递归 scale=1.0"""
        mock_cached.return_value = [[]]
        img = np.zeros((100, 200, 3), dtype=np.uint8)
        ocr_rec.ocr(img, ["不存在的文字"], scale=0.5)
        self.assertEqual(mock_cached.call_count, 1)

    @patch("AutoScriptor.recognition.ocr_rec._raw_ocr_cached")
    def test_returns_empty_when_cached_returns_none(self, mock_cached):
        mock_cached.return_value = None
        img = np.zeros((100, 200, 3), dtype=np.uint8)
        self.assertEqual(ocr_rec.ocr(img, ["test"]), [])

    @patch("AutoScriptor.recognition.ocr_rec._raw_ocr_cached")
    def test_multiple_targets_single_ocr(self, mock_cached):
        """多个目标文本只触发一次 OCR 调用"""
        mock_cached.return_value = [[]]
        img = np.zeros((100, 200, 3), dtype=np.uint8)
        ocr_rec.ocr(img, ["目标A", "目标B", "目标C"])
        self.assertEqual(mock_cached.call_count, 1)


if __name__ == "__main__":
    unittest.main()
