import copy
import unittest
from threading import Event, Thread
from unittest.mock import patch

from AutoScriptor.utils.app_config import cfg


class FakeRoundTaskManager:
    def __init__(self, outcomes):
        self._cancel_event = Event()
        self.outcomes = outcomes
        self.calls = []
        self.reload_calls = 0
        self.character_switches = []
        self.full_character_reload_switches = []

    def execute_tasks(self, tasks, *, max_attempts=None, attempt_offset=0):
        task = tasks[0]
        self.calls.append((task, attempt_offset))
        outcome = self.outcomes.get((task, attempt_offset), (1, 0))
        return outcome

    def reload_tasks(self):
        self.reload_calls += 1
        return None

    def switch_character(self, server, character):
        self.character_switches.append((server, character))

    def switch_character_and_reload(self, server, character):
        self.full_character_reload_switches.append((server, character))
        self.reload_tasks()


class TestSchedulerExecutionGate(unittest.TestCase):
    def test_enabled_idle_scheduler_is_not_busy(self):
        from orchestrator.scheduler import Scheduler, SchedulerState

        scheduler = Scheduler()
        scheduler.state = SchedulerState.RUNNING

        status = scheduler.status_dict()

        self.assertTrue(status["enabled"])
        self.assertFalse(status["executing"])
        self.assertFalse(status["busy"])

    def test_scheduler_waits_for_direct_execution_without_deactivating(self):
        from orchestrator.scheduler import Scheduler, SchedulerState

        scheduler = Scheduler()
        scheduler.state = SchedulerState.RUNNING
        scheduler_attempted_execution = Event()
        scheduler_pipeline_started = Event()
        original_acquire_execution = scheduler.acquire_execution

        def acquire_execution(owner, *, blocking=True):
            if owner == "scheduler":
                scheduler_attempted_execution.set()
            return original_acquire_execution(owner, blocking=blocking)

        self.assertTrue(scheduler.acquire_execution("direct_run", blocking=False))
        with (
            patch.object(scheduler, "acquire_execution", side_effect=acquire_execution),
            patch.object(
                scheduler,
                "_run_task_pipeline",
                side_effect=lambda *args, **kwargs: scheduler_pipeline_started.set(),
            ),
            patch("orchestrator.scheduler.os.system"),
        ):
            scheduler_thread = Thread(target=scheduler._check_and_run, daemon=True)
            scheduler_thread.start()

            self.assertTrue(scheduler_attempted_execution.wait(timeout=1))
            self.assertFalse(scheduler_pipeline_started.wait(timeout=0.05))

            scheduler.release_execution("direct_run")
            self.assertTrue(scheduler_pipeline_started.wait(timeout=1))
            scheduler_thread.join(timeout=1)

        self.assertFalse(scheduler_thread.is_alive())
        self.assertEqual(scheduler.state, SchedulerState.RUNNING)
        self.assertIsNone(scheduler.execution_owner)

    def test_scheduler_does_not_start_after_being_deactivated_while_waiting(self):
        from orchestrator.scheduler import Scheduler, SchedulerState

        scheduler = Scheduler()
        scheduler.state = SchedulerState.RUNNING
        scheduler_attempted_execution = Event()
        scheduler_pipeline_started = Event()
        original_acquire_execution = scheduler.acquire_execution

        def acquire_execution(owner, *, blocking=True):
            if owner == "scheduler":
                scheduler_attempted_execution.set()
            return original_acquire_execution(owner, blocking=blocking)

        self.assertTrue(scheduler.acquire_execution("editor", blocking=False))
        with (
            patch.object(scheduler, "acquire_execution", side_effect=acquire_execution),
            patch.object(
                scheduler,
                "_run_task_pipeline",
                side_effect=lambda *args, **kwargs: scheduler_pipeline_started.set(),
            ),
            patch("orchestrator.scheduler.os.system"),
        ):
            scheduler_thread = Thread(target=scheduler._check_and_run, daemon=True)
            scheduler_thread.start()

            self.assertTrue(scheduler_attempted_execution.wait(timeout=1))
            scheduler.deactivate()
            scheduler.release_execution("editor")
            scheduler_thread.join(timeout=1)

        self.assertFalse(scheduler_thread.is_alive())
        self.assertFalse(scheduler_pipeline_started.is_set())
        self.assertEqual(scheduler.state, SchedulerState.PENDING)
        self.assertIsNone(scheduler.execution_owner)


