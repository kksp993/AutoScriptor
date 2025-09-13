import os
import sys
import threading
import time
import traceback
from AutoScriptor.core.control import MixControl
from AutoScriptor.core.targets import Target, B,I,T
from AutoScriptor.core.targets import ImageTarget,TextTarget,BoxTarget
from AutoScriptor.recognition.ocr_rec import ocr_for_box
from AutoScriptor.recognition.rec import get_box_color
from AutoScriptor.utils.box import Box, b2p
from AutoScriptor.logger import logger
from AutoScriptor.utils.constant import cfg
from AutoScriptor.control.MumuAdaptor.mumu import Mumu
from AutoScriptor.utils.edit_img import launch_editor
logger.info("编排器初始化开始...")
selected_emulator_index = cfg["emulator"]["index"]
adb_addr = cfg["emulator"]["adb_addr"]
app_to_start = cfg["app"]["app_to_start"]
mumu_manager_path = cfg["emulator"]["emu_path"]
print(f"selected_emulator_index: {selected_emulator_index}")
print(f"adb_addr: {adb_addr}")
print(f"app_to_start: {app_to_start}")
print(f"mumu_manager_path: {mumu_manager_path}")
mumu = Mumu().select(selected_emulator_index)
mumu.power.start(app_to_start)
mixctrl = MixControl(mumu)
logger.info("编排器初始化完成.")
success = False
intervals = [1, 2, 3, 4, 5, 5, 5, 5]
for i, interval in enumerate(intervals, 1):
    click_result = {}
    def _click_test():
        try:
            mixctrl.click(0, 0)
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
    logger.error("多次点击测试失败，准备重启框架")
    from AutoScriptor.core.background import bg
    bg.stop()
    os.execv(sys.executable, [sys.executable] + sys.argv)


def ui_idx(target: Target|list[Target]|tuple[Target, ...], timeout: float=10)->bool:
    tuple_tgt, list_tgt = tuple(t for t in target), [t for t in target]
    res = locate(tuple_tgt, timeout)
    if not res: raise Exception(f"{target} 没有找到:" + traceback.print_exc())
    boxes = locate(list_tgt, 0)
    return index(boxes)

def ui_T(target: Target|list[Target]|tuple[Target, ...], timeout: float=0)->bool:
    boxes = locate(target, timeout)
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
    return [len(box_matrix) if box_matrix else 0 for box_matrix in box_matrixes]

def index(box_matrixes: list[list[Box]])-> int:
    if not box_matrixes: return -1
    for i, box in enumerate(box_matrixes):
        if box: return i
    return -1


def stable(boxes1: list[list[Box]], boxes2: list[list[Box]])->bool:
    if not boxes1 or not boxes2: return False
    assert len(boxes1) == len(boxes2)
    for i in range(len(boxes1)):
        if not (boxes1[i] and boxes2[i]): continue
        for j in range(len(boxes1[i])):
            if not boxes1[i][j].sim_box(boxes2[i][j]): return False
    return True

def switch_base(base: str):
    if base == "mumu":
        mixctrl.switch_to_mumu()
    elif base == "nemu":
        mixctrl.switch_to_nemu()
    else:
        raise ValueError(f"Invalid base: {base}")


def _locate_all(target: Target|list[Target]|tuple[Target, ...], *, screenshot=None)->list[list[Box]]:
    def genertate_source(target):
        if isinstance(target, ImageTarget|TextTarget):
            return target.get_source(),target.ui.box,target.ui.color
        elif isinstance(target, BoxTarget):
            return target.box,target.box,None
        else:
            raise ValueError(f"Unsupported target type: {type(target)}")
    tgt_triples = [genertate_source(tgt) for tgt in target]
    boxes = mixctrl.locate(tgt_triples, screenshot=screenshot)
    return boxes

