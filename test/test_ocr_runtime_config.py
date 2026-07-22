import os
import unittest
from unittest.mock import patch

import AutoScriptor.recognition.ocr_runtime_config as ocr_runtime_config


class _ConfigStub:
    def __init__(self, values):
        self.values = values

    def get(self, key, default=None):
        return self.values.get(key, default)


class TestOCRRuntimeConfig(unittest.TestCase):
    def test_reads_device_and_model_profiles_from_config(self):
        config_stub = _ConfigStub(
            {
                "ocr.use_gpu": True,
                "ocr.model": "PP-OCRv6_small",
                "ocr.digit_model": "PP-OCRv6_tiny",
            }
        )

        with (
            patch.object(ocr_runtime_config, "cfg", config_stub),
            patch.dict(os.environ, {}, clear=True),
        ):
            runtime = ocr_runtime_config.read_configured_ocr_runtime()

        self.assertTrue(runtime.use_gpu)
        self.assertEqual(runtime.model_profile, "PP-OCRv6_small")
        self.assertEqual(runtime.digit_model_profile, "PP-OCRv6_tiny")

    def test_environment_overrides_only_model_profiles(self):
        config_stub = _ConfigStub(
            {
                "ocr.use_gpu": False,
                "ocr.model": "PP-OCRv4",
                "ocr.digit_model": "PP-OCRv4",
            }
        )
        environment = {
            "AUTOSCRIPTOR_OCR_MODEL": "PP-OCRv6_medium",
            "AUTOSCRIPTOR_DIGIT_OCR_MODEL": "PP-OCRv6_small",
        }

        with (
            patch.object(ocr_runtime_config, "cfg", config_stub),
            patch.dict(os.environ, environment, clear=True),
        ):
            runtime = ocr_runtime_config.read_configured_ocr_runtime()

        self.assertFalse(runtime.use_gpu)
        self.assertEqual(runtime.model_profile, "PP-OCRv6_medium")
        self.assertEqual(runtime.digit_model_profile, "PP-OCRv6_small")


if __name__ == "__main__":
    unittest.main()
