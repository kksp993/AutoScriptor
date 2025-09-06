from collections.abc import Callable
import threading
import time
from typing import Any
from AutoScriptor import logger
from AutoScriptor.core.api import ui_T
from AutoScriptor.core.targets import Target
DEFAULT_INTERVAL = 0.2

class BackgroundMonitor(threading.Thread):
    def __init__(self):
        super().__init__()
        self.running = True
        self.callbacks = {} # identifier -> callback
        self.signals={}
        self.interval = DEFAULT_INTERVAL
        self._lock = threading.RLock()
        self._stop_event = threading.Event() # Use an Event for graceful stopping
        self.start()
    def run(self):
        while not self._stop_event.is_set():
            if self.callbacks: 
                callbacks_copy = list(self.callbacks.items())
                for name, (idf, callback, once) in callbacks_copy:
                    if ui_T(idf):
                        logger.info(f"🎯 后台检测到: {name} 触发")
                        callback()
                        if once: self.remove(name)
            self._stop_event.wait(self.interval)

    def add(self, name:str, identifier: Target|list[Target]|tuple[Target, ...], callback: Callable[[], None]|list[Callable[[], None]], once:bool=True):
        with self._lock:
            logger.info(f"✅ 添加监控事件: {name}")
            self.set_interval(DEFAULT_INTERVAL)
            
            if isinstance(identifier, Target):
                identifier = (identifier,)
            elif isinstance(identifier, list):
                identifier = tuple(identifier)

            self.callbacks[name] = (identifier, callback, once)


    def remove(self, name:str):
        with self._lock:
            self.callbacks.pop(name, None)

    def clear(self, signals_clear:bool=False):
        with self._lock:
            self.callbacks.clear()
            if signals_clear: self.clear_signals()

    def clear_signals(self):
        with self._lock:
            self.signals.clear()

    def get_idfs(self):
        with self._lock:
            return set(self.callbacks.keys())

    def set_interval(self, interval:int):
        with self._lock:
            self.interval = interval
            logger.info(f"🔄 后台检测间隔设置为 {interval} 秒")

    def stop(self):
        logger.info("❌ 正在停止后台监控...")
        self._stop_event.set() # Signal the thread to stop
        self.join() # Wait for the thread to finish cleanly
        logger.info("✅ 后台监控已停止")

    def signal(self, sig: str, value: Any=None):
        if sig not in self.signals.keys():
            self.signals[sig] = value
        return self.signals[sig]
        
    def set_signal(self, sig: str, value: Any):
        self.signals[sig] = value
        return self.signals[sig]

bg = BackgroundMonitor()

def monitor(idf_callback_pairs:list[tuple[str, Callable[[], None]]]):
    def decorator(fn):
        def wrapper(*args, **kwargs):
            global bg
            for idf, callback in idf_callback_pairs:
                bg.add(idf, callback)
            res = fn(*args, **kwargs)
            for idf, callback in idf_callback_pairs:
                bg.remove(idf)
            return res
        return wrapper
    return decorator
 