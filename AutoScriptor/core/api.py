import os
import sys
import threading
import time
import traceback
import getpass
import cv2
from AutoScriptor.control.MumuAdaptor.constant import AndroidKey
from AutoScriptor.core.control import MixControl
from AutoScriptor.core.targets import Target, B,I,T,V
from AutoScriptor.core.targets import ImageTarget,TextTarget,BoxTarget,VLMTarget
from AutoScriptor.core.locate_dispatch import has_handler, dispatch_locate
from AutoScriptor.recognition.ocr_rec import ocr_for_box
from AutoScriptor.recognition.rec import get_box_color
from AutoScriptor.utils.box import Box, b2p
from AutoScriptor.utils.logger import log_flush, setup_task_aware_logging
from AutoScriptor.utils.tracer import save_debug_screenshot
from AutoScriptor.utils.logger import logger, setup_logfile
from AutoScriptor.utils.constant import cfg
from AutoScriptor.control.MumuAdaptor.mumu import Mumu
from AutoScriptor.utils.edit_img import launch_editor
from AutoScriptor.utils.cancel import check_cancel_raise, cancellable_sleep

def ensure_all_environment_ready():
    # 初始化编排器
    logger.info("编排器初始化开始...")
    import os
    from datetime import datetime
    log_dir = os.path.join(os.getcwd(), 'logs', 'log')
    os.makedirs(log_dir, exist_ok=True)
    timestamp = datetime.now().strftime('%y%m%d_%H%M%S')
    setup_logfile(os.path.join(log_dir, f"[{timestamp}].log"))
    setup_task_aware_logging()
    selected_emulator_index = cfg["emulator"]["index"]
    adb_addr = cfg["emulator"]["adb_addr"]
    app_to_start = cfg["app"]["app_to_start"]
    return selected_emulator_index, adb_addr, app_to_start

def ensure_app_running(selected_emulator_index, adb_addr, app_to_start):
    """
    确保模拟器和应用都在运行。若模拟器未启动则先启动模拟器，再启动应用。
    
    Args:
        package: 应用包名，默认使用 cfg 中配置的 app_to_start
        wait: 启动模拟器后等待就绪的秒数，默认 15s
    
    Returns:
        bool: True 表示应用已在运行或已成功启动
    """
    mumu_manager_path = cfg["emulator"]["emu_path"]
    print(f"selected_emulator_index: {selected_emulator_index}")
    print(f"adb_addr: {adb_addr}")
    print(f"app_to_start: {app_to_start}")
    print(f"mumu_manager_path: {mumu_manager_path}")
    mumu = Mumu().select(selected_emulator_index)
    mumu.power.start(app_to_start) if cfg["app"]["auto_start"] else None
    logger.info("模拟器启动完成")
    mixctrl = MixControl(mumu, serial=adb_addr)
    logger.info("编排器初始化完成.")
    success = False
    intervals = [1, 2, 3, 4, 5, 5, 5, 5]
    for i, interval in enumerate(intervals, 1):
        click_result = {}
        def _click_test():
            try:
                mixctrl.click(2000, 0)
                click_result['ok'] = True
            except Exception as e:
                click_result['error'] = e
                logger.error(f"测试点击(0,0)，第{i}次尝试，第{interval}秒后重试, 错误信息: {e}")
        t = threading.Thread(target=_click_test)
        t.daemon = True
        t.start()
        t.join(5)
        if not t.is_alive() and 'error' not in click_result:
            success = True
        if success:
            logger.info("测试点击(0,0)成功，模拟器响应正常。")
            break
        logger.error(f"测试点击(0,0)，第{i}次尝试，第{interval}秒后重试")
        time.sleep(interval)
    if not success:
        logger.error("多次点击测试失败，模拟器无响应")
        raise RuntimeError("ensure_app_running: 多次点击测试失败，模拟器无响应，请检查模拟器状态")
    mixctrl.window.hidden() if cfg["app"]["run_in_background"] else None
    return mixctrl, mumu


mixctrl = None
mumu = None
_box_click_trace: list[tuple[int, int]] = []


def _diag_info(**extra) -> dict:
    """构建诊断信息 dict，供 save_debug_screenshot 的 extra_info 参数使用。
    自动附加 click mode 与 screenshot source，在两者不一致时信息条会红色高亮。"""
    info = {}
    if mixctrl is not None and hasattr(mixctrl, 'mode'):
        info["click"] = mixctrl.mode
        info["src"] = "nemu"
    info.update(extra)
    return info


