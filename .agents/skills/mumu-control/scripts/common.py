"""
common.py — Shared module for mumu-control Android automation scripts.

Provides: device connection, UIElement model, drawing utilities,
element output, screenshot capture, and OCR text matching.
"""

import sys
import io
import json
import random
import argparse
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field

# Windows UTF-8 console setup
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)

import numpy as np
from PIL import Image, ImageDraw, ImageFont
import uiautomator2 as u2


# ==================== Device Connection ====================

def add_device_args(parser: argparse.ArgumentParser) -> None:
    """Add -s/--serial argument to an argparse parser."""
    parser.add_argument(
        '-s', '--serial',
        type=str,
        default='127.0.0.1:16384',
        help='ADB device serial (default: 127.0.0.1:16384)'
    )


# Default output directory for all scripts
DEFAULT_OUTPUT_DIR = './tmp/mumu-control'


def connect_device(serial: str) -> u2.Device:
    """
    Connect to an Android device via uiautomator2.

    Args:
        serial: ADB device serial (e.g., '127.0.0.1:16384')

    Returns:
        Connected u2.Device instance

    Exits with code 1 on connection failure.
    """
    try:
        d = u2.connect(serial)
        info = d.info
        sdk = info.get('sdkInt', '?')
        w = info.get('displayWidth', '?')
        h = info.get('displayHeight', '?')
        print(f"Connected to {serial} (SDK {sdk}, {w}x{h})")
        return d
    except Exception as e:
        print(f"ERROR: Failed to connect to {serial}: {e}", file=sys.stderr)
        sys.exit(1)


# ==================== UIElement Data Model ====================

@dataclass
class UIElement:
    """UI element data structure, matching win-ui pattern."""
    name: str = ""
    control_type: str = ""
    coords: Dict[str, int] = field(default_factory=lambda: {"x": 0, "y": 0})
    size: Dict[str, int] = field(default_factory=lambda: {"width": 0, "height": 0})
    resource_id: str = ""
    class_name: str = ""
    clickable: bool = False
    text: str = ""
    content_desc: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "control_type": self.control_type,
            "coords": self.coords,
            "size": self.size,
            "resource_id": self.resource_id,
            "class_name": self.class_name,
            "clickable": self.clickable,
            "text": self.text,
            "content_desc": self.content_desc,
        }

    def get_rect(self) -> Tuple[int, int, int, int]:
        """Get bounding rect (left, top, right, bottom)."""
        cx, cy = self.coords["x"], self.coords["y"]
        w, h = self.size["width"], self.size["height"]
        left = cx - w // 2
        top = cy - h // 2
        right = left + w
        bottom = top + h
        return (left, top, right, bottom)


# ==================== Color Generator ====================

