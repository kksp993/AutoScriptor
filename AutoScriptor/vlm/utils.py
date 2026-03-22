"""
VLM 辅助工具
"""

from __future__ import annotations

import base64
import json
import os
import re
from typing import Optional

from AutoScriptor.core.targets import BoxTarget
from AutoScriptor.utils.box import Box

# pre-compiled patterns for coordinate extraction
_BOX_2D_RE = re.compile(
    r"<box[^>]*>\s*\(?\s*(\d+)\s*,\s*(\d+)\s*\)?\s*,?\s*\(?\s*(\d+)\s*,\s*(\d+)\s*\)?\s*</box>",
    re.IGNORECASE,
)
_JSON_RE = re.compile(r"\{[^{}]*\}")
_PAIR_RE = re.compile(r"\(?\s*(\d+)\s*,\s*(\d+)\s*\)?")


def encode_image_to_base64(image_path: Optional[str]) -> str:
    """读取图片并返回 base64 编码字符串"""
    path = image_path or ""
    if not path or not os.path.exists(path):
        raise FileNotFoundError(f"图片不存在: {path}")
    with open(path, "rb") as fp:
        return base64.b64encode(fp.read()).decode("utf-8")


def parse_qwen_vl_coordinates(
    coord_str: str | tuple[int, int],
    *,
    width: int = 1280,
    height: int = 720,
) -> tuple[int, int]:
    """Parse VLM grounding output → pixel (x, y).

    Supported formats (all with 0-999 normalised range):
      - ``(x, y)``  or  ``x, y``
      - ``<box>(x1,y1),(x2,y2)</box>``  →  returns centre
      - ``{"x": N, "y": N}``  JSON
      - tuple passthrough  ``(x, y)``
    """
    if isinstance(coord_str, (tuple, list)) and len(coord_str) >= 2:
        x_norm, y_norm = int(coord_str[0]), int(coord_str[1])
        return int(x_norm / 1000 * width), int(y_norm / 1000 * height)

    text: str = coord_str or ""

    # 1) <box>(x1,y1),(x2,y2)</box>  →  centre point
    m = _BOX_2D_RE.search(text)
    if m:
        x1, y1, x2, y2 = map(int, m.groups())
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        return int(cx / 1000 * width), int(cy / 1000 * height)

    # 2) JSON  {"x": N, "y": N}
    for jm in _JSON_RE.finditer(text):
        try:
            data = json.loads(jm.group(0))
            if "arguments" in data:
                data = data["arguments"]
            if "x" in data and "y" in data:
                x, y = float(data["x"]), float(data["y"])
                if 0 <= x <= 1 and 0 <= y <= 1:
                    return int(x * width), int(y * height)
                return int(x / 1000 * width), int(y / 1000 * height)
        except (json.JSONDecodeError, KeyError, TypeError):
            continue

    # 3) (x, y) or bare  x, y  — take LAST pair found
    pairs = _PAIR_RE.findall(text)
    if pairs:
        x_norm, y_norm = map(int, pairs[-1])
        return int(x_norm / 1000 * width), int(y_norm / 1000 * height)

    # 4) fallback: any two numbers
    numbers = re.findall(r"\d+", text)
    if len(numbers) >= 2:
        x_norm, y_norm = int(numbers[-2]), int(numbers[-1])
        return int(x_norm / 1000 * width), int(y_norm / 1000 * height)

    raise ValueError(f"无法解析坐标: {coord_str}")


def make_box_target(x: int, y: int, size: int = 5) -> BoxTarget:
    """将坐标转换为可供 click 使用的 BoxTarget"""
    half = size // 2
    box = Box(max(x - half, 0), max(y - half, 0), size, size)
    return BoxTarget(box)