def init():
    """Explicitly initialize environment and device controls.

    Must be called once before any API function (click, locate, ...) is used.
    """
    global mixctrl, mumu
    idx, addr, app = ensure_all_environment_ready()
    mixctrl, mumu = ensure_app_running(idx, addr, app)
    # Propagate live references to package-level namespaces so that
    # ``from AutoScriptor import mixctrl`` picks up the real object
    # when the import happens *after* init().
    import AutoScriptor as _pkg
    import AutoScriptor.core as _core_pkg
    _pkg.mixctrl = mixctrl
    _pkg.mumu = mumu
    _core_pkg.mixctrl = mixctrl


def ui_idx(target: Target|list[Target]|tuple[Target, ...], timeout: float=0)->int:
    target = [t for t in target]
    boxes = locate(target, timeout, assure_stable=False)
    if not first(boxes): return -1
    return index(boxes)


def ui_T(target: Target|list[Target]|tuple[Target, ...], timeout: float=0, *, screenshot=None)->bool:
    boxes = locate(target, timeout, assure_stable=False, screenshot=screenshot)
    if isinstance(target, list):
        return full(boxes)
    else:
        return first(boxes) is not None
    

def ui_F(target: Target|list[Target]|tuple[Target, ...], timeout: float=0)->bool:
    return not ui_T(target, timeout)

def first(box_matrixes: list[list[Box]|list[Box]|None])->Box|None:
    """返回第一个找到的Box，如果没有找到返回None"""
    if not box_matrixes: return None
    if not any(isinstance(box_matrix, list) for box_matrix in box_matrixes): return first([box_matrixes])
    for box_matrix in box_matrixes:
        if not box_matrix: continue
        for box in box_matrix:
            if box: return box
    return None

def simple(box_matrixes: list[list[Box]]|list[Box]|None)->list[Box]:
    if not box_matrixes: return None
    for i in range(len(box_matrixes)):
        if box_matrixes[i] and len(box_matrixes[i]) > 1:
            box_matrixes[i] = box_matrixes[i][:1]
    return [b[0] if b else None for b in box_matrixes]

def full(box_matrixes: list[list[Box]])->bool:
    for i in range(len(box_matrixes)):
        if not box_matrixes[i]: return False
    return True

def count(box_matrixes: list[list[Box]])->list[int]:
    return [0 if not box_matrix else len(box_matrix) if not isinstance(box_matrix, Box) else 1 for box_matrix in box_matrixes]

def index(box_matrixes: list[list[Box]])-> int:
    if not box_matrixes: return -1
    for i, box in enumerate(box_matrixes):
        if box: return i
    return -1


def stable(boxes1: list[list[Box]], boxes2: list[list[Box]])->bool:
    if not boxes1 or not boxes2: return False
    assert len(boxes1) == len(boxes2)
    for i in range(len(boxes1)):
        list1, list2 = boxes1[i], boxes2[i]
        if not list1 or not list2: continue
        for b1, b2 in zip(list1, list2):
            if not b1.sim_box(b2): return False
        if len(list1) != len(list2): return False
    return True

def switch_base(base: str):
    if base == "mumu":
        mixctrl.switch_to_mumu()
    elif base == "nemu":
        mixctrl.switch_to_nemu()
    else:
        raise ValueError(f"Invalid base: {base}")


