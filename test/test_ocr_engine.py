import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import AutoScriptor.recognition.ocr_engine as ocr_engine
from AutoScriptor.recognition.ocr_engine import (
    PPOCRv6Engine,
    normalize_ocr_result,
    resolve_model_profile,
)


class _PipelineResult:
    def __init__(self, payload):
        self.json = {"res": payload}


class TestOCRResultNormalization(unittest.TestCase):

    def test_normalize_reads_pipeline_json(self):
        result = _PipelineResult(
            {
                "rec_polys": [
                    [[3, 4], [13, 4], [13, 10], [3, 10]],
                    [[20, 5], [32, 5], [32, 12], [20, 12]],
                ],
                "rec_texts": ["角色", "登录"],
                "rec_scores": [0.97, 0.93],
            }
        )

        normalized = normalize_ocr_result([result])

        self.assertEqual(
            [line[1] for line in normalized[0]],
            [("角色", 0.97), ("登录", 0.93)],
        )
        self.assertEqual(
            normalized[0][0][0],
            [[3.0, 4.0], [13.0, 4.0], [13.0, 10.0], [3.0, 10.0]],
        )

    def test_normalize_converts_rectangle_boxes(self):
        normalized = normalize_ocr_result(
            {"res": {"rec_boxes": [[2, 3, 12, 9]], "rec_texts": ["确定"], "rec_scores": [0.91]}}
        )

        self.assertEqual(
            normalized[0][0][0],
            [[2.0, 3.0], [12.0, 3.0], [12.0, 9.0], [2.0, 9.0]],
        )

    def test_normalize_accepts_generator(self):
        result = _PipelineResult(
            {
                "rec_polys": [[[4, 5], [14, 5], [14, 11], [4, 11]]],
                "rec_texts": ["活动"],
                "rec_scores": [0.95],
            }
        )

        normalized = normalize_ocr_result(item for item in [result])

        self.assertEqual(normalized[0][0][1], ("活动", 0.95))

    def test_normalize_skips_results_without_payload(self):
        self.assertEqual(normalize_ocr_result([object()]), [[]])


class TestPPOCRv6Engine(unittest.TestCase):

    def _engine_with_stubbed_paddleocr(self, use_gpu=False):
        return patch.object(ocr_engine, "PaddleOCR")

    def test_engine_uses_profile_models_and_predict(self):
        image = object()
        result = _PipelineResult(
            {
                "rec_polys": [[[6, 7], [16, 7], [16, 13], [6, 13]]],
                "rec_texts": ["角色"],
                "rec_scores": [0.96],
            }
        )

        with self._engine_with_stubbed_paddleocr() as paddle_ocr_constructor:
            paddle_ocr_constructor.return_value.predict.return_value = iter([result])
            engine = PPOCRv6Engine(model_profile_name="PP-OCRv6_small", use_gpu=False)
            normalized = engine.ocr(image, cls=False)

        paddle_ocr_constructor.assert_called_once_with(
            text_detection_model_name="PP-OCRv6_small_det",
            text_recognition_model_name="PP-OCRv6_small_rec",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            device="cpu",
        )
        paddle_ocr_constructor.return_value.predict.assert_called_once_with(image)
        self.assertEqual(normalized[0][0][1], ("角色", 0.96))

    def test_engine_uses_gpu_device_when_cuda_is_available(self):
        with (
            patch.object(ocr_engine.paddle.device, "is_compiled_with_cuda", return_value=True),
            patch.object(ocr_engine.paddle.device.cuda, "device_count", return_value=1),
            self._engine_with_stubbed_paddleocr() as paddle_ocr_constructor,
        ):
            engine = PPOCRv6Engine(model_profile_name="PP-OCRv6_small", use_gpu=True)

        paddle_ocr_constructor.assert_called_once_with(
            text_detection_model_name="PP-OCRv6_small_det",
            text_recognition_model_name="PP-OCRv6_small_rec",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            device="gpu:0",
        )
        self.assertTrue(engine.use_gpu)
        self.assertEqual(engine.device_name, "gpu:0")

    def test_gpu_request_fails_clearly_with_cpu_only_paddle(self):
        with (
            patch.object(ocr_engine.paddle.device, "is_compiled_with_cuda", return_value=False),
            self._engine_with_stubbed_paddleocr() as paddle_ocr_constructor,
        ):
            with self.assertRaisesRegex(RuntimeError, r"scripts\\install\.bat python gpu"):
                PPOCRv6Engine(model_profile_name="PP-OCRv6_small", use_gpu=True)

        paddle_ocr_constructor.assert_not_called()

    def test_gpu_request_fails_when_cuda_device_is_unavailable(self):
        with (
            patch.object(ocr_engine.paddle.device, "is_compiled_with_cuda", return_value=True),
            patch.object(ocr_engine.paddle.device.cuda, "device_count", return_value=0),
            self._engine_with_stubbed_paddleocr() as paddle_ocr_constructor,
        ):
            with self.assertRaisesRegex(RuntimeError, "no CUDA device is available"):
                PPOCRv6Engine(model_profile_name="PP-OCRv6_small", use_gpu=True)

        paddle_ocr_constructor.assert_not_called()

    def test_resolve_model_profile_returns_detector_and_recognizer(self):
        self.assertEqual(
            resolve_model_profile("PP-OCRv6_tiny"),
            ("PP-OCRv6_tiny_det", "PP-OCRv6_tiny_rec"),
        )

    def test_resolve_model_profile_rejects_unknown_model(self):
        with self.assertRaisesRegex(ValueError, "Unsupported OCR model profile"):
            resolve_model_profile("PP-OCRv6_imaginary")


if __name__ == "__main__":
    unittest.main()
