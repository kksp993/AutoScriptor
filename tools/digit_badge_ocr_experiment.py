"""Experiment: read tiny game item-count digits without touching runtime code.

Usage examples:
  python tools/digit_badge_ocr_experiment.py --image screenshot.png ^
    --box 441,170,28,18:898 --box 751,170,18,18:9 --save-debug

  python tools/digit_badge_ocr_experiment.py --image screenshot.png ^
    --ref 441,170,28,18:898 --ref 603,170,52,18:22500 ^
    --box 751,170,18,18:9 --box 436,262,18,18:3 --save-debug

The script tries two independent ideas:
  1. PaddleOCR on several digit-friendly preprocessed variants.
  2. Template matching using known reference numbers from the same screenshot.

It is intentionally standalone so experiments stay outside the main app.
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


DIGIT_TRANSLATION = str.maketrans({
    "O": "0", "o": "0", "D": "0", "Q": "0",
    "I": "1", "l": "1", "|": "1", "!": "1",
    "Z": "2", "z": "2",
    "A": "4",
    "S": "5", "s": "5", "$": "5",
    "G": "6",
    "B": "8",
    "g": "9", "q": "9",
})


@dataclass(frozen=True)
class BoxSpec:
    left: int
    top: int
    width: int
    height: int
    label: str = ""

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    def name(self, idx: int) -> str:
        suffix = f"_{self.label}" if self.label else ""
        return f"{idx:02d}_{self.left}_{self.top}_{self.width}_{self.height}{suffix}"


def parse_box(raw: str) -> BoxSpec:
    coord, _, label = raw.partition(":")
    parts = [int(x.strip()) for x in coord.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("box must be x,y,w,h or x,y,w,h:label")
    return BoxSpec(*parts, label=label.strip())


def latest_debug_image() -> str | None:
    paths = glob.glob(os.path.join("logs", "**", "*.png"), recursive=True)
    if not paths:
        return None
    return max(paths, key=os.path.getmtime)


def crop(frame: np.ndarray, box: BoxSpec) -> np.ndarray:
    return frame[box.top:box.bottom, box.left:box.right]


def normalize_digits(text: str, expected_len: int | None = None) -> str:
    if not text:
        return ""
    digits = "".join(re.findall(r"\d+", text.translate(DIGIT_TRANSLATION)))
    if expected_len and len(digits) > expected_len:
        digits = digits[-expected_len:]
    return digits


def digit_mask(roi: np.ndarray) -> np.ndarray:
    """Extract bright low-saturation glyphs from a small badge crop."""
    if roi.size == 0:
        return np.zeros((1, 1), dtype=np.uint8)
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    whiteish = cv2.inRange(hsv, np.array([0, 0, 125]), np.array([180, 150, 255]))
    bright = cv2.inRange(gray, 145, 255)
    mask = cv2.bitwise_and(whiteish, bright)
    kernel = np.ones((2, 2), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    return clean_digit_mask(mask)


def clean_digit_mask(mask: np.ndarray) -> np.ndarray:
    """Drop tiny specks that poison template splitting."""
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if count <= 1:
        return mask
    cleaned = np.zeros_like(mask)
    height = mask.shape[0]
    for idx in range(1, count):
        x, y, w, h, area = stats[idx]
        if area < 5:
            continue
        if h < max(3, int(height * 0.18)):
            continue
        cleaned[labels == idx] = 255
    return cleaned


def tight_bbox(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    ys, xs = np.where(mask > 0)
    if len(xs) == 0 or len(ys) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def normalize_mask(mask: np.ndarray, size: tuple[int, int] = (24, 32)) -> np.ndarray:
    bbox = tight_bbox(mask)
    if bbox is None:
        return np.zeros((size[1], size[0]), dtype=np.uint8)
    x1, y1, x2, y2 = bbox
    glyph = mask[y1:y2, x1:x2]
    padded = cv2.copyMakeBorder(glyph, 2, 2, 2, 2, cv2.BORDER_CONSTANT, value=0)
    return cv2.resize(padded, size, interpolation=cv2.INTER_AREA)


def split_by_label(mask: np.ndarray, label: str) -> list[np.ndarray]:
    bbox = tight_bbox(mask)
    if bbox is None or not label:
        return []
    x1, y1, x2, y2 = bbox
    text_mask = mask[y1:y2, x1:x2]
    n = len(label)
    projection = np.count_nonzero(text_mask, axis=0)
    active_cols = np.where(projection > 1)[0]
    if len(active_cols) > 0:
        text_mask = text_mask[:, active_cols[0]:active_cols[-1] + 1]
    pieces = []
    for i in range(n):
        a = round(i * text_mask.shape[1] / n)
        b = round((i + 1) * text_mask.shape[1] / n)
        pieces.append(text_mask[:, a:b])
    return pieces


def split_unknown(mask: np.ndarray, expected_len: int | None = None) -> list[np.ndarray]:
    bbox = tight_bbox(mask)
    if bbox is None:
        return []
    x1, y1, x2, y2 = bbox
    text_mask = mask[y1:y2, x1:x2]
    if expected_len and expected_len > 0:
        return [
            text_mask[:, round(i * text_mask.shape[1] / expected_len):round((i + 1) * text_mask.shape[1] / expected_len)]
            for i in range(expected_len)
        ]
    projection = np.count_nonzero(text_mask, axis=0)
    active = projection > max(1, int(text_mask.shape[0] * 0.08))
    runs: list[tuple[int, int]] = []
    start = None
    for idx, value in enumerate(active):
        if value and start is None:
            start = idx
        elif not value and start is not None:
            runs.append((start, idx))
            start = None
    if start is not None:
        runs.append((start, len(active)))
    merged: list[list[int]] = []
    for a, b in runs:
        if merged and a - merged[-1][1] <= 2:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    return [text_mask[:, a:b] for a, b in merged if b - a >= 2]


def build_templates(frame: np.ndarray, refs: list[BoxSpec], debug_dir: Path | None = None) -> dict[str, list[np.ndarray]]:
    templates: dict[str, list[np.ndarray]] = defaultdict(list)
    for idx, ref in enumerate(refs):
        roi = crop(frame, ref)
        mask = digit_mask(roi)
        if debug_dir:
            cv2.imwrite(str(debug_dir / f"ref_{ref.name(idx)}_mask.png"), mask)
        for ch, piece in zip(ref.label, split_by_label(mask, ref.label)):
            if ch.isdigit():
                templates[ch].append(normalize_mask(piece))
    return templates


def read_with_templates(
    roi: np.ndarray,
    templates: dict[str, list[np.ndarray]],
    expected_len: int | None = None,
) -> tuple[str, float]:
    if not templates:
        return "", 0.0
    pieces = split_unknown(digit_mask(roi), expected_len=expected_len)
    if not pieces:
        return "", 0.0
    chars = []
    scores = []
    for piece in pieces:
        norm = normalize_mask(piece)
        best_digit = ""
        best_score = -1.0
        for digit, digit_templates in templates.items():
            for tmpl in digit_templates:
                score = cv2.matchTemplate(norm, tmpl, cv2.TM_CCOEFF_NORMED)[0][0]
                if score > best_score:
                    best_digit = digit
                    best_score = float(score)
        chars.append(best_digit)
        scores.append(best_score)
    return "".join(chars), float(np.mean(scores)) if scores else 0.0


def ocr_variants(roi: np.ndarray) -> list[tuple[str, np.ndarray]]:
    variants: list[tuple[str, np.ndarray]] = []
    if roi.size == 0:
        return variants

    scale = 5 if max(roi.shape[:2]) < 28 else 4
    enlarged = cv2.resize(roi, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

    def add(name: str, img: np.ndarray) -> None:
        if len(img.shape) == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        img = cv2.copyMakeBorder(img, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=(255, 255, 255))
        variants.append((name, img))

    add("raw_x", enlarged)
    gray = cv2.cvtColor(enlarged, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4)).apply(gray)
    add("clahe", clahe)
    _, otsu = cv2.threshold(clahe, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    add("otsu", otsu)
    add("otsu_inv", 255 - otsu)
    add("white_mask", cv2.resize(digit_mask(roi), None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST))
    adaptive = cv2.adaptiveThreshold(clahe, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 21, 3)
    add("adaptive", adaptive)
    return variants


def extract_ocr_candidates(result) -> list[tuple[str, float]]:
    candidates: list[tuple[str, float]] = []

    def visit(node) -> None:
        if isinstance(node, (list, tuple)):
            if len(node) >= 2:
                if isinstance(node[0], str) and isinstance(node[1], (int, float)):
                    candidates.append((node[0], float(node[1])))
                elif (
                    isinstance(node[1], (list, tuple))
                    and len(node[1]) >= 2
                    and isinstance(node[1][0], str)
                    and isinstance(node[1][1], (int, float))
                ):
                    candidates.append((node[1][0], float(node[1][1])))
            for item in node:
                visit(item)

    visit(result)
    return candidates


def read_with_paddle(roi: np.ndarray, expected_len: int | None, debug_dir: Path | None, stem: str) -> tuple[str, float]:
    try:
        from paddleocr import PaddleOCR
    except Exception as exc:
        print(f"PaddleOCR unavailable: {exc}")
        return "", 0.0

    engine = PaddleOCR(use_angle_cls=False, lang="en", show_log=False)
    votes: dict[str, float] = defaultdict(float)

    for name, img in ocr_variants(roi):
        if debug_dir:
            cv2.imwrite(str(debug_dir / f"{stem}_{name}.png"), img)
        for kwargs, weight in (({"cls": False}, 1.0), ({"det": False, "cls": False}, 1.35)):
            try:
                result = engine.ocr(img, **kwargs)
            except Exception as exc:
                print(f"  OCR variant {name} {kwargs} failed: {exc}")
                continue
            for text, conf in extract_ocr_candidates(result):
                digits = normalize_digits(text, expected_len=expected_len)
                if digits:
                    votes[digits] += max(conf, 0.01) * weight

    if not votes:
        return "", 0.0
    return max(votes.items(), key=lambda item: (item[1], len(item[0])))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", default=None, help="Screenshot path. Defaults to latest logs/**/*.png.")
    parser.add_argument("--box", action="append", type=parse_box, default=[], help="Target x,y,w,h[:expected].")
    parser.add_argument("--ref", action="append", type=parse_box, default=[], help="Reference x,y,w,h:digits for templates.")
    parser.add_argument("--save-debug", action="store_true", help="Write crops and preprocessed variants.")
    parser.add_argument("--no-paddle", action="store_true", help="Skip PaddleOCR and only run template matching.")
    args = parser.parse_args()

    image_path = args.image or latest_debug_image()
    if not image_path:
        print("No image supplied and no logs/**/*.png found.")
        return 2

    frame = cv2.imread(image_path)
    if frame is None:
        print(f"Could not read image: {image_path}")
        return 2

    stamp = time.strftime("%Y%m%d_%H%M%S")
    debug_dir = Path("logs") / "digit_ocr_experiment" / stamp if args.save_debug else None
    if debug_dir:
        debug_dir.mkdir(parents=True, exist_ok=True)
        print(f"debug_dir={debug_dir}")

    templates = build_templates(frame, args.ref, debug_dir)
    if templates:
        print("templates=" + ", ".join(f"{k}:{len(v)}" for k, v in sorted(templates.items())))
    else:
        print("templates=none")

    print(f"image={image_path} shape={frame.shape[1]}x{frame.shape[0]}")
    print("idx box expected template(score) paddle(score)")

    for idx, box in enumerate(args.box):
        roi = crop(frame, box)
        if debug_dir:
            cv2.imwrite(str(debug_dir / f"target_{box.name(idx)}_crop.png"), roi)
            cv2.imwrite(str(debug_dir / f"target_{box.name(idx)}_mask.png"), digit_mask(roi))
        expected_len = len(box.label) if box.label else None
        tmpl_text, tmpl_score = read_with_templates(roi, templates, expected_len=expected_len)
        if args.no_paddle:
            paddle_text, paddle_score = "", 0.0
        else:
            paddle_text, paddle_score = read_with_paddle(roi, expected_len, debug_dir, f"target_{box.name(idx)}")
        print(
            f"{idx:02d} {box.left},{box.top},{box.width},{box.height} "
            f"{box.label or '-'} {tmpl_text or '-'}({tmpl_score:.3f}) "
            f"{paddle_text or '-'}({paddle_score:.3f})"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