def _locate_all(target: Target|list[Target]|tuple[Target, ...], *, screenshot=None, image_first: bool = False)->list[list[Box]]:
    """Locate all targets on the current screen.

    When *image_first* is True, template-matched (ImageTarget) targets are
    resolved before OCR (TextTarget) ones.  If any image target already yields
    a match, text targets are skipped — significantly reducing latency for
    "any-match" (tuple) queries that mix I() and T() targets.
    """
    def genertate_source(target):
        if isinstance(target, ImageTarget|TextTarget):
            return target.get_source(),target.ui.box,target.ui.color
        elif isinstance(target, BoxTarget):
            return target.box, target.box, target.color
        else:
            raise ValueError(f"Unsupported target type: {type(target)}")

    dispatched: dict[int, Target] = {}
    batch: list[tuple[int, Target]] = []
    for i, tgt in enumerate(target):
        if has_handler(type(tgt)):
            dispatched[i] = tgt
        else:
            batch.append((i, tgt))

    boxes: list[list[Box] | None] = [None] * len(target)

    if batch:
        if image_first:
            img_items = [(idx, t) for idx, t in batch if isinstance(t, ImageTarget)]
            rest_items = [(idx, t) for idx, t in batch if not isinstance(t, ImageTarget)]

            if img_items:
                img_triples = [genertate_source(t) for _, t in img_items]
                frame = screenshot if screenshot is not None else mixctrl.screenshot()
                img_boxes = mixctrl.locate(img_triples, screenshot=frame)
                for j, (orig_idx, _) in enumerate(img_items):
                    boxes[orig_idx] = img_boxes[j]
                if first(boxes):
                    return boxes
                screenshot = frame

            if rest_items:
                rest_triples = [genertate_source(t) for _, t in rest_items]
                rest_boxes = mixctrl.locate(rest_triples, screenshot=screenshot)
                for j, (orig_idx, _) in enumerate(rest_items):
                    boxes[orig_idx] = rest_boxes[j]
        else:
            ordered_targets = [t for _, t in batch]
            tgt_triples = [genertate_source(t) for t in ordered_targets]
            batch_boxes = mixctrl.locate(tgt_triples, screenshot=screenshot)
            for j, (orig_idx, _) in enumerate(batch):
                boxes[orig_idx] = batch_boxes[j]

    if dispatched:
        frame = screenshot if screenshot is not None else mixctrl.screenshot()
        for idx, tgt in dispatched.items():
            boxes[idx] = dispatch_locate(tgt, frame)

    return boxes

def locate(target: Target|list[Target]|tuple[Target, ...], timeout: float=0, assure_stable: bool = True, is_simplify: bool = True, screenshot=None)->Box|None|list[Box]:
    """
    在屏幕上查找文本或图片目标，返回第一个匹配的 Box 或 False
    支持多目标等待：列表需全满足，元组任一满足
    Args:
        target: 目标对象或目标对象元组
        timeout: 超时时间
        assure_stable: 是否保证稳定,如果为True，则每次定位都会保证稳定，直到找到目标或超时
    """
    _ensure_boosted()  # 延迟 boost：只在首次真正使用 API 时才执行
    check_cancel_raise()
    first_attempt = True
    _stable_retry = False
    t = time.time()
    # 元组任一满足
    if isinstance(target, tuple):
        logger.info(f"Locate: {target}")
        # Use image-first short circuit when tuple contains both I() and T() targets
        _has_img = any(isinstance(t, ImageTarget) for t in target)
        _has_txt = any(isinstance(t, TextTarget) for t in target)
        _img_first = _has_img and _has_txt
        while first_attempt or _stable_retry or (delta := time.time() - t) < timeout:
            check_cancel_raise()
            first_attempt = False
            was_retry = _stable_retry
            _stable_retry = False
            boxes = _locate_all(target, screenshot=screenshot, image_first=_img_first)
            if assure_stable and not stable(boxes, _locate_all(target, image_first=_img_first)):
                if first(boxes) and not was_retry:
                    _stable_retry = True
                continue
            if first(boxes): return first(boxes) if is_simplify else boxes  # 确保返回单个Box或None
            # if delta > 5 and cfg["llm"]["use_agent"]:
        # 超时未找到目标时，保存搜索失败截图
        if timeout >= 5:
            try:
                save_debug_screenshot(target, mixctrl.screenshot(), prefix="s", extra_info=_diag_info())
            except Exception:
                pass
        return None if is_simplify else boxes
    
    # 列表需全满足
    if isinstance(target, list):
        logger.info(f"Locate: {target}")
        _stable_retry = False
        while first_attempt or _stable_retry or (delta := time.time() - t) < timeout:
            check_cancel_raise()
            first_attempt = False
            was_retry = _stable_retry
            _stable_retry = False
            boxes = _locate_all(target, screenshot=screenshot)
            if assure_stable and not stable(boxes, _locate_all(target)):
                if full(boxes) and not was_retry:
                    _stable_retry = True
                continue
            if full(boxes): return simple(boxes) if is_simplify else boxes
        # 超时未全部找到目标时，保存搜索失败截图
        if timeout >= 5:
            try:
                save_debug_screenshot(target, mixctrl.screenshot(), prefix="s", extra_info=_diag_info())
            except Exception:
                pass
        return boxes if not is_simplify else simple(boxes)
    
    # 单个Target对象，转换为元组处理
    if isinstance(target, Target):
        return locate((target,), timeout, assure_stable=assure_stable, screenshot=screenshot)
    