class TestSchedulerRetryRounds(unittest.TestCase):
    def setUp(self):
        self._cfg_backup = copy.deepcopy(cfg._config)
        cfg._config = {
            "app": {
                "app_to_start": "com.test.app",
                "max_attempts": 3,
                "restart_on_error": True,
            },
            "emulator": {"post_execution": "none"},
            "game": {"character_name": "tester"},
            "tasks": {},
        }

    def tearDown(self):
        cfg._config = self._cfg_backup

    def _run_with_fake_manager(self, tm):
        from orchestrator.scheduler import Scheduler

        sched = Scheduler()
        sched.set_task_manager(tm)
        with (
            patch.object(cfg, "active_character", return_value={"server": "s1", "name": "c1"}),
            patch.object(cfg, "save_config") as save_config,
            patch("orchestrator.scheduler.runtime_ctx.refresh"),
            patch("orchestrator.scheduler.notify_runtime_event"),
            patch.object(sched, "_maybe_daily_restart"),
            patch.object(sched, "_ensure_character_logged_in"),
            patch.object(sched, "_post_execution_action"),
        ):
            sched._run_task_pipeline(explicit_tasks=["A", "B"])
        return sched, save_config

    def _run_scheduled_with_fake_manager(self, sched, due_tasks):
        from orchestrator.scheduler import SchedulerState

        sched.state = SchedulerState.RUNNING
        with (
            patch.object(cfg, "active_character", return_value={"server": "s1", "name": "c1"}),
            patch.object(cfg, "save_config") as save_config,
            patch.object(sched, "_collect_due_cross_character", return_value=due_tasks),
            patch("orchestrator.scheduler.runtime_ctx.refresh"),
            patch("orchestrator.scheduler.notify_runtime_event"),
            patch.object(sched, "_maybe_daily_restart"),
            patch.object(sched, "_ensure_character_logged_in"),
            patch.object(sched, "_post_execution_action"),
            patch.object(sched, "_return_to_first_dispatch_character"),
        ):
            sched._run_task_pipeline(explicit_tasks=None)
        return save_config

    def test_explicit_pipeline_saves_config_without_full_reload(self):
        tm = FakeRoundTaskManager({
            ("A", 0): (1, 0),
            ("B", 0): (1, 0),
        })

        _, save_config = self._run_with_fake_manager(tm)

        self.assertEqual(save_config.call_count, 2)
        self.assertEqual(tm.reload_calls, 0)

    def test_character_notification_merges_retry_results(self):
        from orchestrator.delivery import CharacterReports

        messages = []
        reports = CharacterReports(messages.append, [("s1", "c1")])
        manager = FakeRoundTaskManager({("A", 0): (0, 1), ("A", 1): (1, 0)})
        with patch("orchestrator.scheduler.create_character_reports", return_value=reports):
            self._run_with_fake_manager(manager)
        self.assertEqual(len(messages), 1)
        self.assertIn("1:(c1)任务完成-成功:2,失败:0", messages[0])

    def test_character_notification_marks_cancelled_attempt_pending(self):
        from orchestrator.delivery import CharacterReports

        messages = []
        reports = CharacterReports(messages.append, [("s1", "c1")])
        manager = FakeRoundTaskManager({})

        def cancel_attempt(tasks, **kwargs):
            manager._cancel_event.set()
            return 0, 1

        with (
            patch.object(manager, "execute_tasks", side_effect=cancel_attempt),
            patch("orchestrator.scheduler.create_character_reports", return_value=reports),
        ):
            self._run_with_fake_manager(manager)
        self.assertEqual(len(messages), 1)
        self.assertIn("已中断", messages[0])
        self.assertIn("A未完成", messages[0])
        self.assertNotIn("任务完成", messages[0])

    def test_cross_character_notifications_wait_for_each_final_retry(self):
        from orchestrator.delivery import CharacterReports
        from orchestrator.scheduler import Scheduler, SchedulerState

        current = {"server": "s1", "name": "first"}
        messages = []
        reports = CharacterReports(messages.append, [("s1", "first"), ("s2", "second")])
        manager = FakeRoundTaskManager({("A", 0): (0, 1), ("A", 1): (1, 0)})
        scheduler = Scheduler()
        scheduler.set_task_manager(manager)
        scheduler.state = SchedulerState.RUNNING
        selections = iter([("s1", "first", ["A"]), ("s2", "second", ["B"]), ("s2", "second", [])])

        def collect_due():
            server, character, paths = next(selections)
            current.update(server=server, name=character)
            return paths

        with (
            patch.object(cfg, "active_character", side_effect=lambda: dict(current)),
            patch.object(cfg, "save_config"),
            patch.object(scheduler, "_collect_due_cross_character", side_effect=collect_due),
            patch.object(scheduler, "_switch_active_character", side_effect=lambda server, name: current.update(server=server, name=name)),
            patch.object(scheduler, "_maybe_daily_restart"),
            patch.object(scheduler, "_ensure_character_logged_in"),
            patch.object(scheduler, "_return_to_first_dispatch_character"),
            patch.object(scheduler, "_post_execution_action"),
            patch("orchestrator.scheduler.runtime_ctx.refresh"),
            patch("orchestrator.scheduler.notify_runtime_event"),
            patch("orchestrator.scheduler.create_character_reports", return_value=reports),
        ):
            scheduler._run_task_pipeline()
        self.assertEqual(manager.calls, [("A", 0), ("B", 0), ("A", 1)])
        self.assertEqual(len(messages), 2)
        self.assertIn("2:(second)任务完成-成功:1,失败:0", messages[0])
        self.assertIn("1:(first)任务完成-成功:1,失败:0", messages[1])

    def test_scheduled_pipeline_saves_config_without_full_reload(self):
        from orchestrator.scheduler import Scheduler

        tm = FakeRoundTaskManager({("A", 0): (1, 0)})
        sched = Scheduler()
        sched.set_task_manager(tm)

        save_config = self._run_scheduled_with_fake_manager(sched, ["A"])

        self.assertEqual(save_config.call_count, 1)
        self.assertEqual(tm.reload_calls, 0)

    def test_deferred_reload_still_uses_full_reload(self):
        from orchestrator.scheduler import Scheduler

        tm = FakeRoundTaskManager({("A", 0): (1, 0)})
        sched = Scheduler()
        sched.set_task_manager(tm)
        sched._reload_deferred.set()

        with (
            patch.object(cfg, "active_character", return_value={"server": "s1", "name": "c1"}),
            patch.object(cfg, "save_config") as save_config,
            patch("orchestrator.scheduler.runtime_ctx.refresh"),
            patch("orchestrator.scheduler.notify_runtime_event"),
            patch.object(sched, "_maybe_daily_restart"),
            patch.object(sched, "_ensure_character_logged_in"),
            patch.object(sched, "_post_execution_action"),
        ):
            sched._run_task_pipeline(explicit_tasks=["A"])

        self.assertEqual(save_config.call_count, 0)
        self.assertEqual(tm.reload_calls, 1)
        self.assertFalse(sched._reload_deferred.is_set())

    def test_collect_due_cross_character_uses_lightweight_switch(self):
        from orchestrator.scheduler import Scheduler

        current = {"server": "s1", "name": "first"}

        class SwitchingTaskManager(FakeRoundTaskManager):
            def switch_character(self, server, character):
                super().switch_character(server, character)
                current.update({"server": server, "name": character})

            def switch_character_and_reload(self, server, character):
                super().switch_character_and_reload(server, character)
                current.update({"server": server, "name": character})

        tm = SwitchingTaskManager({})
        sched = Scheduler()
        sched.set_task_manager(tm)
        dispatch_order = [("s1", "first"), ("s2", "second")]

        with (
            patch.object(cfg, "active_character", side_effect=lambda: dict(current)),
            patch.object(sched, "_iter_characters_schedule_order", return_value=iter(dispatch_order)),
            patch.object(sched, "_collect_due", side_effect=[[], ["A"]]),
        ):
            due = sched._collect_due_cross_character()

        self.assertEqual(due, ["A"])
        self.assertEqual(tm.character_switches, [("s2", "second")])
        self.assertEqual(tm.full_character_reload_switches, [])
        self.assertEqual(tm.reload_calls, 0)

    def test_failed_task_retries_after_other_tasks_finish_round(self):
        tm = FakeRoundTaskManager({
            ("A", 0): (0, 1),
            ("A", 1): (1, 0),
            ("B", 0): (1, 0),
        })

        self._run_with_fake_manager(tm)

        self.assertEqual(tm.calls, [("A", 0), ("B", 0), ("A", 1)])

    def test_failed_task_stops_after_max_attempts(self):
        tm = FakeRoundTaskManager({
            ("A", 0): (0, 1),
            ("A", 1): (0, 1),
            ("A", 2): (0, 1),
            ("B", 0): (1, 0),
        })

        self._run_with_fake_manager(tm)

        self.assertEqual(tm.calls, [("A", 0), ("B", 0), ("A", 1), ("A", 2)])

    def test_scheduled_task_exhaustion_survives_next_pipeline_scan(self):
        from orchestrator.scheduler import Scheduler

        tm = FakeRoundTaskManager({
            ("A", 0): (0, 1),
            ("A", 1): (0, 1),
            ("A", 2): (0, 1),
        })
        sched = Scheduler()
        sched.set_task_manager(tm)

        self._run_scheduled_with_fake_manager(sched, ["A"])
        self._run_scheduled_with_fake_manager(sched, ["A"])

        self.assertEqual(tm.calls, [("A", 0), ("A", 1), ("A", 2)])

    def test_exhausted_scheduled_task_does_not_force_zero_wait_spin(self):
        from orchestrator.scheduler import CHECK_INTERVAL, Scheduler
        from tasks.task_register import task_registry

        cfg._config["tasks"] = {"A": {"on": True, "next_exec_time": 0}}
        sched = Scheduler()
        sched._mark_retry_exhausted(("s1", "c1"), "A", 2)

        with patch.object(cfg, "active_character", return_value={"server": "s1", "name": "c1"}):
            with patch.object(sched, "_iter_characters_schedule_order", return_value=iter([("s1", "c1")])):
                with patch.object(task_registry, "has_task", return_value=True):
                    self.assertEqual(sched._collect_active_times(), [])
                    self.assertEqual(sched._get_wait_interval(), CHECK_INTERVAL)

    def test_stop_restores_error_budget_without_clearing_cancel_signal(self):
        from orchestrator.scheduler import Scheduler, SchedulerState

        class CancellableTaskManager:
            def __init__(self):
                self._cancel_event = Event()

            def request_cancel(self):
                self._cancel_event.set()

            def _reset_cancel(self):
                self._cancel_event.clear()

        task_manager = CancellableTaskManager()
        sched = Scheduler()
        sched.set_task_manager(task_manager)
        sched.state = SchedulerState.ERROR
        sched._consecutive_errors = 3
        sched._mark_retry_exhausted(("s1", "c1"), "A", 2)

        sched.request_stop()

        self.assertEqual(sched.state, SchedulerState.PENDING)
        self.assertEqual(sched._consecutive_errors, 0)
        # 标记存的是「打标记的时刻」（key -> timestamp），不是裸 key 集合。
        self.assertEqual(sched._retry_exhausted_tasks, {})
        self.assertTrue(task_manager._cancel_event.is_set())
        self.assertTrue(sched._wake.is_set())

        sched.record_result(0, 1)
        self.assertEqual(sched._consecutive_errors, 0)
        self.assertEqual(sched.state, SchedulerState.PENDING)

        sched._mark_retry_exhausted(("s1", "c1"), "A", 2)
        self.assertEqual(sched._retry_exhausted_tasks, {})

        sched.reset()
        self.assertFalse(task_manager._cancel_event.is_set())

    def test_scheduled_pipeline_returns_to_first_dispatch_character(self):
        from orchestrator.scheduler import Scheduler, SchedulerState

        class SwitchingTaskManager(FakeRoundTaskManager):
            def __init__(self, current):
                super().__init__({("A", 0): (1, 0)})
                self._current = current
                self.switches = []
                self.full_switches = []

            def switch_character(self, server, character):
                self.switches.append((server, character))
                self._current.update({"server": server, "name": character})

            def switch_character_and_reload(self, server, character):
                self.full_switches.append((server, character))
                self.reload_tasks()
                self._current.update({"server": server, "name": character})

        current = {"server": "s2", "name": "last"}
        tm = SwitchingTaskManager(current)
        sched = Scheduler()
        sched.state = SchedulerState.RUNNING
        sched.set_task_manager(tm)

        dispatch_order = [("s1", "first"), ("s2", "last")]
        ensure_seen = []
        def record_login(_cfg):
            ensure_seen.append(dict(current))

        with (
            patch.object(cfg, "active_character", side_effect=lambda: dict(current)),
            patch("orchestrator.scheduler.iter_dispatch_characters", side_effect=lambda _cfg: iter(dispatch_order)),
            patch.object(cfg, "save_config"),
            patch.object(sched, "_collect_due_cross_character", return_value=["A"]),
            patch("orchestrator.scheduler.runtime_ctx.refresh"),
            patch("orchestrator.scheduler.notify_runtime_event"),
            patch.object(sched, "_maybe_daily_restart"),
            patch.object(sched, "_ensure_character_logged_in", side_effect=record_login),
            patch.object(sched, "_post_execution_action"),
        ):
            sched._run_task_pipeline(explicit_tasks=None)

        self.assertEqual(tm.calls, [("A", 0)])
        self.assertEqual(tm.switches, [("s1", "first")])
        self.assertEqual(tm.full_switches, [])
        self.assertEqual(tm.reload_calls, 0)
        self.assertEqual(ensure_seen, [
            {"server": "s2", "name": "last"},
            {"server": "s1", "name": "first"},
        ])
        self.assertEqual(current, {"server": "s1", "name": "first"})


