"""
AutoScriptor 后台定时调度器
===========================
轻量 daemon 线程，动态 sleep 到最早到期任务，扫描并执行。

状态机：
  PENDING ─── activate() ───▶ RUNNING
  RUNNING ─── request_stop()/deactivate() ──▶ PENDING
  RUNNING ─── 连续错误 ≥3 ────────────────▶ ERROR
  ERROR   ─── reset()/request_stop() ─────▶ PENDING

安全策略：
  - 不使用 os.execv / PyThreadState_SetAsyncExc
  - Ctrl+C 由 run.py 主线程处理，调度器仅响应 cooperative cancel
"""

import os
import time
import threading
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Callable
from AutoScriptor.utils.cancel import TaskCancelled
from AutoScriptor.logging.logger import logger

from AutoScriptor.core.runtime_context import runtime_ctx
from orchestrator.delivery import create_character_reports, notify_runtime_event
from orchestrator.model import (
    calc_next_allowed_weekday_ts,
    calc_effective_next_time,
    clamp_to_sched_window,
    collect_active_times_from_all_characters,
    is_human_takeover_blocked,
    is_task_debug_mode,
    iter_dispatch_characters,
    next_display_timestamp_from_times,
    resolve_reschedule,
    sort_paths_by_task_ordering,
)


class SchedulerState(Enum):
    PENDING = "pending"
    RUNNING = "running"
    ERROR   = "error"