def wait_for_appear(target: Target|tuple[Target, ...], timeout: float=30) -> Box:
    """等待目标出现并返回 Box。超时抛 TimeoutError（与 wait_for_disappear 对称）。"""
    if not isinstance(target, (Target, tuple, list)):
        raise TypeError(f"wait_for_appear 期望 Target/tuple/list，收到 {type(target).__name__!r}: {target!r}")
    result = locate(target, timeout, assure_stable=False)
    if result is None:
        raise TimeoutError(f"wait_for_appear({target}) 超时 ({timeout}s)")
    return result

def wait_for_disappear(target: Target|tuple[Target, ...], timeout: float=30)->bool:
    locate(target, timeout=5, assure_stable=False)
    t = time.time()
    while locate(target, timeout=0, assure_stable=False) is not None:
        check_cancel_raise()
        if time.time() - t > timeout:
            raise RuntimeError(f"Wait for disappear {target} timeout, for failed to locate target in {timeout} seconds")
        cancellable_sleep(0.5)
    return True

def click(
        target: Target|tuple[Target, ...], 
        long_click_duration_s: int = 0,
        *,
        timeout: float = 30, 
        if_exist: bool = False,
        repeat: int = 1,
        delay: float = 0,
        interval: float = 0,
        offset:tuple=(0,0), 
        resize:tuple=(-1,-1),
        until: callable = None,
        assure_stable: bool = True,
        save_screenshot: bool = True
):
    _ensure_boosted()  # 延迟 boost：只在首次真正使用 API 时才执行
    """
    点击目标元素
    
    Args:
        target: 目标对象或目标对象元组/列表
            - 单个 Target: 定位并点击该目标
            - tuple[Target, ...]: 任一目标出现即点击（OR逻辑）
            - list[Target]: 所有目标都出现才点击（AND逻辑）
        
        long_click_duration_s: 长按时长（秒），0表示普通点击
        
        timeout: 定位超时时间（秒），默认30秒
        
        if_exist: 如果为True，目标不存在时不抛异常，直接返回False，此时默认timeout=2s
        
        repeat: 重复点击次数，默认1次
        
        delay: 点击前延迟（秒），默认0
        
        interval: 多次点击之间的间隔（秒），默认0
        
        offset: 点击位置偏移量 (x, y)，相对于定位到的Box左上角
            - 示例: offset=(120, 120) 表示在定位到的Box基础上，向右偏移120px，向下偏移120px
            - 偏移后的Box会先应用resize（如果指定），然后在其中心点附近随机点击
            - 用途：当目标文本/图片区域较大，需要点击其内部特定位置时使用
            - 默认: (0, 0) 表示不偏移，直接点击Box中心附近
        
        resize: 调整定位到的Box大小 (width, height)
            - 示例: resize=(80, 80) 将Box调整为80x80像素
            - 如果为(-1, -1)则保持原Box大小
            - 调整后的Box会先应用offset偏移，然后在其中心点附近随机点击
            - 用途：当目标区域太大，需要缩小到更精确的点击范围时使用
            - 默认: (-1, -1) 表示不调整
        
        until: 可调用对象，返回True时停止点击循环
            - 示例: until=lambda: ui_F(T("确定")) 表示点击直到"确定"按钮消失
            - 如果指定until，会忽略timeout参数，持续点击直到until返回True或超时
        
        assure_stable: 是否保证定位稳定，True时会连续两次定位结果一致才认为成功
        
        save_screenshot: 是否在debug模式下保存点击截图（带标注），默认True
    
    Returns:
        bool: 点击是否成功（如果if_exist=True且目标不存在，返回False）
    
    Raises:
        RuntimeError: 目标定位失败或until条件超时
    
    Examples:
        # 普通点击
        click(T("确定"))
        
        # 点击目标内部偏移位置（常用于大按钮内部特定区域）
        click(T("第1关"), offset=(120, 120))  # 在"第1关"文本区域向右下各偏移120px
        
        # 缩小点击范围并偏移
        click(T("第1关"), offset=(120, 120), resize=(80, 80))  # 先缩小到80x80，再偏移
        
        # 长按
        click(B(100, 200), long_click_duration_s=2)
        
        # 点击直到条件满足
        click(T("确定"), until=lambda: ui_F(T("确定")))
    """
    check_cancel_raise()
    if until:
        t = time.time()
        click(target, long_click_duration_s, timeout=timeout, if_exist=False, repeat=repeat, delay=delay, interval=interval, offset=offset, resize=resize,assure_stable=assure_stable)
        while not until():
            check_cancel_raise()
            click(target, long_click_duration_s, timeout=0, if_exist=True, repeat=repeat, delay=delay, interval=interval, offset=offset, resize=resize,assure_stable=assure_stable)
            if time.time() - t > timeout:
                try:
                    save_debug_screenshot(
                        target, mixctrl.screenshot(), prefix="s",
                        extra_info=_diag_info(until=until.__name__, elapsed=f"{time.time()-t:.1f}s"))
                except Exception:
                    pass
                raise RuntimeError(f"Click {target} until {until.__name__} failed, for until function not satisfied in {timeout} seconds")
        return True
    if isinstance(target, list): target = tuple(target)
    if isinstance(target, BoxTarget): box = target.box
    else:
        box = locate(target, timeout if not if_exist else max(2, timeout) if timeout != 30 else 2, assure_stable)    # 至少2s
    if if_exist and first(box) is None: return False
    if first(box) is None:
        try:
            save_debug_screenshot(target, mixctrl.screenshot(), prefix="s", extra_info=_diag_info())
        except Exception:
            pass
        raise RuntimeError(f"Click {target} failed, for failed to locate target in {timeout} seconds")
    cancellable_sleep(delay)
    pre_click_frame = mixctrl.screenshot() if save_screenshot and not isinstance(target, BoxTarget) else None
    pt = None
    for i in range(repeat):
        pt=b2p(box, offset, resize)
        if long_click_duration_s:
            mixctrl.long_click(*pt, duration=long_click_duration_s)
        else:
            mixctrl.click(*pt)
        cancellable_sleep(interval)
    if pt is None:
        return True
    if isinstance(target, BoxTarget):
        _box_click_trace.append(pt)
    elif pre_click_frame is not None:
        prior = list(_box_click_trace)
        _box_click_trace.clear()
        save_debug_screenshot(target, pre_click_frame, box, pt, prefix="c", prior_clicks=prior)
    return True  


