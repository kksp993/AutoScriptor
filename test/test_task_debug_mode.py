import copy
import unittest
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch

from AutoScriptor.utils.app_config import cfg
from AutoScriptor.utils.task_registry import task_registry


class TestTaskDebugMode(unittest.TestCase):
    def setUp(self):
        self._cfg_backup = copy.deepcopy(cfg._config)
        self._reg_backup = dict(task_registry._tasks)
        task_registry.clear()

    def tearDown(self):
        cfg._config = self._cfg_backup
        task_registry._tasks = self._reg_backup

    def _install_task_config(self, *, debug_mode: bool = False):
        cfg._config = {
            "app": {
                "app_to_start": "com.test.app",
                "max_retry": 1,
                "restart_on_error": True,
            },
            "emulator": {"post_execution": "close_game_only"},
            "ocr": {"use_gpu": False},
            "game": {"character_name": "测试角色"},
            "tasks": {
                "测试": {
                    "任务": {
                        "on": True,
                        "next_exec_time": 0,
                        "params": {},
                    }
                }
            },
        }

        def boom():
            raise RuntimeError("debug boom")

        task_registry.register("测试/任务", boom, order=1, debug_mode=debug_mode)

    def test_task_manager_debug_failure_does_not_recover_app(self):
        from services.core import task_manager as tm_mod
        from services.core.task_manager import TaskManager

        self._install_task_config(debug_mode=True)
        tm = TaskManager()
        mixctrl = SimpleNamespace(release_all_keys=lambda: None)

        with patch.object(tm_mod.runtime_ctx, "mixctrl", mixctrl):
            with patch.object(tm, "_archive_error") as archive_error:
                with patch.object(tm, "_try_recover_app") as recover_app:
                    with patch.object(tm_mod.traceback, "print_exc"):
                        self.assertFalse(tm._execute_single_task("测试/任务"))

        archive_error.assert_called_once()
        recover_app.assert_not_called()

    def test_scheduler_debug_task_skips_login_restart_and_post_action(self):
        from services.core import scheduler as scheduler_mod
        from services.core.scheduler import Scheduler

        self._install_task_config(debug_mode=True)

        class FakeTaskManager:
            def __init__(self):
                self._cancel_event = Event()
                self.executed = []

            def execute_tasks(self, tasks):
                self.executed.extend(tasks)
                return 0, 1

            def reload_tasks(self):
                return None

        tm = FakeTaskManager()
        sched = Scheduler()
        sched.set_task_manager(tm)

        with patch.object(cfg, "active_character", return_value={"server": "s1", "name": "c1"}):
            with patch.object(cfg, "save_config"):
                with patch("services.core.scheduler.runtime_ctx.refresh"):
                    with patch("AutoScriptor.utils.perf.boost"):
                        with patch("AutoScriptor.utils.perf.unboost"):
                            with patch("services.core.scheduler.notify_from_config"):
                                with patch.object(sched, "_maybe_daily_restart") as daily_restart:
                                    with patch.object(sched, "_ensure_character_logged_in") as ensure_login:
                                        with patch.object(sched, "_post_execution_action") as post_action:
                                            sched._run_task_pipeline(explicit_tasks=["测试/任务"])

        self.assertEqual(tm.executed, ["测试/任务"])
        daily_restart.assert_not_called()
        ensure_login.assert_not_called()
        post_action.assert_not_called()


if __name__ == "__main__":
    unittest.main()
