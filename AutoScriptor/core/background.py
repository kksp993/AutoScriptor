from collections import deque
from datetime import datetime
from functools import wraps
from threading import Thread, RLock, Event, current_thread, get_ident
import time
from typing import Any, Callable, List
from AutoScriptor.utils.logger import logger
from AutoScriptor.core.targets import Target

DEFAULT_INTERVAL = 1.0

# 常规回调 (allow_concurrent=False) 的 priority：数值越大越先被尝试匹配/触发；
# 内置「前进」(_builtin_advance) 使用最低档，避免先于任务注册的其它常规回调置位。
BG_PRIORITY_DEFAULT = 0
BG_PRIORITY_BUILTIN_ADVANCE = -1_000_000


class BgSignals:
    """Well-known signal names used by battle/task code.

    The values intentionally keep the legacy strings so existing scripts that
    call bg.signal("try_exit") continue to work.
    """

    TRY_EXIT = "try_exit"
    PAUSE_BATTLE = "Pause_battle"
    BUILTIN_ADVANCE = "_builtin_advance"
    FAILED = "failed"
    FAILED_LEGACY = "Failed"
    EXIT = "Exit"


BG_SIGNALS = BgSignals


class BackgroundScope:
    """Context manager for task-local background callbacks.

    New code can use:
        with bg.scope("team") as scope:
            scope.add("entered", I("加载中"), lambda: ...)

    All callbacks registered through the scope are removed on exit, even when
    the task raises. Existing bg.add/bg.remove callers remain supported.
    """

    def __init__(self, monitor: "BackgroundMonitor", prefix: str | None = None, clear_signals: bool = False):
        self._monitor = monitor
        self._prefix = str(prefix).strip() if prefix else ""
        self._clear_signals = clear_signals
        self._items: list[tuple[str, dict | None]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        for name, info in reversed(self._items):
            self._monitor.remove(name, expected_info=info)
        self._items.clear()
        if self._clear_signals:
            self._monitor.clear_signals()
        return False

    def _name(self, name: str) -> str:
        raw = str(name)
        if not self._prefix or raw.startswith(f"{self._prefix}:"):
            return raw
        return f"{self._prefix}:{raw}"

    def add(self, name: str, identifier, callback: Callable[[], None], **kwargs) -> str:
        full_name = self._name(name)
        full_name, info = self._monitor._register_callback(full_name, identifier, callback, **kwargs)
        self._items.append((full_name, info))
        return full_name

    def remove(self, name: str):
        full_name = self._name(name)
        remaining = []
        for item_name, info in self._items:
            if item_name == full_name:
                self._monitor.remove(item_name, expected_info=info)
            else:
                remaining.append((item_name, info))
        self._items = remaining

    def signal(self, key: str, default: Any = None):
        return self._monitor.signal(key, default)

    def set_signal(self, key: str, value: Any):
        return self._monitor.set_signal(key, value)

    def wait_signal(self, *args, **kwargs):
        return self._monitor.wait_signal(*args, **kwargs)


class BackgroundClearProtection:
    """Temporarily ignore external bg.clear() calls for critical sections."""

    def __init__(self, monitor: "BackgroundMonitor"):
        self._monitor = monitor

    def __enter__(self):
        with self._monitor._lock:
            self._monitor._external_clear_protect_count += 1
        return self

    def __exit__(self, exc_type, exc, tb):
        with self._monitor._lock:
            self._monitor._external_clear_protect_count = max(
                0,
                self._monitor._external_clear_protect_count - 1,
            )
        return False


class BackgroundMonitor(Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self._callbacks = {}  # name -> {idf, cb, once, throttle, last, allow_concurrent, priority}
        self._signals = {}
        self._interval = DEFAULT_INTERVAL
        self._lock = RLock()
        self._stop_event = Event()
        self._in_callback = False  # 标记：是否正在执行某个常规 callback
        self._event_history: deque = deque(maxlen=50)  # 最近 50 条事件记录
        self._mutation_version = 0
        self._external_clear_protect_count = 0
        self._callback_thread_ids: set[int] = set()
        self.start()

    def _record_event(self, event: str):
        """记录一条事件到环形缓冲区"""
        ts = datetime.now().strftime('%H:%M:%S')
        self._event_history.append(f"[{ts}] {event}")

    def get_event_history(self) -> List[str]:
        """返回最近的事件历史列表"""
        return list(self._event_history)

    def _any_callback_eligible_for_scan(self, snapshot: list) -> bool:
        """本帧是否有至少一个回调已过 throttle、需要截图并 locate（否则不截屏，避免与主线程争 IPC）。"""
        now = time.time()
        for _name, info in snapshot:
            if now - info.get('last', 0) < info.get('throttle', 0):
                continue
            return True
        return False

    def _callback_is_current(self, name: str, info: dict) -> bool:
        """Return False when a stale snapshot entry was removed/replaced."""
        with self._lock:
            return self._callbacks.get(name) is info

    def _enter_callback_thread(self):
        with self._lock:
            self._callback_thread_ids.add(get_ident())

    def _exit_callback_thread(self):
        with self._lock:
            self._callback_thread_ids.discard(get_ident())

    def _current_thread_can_clear(self) -> bool:
        with self._lock:
            return current_thread() is self or get_ident() in self._callback_thread_ids

    def run(self):
        from AutoScriptor.core.api import _locate_all, first as _first
        import AutoScriptor.core.api as _core_api
        while not self._stop_event.is_set():
            with self._lock:
                snapshot = list(self._callbacks.items())

            # 全部在 throttle 冷却内时：不截屏、不 locate，直接 sleep（主线程 click 不被截图拖慢）
            if not self._any_callback_eligible_for_scan(snapshot):
                time.sleep(self._interval)
                continue

            try:
                mc = _core_api.mixctrl
                screenshot = mc.screenshot() if mc is not None else None
            except Exception:
                screenshot = None
                time.sleep(self._interval)
                continue

            # 先扫描 allow_concurrent（如「知道了」、爆 等），再扫描常规回调（如 _builtin_advance「前进」）。
            # 若顺序相反，同一帧内内置前进会先置位 _builtin_advance，战斗主循环优先 travel()，弹窗无法及时关闭。
            if screenshot is not None:
                self._check_concurrent(screenshot=screenshot)

            # Build a batch of (name, info, flat_targets) for ONE shared locate call
            pending: list[tuple[str, dict, list[Target]]] = []
            all_targets: list[Target] = []
            offsets: list[tuple[int, int]] = []  # (start, end) in all_targets

            rows: list[tuple[int, str, dict, list[Target]]] = []
            for name, info in snapshot:
                if info.get('allow_concurrent'):
                    continue
                now = time.time()
                if now - info.get('last', 0) < info.get('throttle', 0):
                    continue
                idf = info['idf']
                targets = list(idf) if isinstance(idf, (list, tuple)) else [idf]
                pr = info.get('priority', BG_PRIORITY_DEFAULT)
                rows.append((pr, name, info, targets))
            rows.sort(key=lambda r: -r[0])
            for _pr, name, info, targets in rows:
                start = len(all_targets)
                all_targets.extend(targets)
                offsets.append((start, len(all_targets)))
                pending.append((name, info, targets))

            # One batch locate call for ALL callback identifiers
            if pending and all_targets and screenshot is not None:
                try:
                    boxes = _locate_all(tuple(all_targets), screenshot=screenshot, image_first=True)
                except Exception:
                    boxes = [None] * len(all_targets)

                for (name, info, _targets), (start, end) in zip(pending, offsets):
                    if not self._callback_is_current(name, info):
                        continue
                    segment = boxes[start:end]
                    if not _first(segment):
                        continue
                    if not self._callback_is_current(name, info):
                        continue
                    info['last'] = time.time()
                    checker = None
                    logger.info('🔔 bg回调触发: %s', name)
                    self._record_event(f"回调触发: {name} (identifier: {info['idf']})")
                    try:
                        self._in_callback = True
                        checker = Thread(target=self._concurrent_loop, daemon=True, name="BG-Concurrent")
                        checker.start()
                        self._enter_callback_thread()
                        try:
                            info['cb']()
                        finally:
                            self._exit_callback_thread()
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
                        self.remove(name, expected_info=info)

            time.sleep(self._interval)

    # ── allow_concurrent 支持 ──

    def _concurrent_loop(self):
        """子线程：在常规 callback 执行期间，持续扫描 allow_concurrent 的 callback。"""
        while self._in_callback and not self._stop_event.is_set():
            self._check_concurrent()
            time.sleep(self._interval)

    def _check_concurrent(self, screenshot=None):
        """Batch-scan all allow_concurrent=True callbacks in one locate call."""
        from AutoScriptor.core.api import _locate_all, first as _first
        import AutoScriptor.core.api as _core_api

        pending: list[tuple[str, dict, list[Target]]] = []
        all_targets: list[Target] = []
        offsets: list[tuple[int, int]] = []

        with self._lock:
            snapshot = list(self._callbacks.items())

        for name, info in snapshot:
            if not info.get('allow_concurrent'):
                continue
            now = time.time()
            if now - info.get('last', 0) < info.get('throttle', 0):
                continue
            idf = info['idf']
            targets = list(idf) if isinstance(idf, (list, tuple)) else [idf]
            start = len(all_targets)
            all_targets.extend(targets)
            offsets.append((start, len(all_targets)))
            pending.append((name, info, targets))

        if not pending or not all_targets:
            return

        if screenshot is None:
            try:
                mc = _core_api.mixctrl
                screenshot = mc.screenshot() if mc is not None else None
            except Exception:
                return

        try:
            boxes = _locate_all(tuple(all_targets), screenshot=screenshot, image_first=True)
        except Exception:
            return

        for (name, info, _), (start, end) in zip(pending, offsets):
            if not self._callback_is_current(name, info):
                continue
            segment = boxes[start:end]
            if not _first(segment):
                continue
            if not self._callback_is_current(name, info):
                continue
            info['last'] = time.time()
            logger.info('🔔 bg并发回调触发: %s', name)
            self._record_event(f"并发回调触发: {name} (identifier: {info['idf']})")
            try:
                self._enter_callback_thread()
                try:
                    info['cb']()
                finally:
                    self._exit_callback_thread()
                logger.info('✅ bg并发回调完成: %s', name)
                self._record_event(f"并发回调完成: {name}")
            except Exception:
                logger.exception('bg concurrent cb error %s', name)
                self._record_event(f"并发回调异常: {name}")
            if info.get('once', True):
                self.remove(name, expected_info=info)

    def _register_callback(
        self,
        name: str,
        identifier,
        callback: Callable[[], None],
        once: bool = True,
        throttle: float = 0,
        allow_concurrent: bool = False,
        priority: int = BG_PRIORITY_DEFAULT,
    ) -> tuple[str, dict]:
        if isinstance(identifier, Target):
            identifier = (identifier,)
        info = {
            'idf': identifier,
            'cb': callback,
            'once': once,
            'throttle': throttle,
            'last': 0,
            'allow_concurrent': allow_concurrent,
            'priority': priority,
        }
        with self._lock:
            self._callbacks[name] = info
            self._mutation_version += 1
        logger.info('✅ 添加监控事件: %s', name)
        return name, info

    def add(
        self,
        name: str,
        identifier,
        callback: Callable[[], None],
        once: bool = True,
        throttle: float = 0,
        allow_concurrent: bool = False,
        priority: int = BG_PRIORITY_DEFAULT,
    ):
        """
        添加后台监控事件。
        allow_concurrent: 若为 True，即使其他 callback 正在执行，此 callback 也会被检测并触发。
                          适用于"知道了"等全局弹窗，默认 False。
        priority: 仅对常规回调 (allow_concurrent=False) 生效；数值越大越先匹配。
                  内置「前进」使用 BG_PRIORITY_BUILTIN_ADVANCE（最低）。
        """
        self._register_callback(
            name=name,
            identifier=identifier,
            callback=callback,
            once=once,
            throttle=throttle,
            allow_concurrent=allow_concurrent,
            priority=priority,
        )
        return name

    def remove(self, name: str, expected_info: dict | None = None):
        with self._lock:
            if expected_info is not None and self._callbacks.get(name) is not expected_info:
                return
            if name in self._callbacks:
                self._callbacks.pop(name, None)
                self._mutation_version += 1

    def clear(self, clear_signals: bool = False, *, force: bool = False):
        with self._lock:
            if (
                self._external_clear_protect_count > 0
                and not force
                and not self._current_thread_can_clear()
            ):
                self._record_event(f"external clear() ignored during protected section (clear_signals={clear_signals})")
                logger.warning("bg.clear() ignored during protected battle section")
                return
            if self._callbacks:
                self._callbacks.clear()
                self._mutation_version += 1
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
        if current_thread() is not self and self.is_alive():
            self.join()

    def signal(self, key: str, default: Any = None):
        with self._lock:
            return self._signals.get(key, default)

    def set_signal(self, key: str, value: Any):
        with self._lock:
            old_value = self._signals.get(key, '<unset>')
            self._signals[key] = value
        if old_value != value:
            logger.info('📡 signal %s: %s → %s', key, old_value, value)
            self._record_event(f"signal {key}: {old_value} → {value}")
        return value

    def wait_signal(
        self,
        key: str,
        expected: Any = True,
        *,
        timeout: float | None = None,
        interval: float = 0.2,
        default: Any = None,
    ):
        """Wait until a signal reaches expected.

        expected may be a literal value or a predicate callable. A TimeoutError
        is raised when timeout is provided and the condition is not met.
        """
        start = time.time()
        while True:
            current = self.signal(key, default)
            matched = expected(current) if callable(expected) else current == expected
            if matched:
                return current
            if timeout is not None and time.time() - start >= timeout:
                raise TimeoutError(f"等待 signal 超时: {key} != {expected!r}")
            time.sleep(interval)

    def scope(self, prefix: str | None = None, *, clear_signals: bool = False) -> BackgroundScope:
        return BackgroundScope(self, prefix=prefix, clear_signals=clear_signals)

    def protect_clear(self) -> BackgroundClearProtection:
        return BackgroundClearProtection(self)


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
        @wraps(fn)
        def wrapper(*a, **k):
            with bg.scope() as scope:
                for idx, item in enumerate(pairs):
                    if isinstance(item, dict):
                        kwargs = dict(item)
                        name = kwargs.pop("name", f"{fn.__name__}:{idx}")
                        identifier = kwargs.pop("identifier")
                        callback = kwargs.pop("callback")
                        scope.add(name=name, identifier=identifier, callback=callback, **kwargs)
                    else:
                        if len(item) == 3:
                            name, identifier, callback = item
                        elif len(item) == 2:
                            identifier, callback = item
                            name = f"{fn.__name__}:{idx}"
                        else:
                            raise ValueError("monitor pair must be (identifier, callback) or (name, identifier, callback)")
                        scope.add(name=name, identifier=identifier, callback=callback)
                return fn(*a, **k)
        return wrapper
    return deco
