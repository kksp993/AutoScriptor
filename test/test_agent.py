"""
VLM 智能体测试
"""

from __future__ import annotations
import re
import traceback

import cv2
from logzero import logger

from AutoScriptor import bg, mixctrl, click
from AutoScriptor.core.targets import BoxTarget
from AutoScriptor.utils.box import Box
from AutoScriptor.core.vlm_api import make_click_target
from AutoScriptor.vlm.frontend import VLMAgent
from AutoScriptor.vlm.utils import parse_qwen_vl_coordinates

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


def run_agent(intent_desc: str, history: list[str] = None):
    prompt = intent_desc

    content = agent.run(prompt, capture_screen())
    logger.info(f"VLM 响应: {content}")
    
    if "__END_OF_TASK__" in content: return content
    
    return content

if __name__ == "__main__":
    try:
        res = ""
        history = []
        while "__END_OF_TASK__" not in res:
            res = run_agent("帮我去荒古万界，穿梭到外域", history)
            history.append(f"Action Output: {res}")
            if res in history[:-2]:
                logger.warning("检测到死循环，强制停止")
                break
            # 简单防止死循环
            if len(history) > 20:
                logger.warning("任务步数过多，强制停止")
                break
         # 尝试解析并执行点击（如果有）

    except Exception as e:
        traceback.print_exc()
        logger.error(f"测试失败: {e}")
        exit(1)
    finally:
        bg.stop()
        exit(0)
