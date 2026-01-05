"""
调试截图工具类：用于保存带标注的调试截图
"""
import os
import cv2
from datetime import datetime
from typing import Optional
from logzero import logger
from AutoScriptor.core.targets import Target, BoxTarget
from AutoScriptor.utils.box import Box

# 点击截图目录
CLICK_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'logs', 'click_screenshots')
CLICK_DIR = os.path.abspath(CLICK_DIR)
os.makedirs(CLICK_DIR, exist_ok=True)


def _draw_text_with_bg(img, text: str, position: tuple[int, int], font_scale: float = 0.6, thickness: int = 2):
    """在图片上绘制带背景的文字"""
    font = cv2.FONT_HERSHEY_SIMPLEX
    text_color = (255, 255, 255)  # 白色文字
    bg_color = (0, 0, 0)  # 黑色背景
    
    (text_width, text_height), baseline = cv2.getTextSize(text, font, font_scale, thickness)
    text_x, text_y = position
    
    # 绘制文字背景
    cv2.rectangle(img, 
                 (text_x - 2, text_y - text_height - 2), 
                 (text_x + text_width + 2, text_y + baseline + 2), 
                 bg_color, -1)
    
    # 绘制文字
    cv2.putText(img, text, (text_x, text_y), font, font_scale, text_color, thickness)
    
    return text_height + baseline + 4  # 返回文字高度，用于计算下一个文字位置


def save_debug_screenshot(
    target: Target|tuple[Target, ...],
    screenshot,  # numpy array (cv2 image format)
    box: Optional[Box] = None, 
    pt: Optional[tuple[int, int]] = None,
    ocr_text: Optional[str] = None,
):
    """
    保存调试截图，支持多种标注方式
    
    Args:
        target: 目标对象或目标对象元组，用于标注目标信息
        screenshot: 截图底板（numpy array，cv2 格式）
        box: 用于标注框选区域（可选）
        pt: 点击位置 (x, y)，当点击或长按时有效（可选）
        ocr_text: OCR 结果文字，格式为 "ocr:{识别结果}"（可选）
    
    Examples:
        from AutoScriptor.utils.tracer import save_debug_screenshot
        from AutoScriptor.utils.box import Box
        
        # 点击截图
        save_debug_screenshot(target=T("确定"), screenshot=img, box=box, pt=(100, 200))
        
        # OCR 截图
        save_debug_screenshot(target=BoxTarget(Box(100, 100, 200, 50)), screenshot=img, box=Box(100, 100, 200, 50), ocr_text="ocr:购买")
    """
    try:
        img = screenshot.copy()
        
        # 1. 绘制 Target 相关的标注（红色框和点击位置）
        if box is not None:
            right = box.left + box.width
            bottom = box.top + box.height
            cv2.rectangle(img, (box.left, box.top), (right, bottom), (0, 0, 255), 3)
            
            # 绘制 Target 信息文字
            if target is not None:
                target_str = repr(target) if isinstance(target, tuple) else repr(target.set_box(box))
                _draw_text_with_bg(img, target_str, (box.left, max(box.top - 10, 20)))
        
        # 2. 绘制点击位置
        if pt is not None:
            cv2.circle(img, pt, 5, (0, 0, 255), -1)
            
        # 3. 绘制 OCR 结果文字（格式：ocr:{识别结果}）
        if ocr_text is not None:
            # 如果传入的不是 "None" 字符串，格式化为 ocr:{res}
            if ocr_text != "None":
                ocr_display_text = f"ocr:{ocr_text}"
            else:
                ocr_display_text = "ocr:None"
            
            if box is not None:
                # 在 box 上方显示 OCR 文字
                _draw_text_with_bg(img, ocr_display_text, (box.left, max(box.top - 10, 20)))
            else:
                # 如果没有 box，在图片左上角显示
                _draw_text_with_bg(img, ocr_display_text, (10, 30))
        
        # 保存截图
        ts = datetime.now().strftime('%y%m%d_%H%M%S_%f')
        cv2.imwrite(os.path.join(CLICK_DIR, f'c_{ts}.png'), img)
        
        # 只保留20张最新截图
        files = sorted([f for f in os.listdir(CLICK_DIR) if f.startswith('c_')], 
                      key=lambda x: os.path.getmtime(os.path.join(CLICK_DIR, x)), reverse=True)
        for f in files[20:]: 
            os.remove(os.path.join(CLICK_DIR, f))
    except Exception as e:
        logger.debug(f"保存调试截图失败: {e}")