def swipe(
        start_target: Target, 
        end_target: Target, 
        *,
        duration_s: int=1, 
        delay: float = 0,
        ensure_stable_after_swipe: bool = True,
    ):
    _ensure_boosted()  # 延迟 boost：只在首次真正使用 API 时才执行
    check_cancel_raise()
    start_box = locate(start_target, 3) if not isinstance(start_target, BoxTarget) else start_target.box
    end_box = locate(end_target, 3, assure_stable=False) if not isinstance(end_target, BoxTarget) else end_target.box
    if start_box is None or end_box is None: raise RuntimeError(f"Swipe {start_target} to {end_target} failed, for failed to locate target")
    cancellable_sleep(delay)
    mixctrl.swipe(*b2p(start_box), *b2p(end_box), duration_s)
    if ensure_stable_after_swipe:
        cancellable_sleep(duration_s)
    return True

def input(text: str, target_field: Target|tuple[Target, ...] = None):
    _ensure_boosted()  # 延迟 boost：只在首次真正使用 API 时才执行
    check_cancel_raise()
    if target_field:
        click(target_field)
        cancellable_sleep(0.5)
    mixctrl.input_text(text)

def key_event(key_code: int):
    logger.info("Key event: {}".format(next((attr for attr in dir(AndroidKey) if attr.startswith("KEYCODE_") and getattr(AndroidKey, attr) == key_code), key_code)))
    mixctrl.key_event(key_code)

def extract_info(
    target: BoxTarget,
    post_process: callable = None,
    ensure_not_empty: bool = True,
    save_screenshot: bool = True,
    *,
    ocr_ttl: float = 0.5,
    max_retries: int = 10,
)->str|None:
    res = None
    last_ocr_at: float | None = None
    for _ in range(max_retries):
        check_cancel_raise()
        if last_ocr_at is not None:
            wait = ocr_ttl - (time.monotonic() - last_ocr_at)
            if wait > 0:
                cancellable_sleep(wait)
        screenshot = mixctrl.screenshot()
        res = ocr_for_box(screenshot, target.box, ttl=ocr_ttl)
        last_ocr_at = time.monotonic()
        logger.debug(f"Extract info {target} raw_res: {res}")
        if post_process:
            try:
                res = post_process(res)
            except Exception as e:
                logger.error(f"Extract info {target} failed, raw_res: {res}, for {e}")
                continue
        if ensure_not_empty and isinstance(res, str) and len(res) == 0: continue
        if res is not None: break
    if save_screenshot and cfg["app"]["debug_mode"]:
        save_debug_screenshot(target=target, screenshot=mixctrl.screenshot(), box=target.box, ocr_text=res, prefix="e")
    return res