def generate_distinct_colors(n: int, shuffle: bool = True) -> List[Tuple[int, int, int]]:
    """
    Generate n visually distinct colors via HSV rotation.

    Args:
        n: Number of colors
        shuffle: Whether to shuffle order for adjacent contrast
    """
    colors = []
    for i in range(n):
        hue = (i * 360 // n) % 360
        saturation = 0.9
        value = 0.9

        c = value * saturation
        x = c * (1 - abs((hue / 60) % 2 - 1))
        m = value - c

        if 0 <= hue < 60:
            r, g, b = c, x, 0
        elif 60 <= hue < 120:
            r, g, b = x, c, 0
        elif 120 <= hue < 180:
            r, g, b = 0, c, x
        elif 180 <= hue < 240:
            r, g, b = 0, x, c
        elif 240 <= hue < 300:
            r, g, b = x, 0, c
        else:
            r, g, b = c, 0, x

        colors.append((
            int((r + m) * 255),
            int((g + m) * 255),
            int((b + m) * 255)
        ))

    if shuffle and len(colors) > 1:
        random.shuffle(colors)

    return colors


# ==================== Rectangle Utilities ====================

def rects_overlap(rect1: Tuple[int, int, int, int], rect2: Tuple[int, int, int, int]) -> bool:
    """
    Check if two (left, top, right, bottom) rectangles overlap.
    """
    left1, top1, right1, bottom1 = rect1
    left2, top2, right2, bottom2 = rect2

    if right1 <= left2 or right2 <= left1:
        return False
    if bottom1 <= top2 or bottom2 <= top1:
        return False

    return True


def filter_by_size(elements: List[UIElement], max_long_edge: int = 250) -> List[UIElement]:
    """
    Filter out elements whose longest edge exceeds threshold.
    Input elements (EditText, AutoCompleteTextView, etc.) use higher threshold (500px).

    Args:
        elements: UI element list
        max_long_edge: Max long edge in pixels (default 250)
    """
    # Input element types that should use higher threshold
    input_class_names = {'EditText', 'AutoCompleteTextView'}
    input_threshold = 500

    filtered = []
    removed_count = 0
    input_saved_count = 0

    for elem in elements:
        width = elem.size["width"]
        height = elem.size["height"]
        long_edge = max(width, height)

        # Check if this is an input element
        is_input = elem.class_name and elem.class_name.split('.')[-1] in input_class_names
        threshold = input_threshold if is_input else max_long_edge

        if long_edge <= threshold:
            filtered.append(elem)
            if is_input and long_edge > max_long_edge:
                input_saved_count += 1
        else:
            removed_count += 1

    if removed_count > 0:
        print(f"Filtered out {removed_count} oversized elements (>{max_long_edge}px)")
    if input_saved_count > 0:
        print(f"Kept {input_saved_count} input elements with extended threshold (>{max_long_edge}px, <=500px)")

    return filtered


# ==================== Drawing Utilities ====================

def draw_elements_on_screenshot(
    screenshot_path: str,
    elements: List[UIElement],
    output_path: str
) -> bool:
    """
    Draw colored rectangles and index labels on screenshot.

    Args:
        screenshot_path: Path to original screenshot
        elements: UI element list
        output_path: Output annotated image path

    Returns:
        True on success
    """
    try:
        img = Image.open(screenshot_path)
        draw = ImageDraw.Draw(img)

        colors = generate_distinct_colors(max(len(elements), 1))

        try:
            font = ImageFont.truetype("arial.ttf", 12)
        except Exception:
            font = ImageFont.load_default()

        for idx, elem in enumerate(elements):
            color = colors[idx % len(colors)]
            left, top, right, bottom = elem.get_rect()

            # Draw rectangle border
            draw.rectangle([left, top, right, bottom], outline=color, width=2)

            # Draw index label
            label = str(idx)
            try:
                bbox = font.getbbox(label)
                label_width = bbox[2] - bbox[0]
                label_height = bbox[3] - bbox[1]
            except Exception:
                label_width, label_height = 10, 10

            label_bg_left = left
            label_bg_top = max(top - label_height - 4, 0)
            label_bg_right = label_bg_left + label_width + 4
            label_bg_bottom = label_bg_top + label_height + 4

            # Label background
            draw.rectangle(
                [label_bg_left, label_bg_top, label_bg_right, label_bg_bottom],
                fill=color
            )

            # Label text (white or black based on background brightness)
            brightness = (color[0] * 299 + color[1] * 587 + color[2] * 114) / 1000
            text_color = (0, 0, 0) if brightness > 128 else (255, 255, 255)
            draw.text(
                (label_bg_left + 2, label_bg_top + 2),
                label,
                fill=text_color,
                font=font
            )

        img.save(output_path)
        print(f"Annotated screenshot saved: {output_path}")
        return True

    except Exception as e:
        print(f"ERROR: Failed to draw screenshot: {e}", file=sys.stderr)
        return False


# ==================== Output Utilities ====================

def save_elements_json(elements: List[UIElement], output_path: str) -> bool:
    """Save element list as JSON with index field matching annotated screenshot."""
    try:
        data = []
        for idx, elem in enumerate(elements):
            elem_dict = elem.to_dict()
            elem_dict = {"index": idx, **elem_dict}
            data.append(elem_dict)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"Element JSON saved: {output_path}")
        return True
    except Exception as e:
        print(f"ERROR: Failed to save JSON: {e}", file=sys.stderr)
        return False


