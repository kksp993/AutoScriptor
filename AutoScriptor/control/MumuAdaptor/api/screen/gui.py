#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time : 2024/7/30 下午3:06
# @Author : wlkjyy
# @File : gui.py
# @Software: PyCharm
import json
import time

import cv2
import numpy
from adbutils import adb
import threading
from AutoScriptor.utils.box import Box
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

        for r in _locateAll_opencv(needle_image, haystack_frame, confidence=confidence, grayscale=None):
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
        cv2.imwrite("img_roi.png", img_roi)

        # 使用全局 OCR 引擎（只初始化一次）
        ocr_engine = get_ocr_engine()
        if ocr_engine is None:
            return False
        # 执行 ROI OCR 识别
        result = ocr_engine.predict(img_roi, cls=True)
        
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

        for r in _locateAll_opencv(needle_image, haystack_frame, confidence=confidence, grayscale=None):
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

        for r in _locateAll_opencv(needle_image, haystack_frame, confidence=confidence, grayscale=None):
            arr.append(r)

        return arr

    def save(self, frame, path):
        """
            保存帧
        :param path: 路径
        :return:
        """
        cv2.imwrite(path, frame)

def _load_cv2(img, grayscale=None):
    """
    TODO
    """
    # load images if given filename, or convert as needed to opencv
    # Alpha layer just causes failures at this point, so flatten to RGB.
    # RGBA: load with -1 * cv2.CV_LOAD_IMAGE_COLOR to preserve alpha
    # to matchTemplate, need template and image to be the same wrt having alpha
    if grayscale is None:
        grayscale = False
    if isinstance(img, str):
        # The function imread loads an image from the specified file and
        # returns it. If the image cannot be read (because of missing
        # file, improper permissions, unsupported or invalid format),
        # the function returns an empty matrix
        # http://docs.opencv.org/3.0-beta/modules/imgcodecs/doc/reading_and_writing_images.html
        if grayscale:
            img_cv = cv2.imread(img, cv2.IMREAD_GRAYSCALE)
        else:
            img_cv = cv2.imread(img, cv2.IMREAD_COLOR)
        if img_cv is None:
            raise IOError(
                "Failed to read %s because file is missing, "
                "has improper permissions, or is an "
                "unsupported or invalid format" % img
            )
    elif isinstance(img, numpy.ndarray):
        # don't try to convert an already-gray image to gray
        if grayscale and len(img.shape) == 3:  # and img.shape[2] == 3:
            img_cv = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        else:
            img_cv = img
    elif hasattr(img, 'convert'):
        # assume its a PIL.Image, convert to cv format
        img_array = numpy.array(img.convert('RGB'))
        img_cv = img_array[:, :, ::-1].copy()  # -1 does RGB -> BGR
        if grayscale:
            img_cv = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
    else:
        raise TypeError(f'expected an image filename, OpenCV numpy array, or PIL image, got {img} = {type(img)} which is not supported')
    return img_cv


def _locateAll_opencv(needleImage, haystackImage, grayscale=None, limit=10000, region=None, step=1, confidence=0.8):
    """
    TODO - rewrite this
        faster but more memory-intensive than pure python
        step 2 skips every other row and column = ~3x faster but prone to miss;
            to compensate, the algorithm automatically reduces the confidence
            threshold by 5% (which helps but will not avoid all misses).
        limitations:
          - OpenCV 3.x & python 3.x not tested
          - RGBA images are treated as RBG (ignores alpha channel)
    """
    if grayscale is None:
        grayscale = False

    confidence = float(confidence)

    needleImage = _load_cv2(needleImage, grayscale)
    needleHeight, needleWidth = needleImage.shape[:2]
    haystackImage = _load_cv2(haystackImage, grayscale)

    if region:
        haystackImage = haystackImage[region[1]: region[1] + region[3], region[0]: region[0] + region[2]]
    else:
        region = (0, 0)  # full image; these values used in the yield statement
    if haystackImage.shape[0] < needleImage.shape[0] or haystackImage.shape[1] < needleImage.shape[1]:
        # avoid semi-cryptic OpenCV error below if bad size
        raise ValueError('needle dimension(s) exceed the haystack image or region dimensions')

    if step == 2:
        confidence *= 0.95
        needleImage = needleImage[::step, ::step]
        haystackImage = haystackImage[::step, ::step]
    else:
        step = 1

    # get all matches at once, credit: https://stackoverflow.com/questions/7670112/finding-a-subimage-inside-a-numpy-image/9253805#9253805
    result = cv2.matchTemplate(haystackImage, needleImage, cv2.TM_CCOEFF_NORMED)
    match_indices = numpy.arange(result.size)[(result > confidence).flatten()]
    matches = numpy.unravel_index(match_indices[:limit], result.shape)

    if len(matches[0]) == 0:
        return
    # use a generator for API consistency:
    matchx = matches[1] * step + region[0]  # vectorized
    matchy = matches[0] * step + region[1]
    for x, y in zip(matchx, matchy):
        yield Box(x, y, needleWidth, needleHeight)
