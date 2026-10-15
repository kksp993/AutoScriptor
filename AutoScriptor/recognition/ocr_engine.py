"""The PP-OCRv6 engine AutoScriptor runs its recognition on.

PaddleOCR 3.x exposes a pipeline API: ``predict()`` returns per-image result
objects instead of the flat ``[polygon, (text, score)]`` rows the recognition
code consumes. This module owns both halves of that boundary -- the model
profile table and the single adapter that normalizes pipeline output back into
those rows.

Paddle is imported at module level here on purpose, so ``ocr_rec`` may import
this module only inside its OCR worker thread. A plain ``import AutoScriptor``
therefore never pays for the Paddle runtime.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping, Sequence
from importlib.metadata import PackageNotFoundError, version
from typing import Any

import paddle

# PaddleOCR otherwise downloads from Hugging Face by default. BOS is more
# reliable for the project's normal network environment and remains overridable.
os.environ.setdefault("PADDLE_PDX_MODEL_SOURCE", "BOS")

from paddleocr import PaddleOCR


# Detector/recognizer pairs shipped with PaddleOCR 3.x. Both halves are pinned
# per profile so the model actually loaded is visible in logs and reproducible.
OCR_MODEL_PROFILES: dict[str, tuple[str, str]] = {
    "PP-OCRv6_tiny": ("PP-OCRv6_tiny_det", "PP-OCRv6_tiny_rec"),
    "PP-OCRv6_small": ("PP-OCRv6_small_det", "PP-OCRv6_small_rec"),
    "PP-OCRv6_medium": ("PP-OCRv6_medium_det", "PP-OCRv6_medium_rec"),
}


def get_paddleocr_version() -> str:
    """Return the installed PaddleOCR version without importing private APIs."""

    try:
        return version("paddleocr")
    except PackageNotFoundError:
        return "0"


def resolve_model_profile(model_profile_name: str) -> tuple[str, str]:
    """Return the ``(detection_model_name, recognition_model_name)`` pair."""

    normalized_name = str(model_profile_name or "").strip()
    try:
        return OCR_MODEL_PROFILES[normalized_name]
    except KeyError as error:
        supported_names = ", ".join(OCR_MODEL_PROFILES)
        raise ValueError(
            f"Unsupported OCR model profile {normalized_name!r}; "
            f"expected one of: {supported_names}"
        ) from error


def validate_requested_ocr_device(use_gpu: bool) -> None:
    """Fail clearly when GPU OCR is configured without a usable CUDA runtime."""

    if not use_gpu:
        return

    if not paddle.device.is_compiled_with_cuda():
        raise RuntimeError(
            "GPU OCR is enabled by ocr.use_gpu, but the installed Paddle runtime "
            "does not include CUDA support. Run scripts\\install.bat python gpu "
            "and restart AutoScriptor."
        )

    if paddle.device.cuda.device_count() < 1:
        raise RuntimeError(
            "GPU OCR is enabled by ocr.use_gpu and CUDA Paddle is installed, "
            "but no CUDA device is available. Check the NVIDIA driver, then "
            "restart AutoScriptor."
        )


def _convert_to_builtin(value: Any) -> Any:
    return value.tolist() if hasattr(value, "tolist") else value


def _first_present_value(payload: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if payload.get(key) is not None:
            return payload[key]
    return None


def _coerce_result_payload(result_item: Any) -> Mapping[str, Any] | None:
    """Return the ``res`` mapping of a PaddleOCR 3.x result object."""

    if isinstance(result_item, Mapping):
        payload: Any = result_item.get("res", result_item)
        return payload if isinstance(payload, Mapping) else None

    payload = getattr(result_item, "json", None)
    if callable(payload):
        payload = payload()
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return None
    if payload is None:
        to_dict = getattr(result_item, "to_dict", None)
        payload = to_dict() if callable(to_dict) else None
    if isinstance(payload, Mapping):
        payload = payload.get("res", payload)
        return payload if isinstance(payload, Mapping) else None
    return None


def _polygon_from_points(raw_points: Any) -> list[list[float]] | None:
    """Normalize a detected region into four corner points."""

    points = _convert_to_builtin(raw_points)
    if not isinstance(points, Sequence) or isinstance(points, (str, bytes)):
        return None

    # PaddleOCR reports either a flat xyxy rectangle or the full polygon.
    if len(points) == 4 and all(isinstance(value, (int, float)) for value in points):
        left, top, right, bottom = points
        return [
            [float(left), float(top)],
            [float(right), float(top)],
            [float(right), float(bottom)],
            [float(left), float(bottom)],
        ]

    polygon: list[list[float]] = []
    for point in points:
        point = _convert_to_builtin(point)
        if (
            not isinstance(point, Sequence)
            or isinstance(point, (str, bytes))
            or len(point) < 2
        ):
            return None
        polygon.append([float(point[0]), float(point[1])])
    return polygon or None


def normalize_ocr_result(raw_result: Any) -> list[list[Any]]:
    """Normalize PaddleOCR 3.x pipeline output into ``[polygon, (text, score)]``."""

    if isinstance(raw_result, Mapping):
        result_items: Iterable[Any] = [raw_result]
    elif isinstance(raw_result, Iterable) and not isinstance(raw_result, (str, bytes)):
        result_items = raw_result
    else:
        result_items = [raw_result]

    normalized_lines: list[Any] = []
    for result_item in result_items:
        result_payload = _coerce_result_payload(result_item)
        if result_payload is None:
            continue

        raw_polygons = _first_present_value(
            result_payload,
            "rec_polys",
            "dt_polys",
            "rec_boxes",
        )
        polygons = _convert_to_builtin(raw_polygons) or []
        texts = _convert_to_builtin(_first_present_value(result_payload, "rec_texts", "texts")) or []
        scores = _convert_to_builtin(_first_present_value(result_payload, "rec_scores", "scores")) or []

        for result_index, text in enumerate(texts):
            if result_index >= len(polygons):
                break
            polygon = _polygon_from_points(polygons[result_index])
            if polygon is None:
                continue
            confidence = scores[result_index] if result_index < len(scores) else 0.0
            normalized_lines.append([polygon, (str(text), float(confidence))])
    return [normalized_lines]


class PPOCRv6Engine:
    """PaddleOCR 3.x pipeline wrapper exposing AutoScriptor's ``ocr()`` shape."""

    def __init__(self, *, model_profile_name: str, use_gpu: bool) -> None:
        self.use_gpu = bool(use_gpu)
        self.device_name = "gpu:0" if self.use_gpu else "cpu"
        detection_model_name, recognition_model_name = resolve_model_profile(
            model_profile_name
        )
        validate_requested_ocr_device(self.use_gpu)
        self._engine = PaddleOCR(
            text_detection_model_name=detection_model_name,
            text_recognition_model_name=recognition_model_name,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            device=self.device_name,
        )

    def ocr(self, image: Any, **_legacy_options: Any) -> list[list[Any]]:
        return normalize_ocr_result(self._engine.predict(image))
