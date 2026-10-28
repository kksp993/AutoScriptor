import copy
import unittest
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock, patch

from AutoScriptor.utils.app_config import cfg
from tasks.task_register import task_registry


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
                "max_attempts": 2,
                "restart_on_error": True,
            },
            "emulator": {"post_execution": "close_game_only"},
            "ocr": {"use_gpu": False},
            "game": {"character_name": "测试角色"},
            # cfg["tasks"] 是以 id 为键的平表；这里任务没有改名，所以 id 就是显示路径。
            "tasks": {
                "任务": {
                    "on": True,
                    "next_exec_time": 0,
                    "params": {},
                },
            },
        }

        def boom():
            raise RuntimeError("debug boom")

        task_registry.register("测试/任务", boom, debug=debug_mode)

    def test_task_manager_debug_failure_does_not_recover_app(self):
        from orchestrator import task_manager as tm_mod
        from orchestrator.task_manager import TaskManager

        self._install_task_config(debug_mode=True)
        tm = TaskManager()
        mixctrl = SimpleNamespace(release_all_keys=lambda: None)

        with patch.object(tm_mod.runtime_ctx, "mixctrl", mixctrl):
            with patch.object(tm_mod, "new_task_video_recorder", return_value=None):
                with patch.object(tm, "_archive_error") as archive_error:
                    with patch.object(tm, "_try_recover_app") as recover_app:
                        self.assertFalse(tm._execute_single_task("测试/任务"))

        archive_error.assert_called_once()
        recover_app.assert_not_called()

    def test_task_video_follows_task_debug_mode(self):
        from orchestrator import task_manager as tm_mod
        from orchestrator.task_manager import TaskManager

        self._install_task_config(debug_mode=True)
        tm = TaskManager()
        mixctrl = SimpleNamespace(release_all_keys=lambda: None)

        with patch.object(tm_mod.runtime_ctx, "mixctrl", mixctrl):
            with patch.object(tm_mod, "new_task_video_recorder", return_value=None) as recorder:
                with patch.object(tm, "_archive_error"):
                    self.assertFalse(tm._execute_single_task("测试/任务"))

        recorder.assert_called_once_with("测试/任务", True)

    def test_task_debug_mode_is_the_only_recording_source(self):
        """录制只看任务注册的 debug_mode，app 段里留下的旧键不再有任何作用。"""
        from orchestrator import task_manager as tm_mod
        from orchestrator.task_manager import TaskManager

        self._install_task_config(debug_mode=False)
        cfg._config["app"]["debug_mode"] = True
        tm = TaskManager()
        mixctrl = SimpleNamespace(release_all_keys=lambda: None)

        with patch.object(tm_mod.runtime_ctx, "mixctrl", mixctrl):
            with patch.object(tm_mod, "new_task_video_recorder", return_value=None) as recorder:
                with patch.object(tm, "_archive_error"):
                    with patch.object(tm, "_try_recover_app", return_value=False):
                        tm._execute_single_task("测试/任务")

        recorder.assert_called_once_with("测试/任务", False)

    def test_scheduler_debug_task_skips_login_restart_and_post_action(self):
        from orchestrator import scheduler as scheduler_mod
        from orchestrator.scheduler import Scheduler

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

        with (
            patch.object(cfg, "active_character", return_value={"server": "s1", "name": "c1"}),
            patch.object(cfg, "save_config"),
            patch("orchestrator.scheduler.runtime_ctx.refresh"),
            patch("orchestrator.scheduler.notify_runtime_event"),
            patch.object(sched, "_maybe_daily_restart") as daily_restart,
            patch.object(sched, "_ensure_character_logged_in") as ensure_login,
            patch.object(sched, "_post_execution_action") as post_action,
        ):
            sched._run_task_pipeline(explicit_tasks=["测试/任务"])

        self.assertEqual(tm.executed, ["测试/任务"])
        daily_restart.assert_not_called()
        ensure_login.assert_not_called()
        post_action.assert_not_called()

    def test_scheduler_can_force_login_for_debug_task_with_param_override(self):
        from orchestrator.scheduler import Scheduler

        self._install_task_config(debug_mode=True)

        class FakeTaskManager:
            def __init__(self):
                self._cancel_event = Event()
                self.calls = []

            def execute_tasks(self, tasks, *, param_overrides=None):
                self.calls.append((list(tasks), param_overrides))
                return 1, 0

            def reload_tasks(self):
                return None

            def _reset_cancel(self):
                self._cancel_event.clear()

        tm = FakeTaskManager()
        sched = Scheduler()
        sched.set_task_manager(tm)
        overrides = {"测试/任务": {"redeem_code": "临时代码"}}

        with (
            patch.object(cfg, "active_character", return_value={"server": "s1", "name": "c1"}),
            patch.object(cfg, "save_config"),
            patch("orchestrator.scheduler.runtime_ctx.refresh"),
            patch("orchestrator.scheduler.notify_runtime_event"),
            patch.object(sched, "_maybe_daily_restart") as daily_restart,
            patch.object(sched, "_ensure_character_logged_in") as ensure_login,
            patch.object(sched, "_post_execution_action") as post_action,
        ):
            sched._run_task_pipeline(
                explicit_tasks=["测试/任务"],
                force_login=True,
                param_overrides=overrides,
            )

        self.assertEqual(tm.calls, [(["测试/任务"], overrides)])
        daily_restart.assert_not_called()
        ensure_login.assert_called_once()
        post_action.assert_not_called()

    def test_scheduler_runs_same_debug_task_with_distinct_param_overrides(self):
        from orchestrator.scheduler import Scheduler

        self._install_task_config(debug_mode=True)

        class FakeTaskManager:
            def __init__(self):
                self._cancel_event = Event()
                self.calls = []

            def execute_tasks(self, tasks, *, param_overrides=None):
                self.calls.append((list(tasks), param_overrides))
                return 1, 0

            def reload_tasks(self):
                return None

            def _reset_cancel(self):
                self._cancel_event.clear()

        tm = FakeTaskManager()
        sched = Scheduler()
        sched.set_task_manager(tm)
        runs = [
            {"id": "code-1", "task": "测试/任务", "params": {"redeem_code": "A"}},
            {"id": "code-2", "task": "测试/任务", "params": {"redeem_code": "B"}},
        ]

        with (
            patch.object(cfg, "active_character", return_value={"server": "s1", "name": "c1"}),
            patch.object(cfg, "save_config"),
            patch("orchestrator.scheduler.runtime_ctx.refresh"),
            patch("orchestrator.scheduler.notify_runtime_event"),
            patch.object(sched, "_maybe_daily_restart"),
            patch.object(sched, "_ensure_character_logged_in"),
            patch.object(sched, "_post_execution_action"),
        ):
            sched.run_direct_sequence(runs, force_login=True)

        self.assertEqual(tm.calls, [
            (["测试/任务"], {"测试/任务": {"redeem_code": "A"}}),
            (["测试/任务"], {"测试/任务": {"redeem_code": "B"}}),
        ])

    def test_task_list_direct_run_skips_character_login_only_when_requested(self):
        from orchestrator.scheduler import Scheduler

        self._install_task_config(debug_mode=False)

        class SuccessfulTaskManager:
            def __init__(self):
                self._cancel_event = Event()
                self.executed = []

            def execute_tasks(self, tasks):
                self.executed.extend(tasks)
                return 1, 0

            def _reset_cancel(self):
                self._cancel_event.clear()

        def run_direct(*, skip_character_login: bool, force_login: bool = False):
            task_manager = SuccessfulTaskManager()
            scheduler = Scheduler()
            scheduler.set_task_manager(task_manager)

            with (
                patch.object(cfg, "active_character", return_value={"server": "s1", "name": "c1"}),
                patch.object(cfg, "save_config"),
                patch("orchestrator.scheduler.runtime_ctx.refresh"),
                patch("orchestrator.scheduler.notify_runtime_event"),
                patch.object(scheduler, "invalidate_login") as invalidate_login,
                patch.object(scheduler, "_maybe_daily_restart") as daily_restart,
                patch.object(scheduler, "_ensure_character_logged_in") as ensure_login,
                patch.object(scheduler, "_post_execution_action") as post_action,
            ):
                scheduler.run_direct(
                    ["测试/任务"],
                    force_login=force_login,
                    skip_character_login=skip_character_login,
                )

            return task_manager, invalidate_login, daily_restart, ensure_login, post_action

        task_manager, invalidate_login, daily_restart, ensure_login, post_action = run_direct(
            skip_character_login=True,
        )
        self.assertEqual(task_manager.executed, ["测试/任务"])
        invalidate_login.assert_not_called()
        ensure_login.assert_not_called()
        # 任务列表直跑要复用当前游戏现场；每日重启会关掉模拟器，和这个入口的
        # 「跳过角色校验」语义冲突，所以只在真正需要登录的入口做。
        daily_restart.assert_not_called()
        post_action.assert_called_once()

        task_manager, invalidate_login, daily_restart, ensure_login, post_action = run_direct(
            skip_character_login=False,
        )
        self.assertEqual(task_manager.executed, ["测试/任务"])
        invalidate_login.assert_called_once()
        ensure_login.assert_called_once()
        daily_restart.assert_called_once()
        post_action.assert_called_once()

        task_manager, invalidate_login, daily_restart, ensure_login, post_action = run_direct(
            skip_character_login=True,
            force_login=True,
        )
        self.assertEqual(task_manager.executed, ["测试/任务"])
        invalidate_login.assert_called_once()
        ensure_login.assert_called_once()
        daily_restart.assert_called_once()
        post_action.assert_called_once()


