"""
AutoScriptor 后台定时调度器（极简版）
======================================
一个轻量后台 daemon 线程，每小时醒一次，扫描到期任务并执行。
平时 99.9% 时间在 sleep，几乎零开销。

状态机：
  PENDING (绿) ─── 用户按下 Run ───▶ RUNNING (黄)
  RUNNING (黄) ─── 正常退出/未验证 ──▶ PENDING (绿)
  RUNNING (黄) ─── 连续失败 ≥3 ─────▶ ERROR   (红)
  ERROR   (红) ─── 手动恢复 ────────▶ PENDING (绿)
"""

import threading
import time
from enum import Enum
from logzero import logger


class SchedulerState(Enum):
    PENDING = "pending"   # 绿色：待运行
    RUNNING = "running"   # 黄色：运行中
    ERROR   = "error"     # 红色：发生错误


CHECK_INTERVAL = 3600  # 秒（1 小时）
MAX_CONSECUTIVE_ERRORS = 3


class Scheduler:
    """极简后台调度器。无锁、无单例花样，就是一个 daemon 线程 + Event.wait。"""

    def __init__(self):
        self.state = SchedulerState.PENDING
        self._task_manager = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._consecutive_errors = 0

    # ── 外部注入 ──

    def set_task_manager(self, tm):
        self._task_manager = tm

    # ── 状态转换 ──

    def activate(self):
        """用户按下 Run 后调用。"""
        if self.state == SchedulerState.ERROR:
            return  # ERROR 需要手动 reset
        if self.state != SchedulerState.RUNNING:
            logger.info("📅 调度器: %s → running", self.state.value)
        self.state = SchedulerState.RUNNING
        self._consecutive_errors = 0
        # 确保后台线程在跑
        if not self._thread or not self._thread.is_alive():
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, daemon=True, name="Scheduler")
            self._thread.start()

    def deactivate(self):
        if self.state != SchedulerState.PENDING:
            logger.info("📅 调度器: %s → pending", self.state.value)
        self.state = SchedulerState.PENDING

    def mark_error(self):
        if self.state != SchedulerState.ERROR:
            logger.error("📅 调度器: %s → error (连续失败 %d 次)", self.state.value, self._consecutive_errors)
        self.state = SchedulerState.ERROR

    def reset(self):
        """手动恢复。"""
        logger.info("📅 调度器: %s → pending (手动恢复)", self.state.value)
        self.state = SchedulerState.PENDING
        self._consecutive_errors = 0

    def stop(self):
        self._stop.set()

    # ── 结果反馈（由 CLI/WebUI 在 execute 结束后调用）──

    def record_result(self, success: int, failed: int):
        """记录一次执行结果，决定是否进入 ERROR。"""
        if failed > 0:
            self._consecutive_errors += 1
            if self._consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                self.mark_error()
        else:
            self._consecutive_errors = 0

    # ── 后台循环 ──

    def _get_wait_interval(self):
        """计算下一次等待的间隔时间，基于任务的最早到期时间。"""
        from AutoScriptor.utils.constant import cfg
        import time
        now_ts = time.time()
        next_times = []

        def _collect(node: dict):
            for key, val in node.items():
                if not isinstance(val, dict):
                    continue
                if 'fn' in val and 'on' in val and val.get('on'):
                    next_times.append(val.get('next_exec_time', now_ts))
                else:
                    _collect(val)

        _collect(cfg["tasks"])
        # 过滤未来时间，计算最早到期任务的间隔
        future = [t for t in next_times if t > now_ts]
        if future:
            return max(min(future) - now_ts, 0)
        return CHECK_INTERVAL

    def get_next_execution_timestamp(self):
        """返回最早到期任务的绝对时间戳，如果没有到期任务则返回 None。"""
        from AutoScriptor.utils.constant import cfg
        import time
        now_ts = time.time()
        next_times = []

        def _collect(node: dict):
            for key, val in node.items():
                if not isinstance(val, dict):
                    continue
                if 'fn' in val and 'on' in val and val.get('on'):
                    next_times.append(val.get('next_exec_time', now_ts))
                else:
                    _collect(val)

        _collect(cfg["tasks"])
        # 过滤未来时间，取最早到期任务时间
        future = [t for t in next_times if t > now_ts]
        if future:
            return min(future)
        return None

    def _loop(self):
        """主循环：根据最早到期任务时间动态 sleep，实现可中断的精确调度。"""
        while True:
            interval = self._get_wait_interval()
            if self._stop.wait(interval):
                break
            if self.state != SchedulerState.RUNNING or not self._task_manager:
                continue
            self._check_and_run()

    def _check_and_run(self):
        """扫描到期任务并执行。"""
        from AutoScriptor.utils.constant import cfg
        now_ts = time.time()
        due = self._collect_due(cfg["tasks"], "", now_ts)
        if not due:
            return

        logger.info("📅 发现 %d 个到期任务: %s", len(due), due)

        # 启动模拟器（如果没在运行）
        try:
            from AutoScriptor import mixctrl
            app_name = cfg["app"]["app_to_start"]
            if mixctrl.app.state(app_name) != "running":
                logger.info("📅 正在启动模拟器...")
                mixctrl.app.launch(app_name)
                time.sleep(10)
        except Exception as e:
            logger.error("📅 启动模拟器失败: %s", e)
            self._consecutive_errors += 1
            if self._consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                self.mark_error()
            return

        # 执行任务（不做 boost/unboost，api.py 启动时已经 boost 过了）
        try:
            success, failed = self._task_manager.execute_tasks(due)
            logger.info("📅 定时执行完成: 成功 %d, 失败 %d", success, failed)
            self.record_result(success, failed)
        except Exception as e:
            logger.error("📅 定时执行异常: %s", e)
            self._consecutive_errors += 1
            if self._consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                self.mark_error()
        finally:
            self._post_execution_action()

    # ── 辅助 ──

    def _collect_due(self, node: dict, prefix: str, now_ts: float) -> list:
        """递归收集 on=True 且 next_exec_time <= now 的任务路径。"""
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

    def _post_execution_action(self):
        """根据 config 执行任务完成后的动作。"""
        from AutoScriptor.utils.constant import cfg
        action = cfg["emulator"].get("post_execution", "NULL").upper()
        if action == "NULL":
            return
        try:
            from AutoScriptor import mixctrl
            app_name = cfg["app"]["app_to_start"]
            if action == "CLOSE_MUMU":
                logger.info("📅 执行后: 关闭模拟器")
                try:
                    mixctrl.app.close(app_name)
                except Exception:
                    pass
                time.sleep(2)
                try:
                    from AutoScriptor.control.MumuAdaptor.mumu import Mumu
                    Mumu().select(cfg["emulator"]["index"]).power.shutdown()
                except Exception:
                    pass
            elif action == "CLOSE_GAME_ONLY":
                logger.info("📅 执行后: 仅关闭游戏")
                try:
                    mixctrl.app.close(app_name)
                except Exception:
                    pass
        except Exception as e:
            logger.warning("📅 执行后动作异常: %s", e)

    # ── 状态查询 ──

    @property
    def state_label(self) -> str:
        return {"pending": "待运行", "running": "运行中", "error": "发生错误"}.get(self.state.value, "")

    def status_dict(self) -> dict:
        return {
            "state": self.state.value,
            "label": self.state_label,
            "color": {"pending": "green", "running": "orange", "error": "red"}.get(self.state.value, "gray"),
            "consecutive_errors": self._consecutive_errors,
        }


# 模块级实例
scheduler = Scheduler()
