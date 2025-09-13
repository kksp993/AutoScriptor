import time

from logzero import logger
from AutoScriptor.control.MumuAdaptor.mumu import Mumu
from AutoScriptor.control.NemuIpc.device.method.nemu_ipc import NemuIpc
from AutoScriptor.recognition.rec import locate_on_screen
from AutoScriptor.utils.box import Box

class BaseMumuControl:
    def screenshot(self):
        raise NotImplementedError

    def locate(self, tgt_triples, confidence=0.9, screenshot=None)->Box|None:
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
        """rgb image，若 NemuIpc 初始化缺少 emulator_instance 则回退至 Mumu.adb.screenshot()"""
        try:
            return self.nemu_ipc.screenshot_nemu_ipc()
        except AttributeError as e:
            logger.warning(f"NemuIpcControl.screenshot failed ({e}), fallback to adb screenshot.")
            try:
                return self.mumu.adb.screenshot()
            except Exception as ex:
                logger.error(f"Fallback adb.screenshot() also failed: {ex}")
                return None
    
    def long_click(self, x, y, duration=1.0)->None:
        self.nemu_ipc.long_click_nemu_ipc(x, y, duration)
        # self.mumu.adb.swipe(x, y, x, y, duration+0.1)

    def drag(self, x1, y1, x2, y2, duration=500)->None:
        self.nemu_ipc.swipe_nemu_ipc((x1, y1), (x2, y2), speed=0.2)
        # self.mumu.adb.swipe(x1, y1, x2, y2, duration)

    def switch_to_nemu(self)->None:
        logger.info("切换到nemu")
    

class MixControl(BaseMumuControl):
    def __init__(self, mumu: Mumu, serial: str = '127.0.0.1:16416'):
        self.mumu = mumu
        self.nemu_control = NemuIpcControl(mumu, serial)
        self.mode="mumu"

    def switch_to_mumu(self)->None:
        logger.info("切换到mumu")
        self.mode="mumu"
    
    def switch_to_nemu(self)->None:
        logger.info("切换到nemu")
        self.mode="nemu"

    def click(self, x, y)->None:
        logger.info(f"Click: {x}, {y}")
        if self.mode=="mumu":
            self.mumu.adb.click(x, y)
        else:
            self.nemu_control.click(x, y)

    def swipe(self, x1, y1, x2, y2, duration_s=1)->None:
        logger.info(f"Swipe: ({x1},{y1}) -> ({x2},{y2})")
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
        return self.nemu_control.screenshot()

    
    def long_click(self, x, y, duration=1.0)->None:
        logger.info(f"{self.mode} LongClick: {x}, {y} % {duration:0.3f}sec")
        # if self.mode=="mumu":
        self.mumu.adb.swipe(x, y, x, y, int(duration*1000))
        # else:
        #     self.nemu_control.long_click(x, y, duration)



