from __future__ import annotations

import json
import subprocess
import sys
import types
import unittest
from enum import Enum
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def import_task_tree_service_for_test():
    autoscriptor = types.ModuleType("AutoScriptor")
    utils = types.ModuleType("AutoScriptor.utils")

    app_config = types.ModuleType("AutoScriptor.utils.app_config")
    app_config.cfg = SimpleNamespace(
        _config={},
        _account_data={},
        active_character=lambda: {},
        list_characters=lambda: {},
    )

    game_profession = types.ModuleType("AutoScriptor.utils.game_profession")
    game_profession.GAME_PROFESSIONS = ("悟空", "唐僧")
    game_profession.normalize_game_profession = (
        lambda raw: raw if raw in game_profession.GAME_PROFESSIONS else "悟空"
    )

    with patch.dict(sys.modules, {
        "AutoScriptor": autoscriptor,
        "AutoScriptor.utils": utils,
        "AutoScriptor.utils.app_config": app_config,
        "AutoScriptor.utils.game_profession": game_profession,
    }):
        sys.modules.pop("services.webui.task_tree_service", None)
        import services.webui.task_tree_service as module

    return module


def autoscriptor_logger_stubs() -> dict[str, types.ModuleType]:
    autoscriptor = types.ModuleType("AutoScriptor")
    utils = types.ModuleType("AutoScriptor.utils")
    logger_module = types.ModuleType("AutoScriptor.utils.logger")
    logger_module.logger = SimpleNamespace(
        debug=lambda *args, **kwargs: None,
        info=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
        error=lambda *args, **kwargs: None,
    )
    return {
        "AutoScriptor": autoscriptor,
        "AutoScriptor.utils": utils,
        "AutoScriptor.utils.logger": logger_module,
    }


