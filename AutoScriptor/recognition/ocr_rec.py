import cv2
from paddleocr import PaddleOCR
from logzero import logger
from AutoScriptor.utils.box import Box
from AutoScriptor.utils.constant import cfg
from fuzzywuzzy import fuzz
import threading
import paddle
import time
OCR_VERSION = 'PP-OCRv4'
# OCR_VERSION = 'PP-OCRv5'
# OCR_VERSION = 'PP-OCRv5_server_rec'

ocr_config = {
    "use_gpu":cfg["ocr.use_gpu"],
    "gpu_mem":4096,
    "enable_mkldnn":True,
    "use_angle_cls":False,
    "lang":"ch",
    "ocr_version":OCR_VERSION,
    "show_log":False,
    # "det_db_thresh":0.15,
    # "det_db_box_thresh":0.2,
    # "drop_score":0.2,
    # "scales":[0.5,1.0,1.5],
}

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
                # 打印 PaddleGPU 支持情况和可用 GPU 数量
                logger.info(f"Paddle 支持 GPU 编译: {paddle.device.is_compiled_with_cuda()}, 可用 GPU 数量: {paddle.device.cuda.device_count()}")
                logger.info("正在初始化 PaddleOCR 引擎，这可能需要一些时间...")
                start_time = time.time()
                self.ocr_engine = PaddleOCR(
                    **ocr_config,
                )
                logger.info(f"PaddleOCR 初始化参数 use_gpu={cfg['ocr.use_gpu']}, 当前设备={paddle.get_device()}")
                elapsed_time = time.time() - start_time
                logger.info(f"PaddleOCR 引擎初始化完成，耗时 {elapsed_time:.2f} 秒")
                # 预热一次，避免首次调用开销影响后续性能
                try:
                    import numpy as np
                    warm = (np.zeros((64, 64, 3), dtype='uint8'))
                    _ = self.ocr_engine.ocr(warm, cls=False)
                except Exception:
                    pass
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

def get_ocr_engine():
    """获取全局 OCR 引擎实例（阻塞等待初始化完成一次）。
    说明：为避免在 WebUI 多线程环境下重复实例化造成的性能与内存开销，这里统一复用全局引擎。
    """
    if not ocr_manager.wait_for_initialization():
        raise RuntimeError("OCR引擎未初始化完成")
    return ocr_manager.ocr_engine


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
        # 降采样/缩放：对较大 ROI 做一次性等比例下采样，减少 OCR 计算量
        img_for_ocr = img_roi
        try:
            h, w = img_roi.shape[:2]
            # 目标最长边不超过 1280，再结合 stride 做网格采样
            max_side = 1280
            scale = 1.0
            if max(h, w) > max_side:
                scale = max_side / float(max(h, w))
            if stride > 1:
                # 将 stride 折合进缩放比例，避免双重采样失真
                scale = scale * (1.0 / stride)
            if scale < 1.0:
                import cv2
                new_w, new_h = max(1, int(w * scale)), max(1, int(h * scale))
                img_for_ocr = cv2.resize(img_roi, (new_w, new_h), interpolation=cv2.INTER_AREA)
            elif stride > 1:
                img_for_ocr = img_roi[::stride, ::stride]
        except Exception:
            # 回退到原图
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
                        # 根据缩放/stride 还原到原 ROI 坐标
                        scale_x = float(img_roi.shape[1]) / float(img_for_ocr.shape[1])
                        scale_y = float(img_roi.shape[0]) / float(img_for_ocr.shape[0])
                        final_left = preferred_box.left + int(s_left * scale_x)
                        final_top = preferred_box.top + int(s_top * scale_y)
                        final_bounding_box = Box(final_left, final_top, int(s_width * scale_x), int(s_height * scale_y))
                        found_boxes[target_strings.index(target_string)].append(final_bounding_box)
        elif result is None:
            logger.warning("OCR engine returned None. This might indicate an issue with the input image or engine.")
        return found_boxes
    except Exception as e:
        logger.error(f"Exception during OCR processing for '{target_string}': {e}", exc_info=True)
        return []
    

def ocr_for_box(haystack_frame, box):
    roi = haystack_frame[box.top:box.top + box.height, box.left:box.left + box.width]
    # 对较大 ROI 做一次下采样以提升速度
    try:
        import cv2
        h, w = roi.shape[:2]
        max_side = 1280
        if max(h, w) > max_side:
            scale = max_side / float(max(h, w))
            new_w, new_h = max(1, int(w * scale)), max(1, int(h * scale))
            roi_resized = cv2.resize(roi, (new_w, new_h), interpolation=cv2.INTER_AREA)
        else:
            roi_resized = roi
    except Exception:
        roi_resized = roi
    engine = get_ocr_engine()
    result = engine.ocr(roi_resized, cls = False)
    recognized_text = ""
    if result and result[0]:
        for line_info in result[0]:
            recognized_text += line_info[1][0]
    return recognized_text
