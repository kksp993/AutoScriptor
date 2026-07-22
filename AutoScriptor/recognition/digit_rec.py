import re
import threading
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

from AutoScriptor.core.targets import BoxTarget
from AutoScriptor.recognition.paddle_ocr_compat import CompatiblePaddleOCR
from AutoScriptor.recognition.ocr_runtime_config import ocr_runtime_config
from AutoScriptor.utils.box import Box
from AutoScriptor.utils.logger import logger


class DigitRecognitionError(RuntimeError):
    pass


_DIGIT_TRANSLATION = str.maketrans({
    "O": "0",
    "o": "0",
    "D": "0",
    "Q": "0",
    "I": "1",
    "l": "1",
    "|": "1",
    "!": "1",
    "Z": "2",
    "z": "2",
    "A": "4",
    "S": "5",
    "s": "5",
    "$": "5",
    "G": "6",
    "B": "8",
    "g": "9",
    "q": "9",
    "]": "",
    "[": "",
})

_SCALE = 5
_PADDING = 14
_GUTTER = 80
_MIN_CONFIDENCE = 0.85
_MAX_ROW_ITEMS = 6
_digit_engine = None
_digit_engine_lock = threading.Lock()
DIGIT_OCR_MODEL_PROFILE = ocr_runtime_config.digit_model_profile


def _get_digit_engine():
    global _digit_engine
    if _digit_engine is None:
        with _digit_engine_lock:
            if _digit_engine is None:
                _digit_engine = CompatiblePaddleOCR(
                    model_profile_name=DIGIT_OCR_MODEL_PROFILE,
                    language="en",
                    use_gpu=ocr_runtime_config.use_gpu,
                )
    return _digit_engine


@dataclass
class _Slot:
    left: int
    top: int
    width: int
    height: int

    def center_distance2(self, x: float, y: float) -> float:
        cx = self.left + self.width / 2
        cy = self.top + self.height / 2
        return (x - cx) ** 2 + (y - cy) ** 2


def _normalize_digits(text: str) -> str:
    normalized = (text or "").translate(_DIGIT_TRANSLATION)
    return "".join(re.findall(r"\d+", normalized))


def _as_box(target: Any) -> Box | None:
    if target is None:
        return None
    if isinstance(target, BoxTarget):
        return target.box
    if isinstance(target, Box):
        return target
    if hasattr(target, "box") and isinstance(target.box, Box):
        return target.box
    raise TypeError(f"digital_only mode expects Box/BoxTarget, got {type(target)!r}")


def _shape_boxes(target: Any) -> tuple[str, list[list[Box | None]]]:
    if target is None:
        return "single", [[None]]
    if isinstance(target, (BoxTarget, Box)) or (hasattr(target, "box") and isinstance(target.box, Box)):
        return "single", [[_as_box(target)]]
    if not isinstance(target, (list, tuple)):
        raise TypeError(
            "digital_only mode expects Box, list[Box], or list[list[Box]], "
            f"got {type(target)!r}"
        )
    if len(target) == 0:
        return "row", [[]]
    if isinstance(target[0], (list, tuple)):
        return "grid", [[_as_box(item) for item in row] for row in target]
    return "row", [[_as_box(item) for item in target]]


def _restore_shape(kind: str, rows: list[list[int | None]]) -> int | None | list[int | None] | list[list[int | None]]:
    if kind == "single":
        return rows[0][0]
    if kind == "row":
        return rows[0]
    return rows


def _crop(frame, box: Box):
    h, w = frame.shape[:2]
    left = max(0, box.left)
    top = max(0, box.top)
    right = min(w, box.left + box.width)
    bottom = min(h, box.top + box.height)
    if right <= left or bottom <= top:
        raise DigitRecognitionError(f"invalid digit box: {box}")
    return frame[top:bottom, left:right]