CHECK_INTERVAL = 3600
MAX_CONSECUTIVE_ERRORS = 3


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
        self._execution_gate = threading.Lock()
        self._execution_owner_lock = threading.Lock()
        self._execution_owner: str | None = None
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
        notify_runtime_event(
            title="AutoScriptor 调度器错误",
            content=f"连续失败 {self._consecutive_errors} 次，调度器已暂停"
        )

    def reset(self):
        self._transition(SchedulerState.PENDING)
        self._restore_error_recovery_budget()
        if self._task_manager:
            self._task_manager._reset_cancel()

    def request_stop(self):
        """Cooperatively cancel execution and restore scheduler recovery state."""
        logger.info("⏹ 收到停止请求，正在优雅停止任务...")
        if self._task_manager:
            self._task_manager.request_cancel()
        self.deactivate()
        self._restore_error_recovery_budget()
        self._wake.set()

    def wake(self):
        self._wake.set()

    def mark_tasks_updated(self) -> None:
        self._tasks_updated.set()

    def _is_cancel_requested(self) -> bool:
        cancel_event = getattr(self._task_manager, "_cancel_event", None)
        return bool(cancel_event is not None and cancel_event.is_set())

    def _check_cancel_requested(self) -> None:
        if self._is_cancel_requested():
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
        """Whether any task pipeline is currently executing."""
        return self._pipeline_active.is_set()

    @property
    def execution_owner(self) -> str | None:
        """Return the participant that currently owns exclusive device execution."""
        with self._execution_owner_lock:
            return self._execution_owner

    @property
    def is_scheduled_execution(self) -> bool:
        """Whether the activated scheduler currently owns the execution gate."""
        return self.execution_owner == "scheduler"

    def acquire_execution(self, owner: str, *, blocking: bool = True) -> bool:
        """Acquire exclusive task/device execution without changing scheduler activation."""
        normalized_owner = str(owner or "").strip()
        if not normalized_owner:
            raise ValueError("execution owner 不能为空")
        acquired = self._execution_gate.acquire(blocking=blocking)
        if not acquired:
            return False
        with self._execution_owner_lock:
            self._execution_owner = normalized_owner
        return True

    def release_execution(self, owner: str) -> None:
        """Release execution previously acquired by the matching participant."""
        normalized_owner = str(owner or "").strip()
        with self._execution_owner_lock:
            if self._execution_owner != normalized_owner:
                raise RuntimeError(
                    f"execution owner 不匹配: current={self._execution_owner!r}, release={normalized_owner!r}"
                )
            self._execution_owner = None
        self._execution_gate.release()

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
        if failed > 0 and self._is_cancel_requested():
            logger.info("⏹ 用户终止后的任务失败不计入连续错误恢复额度")
            return
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

    def _restore_error_recovery_budget(self) -> None:
        """Restore consecutive-error and retry-exhaustion recovery budgets."""
        self._consecutive_errors = 0
        self._clear_retry_exhaustion()

    def _is_retry_exhausted(self, char_key: tuple[str, str], task_key: str) -> bool:
        return self._retry_key(char_key, task_key) in self._retry_exhausted_tasks

    def _mark_retry_exhausted(self, char_key: tuple[str, str], task_key: str, max_retry: int) -> None:
        if self._is_cancel_requested():
            logger.info("⏹ 用户终止后的任务不再标记为 retry 耗尽: %s", task_key)
            return
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
        from tasks.task_register import task_registry

        if not self._retry_exhausted_tasks:
            return collect_active_times_from_all_characters(cfg, dispatch_only=True)

        now_ts = time.time()
        result: list[float] = []
        active = cfg.active_character()
        active_key = (active.get("server", ""), active.get("name", ""))
        chars = cfg._account_data.get("characters", {}) or {}

        def _collect_from_table(task_table: dict, char_key: tuple[str, str]) -> None:
            for task_id, val in (task_table or {}).items():
                if not isinstance(val, dict) or not val.get("on"):
                    continue
                path = task_registry.get_path(task_id)
                if not path:
                    continue
                if not task_registry.has_task(path):
                    continue
                if self._is_retry_exhausted(char_key, path):
                    continue
                result.append(calc_effective_next_time(val, now_ts, resolve_reschedule(path, val)))

        for server, name in self._iter_characters_schedule_order():
            char_key = (server, name)
            if char_key == active_key:
                task_table = cfg._config.get("tasks", {}) or {}
            else:
                task_table = chars.get(server, {}).get(name, {}).get("tasks", {}) or {}
            _collect_from_table(task_table, char_key)
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
        from AutoScriptor.utils.app_config import cfg
        from ZmxyOL.accounts import get_character_dir, get_custom_task_dir

        def _extra_reload_paths() -> list[str]:
            paths = [
                str(get_character_dir()),
                str(get_custom_task_dir()),
            ]
            if cfg.current_account():
                paths.append(cfg._account_path(cfg.current_account()))
            return paths

        def _runtime_persistence_paths() -> list[str]:
            paths = [cfg.CONFIG_PATH]
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
                watcher.mark_seen()
            if self.state == SchedulerState.RUNNING and self._task_manager:
                try:
                    self._check_and_run()
                except Exception as e:
                    logger.error("📅 调度执行意外崩溃，将在下一轮重试: %s", e, exc_info=True)
                    self.record_result(0, 1)
                finally:
                    # Scheduler/task execution persists task state and next_exec_time.
                    # Those self-writes should update WebUI state, but should not be
                    # mistaken for external config/script edits that need another
                    # task registry hot reload on the next scheduler tick.
                    watcher.mark_seen(_runtime_persistence_paths())

    # ── 到期任务收集 ──

    def _collect_due(self, task_table: dict, now_ts: float) -> list[str]:
        """Paths of the enabled tasks in one flat cfg table that are due now.

        A schedule-window or weekday deferral is written straight into the entry's
        ``next_exec_time``, so the entry is the same dict the pipeline later runs.
        """
        from tasks.task_register import task_registry
        from AutoScriptor.utils.app_config import cfg
        import datetime as _dt

        tasks = []
        for task_id, val in (task_table or {}).items():
            if not isinstance(val, dict) or "on" not in val:
                continue
            path = task_registry.get_path(task_id)
            if not path:
                continue
            if not (
                val.get("on")
                and not is_human_takeover_blocked(val, now_ts)
                and now_ts >= val.get("next_exec_time", 0)
                and task_registry.has_task(path)
            ):
                continue
            spec = resolve_reschedule(path, val)
            if spec["window"] is not None:
                deferred = clamp_to_sched_window(now_ts, *spec["window"])
                if deferred > now_ts:
                    val["next_exec_time"] = deferred
                    logger.info(
                        "📅 任务 %s 不在开放时段 [%02d:00,%02d:00)，已推迟至 %s",
                        path, spec["window"][0], spec["window"][1],
                        _dt.datetime.fromtimestamp(deferred).strftime("%Y-%m-%d %H:%M"),
                    )
                    cfg.save_config()
                    self._tasks_updated.set()
                    continue
            allowed_weekdays = spec["weekdays"]
            if allowed_weekdays is not None:
                now_dt = _dt.datetime.fromtimestamp(now_ts)
                wd = now_dt.weekday() + 1
                if wd not in set(allowed_weekdays):
                    deferred = calc_next_allowed_weekday_ts(now_dt, allowed_weekdays)
                    val["next_exec_time"] = deferred
                    logger.info(
                        "📅 任务 %s 仅允许星期 %s（当前周%d），已推迟至 %s",
                        path, allowed_weekdays, wd,
                        _dt.datetime.fromtimestamp(deferred).strftime("%Y-%m-%d %H:%M"),
                    )
                    cfg.save_config()
                    self._tasks_updated.set()
                    continue
            tasks.append(path)
        return tasks

    def _sort_due_paths(self, due_paths: list[str]) -> list[str]:
        """Sort due paths by the global task ordering overlay."""
        from AutoScriptor.utils.app_config import cfg
        return sort_paths_by_task_ordering(
            due_paths,
            cfg.get("tasks") or {},
            cfg._config.get("task_ordering", {}),
        )

    def _iter_characters_schedule_order(self):
        """调度顺序：优先账号内 dispatch_queue，其余按服务器名、角色名排序。"""
        from AutoScriptor.utils.app_config import cfg

        yield from iter_dispatch_characters(cfg)

    def _switch_active_character(self, server: str, character: str) -> None:
        """Switch cfg/account state without rebuilding task modules."""
        from AutoScriptor.utils.app_config import cfg

        if self._task_manager and hasattr(self._task_manager, "switch_character"):
            self._task_manager.switch_character(server, character)
        else:
            cfg.switch_character(server, character)

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
                due = self._collect_due(cfg.get("tasks") or {}, time.time())
            else:
                try:
                    self._switch_active_character(server, name)
                except (KeyError, ValueError) as e:
                    logger.warning("📅 切换角色跳过 %s/%s: %s", server, name, e)
                    continue
                switched = True
                self.invalidate_login()
                due = self._collect_due(cfg.get("tasks") or {}, time.time())
            due = self._filter_retry_available((server, name), due)
            due = self._sort_due_paths(due)
            if due:
                if switched:
                    self._tasks_updated.set()
                return due
        if switched and original_key[0] and original_key[1]:
            try:
                self._switch_active_character(*original_key)
                self.invalidate_login()
            except (KeyError, ValueError) as e:
                logger.warning("📅 恢复原角色失败 %s/%s: %s", original_key[0], original_key[1], e)
        return []

    def _return_to_first_dispatch_character(self) -> bool:
        """全角色调度完成后回到 dispatch_queue 首角色，并确认游戏内也登录到该角色。"""
        from AutoScriptor.utils.app_config import cfg

        first_char = next(iter_dispatch_characters(cfg), None)
        if first_char is None:
            logger.info("📅 dispatch_queue 为空，跳过回到首个角色")
            return False

        server, name = first_char
        active = cfg.active_character()
        current = (active.get("server", ""), active.get("name", ""))

        try:
            if current != first_char:
                logger.info("📅 全角色调度完成，切回首个角色: %s/%s", server, name)
                self._switch_active_character(server, name)
                self.invalidate_login()
                self._tasks_updated.set()
            else:
                logger.info("📅 全角色调度完成，首个角色已是当前角色: %s/%s", server, name)

            self._ensure_character_logged_in(cfg)
            return True
        except Exception as e:
            logger.warning("📅 回到首个角色失败 %s/%s: %s", server, name, e, exc_info=True)
            return False

    # ── 共用执行管线 ──

    def _run_task_pipeline(
        self,
        explicit_tasks: list[str] | None = None,
        *,
        force_login: bool = False,
        skip_character_login: bool = False,
        param_overrides: dict[str, dict] | None = None,
        explicit_task_runs: list[dict] | None = None,
    ):
        """
        统一的任务执行管线，调度模式和单任务模式共用。

        explicit_tasks=None  → 调度模式，由 _collect_due() 动态收集到期任务
        explicit_tasks=[...] → 单任务模式，执行外部传入的固定列表（仍复用登录确认与中断控制）
        """
        import inspect
        from AutoScriptor.utils.app_config import cfg

        if not cfg._config.get("game", {}).get("character_name", ""):
            logger.warning("⚠️ 账号未验证，跳过执行")
            return

        total_success = total_failed = 0
        max_retry = int(cfg["app"].get("max_retry", 0) or 0)
        retry_round = 0
        attempted_this_round: set[tuple[str, str, str]] = set()
        retry_queue: list[tuple[tuple[str, str], dict]] = []
        failed_next_round: list[tuple[tuple[str, str], dict]] = []
        only_debug_tasks_executed = True
        character_reports = create_character_reports(
            cfg.get("notify.qq", {}), list(self._iter_characters_schedule_order())
        )
        pipeline_completed = False
        self._pipeline_active.set()
        scheduled_mode = explicit_tasks is None and explicit_task_runs is None

        if explicit_task_runs is None and explicit_tasks is not None:
            explicit_task_runs = [
                {"id": f"{i}:{task}", "task": task}
                for i, task in enumerate(explicit_tasks)
            ]

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
                self._switch_active_character(server, name)
                self.invalidate_login()
                self._tasks_updated.set()
                return True
            except (KeyError, ValueError) as e:
                logger.warning("📅 重试轮切换角色失败，跳过 %s/%s: %s", server, name, e)
                return False

        def _run_id(run: dict) -> str:
            return str(run.get("id") or run.get("task") or "")

        def _run_task(run: dict) -> str:
            return str(run.get("task") or "")

        def _run_param_override(run: dict) -> dict | None:
            params = run.get("params")
            return params if isinstance(params, dict) else None

        def _execute_task_attempt(task_key: str, attempt_index: int, param_override: dict | None = None) -> tuple[int, int]:
            execute = self._task_manager.execute_tasks
            params = inspect.signature(execute).parameters
            kwargs = {}
            if "max_attempts" in params:
                kwargs.update(max_attempts=1, attempt_offset=attempt_index)
            if "param_overrides" in params:
                if param_override is not None:
                    kwargs["param_overrides"] = {task_key: param_override}
                elif param_overrides:
                    kwargs["param_overrides"] = param_overrides
            return execute([task_key], **kwargs)

        def _task_is_human_takeover_blocked(task_key: str) -> bool:
            from tasks.task_register import task_registry

            node = cfg["tasks"].get(task_registry.id_of(task_key))
            return isinstance(node, dict) and is_human_takeover_blocked(node, time.time())

        try:
            while True:
                if self._task_manager._cancel_event.is_set():
                    logger.info("⏹ 检测到取消请求，停止执行")
                    break

                if scheduled_mode and self.state != SchedulerState.RUNNING:
                    break

                if retry_queue:
                    char_key, task_run = retry_queue.pop(0)
                    if not _switch_to_char_if_needed(char_key):
                        continue
                    due = [task_run]
                elif explicit_task_runs is not None:
                    char_key = _active_char_key()
                    due = [] if retry_round > 0 else [
                        run for run in explicit_task_runs if (*char_key, _run_id(run)) not in attempted_this_round
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
                character_reports.flush_ready(
                    char_key,
                    {character for character, _ in retry_queue + failed_next_round},
                )
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
                    pipeline_completed = True
                    break

                task_run = due[0] if isinstance(due[0], dict) else {"id": str(due[0]), "task": str(due[0])}
                task_key = _run_task(task_run)
                run_id = _run_id(task_run)
                param_override = _run_param_override(task_run)
                character_reports.record(char_key, run_id, task_key, "pending")
                task_debug_mode = is_task_debug_mode(task_key)
                skip_login_for_debug = task_debug_mode and not force_login
                skip_login_for_task = skip_character_login or skip_login_for_debug
                if not task_debug_mode:
                    only_debug_tasks_executed = False

                logger.info("📅 发现 %d 个待执行任务: %s", len(due), [
                    _run_task(run) if isinstance(run, dict) else run for run in due
                ])
                if skip_character_login:
                    logger.info("📅 任务列表直跑: 跳过当前角色校验与自动登录: %s", task_key)
                if skip_login_for_debug:
                    logger.info("📅 debug_mode: 跳过自动登录与任务前重启: %s", task_key)
                elif task_debug_mode:
                    logger.info("📅 debug_mode: 跳过任务前重启，但按本次请求执行自动登录: %s", task_key)
                else:
                    self._maybe_daily_restart(cfg)

                try:
                    # 与 api.init() 不同：ensure_app_running 的返回值必须写入 runtime_ctx，
                    # 否则 mixctrl 仅存在于栈上，runtime_ctx.mixctrl 仍为 None（例如关机清理后）。
                    runtime_ctx.refresh(cancel_check=self._check_cancel_requested)
                except TaskCancelled:
                    logger.info("⏹ 检测到取消请求，停止执行")
                    break
                except Exception as e:
                    logger.error("📅 模拟器启动失败: %s", e, exc_info=True)
                    self.record_result(0, 1)
                    if self.state == SchedulerState.ERROR:
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

                if not skip_login_for_task:
                    self._ensure_character_logged_in(cfg)

                attempted_this_round.add((*char_key, run_id))
                try:
                    success, failed = _execute_task_attempt(task_key, retry_round, param_override)
                    if not self._task_manager._cancel_event.is_set():
                        outcome = "success" if success else ("failed" if failed else "pending")
                        character_reports.record(char_key, run_id, task_key, outcome)
                    if success:
                        total_success += success
                        self.record_result(success, 0)
                    elif failed:
                        if _task_is_human_takeover_blocked(task_key):
                            logger.info("📅 任务需要人工处理，已标记红色冷却态并跳过本轮自动重试: %s", task_key)
                            total_failed += failed
                            self.record_result(1, 0)
                        elif retry_round < max_retry and not task_debug_mode:
                            failed_next_round.append((char_key, task_run))
                            logger.info(
                                "📅 任务失败，跳过当前任务，等待本轮其他任务完成后重试: %s (%d/%d)",
                                task_key,
                                retry_round + 1,
                                max_retry,
                            )
                        else:
                            if scheduled_mode and not task_debug_mode:
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
                    if not self._task_manager._cancel_event.is_set():
                        character_reports.record(char_key, run_id, task_key, "failed")
                    if retry_round < max_retry and not task_debug_mode:
                        failed_next_round.append((char_key, task_run))
                    else:
                        if scheduled_mode and not task_debug_mode:
                            self._mark_retry_exhausted(char_key, task_key, max_retry)
                        total_failed += 1
                        self.record_result(0, 1)
                        if self.state == SchedulerState.ERROR:
                            break

                try:
                    if self._reload_deferred.is_set():
                        self._apply_deferred_reload_if_needed()
                    else:
                        cfg.save_config()
                        self._tasks_updated.set()
                except Exception as e:
                    logger.error("📅 配置保存失败（将在下一轮重新收集任务）: %s", e)

        finally:
            self._pipeline_active.clear()
            character_reports.finish(
                interrupted=not pipeline_completed or self._task_manager._cancel_event.is_set()
            )

        if total_success > 0 or total_failed > 0:
            logger.info("📅 执行完成: 成功 %d, 失败 %d", total_success, total_failed)
            title = "AutoScriptor 任务失败" if total_failed > 0 else "AutoScriptor 任务完成"
            notify_runtime_event(
                title=title,
                content=f"执行完成: 成功 {total_success}, 失败 {total_failed}"
            )
            if only_debug_tasks_executed:
                logger.info("📅 debug_mode: 跳过 post_execution 收尾动作")
            else:
                if scheduled_mode and self.state == SchedulerState.RUNNING:
                    self._return_to_first_dispatch_character()
                self._post_execution_action()
            self._tasks_updated.set()
        elif self._reload_deferred.is_set():
            self._tasks_updated.set()

    # ── 调度模式入口 ──

    def _check_and_run(self):
        """调度模式：清屏 → 重置取消标记 → 共用管线（自动收集到期任务）。"""
        self.acquire_execution("scheduler")
        try:
            # 调度线程可能在等待手动执行释放闸门期间被停用。
            if self._stop.is_set() or self.state != SchedulerState.RUNNING:
                return
            if not os.environ.get('UVICORN_LOG_LEVEL'):
                os.system('cls' if os.name == 'nt' else 'clear')
            # 每个调度周期开始前重置取消标记，防止上一轮中断后残留的取消状态
            # 阻断后续所有周期（deactivate 已将 state 切回 PENDING，能到这里说明 state 仍为 RUNNING）
            if self._task_manager:
                self._task_manager._reset_cancel()
            self._run_task_pipeline(explicit_tasks=None)
        finally:
            self.release_execution("scheduler")

    # ── 单任务模式入口 ──

    def run_direct(
        self,
        tasks: list[str],
        *,
        force_login: bool = False,
        skip_character_login: bool = False,
        param_overrides: dict[str, dict] | None = None,
    ):
        """单任务模式：执行外部指定的任务列表，共用管线，不激活调度器。"""
        if self._task_manager:
            self._task_manager._reset_cancel()
        should_skip_character_login = skip_character_login and not force_login
        if not should_skip_character_login:
            self.invalidate_login()
        self._run_task_pipeline(
            explicit_tasks=tasks,
            force_login=force_login,
            skip_character_login=should_skip_character_login,
            param_overrides=param_overrides,
        )

    def run_direct_sequence(
        self,
        task_runs: list[dict],
        *,
        force_login: bool = False,
    ):
        """单任务模式的序列入口：允许同一任务路径携带不同一次性参数多次执行。"""
        if self._task_manager:
            self._task_manager._reset_cancel()
        self.invalidate_login()
        self._run_task_pipeline(
            explicit_task_runs=task_runs,
            force_login=force_login,
        )

    def task_call(self, task_path: str):
        """将指定任务设为立即执行（next_exec_time=now, on=True），下一轮自动拾取。"""
        from AutoScriptor.utils.app_config import cfg
        from tasks.task_register import task_registry

        try:
            node = cfg["tasks"].get(task_registry.id_of(task_path))
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

            from AutoScriptor.control.MumuAdaptor.mumu import Mumu
            mumu = Mumu().select(cfg["emulator"]["index"])
            mumu.power.shutdown(wait=True, timeout=30)

            runtime_ctx.release_session()
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
        runtime_ctx.release_session()

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
        scheduled_execution = self.is_scheduled_execution
        return {
            "state": self.state.value,
            "label": self.state_label,
            "color": _STATE_COLORS.get(self.state.value, "gray"),
            "consecutive_errors": self._consecutive_errors,
            "executing": scheduled_execution,
            "busy": scheduled_execution,
            "enabled": self.state == SchedulerState.RUNNING,
            "reload_deferred": self._reload_deferred.is_set(),
        }


scheduler = Scheduler()


class ConfigWatcher:
    """监听配置/用户脚本的修改时间，判断是否需要重新加载。"""

    def __init__(self, config_path: str, extra_paths: Callable[[], list[str]] | None = None):
        self._path = config_path
        self._extra_paths = extra_paths
        self._last_mtime: datetime = datetime.min
        self._seen_mtimes: dict[str, float] = {}

    def start_watching(self):
        """记录当前修改时间作为基准。"""
        self._seen_mtimes = self._snapshot_mtimes()
        self._last_mtime = self._latest_datetime(self._seen_mtimes)

    def _watched_paths(self) -> list[str]:
        paths = [self._path]
        if self._extra_paths is not None:
            paths.extend(path for path in self._extra_paths() if path)
        return paths

    def _iter_existing_paths(self):
        for raw in self._watched_paths():
            path = Path(raw)
            if not path.exists():
                continue
            yield path
            if path.is_dir():
                try:
                    yield from (p for p in path.rglob("*") if p.exists())
                except OSError:
                    continue

    @staticmethod
    def _path_key(path: Path) -> str:
        try:
            return str(path.resolve())
        except OSError:
            return str(path.absolute())

    @staticmethod
    def _same_or_under(path_key: str, root_key: str) -> bool:
        if path_key == root_key:
            return True
        try:
            Path(path_key).relative_to(Path(root_key))
            return True
        except ValueError:
            return False

    @staticmethod
    def _latest_datetime(snapshot: dict[str, float]) -> datetime:
        if not snapshot:
            return datetime.min
        return datetime.fromtimestamp(max(snapshot.values())).replace(microsecond=0)

    def _snapshot_mtimes(self) -> dict[str, float]:
        mtimes: dict[str, float] = {}
        for path in self._iter_existing_paths():
            try:
                mtimes[self._path_key(path)] = os.stat(path).st_mtime
            except OSError:
                continue
        return mtimes

    def _get_latest_mtime(self) -> datetime:
        return self._latest_datetime(self._snapshot_mtimes())

    def mark_seen(self, paths: list[str] | None = None) -> None:
        """Mark current watcher state as already handled.

        Passing paths updates only those files/directories in the baseline.
        Scheduler uses this for its own config/account JSON writes so they do
        not immediately look like external hot-reload requests.
        """
        current = self._snapshot_mtimes()
        if paths is None:
            self._seen_mtimes = current
            self._last_mtime = self._latest_datetime(current)
            return

        roots = [Path(raw) for raw in paths if raw]
        root_keys = {self._path_key(root) for root in roots}
        for key, ts in current.items():
            if any(self._same_or_under(key, root) for root in root_keys):
                self._seen_mtimes[key] = ts
        for key in list(self._seen_mtimes.keys()):
            if any(self._same_or_under(key, root) for root in root_keys) and key not in current:
                self._seen_mtimes.pop(key, None)
        self._last_mtime = self._latest_datetime(self._seen_mtimes)

    def should_reload(self) -> bool:
        """任一监听路径是否在上次检查后被修改过。"""
        snapshot = self._snapshot_mtimes()
        changed = False
        for key, ts in snapshot.items():
            old = self._seen_mtimes.get(key)
            if old is None or ts > old:
                changed = True
                break
        if not changed:
            changed = any(key not in snapshot for key in self._seen_mtimes)

        if changed:
            mtime = self._latest_datetime(snapshot)
            logger.info(f"检测到配置/用户脚本变更 ({mtime})")
            self._seen_mtimes = snapshot
            self._last_mtime = mtime
            return True
        return False
