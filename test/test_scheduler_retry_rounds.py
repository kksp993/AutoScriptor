import copy
import unittest
from threading import Event
from unittest.mock import patch

from AutoScriptor.utils.app_config import cfg


class FakeRoundTaskManager:
    def __init__(self, outcomes):
        self._cancel_event = Event()
        self.outcomes = outcomes
        self.calls = []

    def execute_tasks(self, tasks, *, max_attempts=None, attempt_offset=0):
        task = tasks[0]
        self.calls.append((task, attempt_offset))
        outcome = self.outcomes.get((task, attempt_offset), (1, 0))
        return outcome

    def reload_tasks(self):
        return None


class TestSchedulerRetryRounds(unittest.TestCase):
    def setUp(self):
        self._cfg_backup = copy.deepcopy(cfg._config)
        cfg._config = {
            "app": {
                "app_to_start": "com.test.app",
                "max_retry": 2,
                "restart_on_error": True,
            },
            "emulator": {"post_execution": "none"},
            "game": {"character_name": "tester"},
            "tasks": {},
        }

    def tearDown(self):
        cfg._config = self._cfg_backup

    def _run_with_fake_manager(self, tm):
        from services.core.scheduler import Scheduler

        sched = Scheduler()
        sched.set_task_manager(tm)
        with patch.object(cfg, "active_character", return_value={"server": "s1", "name": "c1"}):
            with patch.object(cfg, "save_config"):
                with patch("services.core.scheduler.runtime_ctx.refresh"):
                    with patch("AutoScriptor.utils.perf.boost"):
                        with patch("AutoScriptor.utils.perf.unboost"):
                            with patch("services.core.scheduler.notify_from_config"):
                                with patch.object(sched, "_maybe_daily_restart"):
                                    with patch.object(sched, "_ensure_character_logged_in"):
                                        with patch.object(sched, "_post_execution_action"):
                                            sched._run_task_pipeline(explicit_tasks=["A", "B"])

    def _run_scheduled_with_fake_manager(self, sched, due_tasks):
        from services.core.scheduler import SchedulerState

        sched.state = SchedulerState.RUNNING
        with patch.object(cfg, "active_character", return_value={"server": "s1", "name": "c1"}):
            with patch.object(cfg, "save_config"):
                with patch.object(sched, "_collect_due_cross_character", return_value=due_tasks):
                    with patch("services.core.scheduler.runtime_ctx.refresh"):
                        with patch("AutoScriptor.utils.perf.boost"):
                            with patch("AutoScriptor.utils.perf.unboost"):
                                with patch("services.core.scheduler.notify_from_config"):
                                    with patch.object(sched, "_maybe_daily_restart"):
                                        with patch.object(sched, "_ensure_character_logged_in"):
                                            with patch.object(sched, "_post_execution_action"):
                                                sched._run_task_pipeline(explicit_tasks=None)

    def test_failed_task_retries_after_other_tasks_finish_round(self):
        tm = FakeRoundTaskManager({
            ("A", 0): (0, 1),
            ("A", 1): (1, 0),
            ("B", 0): (1, 0),
        })

        self._run_with_fake_manager(tm)

        self.assertEqual(tm.calls, [("A", 0), ("B", 0), ("A", 1)])

    def test_failed_task_stops_after_max_retry_rounds(self):
        tm = FakeRoundTaskManager({
            ("A", 0): (0, 1),
            ("A", 1): (0, 1),
            ("A", 2): (0, 1),
            ("B", 0): (1, 0),
        })

        self._run_with_fake_manager(tm)

        self.assertEqual(tm.calls, [("A", 0), ("B", 0), ("A", 1), ("A", 2)])

    def test_scheduled_task_exhaustion_survives_next_pipeline_scan(self):
        from services.core.scheduler import Scheduler

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
        from services.core.scheduler import CHECK_INTERVAL, Scheduler

        cfg._config["tasks"] = {"A": {"on": True, "next_exec_time": 0}}
        sched = Scheduler()
        sched._mark_retry_exhausted(("s1", "c1"), "A", 2)

        with patch.object(cfg, "active_character", return_value={"server": "s1", "name": "c1"}):
            with patch.object(sched, "_iter_characters_schedule_order", return_value=iter([("s1", "c1")])):
                with patch("AutoScriptor.utils.task_registry.task_registry.has_task", return_value=True):
                    self.assertEqual(sched._collect_active_times(), [])
                    self.assertEqual(sched._get_wait_interval(), CHECK_INTERVAL)


if __name__ == "__main__":
    unittest.main()
