import copy
import importlib
import unittest
from datetime import datetime
from threading import Event
from unittest.mock import patch

from AutoScriptor.utils.app_config import cfg
from orchestrator.scheduler import Scheduler
from tasks.task_register import task_registry


# ``orchestrator.scheduler`` 这个包属性在 lazy export 后指向单例对象，不能拿来
# 当模块 patch；直接取 sys.modules 里的模块本体。
scheduler_module = importlib.import_module("orchestrator.scheduler")


def _frozen_datetime(moment: datetime):
    return type("FrozenDateTime", (datetime,), {"now": classmethod(lambda cls, tz=None: moment)})


class FakeTaskManager:
    def __init__(self):
        self._cancel_event = Event()
        self.executed = []

    def execute_tasks(self, tasks, **kwargs):
        self.executed.extend(tasks)
        return 1, 0

    def reload_tasks(self):
        return None

    def _reset_cancel(self):
        self._cancel_event.clear()


class TestDailyRestartTrigger(unittest.TestCase):
    def _restart_with_frozen_clock(self, moment, shutdown_ok=True):
        scheduler = Scheduler()
        scheduler._logged_in_character = ("s1", "c1")
        with (
            patch.object(scheduler_module, "datetime", _frozen_datetime(moment)),
            patch.object(
                scheduler, "_safe_shutdown_emulator", return_value=shutdown_ok
            ) as shutdown,
        ):
            scheduler._maybe_daily_restart(cfg)
        return scheduler, shutdown

    def test_first_run_after_5am_restarts_and_invalidates_login(self):
        scheduler, shutdown = self._restart_with_frozen_clock(datetime(2026, 10, 25, 5, 0, 1))

        shutdown.assert_called_once()
        self.assertEqual(shutdown.call_args.kwargs["reason"], "每日重启")
        self.assertIsNone(scheduler._logged_in_character)

    def test_same_day_second_run_does_not_restart_again(self):
        scheduler = Scheduler()
        shared_now = [datetime(2026, 10, 25, 5, 0, 1)]

        def frozen_now(cls, tz=None):
            return shared_now[0]

        with (
            patch.object(
                scheduler_module,
                "datetime",
                type("FrozenDateTime", (datetime,), {"now": classmethod(frozen_now)}),
            ),
            patch.object(scheduler, "_safe_shutdown_emulator", return_value=True) as shutdown,
        ):
            scheduler._maybe_daily_restart(cfg)
            shared_now[0] = datetime(2026, 10, 25, 23, 59, 59)
            scheduler._maybe_daily_restart(cfg)

        shutdown.assert_called_once()

    def test_before_5am_does_not_restart(self):
        _, shutdown = self._restart_with_frozen_clock(datetime(2026, 10, 25, 4, 59, 59))

        shutdown.assert_not_called()

    def test_next_game_day_restarts_again(self):
        scheduler = Scheduler()
        now = [datetime(2026, 10, 25, 5, 0, 1)]

        def frozen_now(cls, tz=None):
            return now[0]

        with (
            patch.object(
                scheduler_module,
                "datetime",
                type("FrozenDateTime", (datetime,), {"now": classmethod(frozen_now)}),
            ),
            patch.object(scheduler, "_safe_shutdown_emulator", return_value=True) as shutdown,
        ):
            scheduler._maybe_daily_restart(cfg)
            now[0] = datetime(2026, 10, 26, 5, 0, 1)
            scheduler._maybe_daily_restart(cfg)

        self.assertEqual(shutdown.call_count, 2)

    def test_failed_shutdown_still_marks_the_day(self):
        scheduler = Scheduler()
        now = [datetime(2026, 10, 25, 6, 0, 0)]

        def frozen_now(cls, tz=None):
            return now[0]

        with (
            patch.object(
                scheduler_module,
                "datetime",
                type("FrozenDateTime", (datetime,), {"now": classmethod(frozen_now)}),
            ),
            patch.object(scheduler, "_safe_shutdown_emulator", return_value=False) as shutdown,
        ):
            scheduler._maybe_daily_restart(cfg)
            scheduler._maybe_daily_restart(cfg)

        # 关闭失败不重复尝试：同一个任务批次里反复关模拟器只会多等 30 秒，
        # 真正的恢复交给设备启动检查和 MuMu 重启阶梯。
        shutdown.assert_called_once()


class TestDailyRestartPipelineGate(unittest.TestCase):
    def setUp(self):
        self._cfg_backup = copy.deepcopy(cfg._config)
        self._reg_backup = dict(task_registry._tasks)
        task_registry.clear()

    def tearDown(self):
        cfg._config = self._cfg_backup
        task_registry._tasks = self._reg_backup

    def _install_task_config(self):
        cfg._config = {
            "app": {
                "app_to_start": "com.test.app",
                "max_attempts": 1,
                "restart_on_error": True,
            },
            "emulator": {"post_execution": "none"},
            "ocr": {"use_gpu": False},
            "game": {"character_name": "测试角色"},
            "tasks": {
                "任务": {
                    "on": True,
                    "next_exec_time": 0,
                    "params": {},
                },
            },
        }
        task_registry.register("测试/任务", lambda: None)

    def _run_pipeline(self, *, skip_character_login: bool):
        self._install_task_config()
        task_manager = FakeTaskManager()
        scheduler = Scheduler()
        scheduler.set_task_manager(task_manager)
        with (
            patch.object(cfg, "active_character", return_value={"server": "s1", "name": "c1"}),
            patch.object(cfg, "save_config"),
            patch.object(scheduler_module.runtime_ctx, "refresh"),
            patch.object(scheduler_module, "notify_runtime_event"),
            patch.object(scheduler, "_maybe_daily_restart") as daily_restart,
            patch.object(scheduler, "_ensure_character_logged_in"),
            patch.object(scheduler, "_post_execution_action"),
        ):
            scheduler._run_task_pipeline(
                explicit_tasks=["测试/任务"],
                skip_character_login=skip_character_login,
            )
        return task_manager, daily_restart

    def test_scheduled_task_runs_daily_restart_check(self):
        task_manager, daily_restart = self._run_pipeline(skip_character_login=False)

        self.assertEqual(task_manager.executed, ["测试/任务"])
        daily_restart.assert_called_once()

    def test_task_list_direct_run_skips_daily_restart(self):
        task_manager, daily_restart = self._run_pipeline(skip_character_login=True)

        self.assertEqual(task_manager.executed, ["测试/任务"])
        daily_restart.assert_not_called()


if __name__ == "__main__":
    unittest.main()
