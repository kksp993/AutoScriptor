"""Daily continuation must yield without completing the task or spending retries."""
import copy
import datetime
import json
import math
import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch

from AutoScriptor.utils.app_config import cfg
from orchestrator import task_manager as task_manager_module
from orchestrator.delivery import CharacterReports
from orchestrator.model import is_task_due, plan_task_table
from orchestrator.projection import TaskTreeService, WebUILifecycleService
from orchestrator.scheduler import Scheduler, SchedulerState
from orchestrator.task_manager import TaskManager
from tasks import task_state
from tasks.task_register import task_registry


class TestTaskContinuation(unittest.TestCase):
    def setUp(self):
        patches = ExitStack()
        self.addCleanup(patches.close)
        self.addCleanup(task_state.set_current_task_path, None)
        self.task_path = "test/harvest"
        self.entry = {"on": True, "next_exec_time": 0, "params": {}}
        self.table = {"harvest": self.entry}
        patches.enter_context(patch.object(cfg, "_config", {
            "tasks": self.table, "status": {}, "app": {"max_attempts": 3},
            "game": {"character_name": "test"}, "emulator": {"post_execution": "none"},
            "task_ordering": {"selection_policy": "list_ready"},
        }))
        patches.enter_context(patch.object(task_registry, "_tasks", {}))
        self.saved_tables = []
        self.save = patches.enter_context(patch.object(cfg, "save_config", side_effect=lambda: self.saved_tables.append(json.loads(json.dumps(self.table)))))
        patches.enter_context(patch.object(cfg, "active_character", return_value={"server": "test", "name": "hero"}))
        patches.enter_context(patch.object(task_manager_module.runtime_ctx, "mixctrl", Mock()))
        patches.enter_context(patch.object(task_manager_module, "new_task_video_recorder", return_value=None))
        patches.enter_context(patch.object(task_manager_module, "set_run_capture"))
        patches.enter_context(patch.object(task_manager_module, "clear_action_history"))
        self.manager = TaskManager()
        self.archive = patches.enter_context(patch.object(self.manager, "_archive_error"))
        self.recover = patches.enter_context(patch.object(self.manager, "_try_recover_app", return_value=False))
        self.patches = patches

    def install_task(self, function, reschedule="daily"):
        task_registry.register(self.task_path, function, task_id="harvest", reschedule=reschedule)

    def request_continuation(self):
        task_state.set_task_next_run(180)

    def install_registered_task(self, function):
        from pathlib import Path
        from AutoScriptor.core.background import bg
        from AutoScriptor.logging import tracer
        from tasks import task_register
        from ZmxyOL.nav import api as navigation_api

        self.patches.enter_context(patch.object(bg, "clear"))
        self.patches.enter_context(patch.object(tracer, "clear_debug_screenshots"))
        self.patches.enter_context(patch.object(task_register, "_apply_task_battle_startup"))
        self.patches.enter_context(patch.object(task_register, "_clear_task_battle_startup"))
        filename = Path(__file__).resolve().parents[2] / "tasks" / "test" / "harvest.py"
        with patch.object(task_register.inspect, "getfile", return_value=str(filename)):
            task_register.register_task(function, ensure_in="村庄", reschedule="daily")
        return self.patches.enter_context(patch.object(navigation_api, "ensure_in"))

    def test_registered_navigation_failure_uses_existing_retry_and_never_runs_body_early(self):
        task_body = Mock(__name__="harvest", __annotations__={})

        def harvest():
            task_body()

        navigate = self.install_registered_task(harvest)
        navigate.side_effect = [RuntimeError("navigation failed"), None]
        self.recover.return_value = True
        self.assertEqual(self.manager.execute_tasks([self.task_path]), (1, 0))
        self.assertEqual(navigate.call_count, 2)
        task_body.assert_called_once_with()
        self.archive.assert_called_once()
        self.recover.assert_called_once()

    def test_registered_continuation_rechecks_entry_on_next_stage(self):
        events = []

        def harvest():
            events.append("body")
            if events.count("body") == 1:
                self.request_continuation()

        navigate = self.install_registered_task(harvest)
        navigate.side_effect = lambda target: events.append(target)
        self.assertEqual(self.manager.execute_tasks([self.task_path]), (0, 0))
        self.assertTrue(self.entry["continuation_pending"])
        self.assertEqual(self.manager.execute_tasks([self.task_path]), (1, 0))
        self.assertEqual(events, ["村庄", "body", "村庄", "body"])
        self.assertNotIn("continuation_pending", self.entry)

    def test_daily_continuation_persists_without_completion_then_resumes_daily_rule(self):
        calls = []

        def harvest():
            calls.append("stage")
            task_state.set_task_status("progress", "1/2", save=False)
            self.request_continuation()

        self.install_task(harvest)
        started_at = datetime.datetime.now().timestamp()
        self.assertEqual(self.manager.execute_tasks([self.task_path]), (0, 0))
        self.assertEqual(calls, ["stage"])
        self.assertTrue(self.entry["continuation_pending"])
        self.assertTrue(self.entry["on"])
        self.assertNotIn("reschedule", self.entry)
        self.assertGreaterEqual(self.entry["next_exec_time"], started_at + 180)
        self.assertLess(self.entry["next_exec_time"], started_at + 185)
        self.assertEqual(self.saved_tables[-1]["harvest"], self.entry)
        self.assertFalse(is_task_due(self.entry, self.task_path, started_at + 179))
        self.assertTrue(is_task_due(self.entry, self.task_path, self.entry["next_exec_time"]))
        self.assertEqual(TaskTreeService().task_leaf_status(self.entry, self.task_path, started_at), "pending")
        self.assertEqual(task_state.get_task_status("progress", task_path=self.task_path), "1/2")
        self.archive.assert_not_called()
        self.recover.assert_not_called()

        # Load the serialized table as a fresh process would; no thread-local request survives.
        self.table = copy.deepcopy(self.saved_tables[-1])
        cfg._config["tasks"] = self.table
        self.entry = self.table["harvest"]
        self.install_task(lambda: None)
        self.assertEqual(TaskManager().execute_tasks([self.task_path]), (1, 0))
        self.assertNotIn("continuation_pending", self.entry)
        next_execution = datetime.datetime.fromtimestamp(self.entry["next_exec_time"])
        self.assertEqual((next_execution.hour, next_execution.minute), (5, 0))
        self.assertGreater(next_execution, datetime.datetime.now())
        self.assertIsNone(task_state.get_task_status("progress", task_path=self.task_path))
        self.assertIsNone(task_state.get_requested_next_run_time())

    def test_failed_or_cancelled_attempt_never_commits_its_request(self):
        for cancelled in (False, True):
            with self.subTest(cancelled=cancelled):
                self.manager.reset_cancel()

                def unsuccessful_stage():
                    self.request_continuation()
                    if cancelled:
                        self.manager.request_cancel()
                    else:
                        raise RuntimeError("stage cleanup failed")

                self.install_task(unsuccessful_stage)
                self.assertEqual(self.manager.execute_tasks([self.task_path]), (0, 1))
                self.assertEqual(self.entry["next_exec_time"], 0)
                self.assertNotIn("continuation_pending", self.entry)
                self.assertIsNone(task_state.get_requested_next_run_time())
        self.save.assert_not_called()

    def test_request_is_attempt_local_and_failed_attempt_does_not_leak(self):
        from AutoScriptor.errors import TaskRequireReTry

        attempts = []

        def stage():
            attempts.append(1)
            if len(attempts) == 1:
                self.request_continuation()
                raise TaskRequireReTry("retry the stage")

        self.install_task(stage)
        self.assertEqual(self.manager.execute_tasks([self.task_path]), (1, 0))
        self.assertEqual(len(attempts), 2)
        self.assertNotIn("continuation_pending", self.entry)

    def test_request_validates_context_and_delay_without_saving(self):
        with self.assertRaises(RuntimeError):
            task_state.set_task_next_run(180)
        task_state.set_current_task_path(self.task_path)
        for value in (0, -1, True, "180", None, math.inf, math.nan, 1e300):
            with self.subTest(value=value), self.assertRaises((TypeError, ValueError)):
                task_state.set_task_next_run(value)
        self.save.assert_not_called()

    def test_daily_tags_survive_stages_and_reload_but_expire_at_five(self):
        observations = []

        def stage():
            observations.append(task_state.get_task_status("rewards_claimed", False))
            task_state.set_task_status("rewards_claimed", True)
            task_state.set_task_status("parallel_slots", {"left": "growing", "right": "done"})
            self.request_continuation()

        self.install_task(stage)
        before_reset = datetime.datetime(2030, 1, 7, 4, 58)
        with patch.object(task_state.time, "time", return_value=before_reset.timestamp()):
            self.assertEqual(self.manager.execute_tasks([self.task_path]), (0, 0))
        self.assertEqual(self.entry["next_exec_time"], datetime.datetime(2030, 1, 7, 5, 1).timestamp())
        # Serialize both task configuration and status, as account persistence does.
        cfg._config = json.loads(json.dumps(cfg._config))
        self.table = cfg._config["tasks"]
        self.entry = self.table["harvest"]
        with patch.object(task_state.time, "time", return_value=datetime.datetime(2030, 1, 7, 4, 59).timestamp()):
            self.assertTrue(task_state.get_task_status("rewards_claimed", task_path=self.task_path))
            self.assertEqual(task_state.get_task_status("parallel_slots", task_path=self.task_path)["right"], "done")
        after_reset = datetime.datetime(2030, 1, 7, 5, 1)
        with patch.object(task_state.time, "time", return_value=after_reset.timestamp()):
            self.assertFalse(task_state.get_task_status("rewards_claimed", False, task_path=self.task_path))
            self.assertIsNone(task_state.get_task_status("parallel_slots", task_path=self.task_path))
            self.assertEqual(TaskManager().execute_tasks([self.task_path]), (0, 0))
        self.assertEqual(observations, [False, False])

    def test_same_running_function_sees_tag_reset_at_exact_boundary(self):
        before_reset = datetime.datetime(2030, 1, 7, 4, 58).timestamp()
        boundary = datetime.datetime(2030, 1, 7, 5).timestamp()

        def stage():
            task_state.set_task_status("phase", "old")
            clock.return_value = boundary - 0.001
            self.assertEqual(task_state.get_task_status("phase"), "old")
            clock.return_value = boundary
            self.assertIsNone(task_state.get_task_status("phase"))
            task_state.set_task_status("phase", "new")
            clock.return_value = boundary + 60
            self.assertEqual(task_state.get_task_status("phase"), "new")
            self.request_continuation()

        self.install_task(stage)
        with patch.object(task_state.time, "time", return_value=before_reset) as clock:
            self.assertEqual(self.manager.execute_tasks([self.task_path]), (0, 0))

    def test_regular_rule_controls_tags_not_continuation_or_allowed_windows(self):
        started_at = datetime.datetime(2030, 1, 7, 4, 58)
        cases = [
            ("daily", datetime.datetime(2030, 1, 7, 5)),
            ("weekly", datetime.datetime(2030, 1, 7, 5)),
            (2, datetime.datetime(2030, 1, 7, 6, 58)),
            ({"mode": "daily", "window": [10, 22], "weekdays": [5]}, datetime.datetime(2030, 1, 7, 5)),
            (None, None),
        ]
        for rule, boundary in cases:
            with self.subTest(rule=rule):
                cfg._config["status"] = {}
                self.entry["reschedule"] = rule
                self.install_task(self.request_continuation)
                with patch.object(task_state.time, "time", return_value=started_at.timestamp()) as clock:
                    task_state.set_task_status("phase", "ready", task_path=self.task_path)
                    self.assertEqual(self.manager.execute_tasks([self.task_path]), (0, 0))
                    if boundary is None:
                        clock.return_value += 30 * 86400
                        self.assertEqual(task_state.get_task_status("phase", task_path=self.task_path), "ready")
                    else:
                        clock.return_value = boundary.timestamp() - 0.001
                        self.assertEqual(task_state.get_task_status("phase", task_path=self.task_path), "ready")
                        clock.return_value = boundary.timestamp()
                        self.assertIsNone(task_state.get_task_status("phase", task_path=self.task_path))

    def test_weekly_early_tuesday_uses_next_monday_not_tuesday_reset(self):
        from orchestrator.model import next_exec_ts_for_spec, resolve_reschedule

        self.install_task(lambda: None, reschedule="weekly")
        tuesday = datetime.datetime(2030, 1, 8, 4, 58)
        next_monday = datetime.datetime(2030, 1, 14, 5)
        spec = resolve_reschedule(self.task_path, self.entry)
        self.assertEqual(next_exec_ts_for_spec(tuesday, spec), next_monday.timestamp())
        with patch.object(task_state.time, "time", return_value=tuesday.timestamp()) as clock:
            task_state.set_task_status("phase", "ready", task_path=self.task_path)
            clock.return_value = datetime.datetime(2030, 1, 8, 5, 1).timestamp()
            self.assertEqual(task_state.get_task_status("phase", task_path=self.task_path), "ready")
            clock.return_value = next_monday.timestamp()
            self.assertIsNone(task_state.get_task_status("phase", task_path=self.task_path))

    def test_offset_completion_reanchors_deadline_but_reading_and_continuing_do_not(self):
        self.install_task(self.request_continuation, reschedule=2)
        started_at = datetime.datetime(2030, 1, 7, 8).timestamp()
        with patch.object(task_state.time, "time", return_value=started_at) as clock:
            task_state.set_task_status("phase", "planted", task_path=self.task_path)
            self.assertEqual(self.manager.execute_tasks([self.task_path]), (0, 0))
            clock.return_value += 180
            self.assertEqual(self.manager.execute_tasks([self.task_path]), (0, 0))
            self.assertEqual(cfg._config["status"]["task_cycles"][self.task_path]["reset_at"], started_at + 7200)
            self.install_task(lambda: None, reschedule=2)
            clock.return_value += 180
            self.assertEqual(self.manager.execute_tasks([self.task_path]), (1, 0))
            self.assertEqual(self.entry["next_exec_time"], started_at + 7560)
            clock.return_value = started_at + 7200
            self.assertEqual(task_state.get_task_status("phase", task_path=self.task_path), "planted")
            clock.return_value = started_at + 7560
            self.assertIsNone(task_state.get_task_status("phase", task_path=self.task_path))

    def test_failure_preserves_verified_checkpoint_and_reschedule_change_invalidates_it(self):
        from AutoScriptor.errors import TaskRequireReTry

        observations = []

        def stage():
            observations.append(task_state.get_task_status("phase"))
            if len(observations) == 1:
                task_state.set_task_status("phase", "verified")
                raise TaskRequireReTry("later step failed")
            self.request_continuation()

        self.install_task(stage)
        with patch.object(task_state.time, "time", return_value=datetime.datetime(2030, 1, 7, 8).timestamp()):
            self.assertEqual(self.manager.execute_tasks([self.task_path]), (0, 0))
            self.assertEqual(observations, [None, "verified"])
            self.entry["reschedule"] = "weekly"
            self.assertIsNone(task_state.get_task_status("phase", task_path=self.task_path))
            task_state.set_task_status("another_tag", 42, task_path=self.task_path)
            self.assertNotIn("phase", cfg._config["status"]["tasks"][self.task_path])

    def test_state_isolated_by_task_and_character_and_projection_does_not_save(self):
        from ZmxyOL.accounts.account_store import Character

        self.install_task(lambda: None)
        task_registry.register("test/other", lambda: None, task_id="other", reschedule="daily")
        self.table["other"] = {"on": True, "next_exec_time": 0}
        before_reset = datetime.datetime(2030, 1, 7, 4, 58).timestamp()
        with patch.object(task_state.time, "time", return_value=before_reset) as clock:
            task_state.set_task_status("phase", "harvest", task_path=self.task_path)
            task_state.set_task_status("phase", "other", task_path="test/other")
            task_state.set_task_status("progress", "1/2", task_path=self.task_path)
            first_character = Character("server", "first", {"tasks": self.table, "status": cfg._config["status"]}).to_dict()
            with patch.dict(cfg._config, {"status": {}}):
                self.assertIsNone(task_state.get_task_status("phase", task_path=self.task_path))
                task_state.set_task_status("phase", "second-character", task_path=self.task_path)
                self.assertEqual(task_state.get_task_status("phase", task_path=self.task_path), "second-character")
            self.assertEqual(task_state.get_task_status("phase", task_path=self.task_path), "harvest")
            self.assertEqual(task_state.get_task_status("phase", task_path="test/other"), "other")
            persisted = copy.deepcopy(first_character)
            self.save.reset_mock()
            rows = TaskTreeService().flatten_tasks(self.table, before_reset, status_tree=first_character["status"])
            self.assertEqual(rows[0]["progress"], "1/2")
            clock.return_value = datetime.datetime(2030, 1, 7, 5, 1).timestamp()
            rows = TaskTreeService().flatten_tasks(self.table, clock.return_value, status_tree=first_character["status"])
            self.assertNotIn("progress", rows[0])
            self.assertIsNone(task_state.get_task_status("phase", task_path=self.task_path))
            self.assertEqual(first_character, persisted)
            self.save.assert_not_called()

    def test_last_request_wins_and_request_does_not_abort_cleanup(self):
        events = []

        def stage():
            task_state.set_task_next_run(600)
            task_state.set_task_next_run(180)
            events.append("cleanup")

        self.install_task(stage)
        with patch.object(task_state.time, "time", return_value=2000000000):
            self.assertEqual(self.manager.execute_tasks([self.task_path]), (0, 0))
        self.assertEqual(events, ["cleanup"])
        self.assertEqual(self.entry["next_exec_time"], 2000000180)

    def test_failed_persistence_restores_previous_schedule(self):
        self.install_task(self.request_continuation)
        self.save.side_effect = OSError("disk unavailable")
        self.assertEqual(self.manager.execute_tasks([self.task_path]), (0, 1))
        self.assertNotIn("continuation_pending", self.entry)
        self.assertEqual(self.entry["next_exec_time"], 0)
        self.archive.assert_called_once()

    def test_failed_final_save_does_not_extend_status_deadline(self):
        self.install_task(lambda: None, reschedule=2)
        started_at = datetime.datetime(2030, 1, 7, 8).timestamp()
        with patch.object(task_state.time, "time", return_value=started_at) as clock:
            task_state.set_task_status("phase", "verified", task_path=self.task_path)
            previous_status = copy.deepcopy(cfg._config["status"])
            clock.return_value += 180
            self.save.side_effect = OSError("disk unavailable")
            self.assertEqual(self.manager.execute_tasks([self.task_path]), (0, 1))
            self.assertEqual(cfg._config["status"], previous_status)
            self.assertEqual(self.entry["next_exec_time"], 0)

    def test_undated_periodic_tags_are_not_adopted_as_current_work(self):
        self.install_task(lambda: None)
        cfg._config["status"] = {"tasks": {self.task_path: {"old_tag": True, "progress": "1/2"}}}
        self.assertIsNone(task_state.get_task_status("old_tag", task_path=self.task_path))
        task_state.set_task_status("fresh_tag", True, task_path=self.task_path)
        self.assertEqual(cfg._config["status"]["tasks"][self.task_path], {"fresh_tag": True})

    def test_continuation_obeys_window_and_weekdays(self):
        self.install_task(self.request_continuation)
        self.entry["reschedule"] = {"mode": "daily", "window": [10, 22], "weekdays": [5]}
        requested_from = datetime.datetime(2030, 1, 7, 21, 59)
        with patch.object(task_state.time, "time", return_value=requested_from.timestamp()):
            self.assertEqual(self.manager.execute_tasks([self.task_path]), (0, 0))
        next_execution = datetime.datetime.fromtimestamp(self.entry["next_exec_time"])
        self.assertEqual(next_execution, datetime.datetime(2030, 1, 8, 10))
        self.assertFalse(is_task_due(self.entry, self.task_path, next_execution.timestamp()))
        self.assertTrue(is_task_due(self.entry, self.task_path, datetime.datetime(2030, 1, 11, 10).timestamp()))

    def test_reenable_clears_continuation_without_affecting_another_task(self):
        self.install_task(self.request_continuation)
        task_registry.register("test/other", lambda: None, task_id="other")
        self.table["other"] = {"on": True, "next_exec_time": 0}
        task_state.set_task_status("phase", "harvest", task_path=self.task_path)
        task_state.set_task_status("phase", "other", task_path="test/other")
        self.manager.execute_tasks([self.task_path])
        self.entry["on"] = False
        tree = TaskTreeService()
        lifecycle = WebUILifecycleService(cfg, self.manager, Mock(), tree, Mock())
        with patch.object(lifecycle, "_refresh_task_projection"):
            lifecycle.save_tasks({"test": {"harvest": {**self.entry, "id": "harvest", "on": True}, "other": {**self.table["other"], "id": "other"}}})
        self.assertNotIn("continuation_pending", cfg._config["tasks"]["harvest"])
        self.assertEqual(cfg._config["tasks"]["harvest"]["next_exec_time"], 0)
        self.assertNotIn(self.task_path, cfg._config["status"]["tasks"])
        self.assertNotIn(self.task_path, cfg._config["status"]["task_cycles"])
        self.assertEqual(task_state.get_task_status("phase", task_path="test/other"), "other")

    def test_one_shot_stays_enabled_until_final_stage_and_respects_user_rule(self):
        self.install_task(self.request_continuation, reschedule=None)
        self.assertEqual(self.manager.execute_tasks([self.task_path]), (0, 0))
        self.assertTrue(self.entry["on"])
        self.install_task(lambda: None, reschedule=None)
        self.assertEqual(self.manager.execute_tasks([self.task_path]), (1, 0))
        self.assertFalse(self.entry["on"])
        self.assertNotIn("continuation_pending", self.entry)

        self.entry.update(on=True, reschedule=2)
        self.install_task(self.request_continuation)
        self.assertEqual(self.manager.execute_tasks([self.task_path]), (0, 0))
        self.install_task(lambda: None)
        started_at = datetime.datetime.now().timestamp()
        self.assertEqual(self.manager.execute_tasks([self.task_path]), (1, 0))
        self.assertGreaterEqual(self.entry["next_exec_time"], started_at + 7200)
        self.assertEqual(self.entry["reschedule"], 2)

    def test_future_continuation_still_blocks_successors_but_not_independent_tasks(self):
        self.install_task(self.request_continuation)
        task_registry.register("test/after", lambda: None, task_id="after", after_tasks=["harvest"])
        task_registry.register("test/independent", lambda: None, task_id="independent")
        self.table.update(after={"on": True, "next_exec_time": 0}, independent={"on": True, "next_exec_time": 0})
        self.assertEqual(self.manager.execute_tasks([self.task_path]), (0, 0))
        now = datetime.datetime.now().timestamp()
        decision, _specifications = plan_task_table(self.table, {}, now)
        self.assertEqual(decision.ranked_ids, ["independent"])
        self.assertEqual(decision.blocked_by["after"], ["harvest"])

    def test_scheduler_yields_without_retry_and_waits_for_continuation(self):
        stages = Mock(side_effect=self.request_continuation)
        self.install_task(stages)
        task_registry.register("test/other", lambda: None, task_id="other")
        self.table["other"] = {"on": True, "next_exec_time": 0}
        scheduler = Scheduler()
        scheduler.state = SchedulerState.RUNNING
        scheduler.set_task_manager(self.manager)
        self.patches.enter_context(patch.object(scheduler, "_iter_characters_schedule_order", side_effect=lambda: iter([("test", "hero")])))
        self.patches.enter_context(patch.object(scheduler, "_maybe_daily_restart"))
        self.patches.enter_context(patch.object(scheduler, "_ensure_character_logged_in"))
        self.patches.enter_context(patch.object(scheduler, "_return_to_first_dispatch_character"))
        self.patches.enter_context(patch.object(scheduler, "_post_execution_action"))
        self.patches.enter_context(patch("orchestrator.scheduler.runtime_ctx.refresh"))
        self.patches.enter_context(patch("orchestrator.scheduler.notify_runtime_event"))
        messages = []
        self.patches.enter_context(patch("orchestrator.scheduler.create_character_reports", return_value=CharacterReports(messages.append, [])))

        scheduler._run_task_pipeline()

        stages.assert_called_once()
        self.assertFalse(self.table["other"]["on"])
        self.assertEqual(scheduler._retry_exhausted_tasks, {})
        self.assertEqual(scheduler._consecutive_errors, 0)
        self.assertGreater(scheduler._get_wait_interval(), 170)
        self.assertLessEqual(scheduler._get_wait_interval(), 180)
        self.assertEqual(len(messages), 1)
        self.assertIn("待续执行", messages[0])
        self.assertIn("成功:1,失败:0", messages[0])
        self.assertNotIn("已中断", messages[0])
        for _stage in range(4):
            # Make the next persisted stage due; successful yielding has no retry ceiling.
            self.entry["next_exec_time"] = 0
            scheduler._run_task_pipeline()
        self.assertEqual(stages.call_count, 5)
        self.assertEqual(scheduler._retry_exhausted_tasks, {})
        self.assertEqual(scheduler._consecutive_errors, 0)


if __name__ == "__main__":
    unittest.main()
