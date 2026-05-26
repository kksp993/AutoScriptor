"""
AutoScriptor 后台定时调度器
===========================
轻量 daemon 线程，动态 sleep 到最早到期任务，扫描并执行。

状态机：
  PENDING ─── activate() ───▶ RUNNING
  RUNNING ─── 正常完成/未验证 ──▶ PENDING
  RUNNING ─── 连续失败 ≥3 ─────▶ ERROR
  ERROR   ─── reset() ────────▶ PENDING

安全策略：
  - 不使用 os.execv / PyThreadState_SetAsyncExc
  - Ctrl+C 由 run.py 主线程处理，调度器仅响应 cooperative cancel
"""

import os
import time
import threading
from enum import Enum
from AutoScriptor.utils.cancel import TaskCancelled
from AutoScriptor.utils.logger import logger

from services.core.runtime_context import runtime_ctx
from services.core.notify import notify_from_config


class SchedulerState(Enum):
    PENDING = "pending"
    RUNNING = "running"
    ERROR   = "error"


CHECK_INTERVAL = 3600
MAX_CONSECUTIVE_ERRORS = 3


def collect_active_times_from_tasks_tree(tasks: dict) -> list[float]:
    """收集任务树中所有 on=True 且已注册任务的「有效」下次执行时间（含 sched_window / 星期限制）。"""
    from AutoScriptor.utils.task_registry import task_registry
    from services.core.task_manager import (
        parse_sched_window_hours,
        clamp_to_sched_window,
        parse_allowed_weekdays,
        calc_next_allowed_weekday_ts,
    )
    import datetime as _dt

    now_ts = time.time()
    result: list[float] = []

    def _walk(node: dict, prefix: str = "") -> None:
        for key, val in node.items():
            if not isinstance(val, dict):
                continue
            path = f"{prefix}/{key}" if prefix else key
            if "on" in val:
                if val.get("on") and task_registry.has_task(path):
                    if is_human_takeover_blocked(val):
                        continue
                    raw = float(val.get("next_exec_time", 0) or 0)
                    sw = parse_sched_window_hours(val)
                    effective = clamp_to_sched_window(max(raw, now_ts), sw[0], sw[1]) if sw else (raw or now_ts)
                    aw = parse_allowed_weekdays(val)
                    if aw is not None:
                        now_dt = _dt.datetime.fromtimestamp(now_ts)
                        wd = now_dt.weekday() + 1
                        if effective <= now_ts and wd not in set(aw):
                            effective = calc_next_allowed_weekday_ts(now_dt, aw)
                        elif effective > now_ts:
                            tdt = _dt.datetime.fromtimestamp(effective)
                            if (tdt.weekday() + 1) not in set(aw):
                                effective = calc_next_allowed_weekday_ts(tdt, aw)
                    result.append(effective)
            else:
                _walk(val, path)

    _walk(tasks or {})
    return result


def iter_dispatch_characters(cfg):
    """Yield valid dispatch queue characters in the exact configured order."""
    chars = cfg._account_data.get("characters", {}) or {}
    seen: set[tuple[str, str]] = set()
    for item in cfg._account_data.get("dispatch_queue", []) or []:
        server = (item.get("server") or "").strip()
        name = (item.get("name") or "").strip()
        if not server or not name:
            continue
        key = (server, name)
        if key in seen:
            continue
        if server not in chars or name not in chars[server]:
            continue
        seen.add(key)
        yield key


def collect_active_times_from_all_characters(cfg, dispatch_only: bool = False) -> list[float]:
    """当前账号下所有角色的「有效」下次执行时间（与总览 / all_tasks_summary 一致）。"""
    ac = cfg.active_character()
    active_server = ac.get("server", "")
    active_name = ac.get("name", "")
    chars = cfg._account_data.get("characters", {}) or {}
    result: list[float] = []
    if dispatch_only:
        char_keys = list(iter_dispatch_characters(cfg))
    else:
        char_keys = [
            (srv, char_name)
            for srv, srv_chars in chars.items()
            for char_name in srv_chars.keys()
        ]
    for srv, char_name in char_keys:
        if srv == active_server and char_name == active_name:
            tasks_tree = cfg._config.get("tasks", {})
        else:
            tasks_tree = chars.get(srv, {}).get(char_name, {}).get("tasks", {}) or {}
        result.extend(collect_active_times_from_tasks_tree(tasks_tree))
    return result


def next_display_timestamp_from_times(times: list[float]) -> float | None:
    """与 Scheduler.get_next_execution_timestamp 一致：有到期则返回当前时刻，否则最早未来时间。"""
    now = time.time()
    if not times:
        return None
    if any(t <= now for t in times):
        return now
    return min(times)


