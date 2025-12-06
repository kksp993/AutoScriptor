from threading import Thread, RLock, Event
import time
from typing import Any, Callable
from logzero import logger
from AutoScriptor.core.targets import Target

DEFAULT_INTERVAL = 0.2

class BackgroundMonitor(Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self._callbacks = {}  # name -> {idf, cb, once, throttle, last}
        self._signals = {}
        self._interval = DEFAULT_INTERVAL
        self._lock = RLock()
        self._stop_event = Event()
        self.start()

    def run(self):
        from AutoScriptor.core.api import ui_T
        while not self._stop_event.is_set():
            for name, info in list(self._callbacks.items()):
                idf = info['idf']
                if not ui_T(idf):
                    continue
                now = time.time()
                if now - info.get('last', 0) < info.get('throttle', 0):
                    continue
                info['last'] = now
                try:
                    info['cb']()
                except Exception:
                    logger.exception('bg cb error %s', name)
                if info.get('once', True):
                    self.remove(name)
            time.sleep(self._interval)

    def add(self, name: str, identifier, callback: Callable[[], None], once: bool = True, throttle: float = 0):
        if isinstance(identifier, Target):
            identifier = (identifier,)
        with self._lock:
            self._callbacks[name] = {'idf': identifier, 'cb': callback, 'once': once, 'throttle': throttle, 'last': 0}
        logger.info('✅ 添加监控事件: %s', name)

    def remove(self, name: str):
        with self._lock:
            self._callbacks.pop(name, None)

    def clear(self, clear_signals: bool = False):
        with self._lock:
            self._callbacks.clear()
            if clear_signals:
                self._signals.clear()

    def clear_signals(self):
        with self._lock:
            self._signals.clear()
            
    def get_idfs(self):
        with self._lock:
            return set(self._callbacks.keys())

    def set_interval(self, interval: float):
        with self._lock:
            self._interval = interval

    def stop(self):
        self._stop_event.set()
        self.join()

    def signal(self, key: str, default: Any = None):
        return self._signals.get(key, default)

    def set_signal(self, key: str, value: Any):
        self._signals[key] = value
        return value


# lazy proxy
_bg = None
_bg_lock = RLock()

def _ensure_bg():
    global _bg
    with _bg_lock:
        if _bg is None or not _bg.is_alive():
            _bg = BackgroundMonitor()
        return _bg


class BackgroundProxy:
    def __getattr__(self, name):
        return getattr(_ensure_bg(), name)


bg = BackgroundProxy()


def monitor(pairs):
    def deco(fn):
        def wrapper(*a, **k):
            for idf, cb in pairs:
                bg.add(idf, cb)
            r = fn(*a, **k)
            for idf, _ in pairs:
                bg.remove(idf)
            return r
        return wrapper
    return deco
 