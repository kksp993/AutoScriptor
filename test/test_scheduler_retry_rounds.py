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


if __name__ == "__main__":
    unittest.main()
