import threading
import time

import cv2
import numpy as np
from fuzzywuzzy import fuzz

from AutoScriptor.recognition.ocr_runtime_config import (
    ocr_runtime_config,
    read_configured_ocr_runtime,
)
from AutoScriptor.utils.box import Box
from AutoScriptor.utils.logger import logger


OCR_MODEL_PROFILE = ocr_runtime_config.model_profile


def _load_ocr_runtime():
    """Import the heavyweight Paddle runtime only inside the OCR worker."""

    import paddle

    from AutoScriptor.recognition.paddle_ocr_compat import (
        CompatiblePaddleOCR,
        get_paddleocr_version,
    )

    return paddle, CompatiblePaddleOCR, get_paddleocr_version


def _create_ocr_engine():
    from AutoScriptor.recognition.paddle_ocr_compat import CompatiblePaddleOCR

    return CompatiblePaddleOCR(
        model_profile_name=OCR_MODEL_PROFILE,
        language="ch",
        use_gpu=ocr_runtime_config.use_gpu,
    )


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
                    self.initialization_error = None
                    self._initialized = True
                    self._start_async_init()

    def _start_async_init(self):
        def init_ocr():
            total_start_time = time.perf_counter()
            try:
                logger.info("正在后台导入 Paddle/PaddleOCR 运行时...")
                runtime_import_start_time = time.perf_counter()
                paddle_module, ocr_constructor, version_reader = _load_ocr_runtime()
                runtime_import_elapsed = time.perf_counter() - runtime_import_start_time
                logger.info(
                    "Paddle/PaddleOCR 运行时导入完成，耗时 %.2f 秒",
                    runtime_import_elapsed,
                )
                logger.info(
                    "Paddle 支持 GPU 编译: %s, 可用 GPU 数量: %s",
                    paddle_module.device.is_compiled_with_cuda(),
                    paddle_module.device.cuda.device_count(),
                )
                logger.info(
                    "正在初始化 PaddleOCR 引擎: package=%s, model=%s",
                    version_reader(),
                    OCR_MODEL_PROFILE,
                )
                engine_start_time = time.perf_counter()
                self.ocr_engine = ocr_constructor(
                    model_profile_name=OCR_MODEL_PROFILE,
                    language="ch",
                    use_gpu=ocr_runtime_config.use_gpu,
                )
                logger.info(
                    "PaddleOCR 初始化参数 model=%s, use_gpu=%s, 当前设备=%s",
                    OCR_MODEL_PROFILE,
                    ocr_runtime_config.use_gpu,
                    self.ocr_engine.device_name,
                )
                engine_elapsed = time.perf_counter() - engine_start_time
                total_elapsed = time.perf_counter() - total_start_time
                logger.info(
                    "PaddleOCR 引擎初始化完成，模型阶段耗时 %.2f 秒，总耗时 %.2f 秒",
                    engine_elapsed,
                    total_elapsed,
                )
            except Exception as error:
                self.initialization_error = RuntimeError(
                    f"PaddleOCR 引擎初始化失败: {error}"
                )
                logger.exception("%s", self.initialization_error)

        self._init_thread = threading.Thread(target=init_ocr, daemon=True)
        self._init_thread.start()

    def wait_for_initialization(self, timeout=30):
        if self._init_thread and self._init_thread.is_alive():
            logger.info("等待 PaddleOCR 引擎初始化...")
            self._init_thread.join(timeout)
            if self._init_thread.is_alive():
                logger.warning("PaddleOCR 引擎初始化超时")
                return False
        if self.initialization_error is not None:
            raise self.initialization_error
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


