"""Compatibility adapter for PaddleOCR 2.x and 3.x inference APIs."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from typing import Any

import paddle

# PaddleOCR otherwise downloads from Hugging Face by default. BOS is more
# reliable for the project's normal network environment and remains overridable.
os.environ.setdefault("PADDLE_PDX_MODEL_SOURCE", "BOS")

from paddleocr import PaddleOCR


@dataclass(frozen=True)
class OCRModelProfile:
    """A matched detector and recognizer pair exposed by PaddleOCR 3.x."""

    name: str
    detection_model_name: str
    recognition_model_name: str


OCR_MODEL_PROFILES = {
    "PP-OCRv4": OCRModelProfile(
        name="PP-OCRv4",
        detection_model_name="PP-OCRv4_mobile_det",
        recognition_model_name="PP-OCRv4_mobile_rec",
    ),
    "PP-OCRv6_tiny": OCRModelProfile(
        name="PP-OCRv6_tiny",
        detection_model_name="PP-OCRv6_tiny_det",
        recognition_model_name="PP-OCRv6_tiny_rec",
    ),
    "PP-OCRv6_small": OCRModelProfile(
        name="PP-OCRv6_small",
        detection_model_name="PP-OCRv6_small_det",
        recognition_model_name="PP-OCRv6_small_rec",
    ),
    "PP-OCRv6_medium": OCRModelProfile(
        name="PP-OCRv6_medium",
        detection_model_name="PP-OCRv6_medium_det",
        recognition_model_name="PP-OCRv6_medium_rec",
    ),
}


def get_paddleocr_version() -> str:
    """Return the installed PaddleOCR version without importing private APIs."""

    try:
        return version("paddleocr")
    except PackageNotFoundError:
        return "0"


def get_paddleocr_major_version() -> int:
    """Return the installed PaddleOCR major version."""

    version_text = get_paddleocr_version()
    try:
        return int(version_text.split(".", maxsplit=1)[0])
    except (TypeError, ValueError):
        return 0


def resolve_model_profile(model_profile_name: str) -> OCRModelProfile:
    """Validate and resolve an AutoScriptor OCR model profile name."""

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

    gpu_count = paddle.device.cuda.device_count()
    if gpu_count < 1:
        raise RuntimeError(
            "GPU OCR is enabled by ocr.use_gpu and CUDA Paddle is installed, "
            "but no CUDA device is available. Check the NVIDIA driver, then "
            "restart AutoScriptor."
        )


def _convert_to_builtin(value: Any) -> Any:
    if hasattr(value, "tolist"):
        return value.tolist()
    return value


def _coerce_result_mapping(result_item: Any) -> Mapping[str, Any] | None:
    if isinstance(result_item, Mapping):
        return result_item

    json_value = getattr(result_item, "json", None)
    if callable(json_value):
        json_value = json_value()
    if isinstance(json_value, str):
        try:
            json_value = json.loads(json_value)
        except json.JSONDecodeError:
            return None
    if isinstance(json_value, Mapping):
        return json_value

    to_dict = getattr(result_item, "to_dict", None)
    if callable(to_dict):
        mapping_value = to_dict()
        if isinstance(mapping_value, Mapping):
            return mapping_value
    return None


def _normalize_bounding_points(raw_points: Any) -> list[list[float]] | None:
    points = _convert_to_builtin(raw_points)
    if not isinstance(points, Sequence) or isinstance(points, (str, bytes)):
        return None

    if len(points) == 4 and all(isinstance(coordinate, (int, float)) for coordinate in points):
        left, top, right, bottom = points
        return [
            [float(left), float(top)],
            [float(right), float(top)],
            [float(right), float(bottom)],
            [float(left), float(bottom)],
        ]

    normalized_points: list[list[float]] = []
    for point in points:
        point = _convert_to_builtin(point)
        if (
            not isinstance(point, Sequence)
            or isinstance(point, (str, bytes))
            or len(point) < 2
        ):
            return None
        normalized_points.append([float(point[0]), float(point[1])])
    return normalized_points or None


def _normalize_legacy_result(raw_result: Any) -> list[list[Any]] | None:
    if not isinstance(raw_result, Sequence) or isinstance(raw_result, (str, bytes)):
        return None
    if not raw_result:
        return [[]]

    first_image_result = raw_result[0]
    if first_image_result is None:
        return [[]]
    if not isinstance(first_image_result, Sequence) or isinstance(first_image_result, (str, bytes)):
        return None

    normalized_lines: list[Any] = []
    for line_item in first_image_result:
        if not isinstance(line_item, Sequence) or len(line_item) < 2:
            return None
        text_result = line_item[1]
        if not isinstance(text_result, Sequence) or len(text_result) < 2:
            return None
        bounding_points = _normalize_bounding_points(line_item[0])
        if bounding_points is None:
            continue
        normalized_lines.append(
            [bounding_points, (str(text_result[0]), float(text_result[1]))]
        )
    return [normalized_lines]


def _get_first_present_value(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def normalize_ocr_result(raw_result: Any) -> list[list[Any]]:
    """Normalize PaddleOCR 2.x and 3.x output to the legacy nested format."""

    legacy_result = _normalize_legacy_result(raw_result)
    if legacy_result is not None:
        return legacy_result

    if isinstance(raw_result, Mapping):
        result_items = [raw_result]
    elif isinstance(raw_result, Iterable) and not isinstance(raw_result, (str, bytes)):
        result_items = list(raw_result)
    else:
        result_items = [raw_result]

    normalized_lines: list[Any] = []
    for result_item in result_items:
        result_mapping = _coerce_result_mapping(result_item)
        if result_mapping is None:
            continue
        result_payload = result_mapping.get("res", result_mapping)
        if not isinstance(result_payload, Mapping):
            continue

        raw_polygons = _get_first_present_value(
            result_payload,
            "rec_polys",
            "dt_polys",
            "rec_boxes",
        )
        raw_texts = _get_first_present_value(result_payload, "rec_texts", "texts")
        raw_scores = _get_first_present_value(result_payload, "rec_scores", "scores")

        polygons = _convert_to_builtin(raw_polygons) or []
        texts = _convert_to_builtin(raw_texts) or []
        scores = _convert_to_builtin(raw_scores) or []
        for result_index, text in enumerate(texts):
            if result_index >= len(polygons):
                break
            bounding_points = _normalize_bounding_points(polygons[result_index])
            if bounding_points is None:
                continue
            confidence = scores[result_index] if result_index < len(scores) else 0.0
            normalized_lines.append(
                [bounding_points, (str(text), float(confidence))]
            )
    return [normalized_lines]


class CompatiblePaddleOCR:
    """Expose the PaddleOCR 2.x methods used by AutoScriptor on PaddleOCR 3.x."""

    def __init__(
        self,
        *,
        model_profile_name: str,
        language: str,
        use_gpu: bool,
    ) -> None:
        self.model_profile = resolve_model_profile(model_profile_name)
        self.language = language
        self.use_gpu = bool(use_gpu)
        self.device_name = "gpu:0" if self.use_gpu else "cpu"
        self.package_version = get_paddleocr_version()
        self._is_modern_api = get_paddleocr_major_version() >= 3
        validate_requested_ocr_device(self.use_gpu)
        self._engine = self._create_engine()

    def _create_engine(self) -> PaddleOCR:
        if self._is_modern_api:
            return PaddleOCR(
                text_detection_model_name=self.model_profile.detection_model_name,
                text_recognition_model_name=self.model_profile.recognition_model_name,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
                device=self.device_name,
            )

        if self.model_profile.name != "PP-OCRv4":
            raise RuntimeError(
                f"{self.model_profile.name} requires PaddleOCR 3.7 or newer; "
                f"installed version is {self.package_version}"
            )
        return PaddleOCR(
            use_gpu=self.use_gpu,
            gpu_mem=4096,
            enable_mkldnn=True,
            use_angle_cls=False,
            lang=self.language,
            ocr_version="PP-OCRv4",
            show_log=False,
        )

    def ocr(self, image: Any, **legacy_options: Any) -> list[list[Any]]:
        if self._is_modern_api:
            raw_result = self._engine.predict(image)
        else:
            raw_result = self._engine.ocr(image, **legacy_options)
        return normalize_ocr_result(raw_result)

    def text_recognizer(self, crops: Sequence[Any]) -> tuple[list[tuple[str, float]], float]:
        """Provide the legacy recognition-only hook used by digit OCR."""

        if not self._is_modern_api:
            return self._engine.text_recognizer(crops)

        start_time = time.perf_counter()
        recognized_values: list[tuple[str, float]] = []
        for crop in crops:
            normalized_result = self.ocr(crop)
            lines = normalized_result[0] if normalized_result else []
            if not lines:
                recognized_values.append(("", 0.0))
                continue
            best_line = max(lines, key=lambda line: float(line[1][1]))
            recognized_values.append((str(best_line[1][0]), float(best_line[1][1])))
        elapsed_time = time.perf_counter() - start_time
        return recognized_values, elapsed_time
