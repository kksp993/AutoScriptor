import time
from collections import defaultdict
from functools import wraps
from typing import Callable
from AutoScriptor.utils.logger import logger
from AutoScriptor.control.MumuAdaptor.mumu import Mumu
from AutoScriptor.control.NemuIpc.device.method.nemu_ipc import (
    NemuIpc,
    NemuIpcError,
    RequestHumanTakeover,
)
from AutoScriptor.core.display_contract import EXPECTED_FRAME_SIZE, get_frame_size
from AutoScriptor.recognition.rec import locate_on_screen
from AutoScriptor.utils.box import Box
from AutoScriptor.utils.tracer import save_debug_screenshot

class BaseMumuControl:
    def screenshot(self):
        raise NotImplementedError

    def locate(self, tgt_triples, confidence=0.8, screenshot=None)->Box|None:
        tgt_sources, tgt_boxes, tgt_colors = zip(*tgt_triples)
        if screenshot is None: screenshot = self.screenshot()
        boxes = locate_on_screen(screenshot, tgt_sources, confidence, tgt_boxes, tgt_colors)
        return boxes
    
    def switch_to_mumu(self)->None:
        logger.info("暂不支持切换到mumu，请使用mix控制")
    
    def switch_to_nemu(self)->None:
        logger.info("暂不支持切换到nemu，请使用mix控制")

    def key_event(self, key_code: int)->None:
        """AndroidKey"""
        self.mumu.adb.key_event(key_code)

    def __getattr__(self, name):
        from AutoScriptor.utils.app_config import cfg
        return getattr(Mumu().select(cfg["emulator"]["index"]), name)
    
class NemuIpcControl(BaseMumuControl):
    def __init__(self, mumu: Mumu, serial: str = '127.0.0.1:16416'):
        self.nemu_ipc = NemuIpc(serial)
        self.mumu = mumu

    def click(self, x, y)->None:
        self.nemu_ipc.click_nemu_ipc(x, y)
        # self.mumu.adb.click(x, y)

    def swipe(self, x1, y1, x2, y2, duration_s=0.5)->None:
        self.nemu_ipc.swipe_nemu_ipc((x1, y1), (x2, y2), speed=0.2)

    def input_text(self, text)->None:
        self.mumu.adb.input_text(text)

    def screenshot(self):
        """rgb image via NemuIpc"""
        return self.nemu_ipc.screenshot_nemu_ipc()
    
    def long_click(self, x, y, duration=1.0)->None:
        self.nemu_ipc.long_click_nemu_ipc(x, y, duration)
        # self.mumu.adb.swipe(x, y, x, y, duration+0.1)

    def drag(self, x1, y1, x2, y2, duration=500)->None:
        self.nemu_ipc.swipe_nemu_ipc((x1, y1), (x2, y2), speed=0.2)
        # self.mumu.adb.swipe(x1, y1, x2, y2, duration)

    def switch_to_nemu(self)->None:
        logger.info("切换到nemu")
    
    def release_all_keys(self)->None:
        """释放所有按键（触摸和键盘）"""
        try:
            self.nemu_ipc.release_touch_nemu_ipc()
        except (AttributeError, NemuIpcError, RequestHumanTakeover, RuntimeError) as e:
            logger.debug(f"释放NemuIpc按键失败: {e}")

