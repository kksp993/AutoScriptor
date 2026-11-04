import copy
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from threading import Event
from unittest.mock import Mock, call, patch

from AutoScriptor.utils.app_config import cfg
from AutoScriptor.utils.cancel import TaskCancelled
from orchestrator.scheduler import MAX_CONSECUTIVE_ERRORS, Scheduler, SchedulerState


class TestSchedulerStartupFailures(unittest.TestCase):
    def setUp(self):
        self.patches = ExitStack()
        self.addCleanup(self.patches.close)
        self.patches.enter_context(patch.object(cfg, "_config", {
            "app": {"max_attempts": 3},
            "emulator": {"index": 1, "adb_addr": "127.0.0.1:16416"},
            "game": {"character_name": "tester"},
            "tasks": {"test-task": {"on": True, "next_exec_time": 123}},
        }))
        self.original_tasks = copy.deepcopy(cfg["tasks"])
        self.manager = Mock(_cancel_event=Event())
        self.manager.request_cancel.side_effect = self.manager._cancel_event.set
        self.manager.execute_tasks.return_value = (1, 0)
        self.scheduler = Scheduler()
        self.scheduler.state = SchedulerState.RUNNING
        self.scheduler.set_task_manager(self.manager)
        self.patches.enter_context(patch.object(cfg, "active_character", return_value={
            "server": "server", "name": "tester",
        }))
        self.patches.enter_context(patch.object(cfg, "save_config"))
        self.patches.enter_context(patch.object(self.scheduler, "_collect_due_cross_character", return_value=["test-task"]))
        self.patches.enter_context(patch.object(self.scheduler, "_rank_ready_paths", side_effect=lambda paths, **kwargs: list(paths)))
        self.patches.enter_context(patch.object(self.scheduler, "_maybe_daily_restart"))
        self.login = self.patches.enter_context(patch.object(self.scheduler, "_ensure_character_logged_in"))
        self.cleanup = self.patches.enter_context(patch.object(self.scheduler, "_post_execution_action"))
        self.patches.enter_context(patch.object(self.scheduler, "_return_to_first_dispatch_character"))
        self.wait = self.patches.enter_context(patch.object(self.scheduler._wake, "wait"))
        self.refresh = self.patches.enter_context(patch("orchestrator.scheduler.runtime_ctx.refresh"))
        self.notify = self.patches.enter_context(patch("orchestrator.scheduler.notify_runtime_event"))
        self.patches.enter_context(patch("orchestrator.scheduler.logger"))
        self.reports = self.patches.enter_context(patch("orchestrator.scheduler.create_character_reports")).return_value
        self.archive = self.patches.enter_context(patch("AutoScriptor.logging.log_archiver.archive_error"))

    def test_startup_failure_stops_at_limit_while_pipeline_is_active(self):
        self.refresh.side_effect = [
            RuntimeError("Android startup failed") for _ in range(MAX_CONSECUTIVE_ERRORS)
        ] + [TaskCancelled("safety stop: retry limit was bypassed")]

        self.scheduler._run_task_pipeline()

        self.assertEqual(self.refresh.call_count, MAX_CONSECUTIVE_ERRORS)
        self.assertEqual(self.wait.call_args_list, [call(10), call(20)])
        self.assertEqual(self.scheduler.state, SchedulerState.ERROR)
        self.assertEqual(self.scheduler.status_dict()["consecutive_errors"], MAX_CONSECUTIVE_ERRORS)
        self.assertFalse(self.scheduler.is_executing)
        self.assertIsNotNone(self.scheduler._error_at)
        self.notify.assert_called_once()
        self.manager.execute_tasks.assert_not_called()
        self.login.assert_not_called()
        self.cleanup.assert_not_called()
        self.assertEqual(cfg["tasks"], self.original_tasks)
        self.reports.finish.assert_called_once_with(interrupted=True)

    def test_startup_error_is_archived_before_task_execution(self):
        startup_error = RuntimeError("ADB connection refused")
        self.refresh.side_effect = [startup_error, TaskCancelled("end probe")]

        self.scheduler._run_task_pipeline()

        self.archive.assert_called_once()
        arguments, options = self.archive.call_args
        self.assertIs(arguments[1], startup_error)
        self.assertIsNone(options.get("mixctrl"))
        self.assertFalse(options["include_run_screenshots"])
        self.assertFalse(options["include_runtime_context"])
        self.assertEqual(options["extra_context"]["stage"], "device_startup")
        self.assertEqual(options["extra_context"]["pending_task"], "test-task")
        self.manager.execute_tasks.assert_not_called()

    def test_success_after_transient_startup_failure_clears_error_budget(self):
        self.refresh.side_effect = [RuntimeError("temporarily offline"), None]

        self.scheduler._run_task_pipeline()

        self.assertEqual(self.refresh.call_count, 2)
        self.manager.execute_tasks.assert_called_once()
        self.assertEqual(self.scheduler.state, SchedulerState.RUNNING)
        self.assertEqual(self.scheduler._consecutive_errors, 0)

    def test_startup_failure_in_retry_round_keeps_the_pending_task(self):
        self.manager.execute_tasks.side_effect = [(0, 1), (1, 0)]
        self.refresh.side_effect = [None, RuntimeError("offline before task retry"), None]

        self.scheduler._run_task_pipeline()

        self.assertEqual(self.refresh.call_count, 3)
        self.assertEqual(self.manager.execute_tasks.call_count, 2)
        self.assertEqual(self.scheduler._consecutive_errors, 0)
        self.reports.finish.assert_called_once_with(interrupted=False)

    def test_direct_run_does_not_bypass_limit_when_scheduler_is_enabled(self):
        self.refresh.side_effect = [RuntimeError("offline")] * MAX_CONSECUTIVE_ERRORS + [
            TaskCancelled("safety stop"),
        ]

        self.scheduler._run_task_pipeline(explicit_tasks=["test-task"])

        self.assertEqual(self.refresh.call_count, MAX_CONSECUTIVE_ERRORS)
        self.assertEqual(self.scheduler.state, SchedulerState.ERROR)
        self.notify.assert_called_once()

    def test_direct_run_with_inactive_scheduler_fails_without_scheduling_retry(self):
        self.scheduler.state = SchedulerState.PENDING
        self.refresh.side_effect = RuntimeError("offline")

        self.scheduler._run_task_pipeline(explicit_tasks=["test-task"])

        self.refresh.assert_called_once()
        self.archive.assert_called_once()
        self.wait.assert_not_called()
        self.assertEqual(self.scheduler.state, SchedulerState.PENDING)

    def test_stop_during_retry_delay_does_not_start_again(self):
        self.refresh.side_effect = RuntimeError("offline")
        self.wait.side_effect = lambda delay: self.scheduler.request_stop()

        self.scheduler._run_task_pipeline()

        self.refresh.assert_called_once()
        self.assertEqual(self.scheduler.state, SchedulerState.PENDING)
        self.assertEqual(self.scheduler._consecutive_errors, 0)
        self.notify.assert_not_called()

    def test_user_stop_during_failed_startup_does_not_consume_error_budget(self):
        def fail_after_stop(**kwargs):
            self.scheduler.request_stop()
            raise RuntimeError("device closed after user stop")

        self.refresh.side_effect = fail_after_stop
        self.scheduler._run_task_pipeline()

        self.assertEqual(self.scheduler.state, SchedulerState.PENDING)
        self.assertEqual(self.scheduler._consecutive_errors, 0)
        self.wait.assert_not_called()
        self.archive.assert_not_called()
        self.notify.assert_not_called()

    def test_cancelled_startup_is_not_an_error(self):
        self.refresh.side_effect = TaskCancelled("user stopped startup")

        self.scheduler._run_task_pipeline()

        self.assertEqual(self.scheduler._consecutive_errors, 0)
        self.wait.assert_not_called()
        self.archive.assert_not_called()
        self.notify.assert_not_called()


class TestStartupErrorArchive(unittest.TestCase):
    def test_startup_archive_writes_error_without_device_probes_or_old_frames(self):
        from AutoScriptor.logging import log_archiver

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(log_archiver, "get_error_archives_dir", return_value=Path(directory)),
            patch.object(log_archiver, "_recent_log_lines", return_value=(None, [])),
            patch.object(log_archiver, "collect_default_context") as context,
            patch.object(log_archiver, "_collect_run_screenshots") as screenshots,
        ):
            archive_path = log_archiver.archive_error(
                "device_startup", RuntimeError("VERR_NEM_MAP_PAGES_FAILED"),
                include_runtime_context=False,
                include_run_screenshots=False,
                extra_context={"stage": "device_startup", "emulator_index": 1},
            )

            self.assertIsNotNone(archive_path)
            archive_directory = Path(archive_path)
            error_log = (archive_directory / "error.log").read_text(encoding="utf-8")
            self.assertIn("VERR_NEM_MAP_PAGES_FAILED", error_log)
            self.assertIn("stage = device_startup", error_log)
            self.assertEqual([entry.name for entry in archive_directory.iterdir()], ["error.log"])
            context.assert_not_called()
            screenshots.assert_not_called()


if __name__ == "__main__":
    unittest.main()