def locate(target: Target|list[Target]|tuple[Target, ...], timeout: float=0, assure_stable: bool = True)->Box|None|list[Box]:
    """
    在屏幕上查找文本或图片目标，返回第一个匹配的 Box 或 False
    支持多目标等待：列表需全满足，元组任一满足
    Args:
        target: 目标对象或目标对象元组
        timeout: 超时时间
        assure_stable: 是否保证稳定,如果为True，则每次定位都会保证稳定，直到找到目标或超时
    """
    first_attempt = True
    t = time.time()
    # 元组任一满足
    if isinstance(target, tuple):
        logger.info(f"Locate: {target}")
        while first_attempt or time.time() - t < timeout:
            first_attempt = False
            boxes = _locate_all(target)
            if assure_stable and not stable(boxes, _locate_all(target)): continue
            if first(boxes): return first(boxes)  # 确保返回单个Box或None
        return None
    
    # 列表需全满足
    if isinstance(target, list):
        logger.info(f"Locate: {target}")
        while first_attempt or time.time() - t < timeout:
            first_attempt = False
            boxes = _locate_all(target)
            if assure_stable and not stable(boxes, _locate_all(target)): continue
            if full(boxes): return simple(boxes)
        return simple(boxes)
    
    # 单个Target对象，转换为元组处理
    if isinstance(target, Target):
        return locate((target,), timeout)
    
def wait_for_appear(target: Target|tuple[Target, ...], timeout: float=30)->bool:
    return locate(target, timeout) is not None

def wait_for_disappear(target: Target|tuple[Target, ...], timeout: float=30)->bool:
    wait_for_appear(target, timeout=5)
    t = time.time()
    while locate(target, timeout=0, assure_stable=False) is not None:
        if time.time() - t > timeout:
            raise RuntimeError(f"Wait for disappear {target} timeout, for failed to locate target in {timeout} seconds")
        time.sleep(0.5)
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
        assure_stable: bool = True
    ):
    if until:
        t = time.time()
        click(target, long_click_duration_s, timeout=0, if_exist=True, repeat=repeat, delay=delay, interval=interval, offset=offset, resize=resize)
        while not until():
            click(target, long_click_duration_s, timeout=0, if_exist=True, repeat=repeat, delay=delay, interval=interval, offset=offset, resize=resize)
            if time.time() - t > timeout:
                raise RuntimeError(f"Click {target} until {until.__name__} failed, for until function not satisfied in {timeout} seconds")
        return True
    if isinstance(target, list): target = tuple(target)
    if isinstance(target, BoxTarget): box = target.box
    else: 
        box = locate(target, timeout if not if_exist else max(2, timeout) if timeout != 30 else 2, assure_stable)    # 至少2s
    if if_exist and first(box) is None: return False
    if first(box) is None: raise RuntimeError(f"Click {target} failed, for failed to locate target in {timeout} seconds")
    time.sleep(delay)
    for i in range(repeat):
        if long_click_duration_s:
            mixctrl.long_click(*b2p(box, offset, resize), duration=long_click_duration_s)
        else:
            mixctrl.click(*b2p(box, offset, resize))
        time.sleep(interval)
    return True


def swipe(
        start_target: Target, 
        end_target: Target, 
        *,
        duration_s: int=1, 
        delay: float = 0,
    ):
    start_box = locate(start_target, 3) if not isinstance(start_target, BoxTarget) else start_target.box
    end_box = locate(end_target, 3) if not isinstance(end_target, BoxTarget) else end_target.box
    if start_box is None or end_box is None: return RuntimeError(f"Swipe {start_target} to {end_target} failed, for failed to locate target")
    time.sleep(delay)
    mixctrl.swipe(*b2p(start_box), *b2p(end_box), duration_s)
    return True

def input(text: str, target_field: Target|tuple[Target, ...] = None):
    if target_field:
        click(target_field)
        time.sleep(0.5)
    mixctrl.input_text(text)

def key_event(key_code: int):
    mixctrl.key_event(key_code)

def extract_info(target: BoxTarget, post_process: callable = None, ensure_not_empty: bool = True)->str|None:
    for _ in range(40):
        screenshot = mixctrl.screenshot()
        res = ocr_for_box(screenshot, target.box)
        if post_process:
            try:
                res = post_process(res)
            except Exception as e:
                logger.error(f"Extract info {target} failed, raw_res: {res}, for {e}")
                continue
        if ensure_not_empty and isinstance(res, str) and len(res) == 0: continue
        if res: break
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
    return colors

def sleep(seconds: float):
    time.sleep(seconds)

def edit_img():
    launch_editor(mixctrl,is_screenshot=True) 
