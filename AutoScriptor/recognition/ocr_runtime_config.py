"""Process-level OCR configuration shared by every recognition engine."""

from __future__ import annotations

import os
from dataclasses import dataclass

from AutoScriptor.utils.app_config import cfg


DEFAULT_OCR_MODEL_PROFILE = "PP-OCRv6_small"
DEFAULT_DIGIT_OCR_MODEL_PROFILE = "PP-OCRv6_tiny"


@dataclass(frozen=True)
class OCRRuntimeConfig:
    """OCR settings that remain stable for the lifetime of the process."""

    use_gpu: bool
    model_profile: str
    digit_model_profile: str


def read_configured_ocr_runtime() -> OCRRuntimeConfig:
    """Read the current persisted/in-memory configuration and environment overrides."""

    model_profile = os.environ.get(
        "AUTOSCRIPTOR_OCR_MODEL",
        str(cfg.get("ocr.model", DEFAULT_OCR_MODEL_PROFILE)),
    ).strip() or DEFAULT_OCR_MODEL_PROFILE
    digit_model_profile = os.environ.get(
        "AUTOSCRIPTOR_DIGIT_OCR_MODEL",
        str(cfg.get("ocr.digit_model", DEFAULT_DIGIT_OCR_MODEL_PROFILE)),
    ).strip() or DEFAULT_DIGIT_OCR_MODEL_PROFILE
    return OCRRuntimeConfig(
        use_gpu=bool(cfg.get("ocr.use_gpu", False)),
        model_profile=model_profile,
        digit_model_profile=digit_model_profile,
    )


# Paddle engines cannot be safely moved between CPU and GPU in place. Keeping one
# process snapshot also prevents late-created thread-local/digit engines from
# drifting to a different device after a WebUI config save.
ocr_runtime_config = read_configured_ocr_runtime()
