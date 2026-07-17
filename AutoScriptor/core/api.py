import os
import threading
import time
from typing import Callable
from AutoScriptor.control.MumuAdaptor.constant import AndroidKey
from AutoScriptor.core.control import MixControl, ControlModeProxy
from AutoScriptor.core.background import bg
from AutoScriptor.core.targets import Target, B
from AutoScriptor.core.targets import ImageTarget,TextTarget,BoxTarget
from AutoScriptor.recognition.ocr_rec import ocr_for_box
from AutoScriptor.recognition.rec import get_box_color
from AutoScriptor.utils.box import Box, b2p
from AutoScriptor.utils.tracer import save_debug_screenshot
from AutoScriptor.utils.logger import logger, setup_logfile
from AutoScriptor.utils.app_config import cfg
from AutoScriptor.utils.app_package_resolve import resolve_app_to_start
from AutoScriptor.control.MumuAdaptor.mumu import Mumu
from AutoScriptor.utils.cancel import check_cancel_raise, cancellable_sleep, join_with_cancel, sleep_with_cancel

def ensure_all_environment_ready():
    # 初始化编排器
    logger.info("编排器初始化开始...")
    import os
    from datetime import datetime
    log_dir = os.path.join(os.getcwd(), 'logs', 'log')
    os.makedirs(log_dir, exist_ok=True)
    timestamp = datetime.now().strftime('%y%m%d_%H%M%S')
    setup_logfile(os.path.join(log_dir, f"[{timestamp}].log"))
    selected_emulator_index = cfg["emulator"]["index"]
    adb_addr = cfg["emulator"]["adb_addr"]
    app_to_start = cfg["app"]["app_to_start"]
    return selected_emulator_index, adb_addr, app_to_start

def ensure_app_running(
    selected_emulator_index,
    adb_addr,
    app_to_start,
    *,
    start_emulator: bool = True,
    launch_app: bool = True,
    cancel_check: Callable[[], None] | None = None,
):
    """
    确保当前配置的 MuMu 实例可控制，并按需启动游戏。

    start_emulator:
        True 表示执行链需要 MuMu，未运行时必须启动。
    launch_app:
        True 表示启动/拉起 app_to_start。
    cancel_check:
        协作式取消检查；WebUI 停止按钮会通过它快速打断启动、解析和探测等待。
    """
    cancel_check = cancel_check or check_cancel_raise

    mumu_manager_path = cfg["emulator"]["emu_path"]
    logger.debug(
        "ensure_app_running: index=%s, adb=%s, app=%s, emu=%s, start_emulator=%s, launch_app=%s",
        selected_emulator_index, adb_addr, app_to_start, mumu_manager_path, start_emulator, launch_app,
    )
    mumu = Mumu().select(selected_emulator_index)
    cancel_check()

    is_running = mumu.power.is_running()
    if not is_running:
        if not start_emulator:
            raise RuntimeError("ensure_app_running: 模拟器未运行，且当前调用不允许自动启动")
        mumu.power.start(None, cancel_check=cancel_check)
        is_running = True
    if not is_running:
        raise RuntimeError("ensure_app_running: 模拟器启动失败")

    # MuMuManager may report a running process while its TCP ADB endpoint is
    # still offline. Do not create controls or launch the app until the
    # configured serial is connected and Android has completed booting.
    logger.info("正在确认模拟器 ADB 与 Android 启动状态")
    if not mumu.power.wait_until_android_ready(cancel_check=cancel_check):
        raise RuntimeError(
            f"ensure_app_running: ADB 设备 {adb_addr} 未就绪或 Android 启动未完成"
        )

    # app_to_start 为空或未安装时由 resolve_app_to_start 枚举候选包并写回 data/config.json。
    # 解析只在需要拉起应用时进行，避免 WebUI 初始化或纯设备探测误触 MuMuManager。
    if launch_app:
        cancel_check()
        resolved = resolve_app_to_start(mumu, cancel_check=cancel_check)
        mumu.app.launch(resolved)
        cancel_check()

    logger.info("模拟器启动完成")
    mixctrl = MixControl(mumu, serial=adb_addr)
    logger.info("编排器初始化完成.")
    success = False
    intervals = [1, 2, 3, 3, 3, 3, 3, 3]
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
        join_with_cancel(t, 3, cancel_check)
        if not t.is_alive() and 'error' not in click_result:
            success = True
        if success:
            logger.info("测试点击(0,0)成功，模拟器响应正常。")
            break
        logger.error(f"测试点击(0,0)，第{i}次尝试，第{interval}秒后重试")
        sleep_with_cancel(interval, cancel_check)
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
    mixctrl, mumu = ensure_app_running(idx, addr, app, start_emulator=True, launch_app=True)
    # Propagate live references to package-level namespaces so that
    # ``from AutoScriptor import mixctrl`` picks up the real object
    # when the import happens *after* init().
    import AutoScriptor as _pkg
    import AutoScriptor.core as _core_pkg
    _pkg.mixctrl = mixctrl
    _pkg.mumu = mumu
    _core_pkg.mixctrl = mixctrl