def get_colors(targets: Target|tuple[Target, ...], *, offset: tuple = (0, 0), resize: tuple = (-1, -1))->list[str|None]:
    """
    获取目标区域的颜色信息
    Args:
        targets: 目标对象或目标对象元组
        offset: 偏移量 (x, y)，相对于定位到的位置
        resize: 调整大小 (width, height)，-1表示保持原大小
    """
    screenshot = mixctrl.screenshot()
    # 处理生成器对象，转换为列表
    if hasattr(targets, '__iter__') and not isinstance(targets, (list, tuple, str)): targets = list(targets)
    targets = targets if isinstance(targets, list|tuple) else [targets]
    boxes = _locate_all(targets, screenshot=screenshot)
    # 应用offset和resize到boxes
    if offset != (0, 0) or resize != (-1, -1):
        for i in range(len(boxes)):
            if boxes[i]:
                for j in range(len(boxes[i])):
                    offset_tuple = (offset[0], offset[1], 
                                  resize[0] if resize[0] != -1 else boxes[i][j].width,
                                  resize[1] if resize[1] != -1 else boxes[i][j].height)
                    boxes[i][j] = boxes[i][j] + offset_tuple
    
    colors = [[] for _ in range(len(boxes))]
    for i in range(len(boxes)):
        if boxes[i]:
            for j in range(len(boxes[i])):
                colors[i].append(get_box_color(screenshot, boxes[i][j]))
        else:
            colors[i].append(None)
    logger.debug(f"get_colors {targets} colors: {colors}")
    return colors

def sleep(seconds: float):
    cancellable_sleep(seconds)

def edit_img():
    launch_editor(mixctrl,is_screenshot=True) 

def detect_floating_window(debug: bool = False) -> dict:
    """
    检测屏幕边缘的 4399 悬浮窗（基于 HSV 绿色边缘扫描，不依赖模板匹配）。
    
    Returns:
        dict: {'found': bool, 'edge': str, 'box': Box, 'center': (x,y), ...}
    """
    from AutoScriptor.recognition.floating_window import detect_floating_window as _detect
    screenshot = mixctrl.screenshot()
    return _detect(screenshot, debug=debug)


def dismiss_floating_window(max_retries: int = 3, debug: bool = False) -> bool:
    """
    检测并移除 4399 悬浮窗：检测到后将其滑动到屏幕中央触发设置面板，然后隐藏。
    
    Args:
        max_retries: 最大重试次数（悬浮窗可能需要多次截图才能稳定检测到）
        debug: 保存调试图像
    
    Returns:
        bool: True 表示检测到并处理了悬浮窗，False 表示未检测到
    """
    from AutoScriptor.recognition.floating_window import detect_floating_window as _detect

    for attempt in range(max_retries):
        check_cancel_raise()
        screenshot = mixctrl.screenshot()
        result = _detect(screenshot, debug=debug)
        if not result["found"]:
            cancellable_sleep(0.3)
            continue

        logger.info(f"🔍 检测到悬浮窗: {result['edge']}边 {result['box']} (第{attempt+1}次)")

        # 从悬浮窗位置滑到屏幕中央，触发悬浮窗设置面板
        cx, cy = result["center"]
        swipe(B(cx, cy, 10, 10), B(640, 650, 10, 10), duration_s=1)
        cancellable_sleep(1)
        click(B(740, 555, 10, 10))
        cancellable_sleep(0.5)

        verify = _detect(mixctrl.screenshot(), debug=debug)
        if not verify["found"]:
            logger.info("✅ 悬浮窗已隐藏")
            return True

        logger.warning(f"⚠️ 悬浮窗关闭后仍检测到: {verify['edge']}边 {verify['box']}")

    return False

_boosted = False
def _ensure_boosted():
    """延迟 boost：只在首次真正使用 API 时才执行性能优化。"""
    global _boosted
    if _boosted:
        return
    _boosted = True
    from AutoScriptor.utils.perf import boost
    boost()                          # 提升 Python 进程自身（不提升 MuMu，避免干扰其他程序）