def get_ocr_runtime_status() -> dict:
    """Report persisted intent separately from the process-level OCR runtime."""

    configured_runtime = read_configured_ocr_runtime()
    engine = ocr_manager.ocr_engine
    initialization_error = ocr_manager.initialization_error
    return {
        "configured_use_gpu": configured_runtime.use_gpu,
        "runtime_use_gpu": ocr_runtime_config.use_gpu,
        "engine_use_gpu": getattr(engine, "use_gpu", None),
        "engine_device": getattr(engine, "device_name", None),
        "configured_model": configured_runtime.model_profile,
        "runtime_model": ocr_runtime_config.model_profile,
        "configured_digit_model": configured_runtime.digit_model_profile,
        "runtime_digit_model": ocr_runtime_config.digit_model_profile,
        "restart_required": configured_runtime != ocr_runtime_config,
        "engine_ready": ocr_manager.is_ready(),
        "initialization_error": (
            str(initialization_error) if initialization_error is not None else None
        ),
    }

# 引入线程局部存储
_thread_local = threading.local()

def get_ocr_engine():
    """获取OCR引擎实例（不阻塞），为每个线程创建独立实例"""
    # 确保全局引擎已初始化完成
    if not ocr_manager.wait_for_initialization():
        raise RuntimeError("OCR引擎未初始化完成")
    # 如果该线程无本地实例或仍指向全局实例，则创建新的 PaddleOCR 实例
    if not hasattr(_thread_local, 'ocr_engine') or _thread_local.ocr_engine is ocr_manager.ocr_engine:
        _thread_local.ocr_engine = _create_ocr_engine()
    return _thread_local.ocr_engine


# ===== 帧级 OCR 缓存 =====

_frame_cache_lock = threading.Lock()
_frame_cache: dict[tuple, dict] = {}
_FRAME_CACHE_MAX = 4


_SAMPLE_N = 7  # 7×7 = 49 均匀采样点
def _frame_fingerprint(img):
    """7×7 均匀网格采样指纹，覆盖全图，避免局部变化漏检。"""
    h, w = img.shape[:2]
    rs = np.linspace(0, h - 1, _SAMPLE_N, dtype=int)
    cs = np.linspace(0, w - 1, _SAMPLE_N, dtype=int)
    return (h, w, img[np.ix_(rs, cs)].tobytes())


def _raw_ocr_cached(img_for_ocr, ttl=0.5):
    """执行 PaddleOCR 并缓存原始结果；同一帧图像在 TTL 内复用上次结果。
    使用多条目字典缓存，避免不同 scale 图像互相踢掉对方的缓存。"""
    fp = _frame_fingerprint(img_for_ocr)
    now = time.time()
    with _frame_cache_lock:
        entry = _frame_cache.get(fp)
        if entry is not None and now - entry['ts'] < ttl:
            return entry['result']
    engine = get_ocr_engine()
    if engine is None:
        logger.error("OCR engine is not initialized.")
        return None
    result = engine.ocr(img_for_ocr, cls=False)
    with _frame_cache_lock:
        _frame_cache[fp] = {'ts': now, 'result': result}
        if len(_frame_cache) > _FRAME_CACHE_MAX:
            oldest_key = min(_frame_cache, key=lambda k: _frame_cache[k]['ts'])
            del _frame_cache[oldest_key]
    return result


_fallback_log_ts = 0.0
_FALLBACK_LOG_INTERVAL = 2.0

# ===== 主OCR方法（推荐） =====

