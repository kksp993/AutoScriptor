"""
VLM 智能体测试
"""

from __future__ import annotations
from timeit import timeit

import cv2
from logzero import logger

from AutoScriptor import mixctrl
from AutoScriptor.core.targets import BoxTarget
from AutoScriptor.utils.box import Box
from AutoScriptor.vlm.utils import parse_qwen_vl_coordinates
from AutoScriptor.vlm.vlm import VLMAgent

SCREENSHOT_PATH = "screenshot.png"
agent = VLMAgent()  # 复用 Agent


def capture_screen(path: str = SCREENSHOT_PATH) -> str:
    """截取当前屏幕并保存到指定路径"""
    screenshot = mixctrl.nemu_control.screenshot()
    cv2.imwrite(path, screenshot)
    logger.info(f"截图已保存: {path}")
    return path


def make_box_target(x: int, y: int, size: int = 30) -> BoxTarget:
    """将坐标转换为可供 click 使用的 BoxTarget"""
    half = size // 2
    box = Box(max(x - half, 0), max(y - half, 0), size, size)
    return BoxTarget(box)


def run_agent(intent_desc: str, use_tools: bool = True):
    prompt = intent_desc
    content = agent.run(prompt, capture_screen(), use_tools=use_tools)
    logger.debug(f"VLM 响应: {content}")
    return content

def agent_locate_test(intent_desc: str):
    return run_agent(intent_desc, use_tools=False)


if __name__ == "__main__":
    print(timeit(lambda: parse_qwen_vl_coordinates(agent_locate_test("""腾蛇飞升""")), number=2))