def is_task_due(val: dict, path: str, now_ts: float) -> bool:
    """判定单个任务是否到期（与 Scheduler._collect_due 完全一致的判定逻辑，无副作用）。"""
    from AutoScriptor.utils.task_registry import task_registry
    from services.core.task_manager import (
        parse_sched_window_hours,
        clamp_to_sched_window,
        parse_allowed_weekdays,
    )
    import datetime as _dt

    if not val.get("on"):
        return False
    if is_human_takeover_blocked(val):
        return False
    if not task_registry.has_task(path):
        return False
    if now_ts < val.get("next_exec_time", 0):
        return False
    sw = parse_sched_window_hours(val)
    if sw is not None:
        deferred = clamp_to_sched_window(now_ts, sw[0], sw[1])
        if deferred > now_ts:
            return False
    aw = parse_allowed_weekdays(val)
    if aw is not None:
        wd = _dt.datetime.fromtimestamp(now_ts).weekday() + 1
        if wd not in set(aw):
            return False
    return True


def is_task_debug_mode(task_path: str, task_data: dict | None = None) -> bool:
    """Lightweight debug-mode lookup that does not import task runtime modules."""
    from AutoScriptor.utils.app_config import cfg
    from AutoScriptor.utils.task_registry import task_registry
    import dpath

    if task_registry.get_debug_mode(task_path):
        return True
    if isinstance(task_data, dict):
        return bool(task_data.get("debug_mode") or task_data.get("debug"))
    try:
        data = dpath.get(cfg["tasks"], task_path)
    except Exception:
        return False
    return isinstance(data, dict) and bool(data.get("debug_mode") or data.get("debug"))


def is_human_takeover_blocked(val: dict) -> bool:
    """人工接管后的红色冻结态：展示为错误，但不参与自动调度。"""
    return bool(val.get("human_takeover") or val.get("human_takeover_error"))


def calc_effective_next_time(val: dict, now_ts: float) -> float:
    """计算任务的有效下次执行时间（用于展示），与 collect_active_times_from_tasks_tree 一致。"""
    from services.core.task_manager import (
        parse_sched_window_hours,
        clamp_to_sched_window,
        parse_allowed_weekdays,
        calc_next_allowed_weekday_ts,
    )
    import datetime as _dt

    nxt = float(val.get("next_exec_time", 0) or 0)
    sw = parse_sched_window_hours(val)
    eff = clamp_to_sched_window(max(nxt, now_ts), sw[0], sw[1]) if sw else (nxt or now_ts)
    aw = parse_allowed_weekdays(val)
    if aw is not None:
        now_dt = _dt.datetime.fromtimestamp(now_ts)
        wd = now_dt.weekday() + 1
        if eff <= now_ts and wd not in set(aw):
            eff = calc_next_allowed_weekday_ts(now_dt, aw)
        elif eff > now_ts:
            tdt = _dt.datetime.fromtimestamp(eff)
            if (tdt.weekday() + 1) not in set(aw):
                eff = calc_next_allowed_weekday_ts(tdt, aw)
    return eff


_STATE_LABELS = {"pending": "待运行", "running": "运行中", "error": "发生错误"}
_STATE_COLORS = {"pending": "green", "running": "orange", "error": "red"}