def _validate_timeout(timeout, caller: str) -> None:
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        hint = ""
        if isinstance(timeout, Target):
            hint = "；多个目标请用 tuple/list 包起来，例如 wait_for_appear((T(...), T(...)))"
        raise TypeError(
            f"{caller} 的 timeout 必须是数字秒数，收到 {type(timeout).__name__}: {timeout!r}{hint}"
        )


def ui_idx(target: Target|list[Target]|tuple[Target, ...], timeout: float=0)->int:
    _validate_timeout(timeout, "ui_idx")
    target = [t for t in target]
    boxes = locate(target, timeout, assure_stable=False)
    if not first(boxes): return -1
    return index(boxes)


def ui_T(target: Target|list[Target]|tuple[Target, ...], timeout: float=0, *, screenshot=None)->bool:
    _validate_timeout(timeout, "ui_T")
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


def _format_match_path(path: tuple[int, ...]) -> str:
    """嵌套索引路径格式化为 [1.0]、[2] 等（与 locate 目标树结构一致）。"""
    if not path:
        return "[?]"
    return "[" + ".".join(str(p) for p in path) + "]"


def _flatten_target_paths(target: Target|list[Target]|tuple[Target, ...]) -> list[tuple[tuple[int, ...], Target]]:
    """将嵌套 tuple/list of Target 展平为 (从根到叶的索引路径, 叶子 Target)。

    例：(A, (B, C), D) -> [((0,), A), ((1, 0), B), ((1, 1), C), ((2,), D)]，
    对应标注 [0]、[1.0]、[1.1]、[2]。
    """
    if isinstance(target, Target):
        return [((), target)]
    if isinstance(target, (tuple, list)):
        out: list[tuple[tuple[int, ...], Target]] = []
        for i, child in enumerate(target):
            if isinstance(child, Target):
                out.append(((i,), child))
            elif isinstance(child, (tuple, list)):
                for subpath, t in _flatten_target_paths(child):
                    out.append(((i,) + subpath, t))
            else:
                raise TypeError(f"locate 目标必须是 Target 或嵌套序列，收到 {type(child)!r}: {child!r}")
        return out
    raise TypeError(f"locate 目标类型不支持: {type(target)!r}")


def _first_hit_path(boxes: list, target: Target|list[Target]|tuple[Target, ...]) -> str | None:
    """与 first(boxes) 顺序一致：第一个有命中的槽位在 target 树中的路径（[x.x.x]）。"""
    paths = _flatten_target_paths(target)
    if len(paths) != len(boxes):
        for i, b in enumerate(boxes):
            if b and first([b]) is not None:
                return _format_match_path((i,))
        return None
    for i, b in enumerate(boxes):
        if b and first([b]) is not None:
            return _format_match_path(paths[i][0])
    return None


def match(target: Target|list[Target]|tuple[Target, ...], timeout: float=0, *, screenshot=None) -> dict | None:
    """
    结构化匹配目标，沿用 locate 的组合语义，并返回命中细节。

    target:
        Target 表示查找单个目标。
        tuple[Target, ...] 表示 OR，任一目标命中即成功。
        list[Target] 表示 AND，全部目标命中才成功。
    timeout:
        最长等待秒数；0 表示只检查当前画面一次。
    screenshot:
        可传入固定截图帧，复用同一帧做定位，适合截图测试或批量识别。

    返回:
        None 表示未满足 target 对应的组合条件。
        dict 表示匹配成功，常用字段如下：
            all: 是否按 list 的 AND 语义匹配。
            index: 扁平目标列表中的首个命中下标。
            path: 目标结构中的嵌套位置，不是文件路径；如 (1, 0) 表示第 1 组里的第 0 个目标。
            target: 首个命中的目标对象。
            box: 首个命中的 Box。
            boxes: 完整定位结果矩阵。
    """
    _validate_timeout(timeout, "match")
    check_cancel_raise()
    is_all_match = isinstance(target, list)
    if isinstance(target, Target):
        normalized_targets = [target]
        target_for_paths = target
    elif isinstance(target, (list, tuple)):
        normalized_targets = target
        target_for_paths = target
    else:
        raise TypeError(f"match 目标必须是 Target/list/tuple，收到 {type(target)!r}: {target!r}")

    boxes = locate(
        normalized_targets,
        timeout,
        assure_stable=False,
        is_simplify=False,
        screenshot=screenshot,
    )
    if not boxes:
        return None
    if is_all_match:
        if not full(boxes):
            return None
    elif first(boxes) is None:
        return None

    matched_index = index(boxes)
    flattened_targets = _flatten_target_paths(target_for_paths)
    if 0 <= matched_index < len(flattened_targets):
        matched_path, matched_target = flattened_targets[matched_index]
    else:
        matched_path, matched_target = (matched_index,), None
    matched_box = first([boxes[matched_index]]) if matched_index >= 0 else None
    return {
        "all": is_all_match,
        "index": matched_index,
        "path": matched_path,
        "target": matched_target,
        "box": matched_box,
        "boxes": boxes,
    }


