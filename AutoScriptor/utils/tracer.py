"""
调试截图工具类：用于保存带标注的调试截图
"""
import os
import cv2
import numpy as np
from datetime import datetime
from typing import Optional
from AutoScriptor.utils.logger import logger
from AutoScriptor.core.targets import Target, BoxTarget
from AutoScriptor.utils.box import Box

try:
    from PIL import Image, ImageDraw, ImageFont
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False

# 调试截图目录
from AutoScriptor.utils.paths import get_logs_root
CLICK_DIR = str(get_logs_root() / 'debug_screenshot')
os.makedirs(CLICK_DIR, exist_ok=True)


def _draw_text_with_bg(img, text: str, position: tuple[int, int], font_scale: float = 0.6, thickness: int = 2):
    """在图片上绘制带背景的文字（支持中文）"""
    text_x, text_y = position
    text_color, bg_color = (255, 255, 255), (0, 0, 0)
    text = text[:40] + "..." if len(text) > 40 else text
    if any('\u4e00' <= c <= '\u9fff' for c in text) and _HAS_PIL:
        try:
            img_pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
            draw = ImageDraw.Draw(img_pil)
            font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", int(20 * font_scale)) if os.path.exists("C:/Windows/Fonts/msyh.ttc") else ImageFont.load_default()
            bbox = draw.textbbox((0, 0), text, font=font)
            w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
            draw.rectangle([(text_x - 2, text_y - h - 2), (text_x + w + 2, text_y + 2)], fill=bg_color)
            draw.text((text_x, text_y - h), text, fill=text_color, font=font)
            img[:] = cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)
            return h + 4
        except:
            pass
    font = cv2.FONT_HERSHEY_SIMPLEX
    (text_width, text_height), baseline = cv2.getTextSize(text, font, font_scale, thickness)
    cv2.rectangle(img, (text_x - 2, text_y - text_height - 2), (text_x + text_width + 2, text_y + baseline + 2), bg_color, -1)
    cv2.putText(img, text, (text_x, text_y), font, font_scale, text_color, thickness)
    return text_height + baseline + 4


