import time
from collections import defaultdict, deque
from datetime import datetime
from functools import wraps
from typing import Callable
from AutoScriptor.logging.logger import logger
from AutoScriptor.control.MumuAdaptor.mumu import Mumu
from AutoScriptor.control.NemuIpc.device.method.nemu_ipc import (
    NemuIpc,
    NemuIpcError,
    RequestHumanTakeover,
)
from AutoScriptor.recognition.locate import locate_on_screen
from AutoScriptor.core.box import Box
from AutoScriptor.logging.tracer import capture_run_frame

# 输入动作的完整历史。日志里的重复点击有节流（见 _log_action），历史没有：
# 排障要能回答「这一步到底点没点」，而日志少一行不等于没执行。
# 只收离散动作（点击/滑动/长按）；finger_* 是实时循环里的高频事件，收进来会把缓冲冲掉。
# 也刻意不收 input_text：它会带上输入的账号密码，归档不该存这种明文。
_ACTION_HISTORY_LIMIT = 120
_action_history: deque[str] = deque(maxlen=_ACTION_HISTORY_LIMIT)


def get_action_history() -> list[str]:
    """最近输入动作，最早在前；错误归档会整段带走。"""
    return list(_action_history)


def clear_action_history() -> None:
    """每轮任务开始时清空，归档里只留这一轮的操作序列。"""
    _action_history.clear()

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
        return getattr(object.__getattribute__(self, "mumu"), name)
    
class NemuIpcControl(BaseMumuControl):
    def __init__(self, mumu: Mumu, serial: str = '127.0.0.1:16416'):
        self.nemu_ipc = NemuIpc(serial)
        self.mumu = mumu

    def click(self, x, y)->None:
        self.nemu_ipc.click_nemu_ipc(x, y)
        # self.mumu.adb.click(x, y)

    def swipe(self, x1, y1, x2, y2, duration_s=0.5)->None:
        self.nemu_ipc.swipe_nemu_ipc((x1, y1), (x2, y2), speed=0.2)

    def swipe_precise(self, x1, y1, x2, y2, duration_s=0.5)->None:
        """通过 Nemu IPC 按固定直线、端点和时长滑动。"""
        self.nemu_ipc.swipe_precise_nemu_ipc(
            (x1, y1),
            (x2, y2),
            duration_s=duration_s,
        )

    def input_text(self, text)->None:
        self.nemu_ipc.input_text_nemu_ipc(text)

    def screenshot(self):
        """rgb image via NemuIpc"""
        return self.nemu_ipc.screenshot_nemu_ipc()

    def screenshot_region(self, box):
        """只转换给定屏幕区域的快速截图（RGB、正向）。

        ``box`` 为 ``(x, y, width, height)`` 或 ``Box``，使用与点击一致
        的屏幕坐标（左上原点）。返回该区域的 RGB 图像，适合实时检测循环。
        """
        return self.nemu_ipc.screenshot_region_nemu_ipc(box)
    
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

    # 多指 API（finger 1..10）：编号手指是 IPC 原生的多点触控通道。

    def finger_down(self, finger_id, x, y)->None:
        self.nemu_ipc.finger_down_nemu_ipc(finger_id, x, y)

    def finger_move(self, finger_id, x, y)->None:
        self.nemu_ipc.finger_move_nemu_ipc(finger_id, x, y)

    def finger_up(self, finger_id)->None:
        self.nemu_ipc.finger_up_nemu_ipc(finger_id)

    def release_all_fingers(self)->None:
        """兜底释放 1..10 号手指（不会抛错）。"""
        self.nemu_ipc.release_all_fingers_nemu_ipc()

