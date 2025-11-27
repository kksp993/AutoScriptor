"""
AutoScriptor VLM API
"""

from __future__ import annotations

from typing import Optional

from logzero import logger

from AutoScriptor.core.targets import Target
from AutoScriptor.vlm.templates import *
from AutoScriptor.vlm.utils import make_box_target, parse_qwen_vl_coordinates
from AutoScriptor.vlm.vlm import call_vllm_chat_completion, extract_vllm_text


def step(prompt: str, screenshot: Optional[str] = None, intent: str = "", **overrides) -> str:
    """
    调用视觉语言模型获取策略文本

    Args:
        prompt: 发送给模型的问题
        screenshot: 屏幕截图路径
        intent: 下一步意图
        overrides: 允许覆盖的配置项
    """
    result = call_vllm_chat_completion(
        question=prompt.format(
            intent=intent,
        ),
        screenshot=screenshot,
        **overrides,
    )
    return extract_vllm_text(result)

def make_click_target(response: str) -> Target:
    """
    根据响应生成点击目标
    """

    try:
        x, y = parse_qwen_vl_coordinates(response)
        logger.info(f"解析到屏幕坐标: ({x}, {y})")
    except Exception as err:
        logger.error(f"无法解析坐标: {err}")
        return

    target = make_box_target(x, y)
    return target