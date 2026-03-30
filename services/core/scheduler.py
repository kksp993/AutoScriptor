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
from AutoScriptor.utils.logger import logger

from AutoScriptor import ensure_app_running
from services.core.runtime_context import runtime_ctx
from services.core.notify import notify_from_config


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
        self._consecutive_errors = 0

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

    # ── 结果反馈 ──

    def record_result(self, success: int, failed: int):
        if failed == 0:
            self._consecutive_errors = 0
        else:
            self._consecutive_errors += 1
            if self._consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                self.mark_error()

    # ── 任务时间收集（共用） ──

    def _collect_active_times(self) -> list[float]:
        """收集所有 on=True 的叶子任务的「有效」下次执行时间（含 sched_window 映射）。"""
        from AutoScriptor.utils.constant import cfg
        from AutoScriptor.utils.task_registry import task_registry
        from services.core.task_manager import (
            parse_sched_window_hours,
            clamp_to_sched_window,
            parse_allowed_weekdays,
            calc_next_allowed_weekday_ts,
        )
        import datetime as _dt

        now_ts = time.time()
        result = []

        def _walk(node: dict, prefix: str = ""):
            for key, val in node.items():
                if not isinstance(val, dict):
                    continue
                path = f"{prefix}/{key}" if prefix else key
                if 'on' in val:
                    if val.get('on') and task_registry.has_task(path):
                        raw = float(val.get('next_exec_time', 0) or 0)
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

        _walk(cfg["tasks"])
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
        now = time.time()
        times = self._collect_active_times()
        if not times:
            return None
        if any(t <= now for t in times):
            return now
        return min(times)

    # ── 后台主循环 ──

    def _loop(self):
        from services.core.watcher import ConfigWatcher
        from AutoScriptor.utils.constant import cfg
        watcher = ConfigWatcher(cfg.CONFIG_PATH)
        watcher.start_watching()
        while True:
            self._wake.clear()
            self._wake.wait(self._get_wait_interval())
            if self._stop.is_set():
                break
            if watcher.should_reload():
                try:
                    # 必须通过 TaskManager.reload_tasks() 重载：内部会在 load_config 前保存 game，
                    # 无安全密码时写回，避免先 cfg.load_config() 清空 game 导致 character_name 丢失。
                    if self._task_manager:
                        self._task_manager.reload_tasks()
                    else:
                        cfg.load_config()
                    self._tasks_updated.set()
                except Exception as e:
                    logger.warning("配置热重载失败: %s", e)
            if self.state == SchedulerState.RUNNING and self._task_manager:
                self._check_and_run()

    # ── 到期任务收集 ──

    def _collect_due(self, node: dict, prefix: str, now_ts: float) -> list[str]:
        from AutoScriptor.utils.task_registry import task_registry
        from AutoScriptor.utils.constant import cfg
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
                hoarding = val.get("hoarding_minutes", 0)
                effective_now = now_ts - (hoarding * 60) if hoarding else now_ts
                if val.get("on") and effective_now >= val.get("next_exec_time", 0) and task_registry.has_task(path):
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
                            continue
                    tasks.append(path)
            else:
                tasks.extend(self._collect_due(val, path, now_ts))
        return tasks

    # ── 共用执行管线 ──

    def _run_task_pipeline(self, explicit_tasks: list[str] | None = None):
        """
        统一的任务执行管线，调度模式和单任务模式共用。

        explicit_tasks=None  → 调度模式，由 _collect_due() 动态收集到期任务
        explicit_tasks=[...] → 单任务模式，执行外部传入的固定列表
        """
        from AutoScriptor.utils.constant import cfg
        from AutoScriptor.utils.perf import boost, unboost

        if not cfg._config.get("game", {}).get("character_name", ""):
            logger.warning("⚠️ 账号未验证，跳过执行")
            return

        total_success = total_failed = 0
        attempted: set[str] = set()

        try:
            while True:
                if self._task_manager._cancel_event.is_set():
                    logger.info("⏹ 检测到取消请求，停止执行")
                    break

                if explicit_tasks is None and self.state != SchedulerState.RUNNING:
                    break

                if explicit_tasks is not None:
                    due = [t for t in explicit_tasks if t not in attempted]
                else:
                    due = [t for t in self._collect_due(cfg["tasks"], "", time.time())
                           if t not in attempted]
                if not due:
                    break

                logger.info("📅 发现 %d 个待执行任务: %s", len(due), due)
                self._maybe_daily_restart(cfg)

                # 必须先让模拟器在正常优先级下启动，启动完成后再 boost。
                # 如果先 boost 再启动，MuMu 子进程会继承 HIGH_PRIORITY_CLASS，
                # 导致虚拟化引擎误判权限状态 → "安卓设备无法启动"。
                unboost()
                try:
                    ensure_app_running(
                        cfg["emulator"]["index"],
                        cfg["emulator"]["adb_addr"],
                        cfg["app"]["app_to_start"],
                    )
                except Exception as e:
                    logger.error("📅 模拟器启动失败: %s", e)
                    self._consecutive_errors += 1
                    if self._consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                        self.mark_error()
                    break
                boost()

                task_key = due[0]
                attempted.add(task_key)
                try:
                    success, failed = self._task_manager.execute_tasks([task_key])
                    total_success += success
                    total_failed += failed
                    self.record_result(success, failed)
                except KeyboardInterrupt:
                    logger.info("⏹ 任务执行被中断")
                    if self._task_manager:
                        self._task_manager.request_cancel()
                    self.deactivate()
                    break
                except Exception as e:
                    logger.error("📅 执行异常: %s - %s", task_key, e)
                    self._consecutive_errors += 1
                    if self._consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                        self.mark_error()
                        break

                cfg.save_config()
                self._task_manager.reload_tasks()

        finally:
            unboost()

        if total_success > 0 or total_failed > 0:
            logger.info("📅 执行完成: 成功 %d, 失败 %d", total_success, total_failed)
            if total_failed > 0:
                notify_from_config(
                    title="AutoScriptor 任务失败",
                    content=f"执行完成: 成功 {total_success}, 失败 {total_failed}"
                )
            self._post_execution_action()
            self._tasks_updated.set()

    # ── 调度模式入口 ──

    def _check_and_run(self):
        """调度模式：清屏 → 共用管线（自动收集到期任务）。"""
        if not os.environ.get('UVICORN_LOG_LEVEL'):
            os.system('cls' if os.name == 'nt' else 'clear')
        self._run_task_pipeline(explicit_tasks=None)

    # ── 单任务模式入口 ──

    def run_direct(self, tasks: list[str]):
        """单任务模式：执行外部指定的任务列表，共用管线，不激活调度器。"""
        if self._task_manager:
            self._task_manager._reset_cancel()
        self._run_task_pipeline(explicit_tasks=tasks)

    def task_call(self, task_path: str):
        """将指定任务设为立即执行（next_exec_time=now, on=True），下一轮自动拾取。"""
        from AutoScriptor.utils.constant import cfg
        import dpath
        try:
            node = dpath.get(cfg._config, f"tasks/{task_path.replace('/', '/')}")
            if isinstance(node, dict) and "on" in node:
                node["on"] = True
                node["next_exec_time"] = time.time()
                cfg.save_config()
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
        from AutoScriptor.utils.constant import cfg
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
        }


scheduler = Scheduler()
