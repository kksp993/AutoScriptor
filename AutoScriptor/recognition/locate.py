"""Locate targets on a frame: template matching, text OCR, colour and registered images.

This is the single place that answers "where is this target on screen". The OCR
engine import stays lazy on purpose: ``AutoScriptor.core.targets`` imports
``_load_cv2`` from here, and importing ``ocr_rec`` would start the background
OCR engine thread (see docs/AutoScriptor/runtime/lifecycle.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import cv2
import numpy as np

from AutoScriptor.core.box import Box
from AutoScriptor.logging.logger import logger

def _load_cv2(img, grayscale=None):
    """
    TODO
    """
    # load images if given filename, or convert as needed to opencv
    # Alpha layer just causes failures at this point, so flatten to RGB.
    # RGBA: load with -1 * cv2.CV_LOAD_IMAGE_COLOR to preserve alpha
    # to matchTemplate, need template and image to be the same wrt having alpha
    if grayscale is None:
        grayscale = False
    if isinstance(img, str):
        # The function imread loads an image from the specified file and
        # returns it. If the image cannot be read (because of missing
        # file, improper permissions, unsupported or invalid format),
        # the function returns an empty matrix
        # http://docs.opencv.org/3.0-beta/modules/imgcodecs/doc/reading_and_writing_images.html
        if grayscale:
            img_cv = cv2.imread(img, cv2.IMREAD_GRAYSCALE)
        else:
            img_cv = cv2.imread(img, cv2.IMREAD_COLOR)
        if img_cv is None:
            raise IOError(
                "Failed to read %s because file is missing, "
                "has improper permissions, or is an "
                "unsupported or invalid format" % img
            )
    elif isinstance(img, np.ndarray):
        # don't try to convert an already-gray image to gray
        if grayscale and len(img.shape) == 3:  # and img.shape[2] == 3:
            img_cv = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        else:
            img_cv = img
    elif hasattr(img, 'convert'):
        # assume its a PIL.Image, convert to cv format
        img_array = np.array(img.convert('RGB'))
        img_cv = img_array[:, :, ::-1].copy()  # -1 does RGB -> BGR
        if grayscale:
            img_cv = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
    else:
        raise TypeError(f'expected an image filename, OpenCV numpy array, or PIL image, got {img} = {type(img)} which is not supported')
    return img_cv

def imgOnScreen(haystack_frame, needle_images, confidence=0.9):
    """
        在屏幕上查找图片
    :param haystack_frame: 屏幕帧
    :param needle_images: 图片列表
    :param confidence: 置信度
    :param grayscale: 灰度值找图
    :return:
    """
    needle_images = [_load_cv2(needle_image) for needle_image in needle_images]
    haystack_frame = _load_cv2(haystack_frame)
    rs = [_locateAll_opencv(needle_image, haystack_frame, confidence=confidence) for needle_image in needle_images]
    
    # 对每个识别结果进行去重处理
    deduplicated_rs = []
    for boxes in rs:
        if boxes:  # 如果有识别结果
            # 使用Box的去重方法，设置合适的阈值
            deduplicated_boxes = Box.merge_overlapping_boxes(
                boxes, 
                overlap_threshold=0.3,  # 重叠面积超过30%认为重复
                distance_threshold=3     # 距离小于3像素认为重复
            )
            deduplicated_rs.append(deduplicated_boxes)
        else:
            deduplicated_rs.append([])
    
    return deduplicated_rs


# 新的基于金字塔的多尺度匹配实现
def _locateAll_opencv(needleImage, haystackImage, limit=10000, region=None, step=2, confidence=0.9, min_scale=0.8, max_scale=1.2):
    """
    下采样模板与图像后，仅匹配三种 scale：min_scale,1.0,max_scale，加速模板匹配。
    返回所有满足阈值的位置框。
    """
    # 加载灰度图并裁剪区域
    needleGray = _load_cv2(needleImage, True)
    haystackGray = _load_cv2(haystackImage, True)
    if region:
        x0, y0, w0, h0 = region
        haystackGray = haystackGray[y0:y0+h0, x0:x0+w0]
    else:
        x0 = y0 = 0
    # 下采样
    ds = max(2, step)
    hay_ds = haystackGray[::ds, ::ds]
    tpl = needleGray
    tpl_ds = tpl[::ds, ::ds]
    tH, tW = tpl.shape[:2]
    tH_ds, tW_ds = tpl_ds.shape[:2]
    # 关键尺度
    scales = [1.0]
    if min_scale != 1.0:
        scales.append(min_scale)
    if max_scale != 1.0 and max_scale != min_scale:
        scales.append(max_scale)
    boxes = []
    for scale in scales:
        w_s = int(tW_ds * scale)
        h_s = int(tH_ds * scale)
        if w_s < 1 or h_s < 1 or w_s > hay_ds.shape[1] or h_s > hay_ds.shape[0]:
            continue
        tpl_s = cv2.resize(tpl_ds, (w_s, h_s), interpolation=cv2.INTER_AREA)
        res = cv2.matchTemplate(hay_ds, tpl_s, cv2.TM_CCOEFF_NORMED)
        ys, xs = np.where(res >= confidence)
        for y, x in zip(ys, xs):
            real_x = x * ds + x0
            real_y = y * ds + y0
            boxes.append(Box(real_x, real_y, tW, tH))
            if len(boxes) >= limit:
                return boxes
    return boxes


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


def locate_on_screen(haystack_frame, targets, confidence=0.8, pf_boxes=None, colors=None):
    img_targets, text_targets, box_targets = [], [], []
    img_pf_boxes, text_pf_boxes = [], []
    img_colors, text_colors, box_colors = [], [], []
    ids = []

    for i, target in enumerate(targets):
        if isinstance(target, str):
            text_targets.append(target)
            text_pf_boxes.append(pf_boxes[i])
            text_colors.append(colors[i])
            ids.append("t" + str(len(text_targets) - 1))
        elif isinstance(target, Box):
            box_targets.append(target)
            box_colors.append(colors[i] if colors is not None else None)
            ids.append("b" + str(len(box_targets) - 1))
        else:
            img_targets.append(target)
            img_pf_boxes.append(pf_boxes[i])
            img_colors.append(colors[i])
            ids.append("i" + str(len(img_targets) - 1))

    if (img_targets and text_targets) or box_targets:
        img_boxes = locate_on_screen(haystack_frame, img_targets, confidence, img_pf_boxes, img_colors) if img_targets else []
        text_boxes = locate_on_screen(haystack_frame, text_targets, confidence, text_pf_boxes, text_colors) if text_targets else []
        box_boxes = []
        for j, box in enumerate(box_targets):
            color = box_colors[j]
            if color:
                detected_color = get_box_color(haystack_frame, box)
                box_boxes.append([box] if detected_color == color else None)
            else:
                box_boxes.append([box])
        return [
            img_boxes[int(item[1:])]
            if item[0] == "i"
            else text_boxes[int(item[1:])]
            if item[0] == "t"
            else box_boxes[int(item[1:])]
            for item in ids
        ]

    def get_roi(preferred_box):
        if preferred_box:
            return haystack_frame[
                preferred_box.top:preferred_box.top + preferred_box.height,
                preferred_box.left:preferred_box.left + preferred_box.width,
            ]
        return haystack_frame

    roi_dict = {pf_box: get_roi(pf_box) for pf_box in set(pf_boxes)}
    roi = next(iter(roi_dict.values())) if len(roi_dict) == 1 else haystack_frame

    if isinstance(targets[0], str):
        # Local import: this module is imported by core.targets for _load_cv2,
        # and importing ocr_rec would start its background OCR engine thread.
        from AutoScriptor.recognition.ocr_rec import ocr
        from AutoScriptor.utils.app_config import cfg as _cfg

        scale = float(_cfg.get("ocr.scale", 1.0))
        res = ocr(roi, targets, confidence, None, scale=scale)
        assert res is not None, "ocr returned None"
    else:
        res = imgOnScreen(roi, targets, confidence=confidence)
        assert res is not None, "imgOnScreen returned None"

    def to_full_frame(box, preferred_box):
        return Box(
            box.left + preferred_box.left,
            box.top + preferred_box.top,
            box.width,
            box.height,
        )

    if len(roi_dict) == 1:
        if len(res) != len(targets):
            # 识别失败时下游会返回空列表（``ocr()`` 出错就走这条路，例如 OCR 引擎还没就绪），
            # 而不是与 targets 等长的表。照原样按角标取值会把它变成 IndexError，看起来像
            # 定位代码出错，真正的原因（识别没跑成）反而只在日志里。这里收口成「全部未命中」。
            logger.warning(
                "识别结果行数 %s 与目标数 %s 不一致，按未命中处理：%s",
                len(res), len(targets), [repr(item) for item in targets],
            )
            return [None] * len(targets)
        res = [[to_full_frame(box, pf_boxes[i]) for box in res[i]] for i in range(len(targets))]

    for i, boxes in enumerate(res):
        for box in list(boxes):
            if not box.is_in(pf_boxes[i]):
                boxes.remove(box)
        if not boxes:
            res[i] = None

    for i, boxes in enumerate(res):
        if colors[i] and boxes:
            res_color = [get_box_color(haystack_frame, box) for box in boxes]
            if colors[i] not in res_color:
                res[i] = None
            else:
                res[i] = [boxes[j] for j in range(len(boxes)) if res_color[j] == colors[i]]

    return res


def get_box_color(haystack_frame, box):
    roi = haystack_frame[box.top:box.top + box.height, box.left:box.left + box.width]
    if roi.size == 0:
        return "区域无效"

    hsv_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    lower_bound = np.array([0, 50, 50])
    upper_bound = np.array([180, 255, 255])
    mask = cv2.inRange(hsv_roi, lower_bound, upper_bound)

    if mask.any():
        hist = cv2.calcHist([hsv_roi], [0], mask, [180], [0, 180])
        h_main = np.argmax(hist)
        s_main = np.mean(hsv_roi[mask > 0][:, 1])
        v_main = np.mean(hsv_roi[mask > 0][:, 2])
    else:
        h_main = 0
        s_main = 0
        v_main = np.mean(hsv_roi[:, :, 2])

    def get_hsv_color_name(h_value, s_value, v_value):
        if s_value <= 50:
            if v_value <= 50:
                return "黑色"
            if v_value <= 220:
                return "灰色"
            return "白色"
        if (0 <= h_value <= 10) or (156 <= h_value <= 180):
            return "红色"
        if 11 <= h_value <= 25:
            return "橙色"
        if 26 <= h_value <= 34:
            return "黄色"
        if 35 <= h_value <= 77:
            return "绿色"
        if 78 <= h_value <= 99:
            return "青色"
        if 100 <= h_value <= 124:
            return "蓝色"
        if 125 <= h_value <= 155:
            return "紫色"
        return "其他"

    return get_hsv_color_name(h_main, s_main, v_main)
