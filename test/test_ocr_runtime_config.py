import os
import unittest
from unittest.mock import patch

import AutoScriptor.recognition.ocr_rec as ocr_rec


class _ConfigStub:
    def __init__(self, values):
        self.values = values

    def get(self, key, default=None):
        return self.values.get(key, default)


class TestOCRRuntimeConfig(unittest.TestCase):
    def test_reads_device_and_model_profile_from_config(self):
        config_stub = _ConfigStub(
            {
                "ocr.use_gpu": True,
                "ocr.model": "PP-OCRv6_small",
            }
        )

        with (
            patch.object(ocr_rec, "cfg", config_stub),
            patch.dict(os.environ, {}, clear=True),
        ):
            runtime = ocr_rec.read_configured_ocr_runtime()

        self.assertTrue(runtime.use_gpu)
        self.assertEqual(runtime.model_profile, "PP-OCRv6_small")

    def test_environment_overrides_only_the_model_profile(self):
        config_stub = _ConfigStub(
            {
                "ocr.use_gpu": False,
                "ocr.model": "PP-OCRv6_small",
            }
        )
        environment = {
            "AUTOSCRIPTOR_OCR_MODEL": "PP-OCRv6_medium",
        }

        with (
            patch.object(ocr_rec, "cfg", config_stub),
            patch.dict(os.environ, environment, clear=True),
        ):
            runtime = ocr_rec.read_configured_ocr_runtime()

        self.assertFalse(runtime.use_gpu)
        self.assertEqual(runtime.model_profile, "PP-OCRv6_medium")


if __name__ == "__main__":
    unittest.main()
