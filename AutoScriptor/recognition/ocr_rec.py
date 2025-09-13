import cv2
from paddleocr import PaddleOCR
from AutoScriptor.logger import logger
from AutoScriptor.utils.box import Box
from AutoScriptor.utils.constant import cfg
from fuzzywuzzy import fuzz
import threading
import time

class OCRManager:
    """全局OCR引擎管理器"""
    _instance = None
    _lock = threading.Lock()
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(OCRManager, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            with self._lock:
                if not self._initialized:
                    self.ocr_engine = None
                    self._initialized = True
                    self._start_async_init()

    def _start_async_init(self):
        def init_ocr():
            try:
                logger.info("正在初始化 PaddleOCR 引擎，这可能需要一些时间...")
                start_time = time.time()
                self.ocr_engine = PaddleOCR(
                    use_gpu=cfg["ocr"]["use_gpu"],
                    gpu_mem=8192,
                    enable_mkldnn=True,
                    use_angle_cls=False,
                    lang='ch',
                    ocr_version='PP-OCRv4',
                    show_log=False,
                )
                elapsed_time = time.time() - start_time
                logger.info(f"PaddleOCR 引擎初始化完成，耗时 {elapsed_time:.2f} 秒")
            except Exception as e:
                raise RuntimeError(f"PaddleOCR 引擎初始化失败: {e}")
        self._init_thread = threading.Thread(target=init_ocr, daemon=True)
        self._init_thread.start()

    def wait_for_initialization(self, timeout=30):
        if self._init_thread and self._init_thread.is_alive():
            logger.info("等待 PaddleOCR 引擎初始化...")
            self._init_thread.join(timeout)
            if self._init_thread.is_alive():
                logger.warning("PaddleOCR 引擎初始化超时")
                return False
        return self.ocr_engine is not None

    def get_ocr_engine(self):
        """获取OCR引擎实例（不阻塞）"""
        # 如果引擎未初始化完成则等待初始化
        if not self.wait_for_initialization():
            raise RuntimeError("OCR引擎未初始化完成")
        return self.ocr_engine

    def is_ready(self):
        return self.ocr_engine is not None

ocr_manager = OCRManager()

# 引入线程局部存储
_thread_local = threading.local()

def get_ocr_engine():
    """获取OCR引擎实例（不阻塞），为每个线程创建独立实例"""
    # 确保全局引擎已初始化完成
    if not ocr_manager.wait_for_initialization():
        raise RuntimeError("OCR引擎未初始化完成")
    # 如果该线程无本地实例或仍指向全局实例，则创建新的 PaddleOCR 实例
    if not hasattr(_thread_local, 'ocr_engine') or _thread_local.ocr_engine is ocr_manager.ocr_engine:
        # 复制与全局相同的初始化参数
        _thread_local.ocr_engine = PaddleOCR(
            use_gpu=cfg["ocr"]["use_gpu"],
            gpu_mem=8192,
            enable_mkldnn=True,
            use_angle_cls=False,
            lang='ch',
            ocr_version='PP-OCRv4',
            show_log=False,
        )
    return _thread_local.ocr_engine


# ===== 主OCR方法（推荐） =====

def ocr(frame,
        target_strings,
        confidence=0.8,
        preferred_box=None,
        stride=1,
        fuzzy_threshold=100
)->list[list[Box]]:
    """
    标准OCR识别方法，直接用PaddleOCR标准API。
    参数：
        frame: numpy数组，RGB图
        target_strings: 目标字符串列表
        preferred_box: Box对象，指定ROI
        stride: 降采样步长
        fuzzy_threshold: 匹配阈值
    返回：
        List[List[Box]]，所有匹配到的区域
        外层列表长度与target_strings相同，内层列表长度与target_strings中每个字符串匹配到的区域数量相同
    """
    engine = get_ocr_engine()
    if engine is None:  
        logger.error("OCR engine is not initialized. Cannot perform OCR.")
        return []
    if frame is None:
        logger.error("Input frame is None.")
        return []
    try:
        img = frame
        # ROI裁剪
        if preferred_box is None:
            preferred_box = Box(0, 0, img.shape[1], img.shape[0])
        img_roi = img[preferred_box.top: preferred_box.top + preferred_box.height,
                      preferred_box.left: preferred_box.left + preferred_box.width]
        # 降采样
        if stride > 1:
            img_for_ocr = img_roi[::stride, ::stride]
        else:
            img_for_ocr = img_roi
        result = engine.ocr(img_for_ocr, cls=False)
        found_boxes = [[] for _ in range(len(target_strings))]
        if result and result[0]:
            for line_idx, line_info in enumerate(result[0]):
                bounding_points = line_info[0]
                recognized_text, _ = line_info[1]
                # 使用全字符串相似度匹配，避免匹配包含目标串的更长文本
                for target_string in target_strings:
                    similarity_ratio = fuzz.ratio(recognized_text, target_string)
                    if target_string in recognized_text: similarity_ratio=100
                    if similarity_ratio >= fuzzy_threshold:
                        all_x_coords = [p[0] for p in bounding_points]
                        all_y_coords = [p[1] for p in bounding_points]
                        s_left = min(all_x_coords)
                        s_top = min(all_y_coords)
                        s_right = max(all_x_coords)
                        s_bottom = max(all_y_coords)
                        s_width = s_right - s_left
                        s_height = s_bottom - s_top
                        s_left, s_top, s_width, s_height = int(s_left), int(s_top), int(s_width), int(s_height)
                        final_left = preferred_box.left + s_left * stride
                        final_top = preferred_box.top + s_top * stride
                        final_bounding_box = Box(final_left, final_top, s_width * stride, s_height * stride)
                        found_boxes[target_strings.index(target_string)].append(final_bounding_box)
        elif result is None:
            logger.warning("OCR engine returned None. This might indicate an issue with the input image or engine.")
        return found_boxes
    except Exception as e:
        logger.error(f"Exception during OCR processing for '{target_string}': {e}", exc_info=True)
        return []
    

def ocr_for_box(haystack_frame, box):
    roi = haystack_frame[box.top:box.top + box.height, box.left:box.left + box.width]
    engine = get_ocr_engine()
    result = engine.ocr(roi, cls = False)
    recognized_text = ""
    if result and result[0]:
        for line_info in result[0]:
            recognized_text += line_info[1][0]
    return recognized_text
