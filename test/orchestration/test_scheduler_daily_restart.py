import copy
import importlib
import json
import tempfile
import unittest
from datetime import datetime
from contextlib import nullcontext
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock, patch

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
    def setUp(self):
        self.configuration = copy.deepcopy(cfg._config)
        self.global_configuration = copy.deepcopy(cfg._mgr.global_cfg)
        self.original_path = cfg.CONFIG_PATH
        self.original_manager_path = cfg._mgr.config_path
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.addCleanup(self._restore_configuration)
        cfg.CONFIG_PATH = str(Path(self.directory.name) / "config.json")
        cfg._config.pop("runtime_state", None)
        cfg._mgr.global_cfg.pop("runtime_state", None)

    def _restore_configuration(self):
        cfg._config = self.configuration
        cfg._mgr.global_cfg = self.global_configuration
        cfg.CONFIG_PATH = self.original_path
        cfg._mgr.config_path = self.original_manager_path

    def test_new_scheduler_after_config_reload_does_not_restart_again(self):
        moment = datetime(2026, 10, 25, 12, 0)
        with patch.object(scheduler_module, "datetime", _frozen_datetime(moment)), patch.object(
            Scheduler, "_safe_shutdown_emulator", return_value=True,
        ) as shutdown:
            Scheduler()._maybe_daily_restart(cfg)
            saved = json.loads(Path(cfg.CONFIG_PATH).read_text(encoding="utf-8"))
            self.assertEqual(saved["runtime_state"]["daily_restart_day"], "2026-10-25")
            cfg._mgr.load_global()
            cfg._refresh_flat_config()
            Scheduler()._maybe_daily_restart(cfg)
        shutdown.assert_called_once()

    def test_character_switch_and_manual_reset_do_not_clear_global_marker(self):
        moment = datetime(2026, 10, 25, 12, 0)
        with patch.object(scheduler_module, "datetime", _frozen_datetime(moment)), patch.object(
            Scheduler, "_safe_shutdown_emulator", return_value=True,
        ) as shutdown:
            Scheduler()._maybe_daily_restart(cfg)
            cfg._config["status"] = {}
            cfg._config["game"] = {"character_name": "another-character"}
            scheduler = Scheduler()
            scheduler.reset()
            scheduler._maybe_daily_restart(cfg)
        shutdown.assert_called_once()

    def test_save_failure_does_not_shutdown_or_leave_a_false_marker(self):
        moment = datetime(2026, 10, 25, 12, 0)
        scheduler = Scheduler()
        with patch.object(scheduler_module, "datetime", _frozen_datetime(moment)), patch.object(
            scheduler, "_safe_shutdown_emulator", return_value=True,
        ) as shutdown, patch.object(cfg._mgr, "persist_global", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                scheduler._maybe_daily_restart(cfg)
            shutdown.assert_not_called()
        self.assertNotIn("runtime_state", cfg._config)
        self.assertNotIn("runtime_state", cfg._mgr.global_cfg)

    def test_midnight_does_not_reset_marker_but_next_5am_does(self):
        with patch.object(Scheduler, "_safe_shutdown_emulator", return_value=True) as shutdown:
            for moment, expected_calls in (
                (datetime(2026, 10, 25, 23, 59), 1),
                (datetime(2026, 10, 26, 0, 1), 1),
                (datetime(2026, 10, 26, 4, 59), 1),
                (datetime(2026, 10, 26, 5, 0), 2),
            ):
                with patch.object(scheduler_module, "datetime", _frozen_datetime(moment)):
                    Scheduler()._maybe_daily_restart(cfg)
                self.assertEqual(shutdown.call_count, expected_calls)

    def test_cancelled_execution_never_consumes_the_day(self):
        from AutoScriptor.utils.cancel import TaskCancelled

        scheduler = Scheduler()
        with patch.object(scheduler_module, "datetime", _frozen_datetime(datetime(2026, 10, 25, 12))), patch.object(
            scheduler, "_check_cancel_requested", side_effect=TaskCancelled("stop"),
        ), patch.object(scheduler, "_safe_shutdown_emulator") as shutdown:
            with self.assertRaises(TaskCancelled):
                scheduler._maybe_daily_restart(cfg)
            shutdown.assert_not_called()
        self.assertNotIn("runtime_state", cfg._config)

    def test_settings_saves_and_imports_cannot_overwrite_machine_checkpoint(self):
        from orchestrator.projection import TaskTreeService, WebUILifecycleService

        checkpoint = {"daily_restart_day": "2026-10-25"}
        cfg._config["runtime_state"] = copy.deepcopy(checkpoint)
        manager = SimpleNamespace(config_transaction=nullcontext)
        tree = TaskTreeService()
        lifecycle = WebUILifecycleService(cfg, manager, Mock(), tree, Mock(return_value=1))
        incoming = {key: copy.deepcopy(cfg._config[key]) for key in ("app", "ocr", "emulator")}
        incoming["runtime_state"] = {"daily_restart_day": "1900-01-01"}
        with patch.object(lifecycle, "_apply_log_level"), patch.object(lifecycle, "mark_config_changed"):
            lifecycle.save_runtime_config(incoming)
            with patch.object(cfg, "save_config"), patch.object(lifecycle, "_mark_tasks_updated"):
                lifecycle.import_config({"runtime_state": incoming["runtime_state"]})
        self.assertEqual(cfg._config["runtime_state"], checkpoint)
        saved = json.loads(Path(cfg.CONFIG_PATH).read_text(encoding="utf-8"))
        self.assertEqual(saved["runtime_state"], checkpoint)
        with patch.object(tree, "characters_summary", return_value={}), patch.object(
            tree, "game_professions_by_character", return_value={},
        ):
            self.assertNotIn("runtime_state", tree.public_config())

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
            Scheduler()._maybe_daily_restart(cfg)

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