def switch_base(base: str):
    if base == "mumu":
        mixctrl.switch_to_mumu()
    elif base == "nemu":
        mixctrl.switch_to_nemu()
    else:
        raise ValueError(f"Invalid base: {base}")


def _current_control():
    return mixctrl


ctrl_nemu = ControlModeProxy("nemu", _current_control)
ctrl_mumu = ControlModeProxy("mumu", _current_control)


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

    boxes: list[list[Box] | None] = [None] * len(target)

    if image_first:
        img_items = [(idx, t) for idx, t in enumerate(target) if isinstance(t, ImageTarget)]
        rest_items = [(idx, t) for idx, t in enumerate(target) if not isinstance(t, ImageTarget)]

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
        return mixctrl.locate([genertate_source(t) for t in target], screenshot=screenshot)

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
    _validate_timeout(timeout, "locate")
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
            if assure_stable:
                boxes2 = _locate_all(target, screenshot=screenshot, image_first=_img_first)
                if not stable(boxes, boxes2):
                    p1 = _first_hit_path(boxes, target)
                    p2 = _first_hit_path(boxes2, target)
                    logger.debug(
                        f"[locate assure_stable] {p1 or '[?]'} / {p2 or '[?]'} 两次定位不一致，重试"
                    )
                    if first(boxes) and not was_retry:
                        _stable_retry = True
                    continue
            if first(boxes): return first(boxes) if is_simplify else boxes  # 确保返回单个Box或None
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
            if assure_stable:
                boxes2 = _locate_all(target, screenshot=screenshot)
                if not stable(boxes, boxes2):
                    p1 = _first_hit_path(boxes, target)
                    p2 = _first_hit_path(boxes2, target)
                    logger.debug(
                        f"[locate assure_stable] {p1 or '[?]'} / {p2 or '[?]'} 两次定位不一致，重试"
                    )
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
    _validate_timeout(timeout, "wait_for_appear")
    result = locate(target, timeout, assure_stable=False)
    if result is None:
        raise TimeoutError(f"wait_for_appear({target}) 超时 ({timeout}s)")
    return result

def wait_for_disappear(target: Target|tuple[Target, ...], timeout: float=30)->bool:
    _validate_timeout(timeout, "wait_for_disappear")
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
        interval: float | None = None,
        offset:tuple=(0,0), 
        resize:tuple=(-1,-1),
        until: callable = None,
        assure_stable: bool = True,
        save_screenshot: bool = True
):
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
        
        interval: 多次点击之间的间隔（秒）。普通点击默认0；click(..., until=...)未显式传入时默认0.5秒。
        
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
    click_interval = 0 if interval is None else interval
    until_interval = 0.5 if interval is None else interval
    if until:
        t = time.time()
        click(target, long_click_duration_s, timeout=timeout, if_exist=False, repeat=repeat, delay=delay, interval=until_interval, offset=offset, resize=resize,assure_stable=assure_stable)
        while not until():
            check_cancel_raise()
            click(target, long_click_duration_s, timeout=0, if_exist=True, repeat=repeat, delay=delay, interval=until_interval, offset=offset, resize=resize,assure_stable=assure_stable)
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
        box = locate(target, timeout if not if_exist else max(1, timeout) if timeout != 30 else 2, assure_stable)    # 至少1s
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
        cancellable_sleep(click_interval)
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
    check_cancel_raise()
    if target_field:
        click(target_field)
        cancellable_sleep(0.5)
    mixctrl.input_text(text)

def key_event(key_code: int):
    logger.info("Key event: {}".format(next((attr for attr in dir(AndroidKey) if attr.startswith("KEYCODE_") and getattr(AndroidKey, attr) == key_code), key_code)))
    mixctrl.key_event(key_code)