def ocr(frame,
        target_strings,
        confidence=0.8,
        preferred_box=None,
        stride=1,
        fuzzy_threshold=100,
        scale=1.0
)->list[list[Box]]:
    """
    标准OCR识别方法，直接用PaddleOCR标准API。
    参数：
        frame: numpy数组，RGB图
        target_strings: 目标字符串列表
        preferred_box: Box对象，指定ROI
        stride: 降采样步长
        scale: 缩放因子，用于调整图像大小，加快识别速度
        fuzzy_threshold: 匹配阈值
    返回：
        List[List[Box]]，所有匹配到的区域
        外层列表长度与target_strings相同，内层列表长度与target_strings中每个字符串匹配到的区域数量相同

    当 scale 不为 1.0 且本轮未匹配到任何目标（含引擎返回 None）时，自动以 scale=1.0 再执行一次。
    """
    def _iter_substring_spans(haystack: str, needle: str):
        if not haystack or not needle:
            return
        start = 0
        while True:
            idx = haystack.find(needle, start)
            if idx < 0:
                break
            yield idx, idx + len(needle)
            start = idx + len(needle)

    def _subbox_by_span(left: int, top: int, width: int, height: int, full_len: int, span: tuple[int, int]):
        """把 (left,top,width,height) 按 span 在 full_len 中的位置做水平等比例切分"""
        s, e = span
        if full_len <= 0:
            return Box(left, top, width, height)
        # 限制在 [0, full_len]
        s = max(0, min(full_len, s))
        e = max(s, min(full_len, e))
        x0 = left + int(width * (s / full_len))
        x1 = left + int(width * (e / full_len))
        return Box(x0, top, max(1, x1 - x0), height)

    target_string = None
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
        # apply scaling for speed/accuracy tradeoff
        if scale != 1.0:
            img_roi = cv2.resize(img_roi, (int(img_roi.shape[1] * scale), int(img_roi.shape[0] * scale)), interpolation=cv2.INTER_LINEAR)
        # 降采样
        if stride >= 1:
            img_for_ocr = img_roi[::stride, ::stride]
        else:
            img_for_ocr = img_roi
        result = _raw_ocr_cached(img_for_ocr)
        found_boxes = [[] for _ in range(len(target_strings))]
        if result and result[0]:
            for line_idx, line_info in enumerate(result[0]):
                bounding_points = line_info[0]
                recognized_text, _ = line_info[1]
                for target_string in target_strings:
                    similarity_ratio = fuzz.ratio(recognized_text, target_string)
                    # 关键：只要目标串被包含，就视为命中（项目默认 fuzzy_threshold=100，否则会大量漏检）
                    if target_string and target_string in (recognized_text or ""):
                        similarity_ratio = 100
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
                        # adjust coordinates to original scale
                        factor = stride / scale
                        final_left = preferred_box.left + int(s_left * factor)
                        final_top = preferred_box.top + int(s_top * factor)
                        final_width = max(1, int(s_width * factor))
                        final_height = max(1, int(s_height * factor))
                        full_len = len(recognized_text or "")
                        # 关键：当 OCR 把多个词粘连成一个字符串时，按子串位置等比例切分返回更准确的子Box
                        if (recognized_text or "") != target_string and target_string and target_string in (recognized_text or "") and full_len > 0:
                            for span in _iter_substring_spans(recognized_text, target_string):
                                found_boxes[target_strings.index(target_string)].append(
                                    _subbox_by_span(final_left, final_top, final_width, final_height, full_len, span)
                                )
                        else:
                            found_boxes[target_strings.index(target_string)].append(
                                Box(final_left, final_top, final_width, final_height)
                            )
        if (
            scale != 1.0
            and len(target_strings) > 0
            and all(len(b) == 0 for b in found_boxes)
        ):
            global _fallback_log_ts
            _now = time.time()
            if _now - _fallback_log_ts >= _FALLBACK_LOG_INTERVAL:
                logger.debug("OCR scale=%s 未匹配任何目标，回退 scale=1.0 重试", scale)
                _fallback_log_ts = _now
            return ocr(
                frame,
                target_strings,
                confidence,
                preferred_box,
                stride,
                fuzzy_threshold,
                scale=1.0,
            )
        if result is None:
            logger.warning("OCR engine returned None. This might indicate an issue with the input image or engine.")
        return found_boxes
    except Exception as e:
        logger.error(f"Exception during OCR processing for '{target_string}': {e}", exc_info=True)
        return []
    

def ocr_for_box(haystack_frame, box, *, ttl: float = 0.5):
    roi = haystack_frame[box.top:box.top + box.height, box.left:box.left + box.width]
    result = _raw_ocr_cached(roi, ttl=ttl)
    recognized_text = ""
    if result and result[0]:
        for line_info in result[0]:
            recognized_text += line_info[1][0]
    return recognized_text
