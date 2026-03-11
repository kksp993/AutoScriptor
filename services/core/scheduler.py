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
from logzero import logger

from AutoScriptor import ensure_app_running


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

    def stop(self):
        self._stop.set()
        self._wake.set()

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
        """收集所有 on=True 的叶子任务的 next_exec_time。"""
        from AutoScriptor.utils.constant import cfg
        now_ts = time.time()
        result = []

        def _walk(node: dict):
            for val in node.values():
                if not isinstance(val, dict):
                    continue
                if 'fn' in val and val.get('on'):
                    result.append(val.get('next_exec_time', now_ts))
                else:
                    _walk(val)

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

    def get_next_execution_timestamp(self) -> float | None:
        now = time.time()
        future = [t for t in self._collect_active_times() if t > now]
        return min(future) if future else None

    # ── 后台主循环 ──

    def _loop(self):
        while True:
            self._wake.clear()
            self._wake.wait(self._get_wait_interval())
            if self._stop.is_set():
                break
            if self.state == SchedulerState.RUNNING and self._task_manager:
                self._check_and_run()

    # ── 到期任务收集 ──

    def _collect_due(self, node: dict, prefix: str, now_ts: float) -> list[str]:
        tasks = []
        for key, val in node.items():
            if not isinstance(val, dict):
                continue
            path = f"{prefix}/{key}" if prefix else key
            if "fn" in val and "on" in val:
                if val.get("on") and now_ts >= val.get("next_exec_time", 0):
                    tasks.append(path)
            else:
                tasks.extend(self._collect_due(val, path, now_ts))
        return tasks

    # ── 核心调度 ──

    def _check_and_run(self):
        """逐个执行到期任务。attempted_tasks 防止失败任务在同一轮被重复执行。"""
        from AutoScriptor.utils.constant import cfg

        if not cfg._config.get("game", {}).get("character_name", ""):
            logger.warning("⚠️ 账号未验证，跳过本次调度")
            return

        os.system('cls' if os.name == 'nt' else 'clear')
        total_success = total_failed = 0
        attempted: set[str] = set()

        while self.state == SchedulerState.RUNNING:
            if self._task_manager._cancel_event.is_set():
                logger.info("⏹ 检测到取消请求，停止执行")
                break

            due = [t for t in self._collect_due(cfg["tasks"], "", time.time())
                   if t not in attempted]
            if not due:
                break

            logger.info("📅 发现 %d 个到期任务: %s", len(due), due)
            self._maybe_daily_restart(cfg)

            # 确保模拟器运行
            try:
                ensure_app_running(cfg["emulator"]["index"], cfg["emulator"]["adb_addr"], cfg["app"]["app_to_start"])
            except Exception as e:
                logger.error("📅 模拟器启动失败: %s", e)
                self._consecutive_errors += 1
                if self._consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    self.mark_error()
                break

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

            # 无论成功失败，保存并重新加载
            cfg.save_config()
            self._task_manager.reload_tasks()
            logger.info("🔄 [%s] 完成，配置已保存", task_key)

        if total_success > 0 or total_failed > 0:
            logger.info("📅 定时执行完成: 成功 %d, 失败 %d", total_success, total_failed)
            self._post_execution_action()
            self._tasks_updated.set()
            logger.info("📅 已回到待命状态，按 Enter 刷新主菜单")

    # ── 辅助 ──

    def _maybe_daily_restart(self, cfg):
        """每日 5:00 首次执行前重启模拟器（一天只触发一次）。"""
        next_ts = self.get_next_execution_timestamp()
        if not next_ts:
            return
        from datetime import datetime, time as dtime
        next_dt = datetime.fromtimestamp(next_ts)
        now_dt = datetime.now()
        if not (next_dt.date() == now_dt.date() and next_dt.hour == 5 and next_dt.minute == 0):
            return
        today_5am_ts = datetime.combine(now_dt.date(), dtime(5, 0)).timestamp()
        if cfg.get("status.last_login_time.time", 0) >= today_5am_ts:
            return
        logger.info("📅 检测到今日5:00首次执行，先关闭模拟器以清理状态")
        try:
            from AutoScriptor import mixctrl
            from AutoScriptor.control.MumuAdaptor.mumu import Mumu
            mixctrl.app.close(cfg["app"]["app_to_start"])
            time.sleep(2)
            Mumu().select(cfg["emulator"]["index"]).power.shutdown()
            time.sleep(3)
        except Exception as e:
            logger.warning("📅 关闭模拟器失败: %s", e)
        cfg.set("status.last_login_time.time", time.time())
        cfg.save_config()

    def _post_execution_action(self):
        from AutoScriptor.utils.constant import cfg
        action = cfg["emulator"].get("post_execution", "NULL").upper()
        if action == "NULL":
            return
        from AutoScriptor import mixctrl
        app_name = cfg["app"]["app_to_start"]
        if action == "CLOSE_MUMU":
            logger.info("📅 执行后: 关闭模拟器")
            mixctrl.app.close(app_name)
            time.sleep(2)
            from AutoScriptor.control.MumuAdaptor.mumu import Mumu
            Mumu().select(cfg["emulator"]["index"]).power.shutdown()
        elif action == "CLOSE_GAME_ONLY":
            logger.info("📅 执行后: 仅关闭游戏")
            mixctrl.app.close(app_name)

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