def extract_info(
    target,
    post_process: callable = None,
    ensure_not_empty: bool = True,
    save_screenshot: bool = True,
    *,
    digit_only: bool = False,
    digital: bool | None = None,
    ocr_ttl: float = 0.5,
    max_retries: int = 10,
    screenshot_frame=None,
)->str|None:
    """若传入 *screenshot_frame*（BGR ndarray），则在该帧上 OCR，且重试时不再刷新画面；
    用于 Web 编辑器导入图片与模拟执行时与画布一致。未传入时仍每次重试从 mixctrl 截屏。"""
    if digital is not None:
        digit_only = bool(digital)
    if digit_only:
        from AutoScriptor.recognition.digit_rec import extract_digits
        screenshot = screenshot_frame if screenshot_frame is not None else mixctrl.screenshot()
        res = extract_digits(screenshot, target)
        if post_process:
            res = post_process(res)
        return res

    res = None
    last_ocr_at: float | None = None
    for _ in range(max_retries):
        check_cancel_raise()
        if last_ocr_at is not None:
            wait = ocr_ttl - (time.monotonic() - last_ocr_at)
            if wait > 0:
                cancellable_sleep(wait)
        screenshot = screenshot_frame if screenshot_frame is not None else mixctrl.screenshot()
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
        dbg = screenshot_frame if screenshot_frame is not None else mixctrl.screenshot()
        save_debug_screenshot(target=target, screenshot=dbg, box=target.box, ocr_text=res, prefix="e")
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
                    boxes[i][j] = boxes[i][j] + {"offset": offset, "resize": resize}
    
    colors = [[] for _ in range(len(boxes))]
    for i in range(len(boxes)):
        if boxes[i]:
            for j in range(len(boxes[i])):
                colors[i].append(get_box_color(screenshot, boxes[i][j]))
        else:
            colors[i].append(None)
    logger.debug(f"get_colors {targets} colors: {colors}")
    return colors


def coloris(targets: Target|tuple[Target, ...]|list[Target], color: str, timeout: float=0, *, offset: tuple = (0, 0), resize: tuple = (-1, -1))->bool:
    """
    判断目标区域颜色是否匹配，是 get_colors 的布尔快捷入口。

    targets:
        Target 表示判断单个目标区域。
        tuple[Target, ...] 表示 OR，任一目标区域颜色匹配即返回 True。
        list[Target] 表示 AND，全部目标区域颜色都匹配才返回 True。
    color:
        期望颜色名称，例如 "绿色"、"红色"、"灰色"；按 get_colors 返回值精确比较。
    timeout:
        最长等待秒数；0 表示只检查当前画面一次。
    offset:
        颜色采样区域相对定位 Box 的偏移量。
    resize:
        颜色采样区域大小；(-1, -1) 表示保持定位 Box 原大小。

    返回:
        True 表示颜色满足 targets 的组合语义，False 表示超时或不匹配。
    """
    _validate_timeout(timeout, "coloris")
    if hasattr(targets, '__iter__') and not isinstance(targets, (list, tuple, str)):
        targets = list(targets)
    is_all_match = isinstance(targets, list)

    def color_matches_once() -> bool:
        color_matrix = get_colors(targets, offset=offset, resize=resize)
        matched_by_target = []
        for target_colors in color_matrix:
            matched_by_target.append(any(color_value == color for color_value in target_colors))
        return all(matched_by_target) if is_all_match else any(matched_by_target)

    first_attempt = True
    start_time = time.time()
    while first_attempt or time.time() - start_time < timeout:
        check_cancel_raise()
        first_attempt = False
        if color_matches_once():
            return True
        if timeout <= 0:
            break
        cancellable_sleep(0.5)
    return False

def sleep(seconds: float):
    cancellable_sleep(seconds)


def wait_for_signal(
    signal: str,
    expected: bool = True,
    seconds: float = 0,
    *,
    timeout: float | None = None,
    start: float | None = None,
) -> bool:
    start = time.time() if start is None else start
    end = time.time() + max(seconds, 0)
    while True:
        check_cancel_raise()
        now = time.time()
        if timeout is not None and now - start > timeout:
            raise RuntimeError(f"等待信号 {signal!r} 超时: {timeout}秒, 条件 {repr(expected)} 未满足")
        if bool(bg.signal(signal, False)) is expected:
            return True
        remaining = end - now
        if remaining <= 0:
            return False
        sleep(min(0.05, remaining))


def detect_floating_window(debug: bool = False) -> dict:
    """
    检测屏幕边缘的 4399 悬浮窗（基于 HSV 绿色边缘扫描，不依赖模板匹配）。
    
    Returns:
        dict: {'found': bool, 'edge': str, 'box': Box, 'center': (x,y), ...}
    """
    from AutoScriptor.recognition.floating_window import detect_floating_window as _detect
    screenshot = mixctrl.screenshot()
    return _detect(screenshot, debug=debug)


def dismiss_floating_window(max_retries: int = 1, debug: bool = False) -> bool:
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