class MixControl(BaseMumuControl):
    def __init__(self, mumu: Mumu, serial: str = '127.0.0.1:16416'):
        self.mumu = mumu
        self.nemu_control = NemuIpcControl(mumu, serial)
        # 默认走 Nemu IPC：截图与输入同源、无 ADB 进程开销、支持多指。
        # 个别 MuMu 版本对 external renderer 输入行为异常（MAA 对
        # MuMuManager < 6.3.2.0 禁用了 IPC 输入），命中失败时回退 ADB。
        self.mode="nemu"
        self._nemu_input_failed = False
        self._last_action_log = defaultdict(float)
        self._action_suppressed = defaultdict(int)
        self._action_log_interval = 1.0
        self._last_resolution_warning_at = 0.0
        self._last_resolution_warning_size: tuple[int, int] | None = None
        self._resolution_warning_interval = 60.0

    def _nemu_routed(self) -> bool:
        """Whether the next input should go through the Nemu IPC channel."""
        return self.mode == "nemu" and not self._nemu_input_failed

    def _fallback_nemu_input(self, action: str, error: Exception) -> None:
        """Switch the input path back to ADB after an IPC input failure.

        Keeps the run alive on ADB when the renderer IPC rejects input, and
        leaves ``switch_to_nemu()`` as the explicit way to re-arm the fast
        path. Screen capture is unaffected: it proved to work in production.
        """
        self._nemu_input_failed = True
        logger.error(
            f"Nemu IPC {action} 输入失败，本次运行已回退到 ADB"
            f"（可调用 switch_to_nemu() 复位重试）: {error}"
        )

    def _log_action(self, action: str, detail: str) -> None:
        msg = f"【{self.mode}】{action}: {detail}"
        logger.debug(msg)
        # 历史不节流：日志少一行只说明被合并，不说明没执行。
        _action_history.append(f"{datetime.now().strftime('%H:%M:%S.%f')[:-3]} {msg}")
        now = time.monotonic()
        key = (self.mode, action)
        if now - self._last_action_log[key] >= self._action_log_interval:
            suppressed = self._action_suppressed[key]
            self._action_suppressed[key] = 0
            self._last_action_log[key] = now
            if suppressed:
                # 不写清楚少了多少条，读日志的人会把「没记录」当成「没执行」。
                msg = f"{msg}（另有 {suppressed} 次同类操作未逐条记录）"
            logger.info(msg)
        else:
            self._action_suppressed[key] += 1

    def switch_to_mumu(self)->None:
        logger.info("切换到mumu")
        self.mode="mumu"
    
    def switch_to_nemu(self)->None:
        logger.info("切换到nemu")
        self.mode="nemu"
        self._nemu_input_failed = False

    def click(self, x, y)->None:
        self._log_action("Click", f"{x}, {y}")
        if self._nemu_routed():
            try:
                self.nemu_control.click(x, y)
                return
            except (NemuIpcError, RequestHumanTakeover) as error:
                self._fallback_nemu_input("Click", error)
        self.mumu.adb.click(x, y)

    def swipe(self, x1, y1, x2, y2, duration_s=1)->None:
        self._log_action("Swipe", f"({x1},{y1}) -> ({x2},{y2})")
        if self._nemu_routed():
            try:
                self.nemu_control.swipe(x1, y1, x2, y2, duration_s)
                return
            except (NemuIpcError, RequestHumanTakeover) as error:
                self._fallback_nemu_input("Swipe", error)
        self.mumu.adb.swipe(x1, y1, x2, y2, int(duration_s*1000))

    def swipe_precise(self, x1, y1, x2, y2, duration_s=1)->None:
        """通过当前 MuMu 实例的 ADB 按指定端点和时长滑动。

        精确滑动不经过 Nemu IPC 的随机贝塞尔轨迹，也不使用 ``b2p`` 的
        随机点击偏移，适合拖动滑块或需要稳定起止坐标的页面操作。
        """
        self._log_action(
            "PreciseSwipe",
            f"({x1},{y1}) -> ({x2},{y2}), duration={duration_s:.3f}s",
        )
        self.nemu_control.swipe_precise(x1, y1, x2, y2, duration_s)

    def input_text(self, text)->None:
        if self._nemu_routed():
            try:
                self.nemu_control.input_text(text)
                return
            except (NemuIpcError, RequestHumanTakeover) as error:
                self._fallback_nemu_input("InputText", error)
        self.mumu.adb.input_text(text)

    def screenshot(self):
        """根据当前模式返回相应的截图"""
        screenshot=self.nemu_control.screenshot()
        self._warn_if_resolution_mismatch(screenshot)
        # 运行期抓帧的开关由 TaskManager 按任务 debug 状态设置，这里只负责送帧。
        capture_run_frame(screenshot)
        return screenshot

    def _warn_if_resolution_mismatch(self, screenshot) -> None:
        # Imported lazily: AutoScriptor.core.api imports this module at import time.
        from AutoScriptor.core.api import EXPECTED_FRAME_SIZE

        frame_shape = getattr(screenshot, "shape", None)
        if frame_shape is None or len(frame_shape) < 2:
            return
        actual_size = (int(frame_shape[1]), int(frame_shape[0]))
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

    def screenshot_region(self, box):
        """只转换给定屏幕区域的快速截图（RGB、正向）。

        ``box`` 为 ``(x, y, width, height)`` 或 ``Box``，屏幕坐标与点击
        一致。实时检测循环应使用本方法而不是全帧截图。
        """
        return self.nemu_control.screenshot_region(box)

    def finger_down(self, finger_id, x, y)->None:
        """按下 1..10 号手指；对同一编号再次调用即拖动。"""
        self.nemu_control.finger_down(finger_id, x, y)

    def finger_move(self, finger_id, x, y)->None:
        """移动已按住的手指（Nemu IPC 没有独立 move：重复 down 即移动）。"""
        self.nemu_control.finger_move(finger_id, x, y)

    def finger_up(self, finger_id)->None:
        """抬起 1..10 号手指。"""
        self.nemu_control.finger_up(finger_id)

    def multi_finger_down(self, contacts)->None:
        """同时按下多根手指。

        ``contacts`` 为 ``[(finger_id, x, y), ...]``；与逐个 click 不同，
        按下的手指之间不会产生中间 up 事件，可表达双指同按/捏合起手。
        """
        for finger_id, x, y in contacts:
            self.nemu_control.finger_down(finger_id, x, y)

    def release_all_fingers(self)->None:
        """兜底释放 1..10 号手指（不会抛错）；实时步骤的 finally 里调用。"""
        self.nemu_control.release_all_fingers()

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
