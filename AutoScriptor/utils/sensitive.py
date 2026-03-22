"""
敏感信息处理
============
对截图和日志进行脱敏，隐藏 UID、账号等信息。
"""
from __future__ import annotations

import re
from typing import Optional

import numpy as np


def handle_sensitive_image(image: np.ndarray, uid_region: tuple = (680, 720, 0, 180)) -> np.ndarray:
    """
    将截图中可能包含 UID / 角色名的区域涂黑。

    Args:
        image: BGR 图像 (numpy array)
        uid_region: (y1, y2, x1, x2) 涂黑区域

    Returns:
        处理后的图像
    """
    y1, y2, x1, x2 = uid_region
    h, w = image.shape[:2]
    y1, y2 = min(y1, h), min(y2, h)
    x1, x2 = min(x1, w), min(x2, w)
    if y2 > y1 and x2 > x1:
        image[y1:y2, x1:x2] = 0
    return image


_SENSITIVE_PATTERNS = [
    (re.compile(r"(account|账号|用户名)\s*[:=]\s*\S+", re.IGNORECASE), r"\1=***"),
    (re.compile(r"(password|密码)\s*[:=]\s*\S+", re.IGNORECASE), r"\1=***"),
    (re.compile(r"(security_key|安全密码)\s*[:=]\s*\S+", re.IGNORECASE), r"\1=***"),
    (re.compile(r"(token|access_token)\s*[:=]\s*\S+", re.IGNORECASE), r"\1=***"),
]


def handle_sensitive_logs(text: str) -> str:
    """
    替换日志文本中的敏感信息。

    Args:
        text: 原始日志文本

    Returns:
        脱敏后的文本
    """
    for pattern, replacement in _SENSITIVE_PATTERNS:
        text = pattern.sub(replacement, text)
    return text