def _extract_digit_roi(roi):
    h, w = roi.shape[:2]
    search_left = max(0, w - 95) if w > 80 else 0
    search_top = max(0, int(h * 0.35))
    search = roi[search_top:, search_left:]
    if search.size == 0:
        return None
    hsv = cv2.cvtColor(search, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(search, cv2.COLOR_BGR2GRAY)

    def bbox_from_mask(
        mask,
        *,
        min_area: int,
        min_height: int,
        max_area_ratio: float,
        seed_mask=None,
    ):
        kernel = np.ones((2, 2), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)
        count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        kept = np.zeros_like(mask)
        search_area = mask.shape[0] * mask.shape[1]
        for idx in range(1, count):
            _x, _y, cw, ch, area = stats[idx]
            if area < min_area or ch < min_height or cw < 2:
                continue
            if area / max(1, search_area) > max_area_ratio:
                continue
            if seed_mask is not None and np.count_nonzero(seed_mask[labels == idx]) < 3:
                continue
            kept[labels == idx] = 255
        ys, xs = np.where(kept > 0)
        if len(xs) == 0 or len(ys) == 0:
            return None
        return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())

    light_mask = cv2.inRange(hsv, np.array([0, 0, 135]), np.array([180, 165, 255]))
    light_mask = cv2.bitwise_and(light_mask, cv2.inRange(gray, 135, 255))
    light_seed = cv2.inRange(hsv, np.array([0, 0, 205]), np.array([180, 120, 255]))
    light_seed = cv2.bitwise_and(light_seed, cv2.inRange(gray, 205, 255))
    bbox = bbox_from_mask(
        light_mask,
        min_area=5,
        min_height=6,
        max_area_ratio=0.65,
        seed_mask=light_seed,
    )
    if bbox is None:
        dark_mask = cv2.inRange(hsv, np.array([0, 20, 0]), np.array([45, 255, 180]))
        dark_mask = cv2.bitwise_and(dark_mask, cv2.inRange(gray, 0, 170))
        bbox = bbox_from_mask(
            dark_mask,
            min_area=5,
            min_height=5,
            max_area_ratio=0.45,
        )
    if bbox is None:
        return None

    x_min, y_min, x_max, y_max = bbox
    x1 = max(0, x_min + search_left - 8)
    y1 = max(0, y_min + search_top - 4)
    x2 = min(w, x_max + search_left + 9)
    y2 = min(h, y_max + search_top + 5)
    if x2 - x1 < 3 or y2 - y1 < 8:
        return None
    return roi[y1:y2, x1:x2]


def _prepare_digit_crop(frame, box: Box):
    roi = _extract_digit_roi(_crop(frame, box))
    if roi is None:
        return None
    enlarged = cv2.resize(roi, None, fx=_SCALE, fy=_SCALE, interpolation=cv2.INTER_CUBIC)
    return cv2.copyMakeBorder(
        enlarged,
        _PADDING,
        _PADDING,
        _PADDING,
        _PADDING,
        cv2.BORDER_CONSTANT,
        value=(255, 255, 255),
    )


def _stitch_row(frame, row: list[Box | None]):
    indexed_crops = [
        (idx, crop)
        for idx, box in enumerate(row)
        if box is not None and (crop := _prepare_digit_crop(frame, box)) is not None
    ]
    crops = [crop for _, crop in indexed_crops]
    if not crops:
        return None, [], [], []
    canvas_h = max(crop.shape[0] for crop in crops) + _GUTTER * 2
    canvas_w = sum(crop.shape[1] for crop in crops) + _GUTTER * (len(crops) + 1)
    canvas = np.full((canvas_h, canvas_w, 3), 255, dtype=np.uint8)
    slots: list[_Slot] = []
    x = _GUTTER
    y = _GUTTER
    for crop in crops:
        h, w = crop.shape[:2]
        canvas[y:y + h, x:x + w] = crop
        slots.append(_Slot(x, y, w, h))
        x += w + _GUTTER
    return canvas, slots, crops, [idx for idx, _ in indexed_crops]


def _chunks(row: list[Box | None]):
    for start in range(0, len(row), _MAX_ROW_ITEMS):
        yield row[start:start + _MAX_ROW_ITEMS]


def _visual_rows(row: list[Box | None]) -> list[list[tuple[int, Box]]]:
    if not row:
        return []
    indexed = [(idx, box) for idx, box in enumerate(row) if box is not None]
    if not indexed:
        return []
    indexed.sort(key=lambda item: (item[1].top + item[1].height / 2, item[1].left))
    rows: list[list[tuple[int, Box]]] = []
    for item in indexed:
        _, box = item
        cy = box.top + box.height / 2
        if not rows:
            rows.append([item])
            continue
        last_centers = [b.top + b.height / 2 for _, b in rows[-1]]
        last_cy = sum(last_centers) / len(last_centers)
        tolerance = max(12, max(box.height, *(b.height for _, b in rows[-1])) * 0.75)
        if abs(cy - last_cy) <= tolerance:
            rows[-1].append(item)
        else:
            rows.append([item])
    for visual_row in rows:
        visual_row.sort(key=lambda item: item[1].left)
    return rows


def _iter_ocr_items(result):
    if not result or not result[0]:
        return
    for item in result[0]:
        try:
            points = item[0]
            text, confidence = item[1]
        except (TypeError, ValueError, IndexError):
            continue
        yield points, str(text), float(confidence)