class TestConfigTemplateContract(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((ROOT / "config template.json").read_text(encoding="utf-8"))

    def test_runtime_config_uses_account_model(self):
        self.assertEqual(self.config["current_account"], "default")
        self.assertIn("accounts", self.config)
        self.assertNotIn("current_profile", self.config)
        self.assertNotIn("profiles", self.config)

    def test_scheduler_and_post_execution_defaults_are_valid(self):
        self.assertFalse(self.config["scheduler"]["auto_start"])
        self.assertEqual(self.config["emulator"]["post_execution"], "none")


class TestTaskTreeServiceContract(unittest.TestCase):
    def setUp(self):
        self.module = import_task_tree_service_for_test()
        self.service = self.module.TaskTreeService()

    def test_ordered_paths_preserves_nested_leaf_order(self):
        tree = {
            "每日任务": {
                "任务A": {"on": True, "next_exec_time": 0},
                "分组": {
                    "任务B": {"on": False, "next_exec_time": 0},
                },
            },
            "每周任务": {"on": True, "next_exec_time": 1},
        }

        self.assertEqual(
            self.service.ordered_paths(tree),
            ["每日任务/任务A", "每日任务/分组/任务B", "每周任务"],
        )

    def test_strip_runtime_fields_only_removes_ui_metadata(self):
        tasks = {
            "每日任务": {
                "任务A": {
                    "on": True,
                    "next_exec_time": 0,
                    "params": {"x": 1},
                    "param_meta": {"x": "enum"},
                    "param_keys": ["x"],
                    "task_description": "desc",
                    "task_doc_flow": "flow",
                    "fn": "callable-name",
                    "order": 3,
                    "_due": True,
                    "beta": True,
                    "custom": True,
                },
            },
        }

        cleaned = self.service.strip_runtime_fields(tasks)
        leaf = cleaned["每日任务"]["任务A"]

        self.assertEqual(leaf["params"], {"x": 1})
        self.assertEqual(leaf["next_exec_time"], 0)
        self.assertTrue(leaf["on"])
        for key in self.service.RUNTIME_TASK_FIELDS:
            self.assertNotIn(key, leaf)
        self.assertIn("param_meta", tasks["每日任务"]["任务A"], "strip_runtime_fields must not mutate input")

    def test_normalize_dispatch_queue_keeps_existing_unique_characters(self):
        account_data = {
            "characters": {
                "s1": {"a": {}, "b": {}},
                "s2": {"c": {}},
            }
        }
        raw = [
            {"server": " s1 ", "name": " a "},
            {"server": "s1", "name": "a"},
            {"server": "missing", "name": "x"},
            {"server": "s2", "name": "c"},
            {"server": "", "name": "c"},
            "bad",
        ]

        with patch.object(self.module, "cfg") as cfg:
            cfg._account_data = account_data
            self.assertEqual(
                self.service.normalize_dispatch_queue(raw),
                [{"server": "s1", "name": "a"}, {"server": "s2", "name": "c"}],
            )

    def test_public_config_removes_sensitive_fields_and_adds_public_summaries(self):
        config = {
            "game": {"account": "u", "password": "p", "character_name": "hero"},
            "deploy": {"password": "web"},
            "tasks": {"任务": {"on": True, "next_exec_time": 0, "params": {"security_key": "secret"}}},
            "encryption": {"encrypted_data": "secret"},
        }

        with patch.object(self.module, "cfg") as cfg, \
                patch.object(self.service, "inject_public_task_fields") as inject:
            cfg._config = config
            cfg.active_character.return_value = {"server": "s1", "name": "hero"}
            cfg.list_characters.return_value = {"s1": {"hero": {"game_profession": "悟空"}}}
            public = self.service.public_config()

        self.assertNotIn("encryption", public)
        self.assertNotIn("account", public["game"])
        self.assertNotIn("password", public["game"])
        self.assertNotIn("password", public["deploy"])
        self.assertNotIn("security_key", public["tasks"]["任务"]["params"])
        self.assertEqual(public["active_character"], {"server": "s1", "name": "hero"})
        self.assertEqual(public["characters_summary"], {"s1": ["hero"]})
        inject.assert_called_once()


class TestRuntimeControllerContract(unittest.TestCase):
    class SchedulerState(Enum):
        PENDING = "pending"
        RUNNING = "running"
        ERROR = "error"

    @classmethod
    def setUpClass(cls):
        scheduler_mod = types.ModuleType("services.core.scheduler")
        scheduler_mod.Scheduler = object
        scheduler_mod.SchedulerState = cls.SchedulerState
        task_manager_mod = types.ModuleType("services.core.task_manager")
        task_manager_mod.TaskManager = object
        modules = autoscriptor_logger_stubs()
        modules.update({
            "services.core.scheduler": scheduler_mod,
            "services.core.task_manager": task_manager_mod,
        })
        with patch.dict(sys.modules, modules):
            sys.modules.pop("services.webui.runtime_controller", None)
            from services.webui.runtime_controller import RuntimeController

        cls.RuntimeController = RuntimeController

    def _controller(self, scheduler=None, task_manager=None):
        scheduler = scheduler or SimpleNamespace(
            state=self.SchedulerState.PENDING,
            is_executing=False,
            status_dict=lambda: {"state": "stopped"},
            request_stop=lambda: None,
            invalidate_login=lambda: None,
        )
        task_manager = task_manager or SimpleNamespace(request_cancel=lambda: None)
        return self.RuntimeController(scheduler, task_manager)

    def test_status_idle_resets_stopping_flag(self):
        controller = self._controller()
        controller._stop_requested = True

        status = controller.status()

        self.assertFalse(status["running"])
        self.assertFalse(status["busy"])
        self.assertFalse(status["stopping"])
        self.assertIsNone(status["reason"])
        self.assertFalse(controller._stop_requested)

    def test_scheduler_busy_blocks_runtime(self):
        controller = self._controller(
            scheduler=SimpleNamespace(
                state=self.SchedulerState.RUNNING,
                is_executing=False,
                status_dict=lambda: {"state": "running"},
                request_stop=lambda: None,
                invalidate_login=lambda: None,
            )
        )

        self.assertEqual(controller.busy_reason(), "scheduler")
        self.assertTrue(controller.is_busy())
        self.assertEqual(controller.status()["reason"], "scheduler")

    def test_direct_run_lifecycle_clears_busy_state(self):
        controller = self._controller()
        completed = []

        thread = controller.start_direct(lambda tasks: completed.extend(tasks), ["a", "b"])
        thread.join(timeout=2)

        self.assertEqual(completed, ["a", "b"])
        self.assertFalse(controller.direct_run_alive())
        self.assertFalse(controller.is_busy())

    def test_request_stop_notifies_task_manager_and_scheduler_when_idle(self):
        calls = []
        scheduler = SimpleNamespace(
            state=self.SchedulerState.PENDING,
            is_executing=False,
            status_dict=lambda: {"state": "stopped"},
            request_stop=lambda: calls.append("scheduler_stop"),
            invalidate_login=lambda: calls.append("invalidate_login"),
        )
        task_manager = SimpleNamespace(request_cancel=lambda: calls.append("cancel"))
        controller = self._controller(scheduler=scheduler, task_manager=task_manager)

        self.assertEqual(controller.request_stop(), "idle")
        self.assertEqual(calls, ["cancel", "scheduler_stop", "invalidate_login"])


class TestWebUIFrontendContract(unittest.TestCase):
    JS_FILES = [
        ROOT / "services/webui/static/js/app.js",
        ROOT / "services/webui/static/js/stores/runtimeStore.js",
        ROOT / "services/webui/static/js/components/Overview.js",
        ROOT / "services/webui/static/js/components/TaskPanel.js",
        ROOT / "services/webui/static/js/components/TaskTree.js",
        ROOT / "services/webui/static/js/components/Settings.js",
    ]

    def test_changed_frontend_files_parse_as_javascript(self):
        for path in self.JS_FILES:
            with self.subTest(path=path.name):
                subprocess.run(["node", "--check", str(path)], cwd=ROOT, check=True, capture_output=True, text=True)

    def test_app_uses_single_runtime_snapshot_polling_path(self):
        content = (ROOT / "services/webui/static/js/app.js").read_text(encoding="utf-8")

        self.assertIn("fetchRuntimeSnapshot", content)
        self.assertIn("'/runtime/snapshot'", content)
        self.assertNotIn("fetchOverview", content)
        self.assertNotIn("fetchSchedulerStatus", content)
        self.assertNotIn("fetchRunStatus", content)
        self.assertNotIn("fetchAccounts", content)
        self.assertNotIn("loadDispatchQueue", content)

    def test_frontend_uses_account_terms_not_profile_terms(self):
        index = (ROOT / "services/webui/static/index.html").read_text(encoding="utf-8")
        style = (ROOT / "services/webui/static/css/style.css").read_text(encoding="utf-8")

        self.assertIn("account-dropdown", index)
        self.assertIn("topbar-account", index)
        self.assertIn(".account-dropdown", style)
        self.assertNotIn("profile-dropdown", index + style)
        self.assertNotIn("topbar-profile", index + style)

    def test_overview_scheduled_status_is_displayed_as_completed(self):
        content = (ROOT / "services/webui/static/js/components/Overview.js").read_text(encoding="utf-8")
        self.assertIn("scheduled: '已完成'", content)
        self.assertNotIn("scheduled: '已计划'", content)

    def test_settings_contains_only_active_settings_ui(self):
        content = (ROOT / "services/webui/static/js/components/Settings.js").read_text(encoding="utf-8")

        self.assertIn("SettingsPanel", content)
        self.assertIn("post_execution", content)
        self.assertIn('value="goto_main"', content)
        self.assertNotIn("notifyConfig", content)
        self.assertNotIn("updateConfig", content)
        self.assertNotIn("remoteConfig", content)
        self.assertNotIn("passwordProtected", content)


class TestWebUIServerRouteContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        content = (ROOT / "services/webui/server.py").read_text(encoding="utf-8")
        cls.routes = set()
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("@app.") and '("' in stripped:
                cls.routes.add(stripped.split('("', 1)[1].split('"', 1)[0])

    def test_runtime_routes_are_registered(self):
        for path in {
            "/api/runtime/snapshot",
            "/api/run",
            "/api/stop",
            "/api/tasks",
            "/api/tasks/reload",
            "/api/accounts",
            "/api/accounts/switch",
            "/api/characters/switch",
            "/api/dispatch/queue",
        }:
            with self.subTest(path=path):
                self.assertIn(path, self.routes)

    def test_removed_profile_routes_do_not_return(self):
        self.assertNotIn("/api/profiles", self.routes)
        self.assertNotIn("/api/profiles/switch", self.routes)


class TestUpdaterGitCommandContract(unittest.TestCase):
    def test_git_command_includes_safe_directory_for_repo_root(self):
        with patch.dict(sys.modules, autoscriptor_logger_stubs()):
            sys.modules.pop("services.core.updater", None)
            from services.core.updater import Updater

        updater = Updater()
        updater._root = str(ROOT)
        cmd = updater._git_cmd("status", "--short")

        self.assertEqual(cmd[1], "-c")
        self.assertEqual(cmd[2], f"safe.directory={str(ROOT).replace(chr(92), '/')}")
        self.assertEqual(cmd[-2:], ["status", "--short"])


if __name__ == "__main__":
    unittest.main()