class TestTaskManagerMumuFallback(unittest.TestCase):
    def setUp(self):
        self._cfg_backup = cfg._config
        cfg._config = {
            "app": {
                "app_to_start": "com.test.app",
                "restart_on_error": True,
            },
        }

    def tearDown(self):
        cfg._config = self._cfg_backup

    def test_repeated_app_start_failures_trigger_mumu_fallback(self):
        from orchestrator import task_manager as task_manager_module
        from orchestrator.task_manager import (
            APP_START_FAILURE_RESTART_THRESHOLD,
            TaskManager,
        )

        task_manager = TaskManager()
        mixctrl = SimpleNamespace(app=SimpleNamespace(close=lambda package: True))

        with (
            patch.object(task_manager_module.runtime_ctx, "mixctrl", mixctrl),
            patch.object(task_manager, "_wait_app_stopped"),
            patch.object(task_manager, "_wait_app_running", return_value=False),
            patch.object(task_manager, "_restart_mumu_and_launch_app", return_value=False) as restart_mumu,
        ):
            for _ in range(APP_START_FAILURE_RESTART_THRESHOLD):
                self.assertFalse(task_manager._try_recover_app(retry_count=0))

        restart_mumu.assert_called_once_with("com.test.app")
        self.assertEqual(task_manager._app_start_failure_count, 0)

    def test_mumu_fallback_restarts_power_and_rebuilds_session(self):
        from orchestrator import task_manager as task_manager_module
        from orchestrator.task_manager import TaskManager

        power = SimpleNamespace(restart=Mock())
        mumu = SimpleNamespace(power=power)
        task_manager = TaskManager()

        with (
            patch.object(task_manager_module.runtime_ctx, "mumu", mumu),
            patch.object(task_manager_module.runtime_ctx, "release_session") as release_session,
            patch.object(task_manager_module.runtime_ctx, "refresh") as refresh,
            patch.object(task_manager, "_wait_app_running", return_value=True),
        ):
            self.assertTrue(task_manager._restart_mumu_and_launch_app("com.test.app"))

        release_session.assert_called_once_with()
        power.restart.assert_called_once_with()
        refresh.assert_called_once_with(
            cancel_check=task_manager._check_cancel_requested,
            launch_app=False,
        )

    def test_mumu_fallback_respects_the_restart_cooldown(self):
        import time

        from orchestrator import task_manager as task_manager_module
        from orchestrator.task_manager import TaskManager

        power = SimpleNamespace(restart=Mock())
        task_manager = TaskManager()
        task_manager._last_mumu_restart_at = time.monotonic()

        with (
            patch.object(
                task_manager_module.runtime_ctx,
                "mumu",
                SimpleNamespace(power=power),
            ),
            patch.object(task_manager_module.runtime_ctx, "release_session") as release_session,
        ):
            self.assertFalse(task_manager._restart_mumu_and_launch_app("com.test.app"))

        power.restart.assert_not_called()
        release_session.assert_not_called()


if __name__ == "__main__":
    unittest.main()
