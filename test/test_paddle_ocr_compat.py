import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import AutoScriptor.recognition.paddle_ocr_compat as paddle_ocr_compat
from AutoScriptor.recognition.paddle_ocr_compat import (
    CompatiblePaddleOCR,
    normalize_ocr_result,
    resolve_model_profile,
)


class _ModernOCRResult:
    def __init__(self, result_payload):
        self.json = {"res": result_payload}


class TestPaddleOCRCompatibility(unittest.TestCase):

    def test_normalize_legacy_result_preserves_text_and_box(self):
        legacy_result = [
            [
                [
                    [[1, 2], [11, 2], [11, 8], [1, 8]],
                    ("测试", 0.98),
                ]
            ]
        ]

        normalized_result = normalize_ocr_result(legacy_result)

        self.assertEqual(normalized_result[0][0][1], ("测试", 0.98))
        self.assertEqual(
            normalized_result[0][0][0],
            [[1.0, 2.0], [11.0, 2.0], [11.0, 8.0], [1.0, 8.0]],
        )

    def test_normalize_modern_result_reads_pipeline_json(self):
        modern_result = _ModernOCRResult(
            {
                "rec_polys": [
                    [[3, 4], [13, 4], [13, 10], [3, 10]],
                    [[20, 5], [32, 5], [32, 12], [20, 12]],
                ],
                "rec_texts": ["角色", "登录"],
                "rec_scores": [0.97, 0.93],
            }
        )

        normalized_result = normalize_ocr_result([modern_result])

        self.assertEqual(
            [line[1] for line in normalized_result[0]],
            [("角色", 0.97), ("登录", 0.93)],
        )

    def test_normalize_modern_result_converts_rectangle_boxes(self):
        modern_result = {
            "res": {
                "rec_boxes": [[2, 3, 12, 9]],
                "rec_texts": ["确定"],
                "rec_scores": [0.91],
            }
        }

        normalized_result = normalize_ocr_result([modern_result])

        self.assertEqual(
            normalized_result[0][0][0],
            [[2.0, 3.0], [12.0, 3.0], [12.0, 9.0], [2.0, 9.0]],
        )

    def test_normalize_modern_result_accepts_generator(self):
        modern_result = _ModernOCRResult(
            {
                "rec_polys": [[[4, 5], [14, 5], [14, 11], [4, 11]]],
                "rec_texts": ["活动"],
                "rec_scores": [0.95],
            }
        )

        normalized_result = normalize_ocr_result(
            result_item for result_item in [modern_result]
        )

        self.assertEqual(normalized_result[0][0][1], ("活动", 0.95))

    def test_modern_adapter_uses_profile_models_and_predict(self):
        image = object()
        modern_result = _ModernOCRResult(
            {
                "rec_polys": [[[6, 7], [16, 7], [16, 13], [6, 13]]],
                "rec_texts": ["角色"],
                "rec_scores": [0.96],
            }
        )

        with (
            patch.object(
                paddle_ocr_compat,
                "get_paddleocr_version",
                return_value="3.7.0",
            ),
            patch.object(
                paddle_ocr_compat,
                "get_paddleocr_major_version",
                return_value=3,
            ),
            patch.object(paddle_ocr_compat, "PaddleOCR") as paddle_ocr_constructor,
        ):
            paddle_ocr_constructor.return_value.predict.return_value = iter(
                [modern_result]
            )
            engine = CompatiblePaddleOCR(
                model_profile_name="PP-OCRv6_small",
                language="ch",
                use_gpu=False,
            )
            normalized_result = engine.ocr(image, cls=False)

        paddle_ocr_constructor.assert_called_once_with(
            text_detection_model_name="PP-OCRv6_small_det",
            text_recognition_model_name="PP-OCRv6_small_rec",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            device="cpu",
        )
        paddle_ocr_constructor.return_value.predict.assert_called_once_with(image)
        self.assertEqual(normalized_result[0][0][1], ("角色", 0.96))

    def test_modern_adapter_uses_gpu_device_when_cuda_is_available(self):
        with (
            patch.object(
                paddle_ocr_compat,
                "get_paddleocr_version",
                return_value="3.7.0",
            ),
            patch.object(
                paddle_ocr_compat,
                "get_paddleocr_major_version",
                return_value=3,
            ),
            patch.object(
                paddle_ocr_compat.paddle.device,
                "is_compiled_with_cuda",
                return_value=True,
            ),
            patch.object(
                paddle_ocr_compat.paddle.device.cuda,
                "device_count",
                return_value=1,
            ),
            patch.object(paddle_ocr_compat, "PaddleOCR") as paddle_ocr_constructor,
        ):
            engine = CompatiblePaddleOCR(
                model_profile_name="PP-OCRv6_small",
                language="ch",
                use_gpu=True,
            )

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
            patch.object(
                paddle_ocr_compat.paddle.device,
                "is_compiled_with_cuda",
                return_value=False,
            ),
            patch.object(paddle_ocr_compat, "PaddleOCR") as paddle_ocr_constructor,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                r"scripts\\install\.bat python gpu",
            ):
                CompatiblePaddleOCR(
                    model_profile_name="PP-OCRv6_small",
                    language="ch",
                    use_gpu=True,
                )

        paddle_ocr_constructor.assert_not_called()

    def test_gpu_request_fails_when_cuda_device_is_unavailable(self):
        with (
            patch.object(
                paddle_ocr_compat.paddle.device,
                "is_compiled_with_cuda",
                return_value=True,
            ),
            patch.object(
                paddle_ocr_compat.paddle.device.cuda,
                "device_count",
                return_value=0,
            ),
            patch.object(paddle_ocr_compat, "PaddleOCR") as paddle_ocr_constructor,
        ):
            with self.assertRaisesRegex(RuntimeError, "no CUDA device is available"):
                CompatiblePaddleOCR(
                    model_profile_name="PP-OCRv6_small",
                    language="ch",
                    use_gpu=True,
                )

        paddle_ocr_constructor.assert_not_called()

    def test_resolve_model_profile_rejects_unknown_model(self):
        with self.assertRaisesRegex(ValueError, "Unsupported OCR model profile"):
            resolve_model_profile("PP-OCRv6_imaginary")


if __name__ == "__main__":
    unittest.main()