def print_elements_summary(elements: List[UIElement]) -> None:
    """Print human-readable element summary to stdout in AI-friendly Markdown table format."""
    if not elements:
        print("Detected 0 UI elements")
        return

    print(f"Detected {len(elements)} UI elements")
    print()

    # Markdown table header
    print("| Index | X | Y | Name | Type | Resource ID |")
    print("|-------|---|---|------|------|-------------|")

    # Table rows
    for idx, elem in enumerate(elements):
        x = elem.coords["x"]
        y = elem.coords["y"]
        # Escape pipe characters in names
        name = elem.name.replace('|', '\\|') if elem.name else ""

        if elem.control_type == "OCRText":
            elem_type = "OCR"
            res_id = "-"
        else:
            clickable_flag = "✓" if elem.clickable else ""
            elem_type = f"{elem.control_type}"
            if clickable_flag:
                elem_type += " (clickable)"
            res_id = elem.resource_id if elem.resource_id else "-"

        print(f"| {idx} | {x} | {y} | {name} | {elem_type} | {res_id} |")


# ==================== Screenshot ====================

def take_screenshot(device: u2.Device, save_path: str = None) -> Image.Image:
    """
    Capture screenshot via uiautomator2.

    Args:
        device: Connected u2.Device
        save_path: Optional path to save screenshot

    Returns:
        PIL Image
    """
    img = device.screenshot()
    if save_path:
        Path(save_path).parent.mkdir(parents=True, exist_ok=True)
        img.save(save_path)
        print(f"Screenshot saved: {save_path}")
    return img


# ==================== OCR Text Matching ====================

# Lazy-loaded RapidOCR singleton
_rapidocr = None


def _get_rapidocr():
    """Get RapidOCR instance (singleton)."""
    global _rapidocr
    if _rapidocr is None:
        from rapidocr_onnxruntime import RapidOCR
        _rapidocr = RapidOCR()
    return _rapidocr


def ocr_image(image: np.ndarray) -> List[Dict[str, Any]]:
    """
    Run OCR on an image and return structured results.

    Args:
        image: numpy array (BGR or RGB)

    Returns:
        List of dicts with: text, center_x, center_y, width, height, confidence
    """
    ocr = _get_rapidocr()
    result, _ = ocr(image)
    if result is None:
        return []

    ocr_results = []
    for item in result:
        bbox, text, confidence = item
        x_coords = [p[0] for p in bbox]
        y_coords = [p[1] for p in bbox]

        x_min, x_max = min(x_coords), max(x_coords)
        y_min, y_max = min(y_coords), max(y_coords)

        width = x_max - x_min
        height = y_max - y_min
        center_x = int(x_min + width / 2)
        center_y = int(y_min + height / 2)

        ocr_results.append({
            "text": text,
            "confidence": confidence,
            "center_x": center_x,
            "center_y": center_y,
            "width": int(width),
            "height": int(height),
        })

    return ocr_results


def match_text_in_screenshot(
    image: Image.Image,
    text: str,
    exact_match: bool = True
) -> List[Dict[str, Any]]:
    """
    Find text in a screenshot using RapidOCR.

    Args:
        image: PIL Image (screenshot)
        text: Text to search for
        exact_match: If True, match full text; if False, match substring

    Returns:
        List of matches with coords and size dicts
    """
    import cv2
    # Convert PIL Image to numpy array for OCR
    img_array = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
    ocr_results = ocr_image(img_array)

    matches = []
    for ocr_item in ocr_results:
        detected = ocr_item["text"]

        if exact_match:
            matched = text.strip().lower() == detected.strip().lower()
        else:
            matched = text.lower() in detected.lower()

        if matched:
            matches.append({
                "text": detected,
                "coords": {"x": ocr_item["center_x"], "y": ocr_item["center_y"]},
                "size": {"width": ocr_item["width"], "height": ocr_item["height"]},
                "confidence": ocr_item["confidence"],
            })

    return matches