def _draw_prior_clicks(img, prior_clicks: list[tuple[int, int]], final_color: tuple[int, int, int] = (0, 0, 255)):
    """绘制累积的 BoxTarget 点击轨迹，编号 1..N，颜色从浅红渐变到深红"""
    n = len(prior_clicks)
    if n == 0:
        return
    for i, pt in enumerate(prior_clicks):
        ratio = i / n  # 0 → 最浅, (n-1)/n → 次深 (最深留给当前 click)
        b = int(200 * (1 - ratio))
        g = int(200 * (1 - ratio))
        color = (b, g, 255)  # BGR: 浅红 (200,200,255) → 深红 (0,0,255)
        cv2.circle(img, pt, 8, color, -1)
        cv2.circle(img, pt, 8, (0, 0, 0), 1)
        label = str(i + 1)
        font = cv2.FONT_HERSHEY_SIMPLEX
        (tw, th), _ = cv2.getTextSize(label, font, 0.4, 1)
        cv2.putText(img, label, (pt[0] - tw // 2, pt[1] + th // 2), font, 0.4, (255, 255, 255), 1)


def _draw_info_bar(img, extra_info: dict):
    """在图像顶部绘制诊断信息条。click_mode 与 screenshot_src 不一致时显示红色警告。"""
    if not extra_info:
        return
    parts = [f"{k}:{v}" for k, v in extra_info.items()]
    click_mode = extra_info.get("click", "")
    src = extra_info.get("src", "")
    has_mismatch = click_mode and src and click_mode != src
    if has_mismatch:
        parts.insert(0, "MISMATCH!")
    info_text = "  ".join(parts)
    h, w = img.shape[:2]
    bar_h = 24
    bar_color = (0, 0, 200) if has_mismatch else (50, 50, 50)
    cv2.rectangle(img, (0, 0), (w, bar_h), bar_color, -1)
    cv2.putText(img, info_text, (4, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.48,
                (255, 255, 255), 1, cv2.LINE_AA)


def save_debug_screenshot(
    target: Target|tuple[Target, ...],
    screenshot,  # numpy array (cv2 image format)
    box: Optional[Box] = None, 
    pt: Optional[tuple[int, int]] = None,
    ocr_text: Optional[str] = None,
    prefix: str = "c",
    prior_clicks: Optional[list[tuple[int, int]]] = None,
    extra_info: Optional[dict] = None
):
    """
    保存调试截图，支持多种标注方式
    
    Args:
        target: 目标对象或目标对象元组，用于标注目标信息
        screenshot: 截图底板（numpy array，cv2 格式）
        box: 用于标注框选区域（可选）
        pt: 点击位置 (x, y)，当点击或长按时有效（可选）
        ocr_text: OCR 结果文字，格式为 "ocr:{识别结果}"（可选）
        prior_clicks: 两次截图保存之间累积的 BoxTarget 点击位置列表（可选）
    
    Examples:
        from AutoScriptor.utils.tracer import save_debug_screenshot
        from AutoScriptor.utils.box import Box
        
        # 点击截图
        save_debug_screenshot(target=T("确定"), screenshot=img, box=box, pt=(100, 200))
        
        # OCR 截图
        save_debug_screenshot(target=BoxTarget(Box(100, 100, 200, 50)), screenshot=img, box=Box(100, 100, 200, 50), ocr_text="ocr:购买")
        
        # 带诊断信息的截图（extra_info 会渲染到顶部信息条，click/src 不一致时红色高亮）
        save_debug_screenshot(target=T("确定"), screenshot=img, prefix="s",
                              extra_info={"click": "mumu", "src": "nemu", "until": "<lambda>", "elapsed": "30.1s"})
    """
    try:
        img = screenshot.copy()
        
        # 0-A. 绘制诊断信息条（mode/mismatch/until 等）
        if extra_info:
            _draw_info_bar(img, extra_info)
        
        # 0-B. 绘制累积的 BoxTarget 点击轨迹（浅红→深红，编号 1,2,3...）
        if prior_clicks:
            _draw_prior_clicks(img, prior_clicks)
        
        # 1. 绘制 Target 相关的标注（红色框和点击位置）
        if box is not None:
            right = box.left + box.width
            bottom = box.top + box.height
            cv2.rectangle(img, (box.left, box.top), (right, bottom), (0, 0, 255), 3)
            
            # 绘制 Target 信息文字（简化显示）
            if target is not None:
                t = target[0] if isinstance(target, tuple) else target
                target_str = f"T('{t.ui.text}')" if hasattr(t, 'ui') and hasattr(t.ui, 'text') and t.ui.text else f"Box[{box.left},{box.top}]"
                _draw_text_with_bg(img, target_str, (box.left, max(box.top - 10, 20)))
        
        # 2. 绘制点击位置（最深红，当前 click）
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
        
        # 保存截图：时间戳在前，类型前缀在后，便于按文件名排序即按时间排序
        ts = datetime.now().strftime('%y%m%d_%H%M%S_%f')
        cv2.imwrite(os.path.join(CLICK_DIR, f'{ts}_{prefix}.png'), img)
        
        # 按类型保留最新截图：c 30 + s 10 + e 5 = 45 张（兼容旧名 c_/s_/e_ 前缀）
        files = sorted([f for f in os.listdir(CLICK_DIR)], key=lambda x: os.path.getmtime(os.path.join(CLICK_DIR, x)), reverse=True)

        def _files_of_type(letter: str) -> list[str]:
            suf = f"_{letter}.png"
            pre = f"{letter}_"
            return [f for f in files if f.endswith(suf) or (f.startswith(pre) and f.endswith(".png"))]

        c_files = _files_of_type("c")
        s_files = _files_of_type("s")
        e_files = _files_of_type("e")
        keep = set(c_files[:30] + s_files[:10] + e_files[:5])
        files_to_remove = [f for f in files if f not in keep]
        for f in files_to_remove: 
            os.remove(os.path.join(CLICK_DIR, f))
    except Exception as e:
        logger.debug(f"保存调试截图失败: {e}")


def clear_debug_screenshots():
    """清空调试截图目录，在每个任务开始前调用，确保截图都属于当前任务"""
    try:
        for f in os.listdir(CLICK_DIR):
            fp = os.path.join(CLICK_DIR, f)
            if os.path.isfile(fp):
                os.remove(fp)
    except Exception as e:
        logger.debug(f"清理调试截图目录失败: {e}")