class TestSchedulerSelfHealing(unittest.TestCase):
    """调度自己从「跳过一个任务」和「整机停摆」里恢复的能力。

    抓过的事故（2026-10-06）：任务到期了、也在调度时间窗内，却没有继续跑。
    两个独立原因叠加：

    1. 失败耗尽重试的任务被**永久**跳过。标记只在重新激活调度时清除，而用户
       往往一直开着调度不点停止，于是昨天失败过的任务今天到期也不会跑。
    2. 连续错误把调度送进 ERROR，而 ERROR 只能靠人工点「恢复调度」出来。更糟
       的是计数把重试也算上，一个必失败的任务（1 主跑 + 2 重试）就能停掉全部。
    """

    def test_retry_skip_expires_when_the_task_gets_a_new_plan(self):
        """retry 跳过只作用于同一份计划；任务被排到未来后它就该失效。"""
        import time

        from orchestrator.scheduler import Scheduler

        sched = Scheduler()
        sched._mark_retry_exhausted(("s1", "c1"), "每日任务/村庄/某任务", 2)

        # 同一份计划：next_exec_time 还停在过去（失败后没被推进）→ 继续跳过，
        # 这是标记本来的用途，挡住同一计划内的无限重试。
        with patch.object(Scheduler, "_next_exec_time_of", return_value=0.0):
            self.assertTrue(sched._is_retry_exhausted(("s1", "c1"), "每日任务/村庄/某任务"))

        # 任务已被排到未来（第二天 05:00）→ 这是新一轮计划，标记失效。
        with patch.object(Scheduler, "_next_exec_time_of", return_value=time.time() + 86400):
            self.assertFalse(sched._is_retry_exhausted(("s1", "c1"), "每日任务/村庄/某任务"))

            # 失效是持久的：再查一次仍然放行，而不是每次都要重新判定。
            self.assertFalse(sched._is_retry_exhausted(("s1", "c1"), "每日任务/村庄/某任务"))

    def test_one_bad_task_does_not_trip_the_error_state(self):
        """同一个任务反复失败按同一故障计，不该把整个调度停掉。"""
        from orchestrator.scheduler import MAX_CONSECUTIVE_ERRORS, Scheduler, SchedulerState

        sched = Scheduler()
        with patch("orchestrator.scheduler.notify_runtime_event"):
            for _ in range(MAX_CONSECUTIVE_ERRORS + 3):
                sched.record_result(0, 1, "其他任务/特殊功能/领取4399优惠券")

        self.assertEqual(sched.state, SchedulerState.PENDING, "一个坏任务不该让调度停机")
        self.assertEqual(sched._consecutive_errors, 1, "同一个任务只贡献一次错误")

    def test_different_tasks_failing_still_trip_the_error_state(self):
        """不同任务接连失败是真的环境故障，仍然要停机保护。"""
        from orchestrator.scheduler import MAX_CONSECUTIVE_ERRORS, Scheduler, SchedulerState

        sched = Scheduler()
        with patch("orchestrator.scheduler.notify_runtime_event"):
            for index in range(MAX_CONSECUTIVE_ERRORS):
                sched.record_result(0, 1, f"每日任务/村庄/任务{index}")
            self.assertEqual(sched.state, SchedulerState.ERROR)

    def test_success_clears_the_repeat_failure_tracking(self):
        """成功后重新开始计数：隔了一个成功任务的失败是新故障。"""
        from orchestrator.scheduler import Scheduler, SchedulerState

        sched = Scheduler()
        with patch("orchestrator.scheduler.notify_runtime_event"):
            sched.record_result(0, 1, "任务A")
            self.assertEqual(sched._consecutive_errors, 1)
            sched.record_result(1, 0)
            self.assertEqual(sched._consecutive_errors, 0)
            self.assertIsNone(sched._last_failed_task)
            # 同一个任务再次失败，因为中间成功过，算新的一次错误。
            sched.record_result(0, 1, "任务A")
        self.assertEqual(sched._consecutive_errors, 1)
        self.assertEqual(sched.state, SchedulerState.PENDING)

    def test_error_state_recovers_after_the_cooldown(self):
        """ERROR 不是终点：冷却结束后自动恢复，不需要人工点「恢复调度」。"""
        import time

        from orchestrator.scheduler import (
            ERROR_AUTO_RECOVER_SECONDS,
            Scheduler,
            SchedulerState,
        )

        sched = Scheduler()
        sched._consecutive_errors = 3
        with patch("orchestrator.scheduler.notify_runtime_event"):
            sched.mark_error()
        self.assertEqual(sched.state, SchedulerState.ERROR)

        # 冷却没到 → 保持错误态
        self.assertFalse(sched._maybe_recover_from_error())
        self.assertEqual(sched.state, SchedulerState.ERROR)

        # 冷却到了 → 自动回到 running（patch 掉 _loop：测试里不需要真的调度线程）
        sched._error_at = time.time() - ERROR_AUTO_RECOVER_SECONDS - 1
        with patch.object(Scheduler, "_loop", return_value=None):
            self.assertTrue(sched._maybe_recover_from_error())
        self.assertEqual(sched.state, SchedulerState.RUNNING)
        self.assertEqual(sched._consecutive_errors, 0)

    def test_error_state_wakes_up_to_notice_the_cooldown(self):
        """错误态必须定期醒来检查冷却，否则可能一觉睡到明天的任务点。"""
        import time

        from orchestrator.scheduler import (
            ERROR_AUTO_RECOVER_SECONDS,
            ERROR_WAKE_INTERVAL,
            Scheduler,
            SchedulerState,
        )

        sched = Scheduler()
        sched.state = SchedulerState.ERROR
        sched._error_at = time.time()

        self.assertLessEqual(sched._get_wait_interval(), ERROR_WAKE_INTERVAL)

        # 冷却已过 → 立即醒来处理
        sched._error_at = time.time() - ERROR_AUTO_RECOVER_SECONDS - 1
        self.assertEqual(sched._get_wait_interval(), 0)


if __name__ == "__main__":
    unittest.main()
