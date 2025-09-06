
import collections
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import cv2

from AutoScriptor.recognition.img_rec import imgOnScreen
from AutoScriptor.recognition.ocr_rec import ocr
from AutoScriptor.utils.box import Box



def locate_on_screen(haystack_frame, targets, confidence=0.8, pf_boxes=None, colors=None):
    """
    在屏幕上定位多个目标
    
    Args:
        haystack_frame: 屏幕帧图像
        targets: 目标列表，可以是图像、文本或Box对象
        confidence: 置信度阈值
        pf_boxes: 偏好区域列表
        colors: 颜色筛选列表
    
    Returns:
        list[None|list[Box]]
        外层列表长度与targets相同，内层列表长度与targets中每个目标匹配到的区域数量相同
        当没找到，对应元素返回None
    """
    # 1. 分离img和text,并记录位置，方便后续组装list[Box]
    img_targets, text_targets, box_targets = [], [], []
    img_pf_boxes, text_pf_boxes = [], []
    img_colors, text_colors = [], []
    idfs = []
    for i, target in enumerate(targets):
        if isinstance(target, str):
            text_targets.append(target)
            text_pf_boxes.append(pf_boxes[i])
            text_colors.append(colors[i])
            idfs.append("t"+str(len(text_targets)-1))
        elif isinstance(target, Box):
            box_targets.append(target)
            idfs.append("b"+str(len(box_targets)-1))
        else:
            img_targets.append(target)
            img_pf_boxes.append(pf_boxes[i])
            img_colors.append(colors[i])
            idfs.append("i"+str(len(img_targets)-1))
    if img_targets and text_targets or box_targets:
        img_boxes = locate_on_screen(haystack_frame, img_targets, confidence, img_pf_boxes, img_colors) if img_targets else []
        text_boxes = locate_on_screen(haystack_frame, text_targets, confidence, text_pf_boxes, text_colors) if text_targets else []
        box_boxes = [[box_targets[i]] for i in range(len(box_targets))]
        boxes = [img_boxes[int(idfs[i][1:])] if idfs[i][0]=="i" else text_boxes[int(idfs[i][1:])] if idfs[i][0]=="t" else box_boxes[int(idfs[i][1:])] for i in range(len(targets))]
        return boxes
    
    # 2. 裁剪ROI
    def get_roi(preferred_box):
        if preferred_box:
            return haystack_frame[preferred_box.top:preferred_box.top + preferred_box.height,
                                preferred_box.left:preferred_box.left + preferred_box.width]
        else:
            return haystack_frame
    roi_dict = {pf_box: get_roi(pf_box) for pf_box in set(pf_boxes)}
    # 如果ROI只有一个，则直接使用，否则全图识别再作筛选
    if len(roi_dict.keys()) == 1:
        roi = next(iter(roi_dict.values()))
    else: 
        roi = haystack_frame
    # 3. 全图或ROI识别
    if isinstance(targets[0], str):
        res = ocr(roi, targets, confidence, None)
        assert res is not None, "ocr omit None！"
    else:
        res = imgOnScreen(roi, targets, confidence=confidence)
        assert res is not None, "imgOnScreen omit None！"
    # 4. 筛选
    # 4.0 调到全图坐标
    def to_full_frame(box, preferred_box):
        return Box(box.left + preferred_box.left,
                    box.top + preferred_box.top,
                    box.width,
                    box.height)
    # 只有当用roi扫描才需要恢复全图坐标
    if len(roi_dict.keys()) == 1:
        res = [[to_full_frame(box, pf_boxes[i]) for box in res[i]] for i in range(len(targets))]
    # 4.1 筛选范围,判断是否在对应的prefer_box里
    for i, boxes in enumerate(res):
        for box in boxes:
            if not box.is_in(pf_boxes[i]):
                res[i].remove(box)
        if not res[i]: res[i] = None
        
    # 4.2 筛选颜色
    for i, boxes in enumerate(res):
        if colors[i] and boxes:   
            res_color = [get_box_color(haystack_frame, b) for b in boxes]
            if not colors[i] in res_color: res[i] = None
            else: res[i] = [res[i][j] for j in range(len(res[i])) if res_color[j] == colors[i]]

    return res

def get_box_color(haystack_frame, box):
    """
    【最终修正版 v2.1】修复了UnboundLocalError变量未定义错误。

    Args:
        haystack_frame: 屏幕帧图像 (BGR格式)
        box: Box对象，指定要分析的区域

    Returns:
        str: 主要颜色名称
    """
    import cv2
    import numpy as np

    # 1. 裁剪ROI区域
    roi = haystack_frame[box.top:box.top + box.height, 
                         box.left:box.left + box.width]
    
    if roi.size == 0:
        return "区域无效"

    # 2. 转换为HSV格式
    hsv_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

    # 3. 创建遮罩，过滤掉“非彩色”像素
    lower_bound = np.array([0, 50, 50])
    upper_bound = np.array([180, 255, 255])
    mask = cv2.inRange(hsv_roi, lower_bound, upper_bound)

    # 4. 根据是否存在有效像素来决定如何获取HSV值
    if mask.any():
        # 如果有彩色像素，计算色相直方图
        hist = cv2.calcHist([hsv_roi], [0], mask, [180], [0, 180])
        h_main = np.argmax(hist)
        
        # --- FIX: Renamed s_mean/v_mean to s_main/v_main for consistency ---
        s_main = np.mean(hsv_roi[mask > 0][:, 1])
        v_main = np.mean(hsv_roi[mask > 0][:, 2])

    else:
        # 如果没有彩色像素（图像是纯黑/白/灰），则根据平均亮度判断
        h_main = 0 
        s_main = 0
        v_main = np.mean(hsv_roi[:, :, 2])

    # 5. 根据HSV值获取颜色名称
    def get_hsv_color_name(h_value, s_value, v_value):
        if s_value <= 50:
            if v_value <= 50: return "黑色"
            elif v_value <= 220: return "灰色"
            else: return "白色"

        if (0 <= h_value <= 10) or (156 <= h_value <= 180): return "红色"
        elif 11 <= h_value <= 25: return "橙色"
        elif 26 <= h_value <= 34: return "黄色"
        elif 35 <= h_value <= 77: return "绿色"
        elif 78 <= h_value <= 99: return "青色"
        elif 100 <= h_value <= 124: return "蓝色"
        elif 125 <= h_value <= 155: return "紫色"
        
        return "其他"

    color_name = get_hsv_color_name(h_main, s_main, v_main)
    return color_name