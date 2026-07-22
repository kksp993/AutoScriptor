"""Shape-preserving text/image extraction helpers for Box targets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import cv2
import numpy as np

from AutoScriptor.utils.box import Box
from AutoScriptor.utils.logger import logger


@dataclass(frozen=True)
class BoxTargetLayout:
    """Normalized single, row, or grid arrangement of Box targets."""

    kind: Literal["single", "row", "grid"]
    rows: tuple[tuple[Box, ...], ...]

    @classmethod
    def from_target(cls, target: Any) -> "BoxTargetLayout":
        if _is_box_like(target):
            return cls("single", ((_as_box(target),),))

        if not isinstance(target, (list, tuple)):
            raise TypeError(
                "extract_info expects Box/BoxTarget, list[Box], or list[list[Box]], "
                f"got {type(target)!r}"
            )
        if not target:
            return cls("row", ((),))

        contains_nested_rows = any(
            isinstance(item, (list, tuple)) and not _is_box_like(item)
            for item in target
        )
        if contains_nested_rows:
            if not all(
                isinstance(item, (list, tuple)) and not _is_box_like(item)
                for item in target
            ):
                raise TypeError("extract_info grid rows must all be list/tuple values")
            rows = tuple(tuple(_as_box(item) for item in row) for row in target)
            return cls("grid", rows)

        return cls("row", (tuple(_as_box(item) for item in target),))

    @property
    def flat_boxes(self) -> list[Box]:
        return [box for row in self.rows for box in row]

    @property
    def box_count(self) -> int:
        return sum(len(row) for row in self.rows)

    @property
    def bounding_box(self) -> Box:
        flat_boxes = self.flat_boxes
        if not flat_boxes:
            return Box(0, 0, 0, 0)

        left = min(box.left for box in flat_boxes)
        top = min(box.top for box in flat_boxes)
        right = max(box.left + box.width for box in flat_boxes)
        bottom = max(box.top + box.height for box in flat_boxes)
        return Box(left, top, right - left, bottom - top)

    def restore_values(self, flat_values: list[Any]) -> Any:
        if len(flat_values) != self.box_count:
            raise ValueError(
                f"extract_info received {len(flat_values)} values for {self.box_count} boxes"
            )

        if self.kind == "single":
            return flat_values[0]
        if self.kind == "row":
            return list(flat_values)

        restored_rows: list[list[Any]] = []
        value_index = 0
        for row in self.rows:
            next_value_index = value_index + len(row)
            restored_rows.append(list(flat_values[value_index:next_value_index]))
            value_index = next_value_index
        return restored_rows

    def flatten_values(self, shaped_values: Any) -> list[Any]:
        if self.kind == "single":
            return [shaped_values]
        if self.kind == "row":
            if not isinstance(shaped_values, (list, tuple)):
                raise TypeError("extract_info row recognition must return a list/tuple")
            flat_values = list(shaped_values)
        else:
            if not isinstance(shaped_values, (list, tuple)):
                raise TypeError("extract_info grid recognition must return nested list/tuple rows")
            if len(shaped_values) != len(self.rows):
                raise ValueError("extract_info grid recognition returned the wrong row count")
            flat_values = []
            for expected_row, result_row in zip(self.rows, shaped_values):
                if not isinstance(result_row, (list, tuple)):
                    raise TypeError("extract_info grid recognition rows must be list/tuple values")
                if len(result_row) != len(expected_row):
                    raise ValueError("extract_info grid recognition returned the wrong column count")
                flat_values.extend(result_row)

        if len(flat_values) != self.box_count:
            raise ValueError(
                f"extract_info recognition returned {len(flat_values)} values for {self.box_count} boxes"
            )
        return flat_values


def _is_box_like(target: Any) -> bool:
    return isinstance(target, Box) or (
        hasattr(target, "box") and isinstance(target.box, Box)
    )


def _as_box(target: Any) -> Box:
    if isinstance(target, Box):
        return target
    if hasattr(target, "box") and isinstance(target.box, Box):
        return target.box
    raise TypeError(f"extract_info expects Box/BoxTarget values, got {type(target)!r}")


def _as_grayscale(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        return image
    if image.ndim == 3 and image.shape[2] == 3:
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if image.ndim == 3 and image.shape[2] == 4:
        return cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY)
    raise ValueError(f"Unsupported image shape for extract_info: {image.shape!r}")


def _crop_box(frame: np.ndarray, box: Box) -> np.ndarray | None:
    frame_height, frame_width = frame.shape[:2]
    left = max(0, box.left)
    top = max(0, box.top)
    right = min(frame_width, box.left + box.width)
    bottom = min(frame_height, box.top + box.height)
    if right <= left or bottom <= top:
        return None
    return frame[top:bottom, left:right]


def _best_template_confidence(
    haystack_gray: np.ndarray,
    template_gray: np.ndarray,
) -> float:
    best_confidence = -1.0
    for scale in (1.0, 0.8, 1.2):
        template_height, template_width = template_gray.shape[:2]
        scaled_width = max(1, round(template_width * scale))
        scaled_height = max(1, round(template_height * scale))
        if scaled_width > haystack_gray.shape[1] or scaled_height > haystack_gray.shape[0]:
            continue

        if scale == 1.0:
            scaled_template = template_gray
        else:
            interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC
            scaled_template = cv2.resize(
                template_gray,
                (scaled_width, scaled_height),
                interpolation=interpolation,
            )

        confidence_map = cv2.matchTemplate(
            haystack_gray,
            scaled_template,
            cv2.TM_CCOEFF_NORMED,
        )
        _, confidence, _, _ = cv2.minMaxLoc(confidence_map)
        if np.isfinite(confidence):
            best_confidence = max(best_confidence, float(confidence))

    return best_confidence


def _get_registered_image_candidates() -> list[tuple[str, np.ndarray]]:
    # Read through the manager so editor-triggered ui_map reloads are observed.
    from AutoScriptor.utils.ui_map import ui_manager

    candidates: list[tuple[str, np.ndarray]] = []
    for key, entry in ui_manager.get_ui().items():
        if isinstance(entry.img, np.ndarray) and entry.img.size:
            candidates.append((key, _as_grayscale(entry.img)))
    return candidates


def extract_registered_image_keys(
    screenshot_frame: np.ndarray,
    target: Any,
    *,
    confidence: float = 0.8,
) -> Any:
    """Return the best registered ``ui_map`` image key for each target box."""
    if not 0.0 <= confidence <= 1.0:
        raise ValueError(f"image confidence must be between 0 and 1, got {confidence!r}")
    if not isinstance(screenshot_frame, np.ndarray):
        raise TypeError("img/both extract_info modes require a BGR ndarray screenshot")

    target_layout = BoxTargetLayout.from_target(target)
    screenshot_gray = _as_grayscale(screenshot_frame)
    candidates = _get_registered_image_candidates()
    recognized_keys: list[str | None] = []

    for target_box in target_layout.flat_boxes:
        target_region = _crop_box(screenshot_gray, target_box)
        best_key = None
        best_confidence = confidence
        if target_region is not None:
            for candidate_key, candidate_image in candidates:
                candidate_confidence = _best_template_confidence(
                    target_region,
                    candidate_image,
                )
                if candidate_confidence >= best_confidence:
                    best_key = candidate_key
                    best_confidence = candidate_confidence

        logger.debug(
            "Extract registered image box=%s key=%s confidence=%.4f",
            target_box,
            best_key,
            best_confidence,
        )
        recognized_keys.append(best_key)

    return target_layout.restore_values(recognized_keys)
