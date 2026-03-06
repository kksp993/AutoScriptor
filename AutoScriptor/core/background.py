from collections import deque
from datetime import datetime
from threading import Thread, RLock, Event
import time
from typing import Any, Callable, List
from logzero import logger
from AutoScriptor.core.targets import Target

DEFAULT_INTERVAL = 0.2

class BackgroundMonitor(Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self._callbacks = {}  # name -> {idf, cb, once, throttle, last, allow_concurrent}
        self._signals = {}
        self._interval = DEFAULT_INTERVAL
        self._lock = RLock()
        self._stop_event = Event()
        self._in_callback = False  # 标记：是否正在执行某个常规 callback
        self._event_history: deque = deque(maxlen=50)  # 最近 50 条事件记录
        self.start()

    def _record_event(self, event: str):
        """记录一条事件到环形缓冲区"""
        ts = datetime.now().strftime('%H:%M:%S')
        self._event_history.append(f"[{ts}] {event}")

    def get_event_history(self) -> List[str]:
        """返回最近的事件历史列表"""
        return list(self._event_history)

    def run(self):
        from AutoScriptor.core.api import ui_T
        while not self._stop_event.is_set():
            # 1. 扫描常规（非 allow_concurrent）的 callback
            for name, info in list(self._callbacks.items()):
                if info.get('allow_concurrent'):
                    continue  # concurrent 的在下面统一处理
                idf = info['idf']
                if not ui_T(idf):
                    continue
                now = time.time()
                if now - info.get('last', 0) < info.get('throttle', 0):
                    continue
                info['last'] = now
                # 执行常规 callback，同时启动子线程扫描 concurrent callback
                checker = None
                logger.info('🔔 bg回调触发: %s', name)
                self._record_event(f"回调触发: {name} (identifier: {info['idf']})")
                try:
                    self._in_callback = True
                    checker = Thread(target=self._concurrent_loop, daemon=True, name="BG-Concurrent")
                    checker.start()
                    info['cb']()
                    logger.info('✅ bg回调完成: %s', name)
                    self._record_event(f"回调完成: {name}")
                except Exception:
                    logger.exception('bg cb error %s', name)
                    self._record_event(f"回调异常: {name}")
                finally:
                    self._in_callback = False
                    if checker is not None and checker.is_alive():
                        checker.join(timeout=2)
                if info.get('once', True):
                    self.remove(name)
            # 2. 空闲时也扫描一轮 concurrent callback
            self._check_concurrent()
            time.sleep(self._interval)

    # ── allow_concurrent 支持 ──

    def _concurrent_loop(self):
        """子线程：在常规 callback 执行期间，持续扫描 allow_concurrent 的 callback。"""
        while self._in_callback and not self._stop_event.is_set():
            self._check_concurrent()
            time.sleep(self._interval)

    def _check_concurrent(self):
        """扫描并执行所有 allow_concurrent=True 的 callback（一轮）。"""
        from AutoScriptor.core.api import ui_T
        for name, info in list(self._callbacks.items()):
            if not info.get('allow_concurrent'):
                continue
            idf = info['idf']
            if not ui_T(idf):
                continue
            now = time.time()
            if now - info.get('last', 0) < info.get('throttle', 0):
                continue
            info['last'] = now
            logger.info('🔔 bg并发回调触发: %s', name)
            self._record_event(f"并发回调触发: {name} (identifier: {info['idf']})")
            try:
                info['cb']()
                logger.info('✅ bg并发回调完成: %s', name)
                self._record_event(f"并发回调完成: {name}")
            except Exception:
                logger.exception('bg concurrent cb error %s', name)
                self._record_event(f"并发回调异常: {name}")
            if info.get('once', True):
                self.remove(name)

    def add(self, name: str, identifier, callback: Callable[[], None], once: bool = True, throttle: float = 0, allow_concurrent: bool = False):
        """
        添加后台监控事件。
        allow_concurrent: 若为 True，即使其他 callback 正在执行，此 callback 也会被检测并触发。
                          适用于"知道了"等全局弹窗，默认 False。
        """
        if isinstance(identifier, Target):
            identifier = (identifier,)
        with self._lock:
            self._callbacks[name] = {'idf': identifier, 'cb': callback, 'once': once, 'throttle': throttle, 'last': 0, 'allow_concurrent': allow_concurrent}
        logger.info('✅ 添加监控事件: %s', name)

    def remove(self, name: str):
        with self._lock:
            self._callbacks.pop(name, None)

    def clear(self, clear_signals: bool = False):
        with self._lock:
            self._callbacks.clear()
            if clear_signals:
                self._signals.clear()
        self._record_event(f"clear() 被调用 (clear_signals={clear_signals})")

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
        old_value = self._signals.get(key, '<unset>')
        self._signals[key] = value
        if old_value != value:
            logger.info('📡 signal %s: %s → %s', key, old_value, value)
            self._record_event(f"signal {key}: {old_value} → {value}")
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
 