class Scheduler:
    """后台调度器。daemon 线程 + Event.wait，cooperative cancellation。"""

    def __init__(self):
        self.state = SchedulerState.PENDING
        self._task_manager = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._tasks_updated = threading.Event()
        self._pipeline_active = threading.Event()
        self._reload_deferred = threading.Event()
        self._consecutive_errors = 0
        self._logged_in_character: tuple[str, str] | None = None  # (server, name)
        self._retry_exhausted_tasks: set[tuple[str, str, str]] = set()

    # ── 注入 ──

    def set_task_manager(self, tm):
        self._task_manager = tm

    # ── 状态转换 ──

    def _transition(self, target: SchedulerState):
        if self.state != target:
            logger.info("📅 调度器: %s → %s", self.state.value, target.value)
        self.state = target

    def activate(self):
        if self.state == SchedulerState.ERROR:
            return
        if self.state != SchedulerState.RUNNING:
            self._clear_retry_exhaustion()
        self._transition(SchedulerState.RUNNING)
        self._consecutive_errors = 0
        if self._task_manager:
            self._task_manager._reset_cancel()
        if not self._thread or not self._thread.is_alive():
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, daemon=True, name="Scheduler")
            self._thread.start()

    def deactivate(self):
        self._transition(SchedulerState.PENDING)

    def mark_error(self):
        logger.error("📅 连续失败 %d 次，进入 ERROR 状态", self._consecutive_errors)
        self._transition(SchedulerState.ERROR)
        notify_from_config(
            title="AutoScriptor 调度器错误",
            content=f"连续失败 {self._consecutive_errors} 次，调度器已暂停"
        )

    def reset(self):
        self._transition(SchedulerState.PENDING)
        self._consecutive_errors = 0
        self._clear_retry_exhaustion()
        if self._task_manager:
            self._task_manager._reset_cancel()

    def request_stop(self):
        """Ctrl+C 时由主线程调用：cooperative cancel + 回到 PENDING。"""
        logger.info("⏹ 收到停止请求，正在优雅停止任务...")
        if self._task_manager:
            self._task_manager.request_cancel()
        self.deactivate()
        self._wake.set()

    def wake(self):
        self._wake.set()

    def _check_cancel_requested(self) -> None:
        if self._task_manager and self._task_manager._cancel_event.is_set():
            raise TaskCancelled("scheduler stop requested")

    def stop(self, timeout: float | None = None):
        self._stop.set()
        self._wake.set()
        if self._thread and self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(timeout)

    def consume_tasks_updated(self) -> bool:
        if self._tasks_updated.is_set():
            self._tasks_updated.clear()
            return True
        return False

    @property
    def is_executing(self) -> bool:
        return self._pipeline_active.is_set()

    def _reload_tasks_from_disk(self, *, reason: str) -> bool:
        """Reload config/tasks at a safe boundary."""
        from AutoScriptor.utils.app_config import cfg

        try:
            # 必须通过 TaskManager.reload_tasks() 重载：内部会在 load_config 前保存 game，
            # 无安全密码时写回，避免先 cfg.load_config() 清空 game 导致 character_name 丢失。
            if self._task_manager:
                self._task_manager.reload_tasks()
            else:
                cfg.load_config()
            self._tasks_updated.set()
            self._reload_deferred.clear()
            if reason:
                logger.info("📅 已应用延迟重载: %s", reason)
            return True
        except Exception as e:
            logger.warning("配置热重载失败: %s", e)
            return False

    def _handle_watched_config_change(self) -> None:
        if self.is_executing:
            from AutoScriptor.utils.app_config import cfg

            if not self._reload_deferred.is_set():
                logger.info("📅 检测到运行期配置变更，延迟到当前任务结束后重载")
            try:
                # 运行中只同步 cfg，避免后续 cfg.save_config() 用旧内存覆盖磁盘变更。
                # 任务注册表热重载会清 bg，必须等当前任务退出后再做。
                cfg.reload_preserving_decrypted_credentials()
            except Exception as e:
                logger.warning("运行期配置同步失败，将在任务结束后重试: %s", e)
            self._reload_deferred.set()
            self._tasks_updated.set()
            return
        self._reload_tasks_from_disk(reason="配置文件变更")

    def _apply_deferred_reload_if_needed(self) -> bool:
        if not self._reload_deferred.is_set():
            return False
        logger.info("📅 正在应用运行期延迟重载")
        return self._reload_tasks_from_disk(reason="运行期配置变更")

    # ── 结果反馈 ──

    def record_result(self, success: int, failed: int):
        if failed == 0:
            self._consecutive_errors = 0
        else:
            self._consecutive_errors += 1
            if self._consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                self.mark_error()

    # ── 调度周期 retry 上限 ──

    @staticmethod
    def _retry_key(char_key: tuple[str, str], task_key: str) -> tuple[str, str, str]:
        return char_key[0] or "", char_key[1] or "", task_key

    def _clear_retry_exhaustion(self) -> None:
        self._retry_exhausted_tasks.clear()

    def _is_retry_exhausted(self, char_key: tuple[str, str], task_key: str) -> bool:
        return self._retry_key(char_key, task_key) in self._retry_exhausted_tasks

    def _mark_retry_exhausted(self, char_key: tuple[str, str], task_key: str, max_retry: int) -> None:
        key = self._retry_key(char_key, task_key)
        if key in self._retry_exhausted_tasks:
            return
        self._retry_exhausted_tasks.add(key)
        logger.warning(
            "📅 任务已达到本次调度周期 retry 上限，后续将跳过直到重新启动调度: %s/%s %s (max_retry=%d)",
            key[0],
            key[1],
            key[2],
            max_retry,
        )

    def _filter_retry_available(self, char_key: tuple[str, str], tasks: list[str]) -> list[str]:
        available = []
        for task_key in tasks:
            if self._is_retry_exhausted(char_key, task_key):
                logger.info("📅 跳过本调度周期已耗尽 retry 的任务: %s/%s %s", char_key[0], char_key[1], task_key)
                continue
            available.append(task_key)
        return available

    # ── 任务时间收集（共用） ──

    def _collect_active_times(self) -> list[float]:
        """收集当前账号下所有角色的 on=True 任务的「有效」下次执行时间（含 sched_window 等）。"""
        from AutoScriptor.utils.app_config import cfg
        from AutoScriptor.utils.task_registry import task_registry

        if not self._retry_exhausted_tasks:
            return collect_active_times_from_all_characters(cfg, dispatch_only=True)

        now_ts = time.time()
        result: list[float] = []
        active = cfg.active_character()
        active_key = (active.get("server", ""), active.get("name", ""))
        chars = cfg._account_data.get("characters", {}) or {}

        def _walk(node: dict, prefix: str, char_key: tuple[str, str]) -> None:
            for key, val in node.items():
                if not isinstance(val, dict):
                    continue
                path = f"{prefix}/{key}" if prefix else key
                if "on" in val:
                    if (
                        val.get("on")
                        and task_registry.has_task(path)
                        and not self._is_retry_exhausted(char_key, path)
                    ):
                        result.append(calc_effective_next_time(val, now_ts))
                else:
                    _walk(val, path, char_key)

        for server, name in self._iter_characters_schedule_order():
            char_key = (server, name)
            if char_key == active_key:
                tasks_tree = cfg._config.get("tasks", {}) or {}
            else:
                tasks_tree = chars.get(server, {}).get(name, {}).get("tasks", {}) or {}
            _walk(tasks_tree, "", char_key)
        return result

    def _get_wait_interval(self) -> float:
        times = self._collect_active_times()
        if not times:
            return CHECK_INTERVAL
        now = time.time()
        if any(t <= now for t in times):
            return 0
        return max(min(times) - now, 0)

    def _earliest_future_active_time(self) -> float | None:
        """仅统计严格晚于当前时刻的 next_exec_time（供每日 5:00 重启等逻辑使用）。"""
        now = time.time()
        future = [t for t in self._collect_active_times() if t > now]
        return min(future) if future else None

    def get_next_execution_timestamp(self) -> float | None:
        """对外展示的「下次执行」：若有已到期任务则视为即刻，否则为最早的未来计划时间。"""
        return next_display_timestamp_from_times(self._collect_active_times())

    # ── 后台主循环 ──

    def _loop(self):
        from services.core.watcher import ConfigWatcher
        from AutoScriptor.utils.app_config import cfg
        from AutoScriptor.utils.paths import get_battle_character_dir, get_custom_task_dir

        def _extra_reload_paths() -> list[str]:
            paths = [
                str(get_battle_character_dir()),
                str(get_custom_task_dir()),
            ]
            if cfg.current_account():
                paths.append(cfg._account_path(cfg.current_account()))
            return paths

        watcher = ConfigWatcher(
            cfg.CONFIG_PATH,
            extra_paths=_extra_reload_paths,
        )
        watcher.start_watching()
        while True:
            self._wake.clear()
            self._wake.wait(self._get_wait_interval())
            if self._stop.is_set():
                break
            if watcher.should_reload():
                self._handle_watched_config_change()
            if self.state == SchedulerState.RUNNING and self._task_manager:
                try:
                    self._check_and_run()
                except Exception as e:
                    logger.error("📅 调度执行意外崩溃，将在下一轮重试: %s", e, exc_info=True)
                    self._consecutive_errors += 1
                    if self._consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                        self.mark_error()

    # ── 到期任务收集 ──

    def _collect_due(self, node: dict, prefix: str, now_ts: float) -> list[str]:
        from AutoScriptor.utils.task_registry import task_registry
        from AutoScriptor.utils.app_config import cfg
        from services.core.task_manager import (
            parse_sched_window_hours,
            clamp_to_sched_window,
            parse_allowed_weekdays,
            calc_next_allowed_weekday_ts,
        )
        import datetime as _dt

        tasks = []
        for key, val in node.items():
            if not isinstance(val, dict):
                continue
            path = f"{prefix}/{key}" if prefix else key
            if "on" in val:
                if (
                    val.get("on")
                    and not is_human_takeover_blocked(val)
                    and now_ts >= val.get("next_exec_time", 0)
                    and task_registry.has_task(path)
                ):
                    sw = parse_sched_window_hours(val)
                    if sw is not None:
                        deferred = clamp_to_sched_window(now_ts, sw[0], sw[1])
                        if deferred > now_ts:
                            val["next_exec_time"] = deferred
                            logger.info(
                                "📅 任务 %s 不在开放时段 [%02d:00,%02d:00)，已推迟至 %s",
                                path, sw[0], sw[1],
                                _dt.datetime.fromtimestamp(deferred).strftime("%Y-%m-%d %H:%M"),
                            )
                            cfg.save_config()
                            self._tasks_updated.set()
                            continue
                    aw = parse_allowed_weekdays(val)
                    if aw is not None:
                        now_dt = _dt.datetime.fromtimestamp(now_ts)
                        wd = now_dt.weekday() + 1
                        if wd not in set(aw):
                            deferred = calc_next_allowed_weekday_ts(now_dt, aw)
                            val["next_exec_time"] = deferred
                            logger.info(
                                "📅 任务 %s 仅允许星期 %s（当前周%d），已推迟至 %s",
                                path, aw, wd,
                                _dt.datetime.fromtimestamp(deferred).strftime("%Y-%m-%d %H:%M"),
                            )
                            cfg.save_config()
                            self._tasks_updated.set()
                            continue
                    tasks.append(path)
            else:
                tasks.extend(self._collect_due(val, path, now_ts))
        return tasks

    def _iter_characters_schedule_order(self):
        """调度顺序：优先账号内 dispatch_queue，其余按服务器名、角色名排序。"""
        from AutoScriptor.utils.app_config import cfg

        yield from iter_dispatch_characters(cfg)

    def _collect_due_cross_character(self) -> list[str]:
        """
        收集到期任务路径；若当前角色无到期，则按顺序切换到下一有到期任务的角色。
        与总览多角色统计一致，避免「全角色调度」后活动角色停在队列末尾时其他角色永不执行。
        """
        from AutoScriptor.utils.app_config import cfg

        original = cfg.active_character()
        original_key = (original.get("server", ""), original.get("name", ""))
        dispatch_order = list(self._iter_characters_schedule_order())
        if not dispatch_order:
            logger.info("📅 dispatch_queue is empty; scheduler has no characters to run")
            return []
        switched = False
        for server, name in dispatch_order:
            ac = cfg.active_character()
            cur = (ac.get("server", ""), ac.get("name", ""))
            if (server, name) == cur:
                due = self._collect_due(cfg.get("tasks") or {}, "", time.time())
            else:
                try:
                    if self._task_manager:
                        self._task_manager.switch_character_and_reload(server, name)
                    else:
                        cfg.switch_character(server, name)
                except (KeyError, ValueError) as e:
                    logger.warning("📅 切换角色跳过 %s/%s: %s", server, name, e)
                    continue
                switched = True
                self.invalidate_login()
                due = self._collect_due(cfg.get("tasks") or {}, "", time.time())
            due = self._filter_retry_available((server, name), due)
            if due:
                if switched:
                    self._tasks_updated.set()
                return due
        if switched and original_key[0] and original_key[1]:
            try:
                if self._task_manager:
                    self._task_manager.switch_character_and_reload(*original_key)
                else:
                    cfg.switch_character(*original_key)
                self.invalidate_login()
            except (KeyError, ValueError) as e:
                logger.warning("📅 恢复原角色失败 %s/%s: %s", original_key[0], original_key[1], e)
        return []

    # ── 共用执行管线 ──

    def _run_task_pipeline(self, explicit_tasks: list[str] | None = None):
        """
        统一的任务执行管线，调度模式和单任务模式共用。

        explicit_tasks=None  → 调度模式，由 _collect_due() 动态收集到期任务
        explicit_tasks=[...] → 单任务模式，执行外部传入的固定列表（仍复用登录确认与中断控制）
        """
        import inspect
        from AutoScriptor.utils.app_config import cfg
        from AutoScriptor.utils.perf import ABOVE_NORMAL_PRIORITY_CLASS, boost, unboost

        if not cfg._config.get("game", {}).get("character_name", ""):
            logger.warning("⚠️ 账号未验证，跳过执行")
            return

        total_success = total_failed = 0
        max_retry = int(cfg["app"].get("max_retry", 0) or 0)
        retry_round = 0
        attempted_this_round: set[tuple[str, str, str]] = set()
        retry_queue: list[tuple[tuple[str, str], str]] = []
        failed_next_round: list[tuple[tuple[str, str], str]] = []
        only_debug_tasks_executed = True
        self._pipeline_active.set()

        def _active_char_key() -> tuple[str, str]:
            ac = cfg.active_character()
            return ac.get("server", ""), ac.get("name", "")

        def _switch_to_char_if_needed(char_key: tuple[str, str]) -> bool:
            if explicit_tasks is not None:
                return True
            cur = _active_char_key()
            if cur == char_key:
                return True
            server, name = char_key
            if not server or not name:
                return False
            try:
                self._task_manager.switch_character_and_reload(server, name)
                self.invalidate_login()
                self._tasks_updated.set()
                return True
            except (KeyError, ValueError) as e:
                logger.warning("📅 重试轮切换角色失败，跳过 %s/%s: %s", server, name, e)
                return False

        def _execute_task_attempt(task_key: str, attempt_index: int) -> tuple[int, int]:
            execute = self._task_manager.execute_tasks
            params = inspect.signature(execute).parameters
            if "max_attempts" in params:
                return execute([task_key], max_attempts=1, attempt_offset=attempt_index)
            return execute([task_key])

        def _task_is_human_takeover_blocked(task_key: str) -> bool:
            import dpath

            try:
                node = dpath.get(cfg["tasks"], task_key)
            except Exception:
                return False
            return isinstance(node, dict) and is_human_takeover_blocked(node)

        try:
            while True:
                if self._task_manager._cancel_event.is_set():
                    logger.info("⏹ 检测到取消请求，停止执行")
                    break

                if explicit_tasks is None and self.state != SchedulerState.RUNNING:
                    break

                if retry_queue:
                    char_key, task_key = retry_queue.pop(0)
                    if not _switch_to_char_if_needed(char_key):
                        continue
                    due = [task_key]
                elif explicit_tasks is not None:
                    char_key = _active_char_key()
                    due = [] if retry_round > 0 else [
                        t for t in explicit_tasks if (*char_key, t) not in attempted_this_round
                    ]
                else:
                    char_key = _active_char_key()
                    if retry_round > 0:
                        due = []
                    else:
                        collected_due = self._collect_due_cross_character()
                        char_key = _active_char_key()
                        due = [
                            t
                            for t in collected_due
                            if (
                                (*char_key, t) not in attempted_this_round
                                and not self._is_retry_exhausted(char_key, t)
                            )
                        ]
                if not due:
                    if failed_next_round and retry_round < max_retry:
                        retry_round += 1
                        retry_queue = failed_next_round
                        failed_next_round = []
                        attempted_this_round = set()
                        logger.info(
                            "📅 开始第 %d/%d 轮失败任务重试，共 %d 个任务",
                            retry_round,
                            max_retry,
                            len(retry_queue),
                        )
                        continue
                    break

                task_key = due[0]
                task_debug_mode = is_task_debug_mode(task_key)
                if not task_debug_mode:
                    only_debug_tasks_executed = False

                logger.info("📅 发现 %d 个待执行任务: %s", len(due), due)
                if task_debug_mode:
                    logger.info("📅 debug_mode: 跳过自动登录与任务前重启: %s", task_key)
                else:
                    self._maybe_daily_restart(cfg)

                # 必须先让模拟器在正常优先级下启动，启动完成后再温和 boost。
                # 如果先 boost 再启动，MuMu 子进程会继承提升后的优先级，
                # 可能导致虚拟化引擎误判权限状态 → "安卓设备无法启动"。
                unboost()
                try:
                    # 与 api.init() 不同：ensure_app_running 的返回值必须写入 runtime_ctx，
                    # 否则 mixctrl 仅存在于栈上，runtime_ctx.mixctrl 仍为 None（例如关机清理后）。
                    runtime_ctx.refresh(cancel_check=self._check_cancel_requested)
                except TaskCancelled:
                    logger.info("⏹ 检测到取消请求，停止执行")
                    break
                except Exception as e:
                    logger.error("📅 模拟器启动失败: %s", e, exc_info=True)
                    self._consecutive_errors += 1
                    if self._consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                        self.mark_error()
                        break
                    delay = min(30, 10 * self._consecutive_errors)
                    logger.info("📅 %d 秒后重试 (%d/%d)",
                                delay, self._consecutive_errors, MAX_CONSECUTIVE_ERRORS)
                    self._wake.clear()
                    self._wake.wait(delay)
                    if self._task_manager._cancel_event.is_set() or self.state != SchedulerState.RUNNING:
                        logger.info("⏹ 检测到取消请求，停止执行")
                        break
                    continue
                boost(process_priority=ABOVE_NORMAL_PRIORITY_CLASS)

                if not task_debug_mode:
                    self._ensure_character_logged_in(cfg)

                attempted_this_round.add((*char_key, task_key))
                try:
                    success, failed = _execute_task_attempt(task_key, retry_round)
                    if success:
                        total_success += success
                        self.record_result(success, 0)
                    elif failed:
                        if _task_is_human_takeover_blocked(task_key):
                            logger.info("📅 任务需要人工处理，已标记红色冻结态并跳过自动重试: %s", task_key)
                            total_failed += failed
                            self.record_result(1, 0)
                        elif retry_round < max_retry and not task_debug_mode:
                            failed_next_round.append((char_key, task_key))
                            logger.info(
                                "📅 任务失败，跳过当前任务，等待本轮其他任务完成后重试: %s (%d/%d)",
                                task_key,
                                retry_round + 1,
                                max_retry,
                            )
                        else:
                            if explicit_tasks is None and not task_debug_mode:
                                self._mark_retry_exhausted(char_key, task_key, max_retry)
                            total_failed += failed
                            self.record_result(0, failed)
                except KeyboardInterrupt:
                    logger.info("⏹ 任务执行被中断")
                    if self._task_manager:
                        self._task_manager.request_cancel()
                    self.deactivate()
                    break
                except Exception as e:
                    logger.error("📅 执行异常: %s - %s", task_key, e)
                    if retry_round < max_retry and not task_debug_mode:
                        failed_next_round.append((char_key, task_key))
                    else:
                        if explicit_tasks is None and not task_debug_mode:
                            self._mark_retry_exhausted(char_key, task_key, max_retry)
                        total_failed += 1
                        self._consecutive_errors += 1
                        if self._consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                            self.mark_error()
                            break

                try:
                    if self._reload_deferred.is_set():
                        self._apply_deferred_reload_if_needed()
                    else:
                        cfg.save_config()
                        self._task_manager.reload_tasks()
                except Exception as e:
                    logger.error("📅 配置保存/重载失败（将在下一轮重新收集任务）: %s", e)

        finally:
            self._pipeline_active.clear()
            unboost()

        if total_success > 0 or total_failed > 0:
            logger.info("📅 执行完成: 成功 %d, 失败 %d", total_success, total_failed)
            if total_failed > 0:
                notify_from_config(
                    title="AutoScriptor 任务失败",
                    content=f"执行完成: 成功 {total_success}, 失败 {total_failed}"
                )
            if only_debug_tasks_executed:
                logger.info("📅 debug_mode: 跳过 post_execution 收尾动作")
            else:
                self._post_execution_action()
            self._tasks_updated.set()
        elif self._reload_deferred.is_set():
            self._tasks_updated.set()

    # ── 调度模式入口 ──

    def _check_and_run(self):
        """调度模式：清屏 → 重置取消标记 → 共用管线（自动收集到期任务）。"""
        if not os.environ.get('UVICORN_LOG_LEVEL'):
            os.system('cls' if os.name == 'nt' else 'clear')
        # 每个调度周期开始前重置取消标记，防止上一轮中断后残留的取消状态
        # 阻断后续所有周期（deactivate 已将 state 切回 PENDING，能到这里说明 state 仍为 RUNNING）
        if self._task_manager:
            self._task_manager._reset_cancel()
        self._run_task_pipeline(explicit_tasks=None)

    # ── 单任务模式入口 ──

    def run_direct(self, tasks: list[str]):
        """单任务模式：执行外部指定的任务列表，共用管线，不激活调度器。"""
        if self._task_manager:
            self._task_manager._reset_cancel()
        self.invalidate_login()
        self._run_task_pipeline(explicit_tasks=tasks)

    def task_call(self, task_path: str):
        """将指定任务设为立即执行（next_exec_time=now, on=True），下一轮自动拾取。"""
        from AutoScriptor.utils.app_config import cfg
        import dpath
        try:
            node = dpath.get(cfg._config, f"tasks/{task_path.replace('/', '/')}")
            if isinstance(node, dict) and "on" in node:
                node["on"] = True
                for field in ("human_takeover", "human_takeover_error", "human_takeover_at"):
                    node.pop(field, None)
                node["next_exec_time"] = time.time()
                cfg.save_config()
                self._tasks_updated.set()
                logger.info("📅 task_call: %s 已设为立即执行", task_path)
                self.wake()
        except Exception as e:
            logger.warning("📅 task_call 失败: %s -> %s", task_path, e)

    # ── 辅助 ──

    def _safe_shutdown_emulator(self, cfg, reason: str = ""):
        """
        安全关闭模拟器：释放 IPC → 关闭应用 → shutdown 并等待验证 → 清理 runtime。
        供 _maybe_daily_restart / _post_execution_action 等统一调用。
        """
        tag = f"📅 [{reason}]" if reason else "📅"
        try:
            if runtime_ctx.mixctrl is not None:
                try:
                    runtime_ctx.mixctrl.app.close(cfg["app"]["app_to_start"])
                    time.sleep(2)
                except Exception as e:
                    logger.debug("%s 关闭应用失败(可忽略): %s", tag, e)

            runtime_ctx._release_nemu_ipc()

            # 关闭模拟器前恢复正常优先级，防止 MuMu 子进程继承 HIGH_PRIORITY_CLASS
            from AutoScriptor.utils.perf import unboost as _unboost
            _unboost()
            from AutoScriptor.control.MumuAdaptor.mumu import Mumu
            mumu = Mumu().select(cfg["emulator"]["index"])
            mumu.power.shutdown(wait=True, timeout=30)

            runtime_ctx.mixctrl = None
            runtime_ctx.mumu = None
            self._logged_in_character = None
            logger.info("%s 模拟器已安全关闭", tag)
            return True
        except Exception as e:
            logger.warning("%s 模拟器安全关闭失败: %s", tag, e)
            return False

    def _maybe_daily_restart(self, cfg):
        """每日 5:00 首次执行前重启模拟器（一天只触发一次）。"""
        next_ts = self._earliest_future_active_time()
        if next_ts is None:
            return
        from datetime import datetime, time as dtime
        next_dt = datetime.fromtimestamp(next_ts)
        now_dt = datetime.now()
        if not (next_dt.date() == now_dt.date() and next_dt.hour == 5 and next_dt.minute == 0):
            return
        today_5am_ts = datetime.combine(now_dt.date(), dtime(5, 0)).timestamp()
        if cfg.get("status.last_login_time.time", 0) >= today_5am_ts or datetime.now().hour < 5:
            return
        logger.info("📅 检测到今日5:00首次执行，先关闭模拟器以清理状态")
        self._safe_shutdown_emulator(cfg, reason="每日重启")
        cfg.set("status.last_login_time.time", time.time())
        cfg.save_config()

    @staticmethod
    def _release_nemu_ipc():
        """释放旧 mixctrl 持有的 NemuIpc 原生连接，防止泄露。"""
        runtime_ctx._release_nemu_ipc()

    @staticmethod
    def _refresh_runtime_controls(cfg):
        """仅在模拟器完全重启后调用：释放旧 IPC 连接，替换全局运行时对象。"""
        return runtime_ctx.refresh()

    def _post_execution_action(self):
        from AutoScriptor.utils.app_config import cfg
        action = cfg["emulator"].get("post_execution", "none").lower()
        if action == "none" or action == "null":
            return
        app_name = cfg["app"]["app_to_start"]
        if runtime_ctx.mixctrl is None:
            logger.warning("📅 runtime_ctx.mixctrl 不可用，跳过 post_execution")
            return
        if action == "close_mumu":
            logger.info("📅 执行后: 关闭模拟器")
            self._safe_shutdown_emulator(cfg, reason="执行后关闭模拟器")
        elif action == "close_game_only":
            logger.info("📅 执行后: 仅关闭游戏")
            try:
                runtime_ctx.mixctrl.app.close(app_name)
            except Exception as e:
                logger.warning("📅 关闭游戏失败: %s", e)
        elif action == "goto_main":
            logger.info("📅 执行后: 回到主界面")
            try:
                from ZmxyOL.nav import ensure_in, Loc
                ensure_in(Loc.HOME)
            except Exception as e:
                logger.warning("📅 回到主界面失败: %s", e)

    # ── 角色登录检查 ──

    def _ensure_character_logged_in(self, cfg):
        """检查当前游戏中登录的角色是否与 cfg 中的一致，不一致则自动登录。"""
        ac = cfg.active_character()
        server = ac.get("server", "")
        char_name = ac.get("name", "")
        current = (server, char_name)

        if current == self._logged_in_character:
            return

        logger.info("📅 角色变更: %s → %s/%s，执行自动登录",
                     self._logged_in_character or "(无)", server, char_name)
        try:
            from ZmxyOL.nav import ensure_in
            from ZmxyOL.nav.envs.login import login
            ensure_in("登录")
            login()
            self._logged_in_character = current
            logger.info("📅 自动登录完成: %s/%s", server, char_name)
        except Exception as e:
            logger.error("📅 自动登录失败: %s", e)
            raise

    def invalidate_login(self):
        """外部通知角色已切换，下次执行前需重新登录。"""
        self._logged_in_character = None

    # ── 状态查询 ──

    @property
    def state_label(self) -> str:
        return _STATE_LABELS.get(self.state.value, "")

    def status_dict(self) -> dict:
        return {
            "state": self.state.value,
            "label": self.state_label,
            "color": _STATE_COLORS.get(self.state.value, "gray"),
            "consecutive_errors": self._consecutive_errors,
            "executing": self.is_executing,
            "busy": self.state == SchedulerState.RUNNING or self.is_executing,
            "reload_deferred": self._reload_deferred.is_set(),
        }


scheduler = Scheduler()