class MixControl(BaseMumuControl):
    def __init__(self, mumu: Mumu, serial: str = '127.0.0.1:16416'):
        self.mumu = mumu
        self.nemu_control = NemuIpcControl(mumu, serial)
        self.mode="mumu"
        self.last_screenshot_time=0
        self.screenshot_interval=5
        self._last_action_log = defaultdict(float)
        self._action_log_interval = 1.0
        self._last_resolution_warning_at = 0.0
        self._last_resolution_warning_size: tuple[int, int] | None = None
        self._resolution_warning_interval = 60.0

    def _log_action(self, action: str, detail: str) -> None:
        msg = f"【{self.mode}】{action}: {detail}"
        logger.debug(msg)
        now = time.monotonic()
        key = (self.mode, action)
        if now - self._last_action_log[key] >= self._action_log_interval:
            self._last_action_log[key] = now
            logger.info(msg)

    def switch_to_mumu(self)->None:
        logger.info("切换到mumu")
        self.mode="mumu"
    
    def switch_to_nemu(self)->None:
        logger.info("切换到nemu")
        self.mode="nemu"

    def click(self, x, y)->None:
        self._log_action("Click", f"{x}, {y}")
        if self.mode=="mumu":
            self.mumu.adb.click(x, y)
        else:
            self.nemu_control.click(x, y)

    def swipe(self, x1, y1, x2, y2, duration_s=1)->None:
        self._log_action("Swipe", f"({x1},{y1}) -> ({x2},{y2})")
        if self.mode=="mumu":
            self.mumu.adb.swipe(x1, y1, x2, y2, int(duration_s*1000))
        else:
            self.nemu_control.swipe(x1, y1, x2, y2, duration_s)

    def input_text(self, text)->None:
        if self.mode=="mumu":
            self.mumu.adb.input_text(text)
        else:
            self.nemu_control.input_text(text)

    def screenshot(self):
        """根据当前模式返回相应的截图"""
        from AutoScriptor import cfg
        screenshot=self.nemu_control.screenshot()
        self._warn_if_resolution_mismatch(screenshot)
        if cfg["app"]["debug_mode"] and (t:=time.time()) - self.last_screenshot_time > self.screenshot_interval:
            self.last_screenshot_time = t
            save_debug_screenshot(target=None, screenshot=screenshot, prefix="s")
        return screenshot

    def _warn_if_resolution_mismatch(self, screenshot) -> None:
        actual_size = get_frame_size(screenshot)
        if actual_size is None:
            return
        if actual_size == EXPECTED_FRAME_SIZE:
            self._last_resolution_warning_size = None
            return

        current_time = time.monotonic()
        resolution_changed = actual_size != self._last_resolution_warning_size
        warning_interval_elapsed = (
            current_time - self._last_resolution_warning_at >= self._resolution_warning_interval
        )
        if not resolution_changed and not warning_interval_elapsed:
            return

        self._last_resolution_warning_at = current_time
        self._last_resolution_warning_size = actual_size
        logger.warning(
            "当前 MuMu 截图分辨率为 %sx%s，不符合 AutoScriptor 的 %sx%s 横屏坐标合同；"
            "现有素材、Box 与点击坐标均按绝对像素编写。任务会继续运行，但识别和点击可能偏移，"
            "请在 MuMu 设置中切换为 %sx%s 横屏分辨率。",
            actual_size[0],
            actual_size[1],
            EXPECTED_FRAME_SIZE[0],
            EXPECTED_FRAME_SIZE[1],
            EXPECTED_FRAME_SIZE[0],
            EXPECTED_FRAME_SIZE[1],
        )

    
    def long_click(self, x, y, duration=1.0)->None:
        self._log_action("LongClick", f"{x}, {y} % {duration:0.3f}sec")
        # mumu 长按不支持，连续长按会造成RuntimeError，所以使用nemu_control.long_click
        # self.mumu.adb.swipe(x, y, x, y, int(duration*1000))
        self.nemu_control.long_click(x, y, duration)

    def release_all_keys(self)->None:
        """释放所有按键（主要是触摸按键）"""
        self.nemu_control.release_all_keys()

class ControlModeProxy:
    """临时切换 mixctrl.mode，执行 fn(*args)，再恢复原 mode。"""

    def __init__(self, base: str, control_getter: Callable):
        self._base = base
        self._control_getter = control_getter

    def __call__(self, fn: Callable):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            mixctrl = self._control_getter()
            previous = getattr(mixctrl, "mode", None)
            self._switch(mixctrl, self._base)
            try:
                return fn(*args, **kwargs)
            finally:
                if previous and previous != getattr(mixctrl, "mode", None):
                    self._switch(mixctrl, previous)
        return wrapper

    @staticmethod
    def _switch(mixctrl, base: str):
        if base == "mumu":
            mixctrl.switch_to_mumu()
        elif base == "nemu":
            mixctrl.switch_to_nemu()
        else:
            raise ValueError(f"Invalid base: {base}")
