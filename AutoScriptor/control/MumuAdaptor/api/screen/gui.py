#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time : 2024/7/30 下午3:06
# @Author : wlkjyy
# @File : gui.py
# @Software: PyCharm
import cv2

from AutoScriptor.recognition.locate import _load_cv2, _locateAll_opencv
from AutoScriptor.recognition.ocr_rec import get_ocr_engine

class Gui:

    def __init__(self, utils):
        self.utils = utils

    def locateOnScreen(self, haystack_frame, target, confidence=0.8, grayscale=None, preferred_box=None):
        if isinstance(target, str):
            return self.ocrOnScreen(haystack_frame, target, confidence, grayscale, preferred_box)
        else:
            return self.imgOnScreen(haystack_frame, target, confidence, grayscale, preferred_box)

    def imgOnScreen(self, haystack_frame, needle_image, confidence=0.8, grayscale=None, preferred_box=None):
        """
            在屏幕上查找图片
        :param haystack_frame: 屏幕帧
        :param needle_image: 图片
        :param confidence: 置信度
        :param grayscale: 灰度值找图
        :return:
        """
        needle_image = _load_cv2(needle_image)
        haystack_frame = _load_cv2(haystack_frame)

        for r in _locateAll_opencv(needle_image, haystack_frame, confidence=confidence):
            return r

        return False

    def ocr(self, haystack_frame):
        import cv2
        import numpy as np
        cv_img = cv2.cvtColor(np.array(haystack_frame), cv2.COLOR_RGB2BGR)
        result = self.ocrOnScreen(cv_img, None, confidence=0.8, grayscale=None, preferred_box=None, use_cpu=None)
        res = [r[1][0] for r in result[0]]
        return res
    
    def ocrOnScreen(self, haystack_frame, target_string, confidence=0.8, grayscale=None, preferred_box=None, use_cpu=None):
        """
            在屏幕上查找文字（快速模式可选 CPU/GPU）
        :param haystack_frame: 屏幕帧
        :param target_string: 目标文字
        :param confidence: 置信度，对应 fuzzy_threshold(0-1)
        :param use_cpu: 是否使用 CPU 快速识别，默认读取配置
        """
        import cv2
        import numpy as np
        
        # 转换图像格式
        cv_img = cv2.cvtColor(np.array(haystack_frame), cv2.COLOR_RGB2BGR)
        # 裁剪 ROI
        if preferred_box is not None:
            x0, y0, w0, h0 = preferred_box.left, preferred_box.top, preferred_box.width, preferred_box.height
            img_roi = cv_img[y0:y0+h0, x0:x0+w0]
            offset_x, offset_y = x0, y0
        else:
            img_roi = cv_img
            offset_x, offset_y = 0, 0
            w0, h0 = cv_img.shape[1], cv_img.shape[0]

        # 使用全局 OCR 引擎（只初始化一次）
        ocr_engine = get_ocr_engine()
        if ocr_engine is None:
            return False
        # 执行 ROI OCR 识别
        result = ocr_engine.ocr(img_roi, cls=True)
        
        if result and result[0]:
            for line in result[0]:
                box = line[0]
                text, conf = line[1]
                if text == target_string and conf >= confidence:
                    # 计算边界框（相对于 ROI）
                    xs = [int(p[0]) for p in box]
                    ys = [int(p[1]) for p in box]
                    x1_roi, y1_roi = min(xs), min(ys)
                    x2_roi, y2_roi = max(xs), max(ys)
                    width = x2_roi - x1_roi
                    height = y2_roi - y1_roi
                    # 转换回原始图像坐标
                    x1, y1 = x1_roi + offset_x, y1_roi + offset_y
                    return (x1, y1, width, height)

        # ROI识别未命中，尝试全图OCR，但仅返回在ROI内的结果
        full_result = ocr_engine.ocr(cv_img, cls=True)
        if full_result and full_result[0]:
            for line in full_result[0]:
                box_full = line[0]
                text_full, conf_full = line[1]
                if text_full == target_string and conf_full >= confidence:
                    xs_full = [int(p[0]) for p in box_full]
                    ys_full = [int(p[1]) for p in box_full]
                    x1_full, y1_full = min(xs_full), min(ys_full)
                    x2_full, y2_full = max(xs_full), max(ys_full)
                    width_full = x2_full - x1_full
                    height_full = y2_full - y1_full
                    # 确保结果在偏好区域内
                    if x1_full >= offset_x and y1_full >= offset_y and x2_full <= offset_x + w0 and y2_full <= offset_y + h0:
                        return (x1_full, y1_full, width_full, height_full)
        return False

    def center(self, box):
        """
            获取中心点
        :param box: Box
        :return:
        """
        return int(box.left + box.width / 2), int(box.top + box.height / 2)

    def locateCenterOnScreen(self, haystack_frame, needle_image, confidence=0.8, grayscale=None):
        """
            在屏幕上查找图片
        :param haystack_frame: 屏幕帧
        :param needle_image: 图片
        :param confidence: 置信度
        :param grayscale: 灰度值找图
        :return:
        """
        needle_image = _load_cv2(needle_image)
        haystack_frame = _load_cv2(haystack_frame)

        for r in _locateAll_opencv(needle_image, haystack_frame, confidence=confidence):
            return self.center(r)

        return False

    def locateAllOnScreen(self, haystack_frame, needle_image, confidence=0.8, grayscale=None):
        """
            在屏幕上查找所有图片
        :param haystack_frame: 屏幕帧
        :param needle_image: 图片
        :param confidence: 置信度
        :param grayscale: 灰度值找图
        :return:
        """
        arr = []
        needle_image = _load_cv2(needle_image)
        haystack_frame = _load_cv2(haystack_frame)

        for r in _locateAll_opencv(needle_image, haystack_frame, confidence=confidence):
            arr.append(r)

        return arr

    def save(self, frame, path):
        """
            保存帧
        :param path: 路径
        :return:
        """
        cv2.imwrite(path, frame)