def _assign_row_results(result, slots: list[_Slot]) -> list[int | None]:
    values: list[str | None] = [None] * len(slots)
    confidences = [0.0] * len(slots)
    for points, text, confidence in _iter_ocr_items(result):
        if confidence < _MIN_CONFIDENCE:
            continue
        digits = _normalize_digits(text)
        if not digits:
            continue
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        cx = sum(xs) / len(xs)
        cy = sum(ys) / len(ys)
        slot_index = min(range(len(slots)), key=lambda i: slots[i].center_distance2(cx, cy))
        current = values[slot_index]
        if current is not None and current != digits:
            raise DigitRecognitionError(
                f"conflicting digit OCR for slot {slot_index}: {current!r} vs {digits!r}"
            )
        if confidence > confidences[slot_index]:
            values[slot_index] = digits
            confidences[slot_index] = confidence

    missing = [idx for idx, value in enumerate(values) if value is None]
    if missing:
        logger.debug("digit OCR empty/missed slot(s): %s", missing)
    logger.debug("digit OCR row values=%s confidences=%s", values, confidences)
    return [int(value) if value is not None else None for value in values]


def _recognize_missing_slots(engine, crops, result, slots: list[_Slot]) -> list[int | None]:
    values: list[str | None] = [None] * len(slots)
    confidences = [0.0] * len(slots)
    for points, text, confidence in _iter_ocr_items(result):
        if confidence < _MIN_CONFIDENCE:
            continue
        digits = _normalize_digits(text)
        if not digits:
            continue
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        cx = sum(xs) / len(xs)
        cy = sum(ys) / len(ys)
        slot_index = min(range(len(slots)), key=lambda i: slots[i].center_distance2(cx, cy))
        values[slot_index] = digits
        confidences[slot_index] = confidence

    missing = [idx for idx, value in enumerate(values) if value is None]
    if missing:
        rec_result, _ = engine.text_recognizer([crops[idx] for idx in missing])
        for idx, (text, confidence) in zip(missing, rec_result):
            digits = _normalize_digits(str(text))
            if digits and float(confidence) >= _MIN_CONFIDENCE:
                values[idx] = digits
                confidences[idx] = float(confidence)

    still_missing = [idx for idx, value in enumerate(values) if value is None]
    if still_missing:
        logger.debug("digit OCR empty/missed slot(s): %s", still_missing)
    logger.debug("digit OCR row values=%s confidences=%s", values, confidences)
    return [int(value) if value is not None else None for value in values]


def _recognize_row_values(engine, canvas, slots: list[_Slot], crops) -> list[int | None]:
    result = engine.ocr(canvas, det=True, rec=True, cls=False)
    try:
        values = _assign_row_results(result, slots)
    except DigitRecognitionError:
        return _recognize_missing_slots(engine, crops, result, slots)
    if any(value is None for value in values):
        values = _recognize_missing_slots(engine, crops, result, slots)
    return values


def extract_digits(frame, target) -> int | None | list[int | None] | list[list[int | None]]:
    kind, rows = _shape_boxes(target)
    engine = _get_digit_engine()
    if kind == "row":
        flat_values: list[int | None] = [None] * len(rows[0])
        for visual_row in _visual_rows(rows[0]):
            row_values: list[int | None] = [None] * len(visual_row)
            for chunk_index, chunk in enumerate(_chunks([box for _, box in visual_row])):
                canvas, slots, crops, kept_indices = _stitch_row(frame, chunk)
                if canvas is None:
                    continue
                chunk_values = _recognize_row_values(engine, canvas, slots, crops)
                base_index = chunk_index * _MAX_ROW_ITEMS
                for local_index, value in zip(kept_indices, chunk_values):
                    row_values[base_index + local_index] = value
            for (original_index, _), value in zip(visual_row, row_values):
                flat_values[original_index] = value
        return flat_values

    digit_rows: list[list[int | None]] = []
    for row_index, row in enumerate(rows):
        digit_row: list[int | None] = []
        for chunk_index, chunk in enumerate(_chunks(row)):
            chunk_values: list[int | None] = [None] * len(chunk)
            canvas, slots, crops, kept_indices = _stitch_row(frame, chunk)
            if canvas is None:
                digit_row.extend(chunk_values)
                continue
            try:
                recognized_values = _recognize_row_values(engine, canvas, slots, crops)
            except DigitRecognitionError as e:
                raise DigitRecognitionError(
                    f"digit OCR failed on row {row_index}, chunk {chunk_index}: {e}"
                ) from e
            for local_index, value in zip(kept_indices, recognized_values):
                chunk_values[local_index] = value
            digit_row.extend(chunk_values)
        digit_rows.append(digit_row)
    return _restore_shape(kind, digit_rows)
