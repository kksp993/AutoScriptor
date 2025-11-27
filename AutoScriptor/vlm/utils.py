"""
VLM 辅助工具
"""

from __future__ import annotations

import base64
import os
from typing import Optional

from AutoScriptor.core.targets import BoxTarget
from AutoScriptor.utils.box import Box


def encode_image_to_base64(image_path: Optional[str]) -> str:
    """读取图片并返回 base64 编码字符串"""
    path = image_path or ''
    if not path or not os.path.exists(path):
        raise FileNotFoundError(f"图片不存在: {path}")

    with open(path, "rb") as fp:
        return base64.b64encode(fp.read()).decode("utf-8")



def parse_qwen_vl_coordinates(coord_str: str|tuple[int, int], *, width: int = 1280, height: int = 720) -> tuple[int, int]:
    """将 Qwen-VL 返回的坐标转换为像素坐标（支持归一化和像素值）"""
    import re
    import json

    # 1. 尝试解析 JSON 格式 (e.g. {"x": 632, "y": 197})
    try:
        if isinstance(coord_str, str) and "{" in coord_str:
            match = re.search(r"\{.*\}", coord_str)
            if match:
                data = json.loads(match.group(0))
                if "arguments" in data: data = data["arguments"]
                if "x" in data and "y" in data:
                    x, y = float(data["x"]), float(data["y"])
                    # 简单的启发式判断：如果坐标看起来是归一化的 (0-1 之间的小数)
                    if 0 <= x <= 1 and 0 <= y <= 1:
                        return int(x * width), int(y * height)
                    # 如果是归一化整数 (0-1000)
                    elif 0 <= x <= 1000 and 0 <= y <= 1000 and (x > 1 or y > 1):
                        # 这里的歧义很大，有些模型输出 0-1000，有些输出真实像素
                        # 假设: 如果 x 或 y 大于 1，且看起来不像屏幕尺寸的一半，可能是 0-1000
                        # 但如果屏幕很小... 无论如何，Qwen-VL 默认是 0-1000
                        # 除非明确知道这是像素坐标。
                        # 给定日志里的 (632, 197)，在 720p 屏幕上，这既可能是像素也可能是 0-1000。
                        # 必须看 Prompt 要求。通常 Tool Call 输出的是像素。
                        # 让我们假设 JSON tool call 输出的是绝对像素，除非它特别大。
                        return int(x), int(y)
    except Exception:
        pass

    # 2. 回退到正则提取数字 (Qwen-VL 默认输出 <box_2d> [x1, y1, x2, y2] </box_2d> 是 0-1000)
    if isinstance(coord_str, tuple):
        x_norm, y_norm = coord_str
    else:
        numbers = re.findall(r"\d+", coord_str or "")
        if len(numbers) < 2:
            raise ValueError(f"无法解析坐标: {coord_str}")
        x_norm, y_norm = map(int, numbers[-2:])

    x = int(x_norm / 1000 * width)
    y = int(y_norm / 1000 * height)
    return x, y

def make_box_target(x: int, y: int, size: int = 5) -> BoxTarget:
    """将坐标转换为可供 click 使用的 BoxTarget"""
    half = size // 2
    box = Box(max(x - half, 0), max(y - half, 0), size, size)
    return BoxTarget(box)
