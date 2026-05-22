from __future__ import annotations

import json
import importlib.util
import subprocess
import sys
import tempfile
import types
import unittest
from contextlib import contextmanager
from copy import deepcopy
from enum import Enum
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import os
import time

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


def import_app_config_for_test(tmp_root: str):
    autoscriptor = types.ModuleType("AutoScriptor")
    crypto = types.ModuleType("AutoScriptor.crypto")
    crypto_config = types.ModuleType("AutoScriptor.crypto.config_manager")
    crypto_config.ConfigManager = SimpleNamespace(
        encrypt_data=lambda data, key: {"encrypted_data": json.dumps(data), "key": key},
        decrypt_data=lambda enc, key: json.loads(enc.get("encrypted_data", "{}")),
    )
    utils = types.ModuleType("AutoScriptor.utils")
    game_profession = types.ModuleType("AutoScriptor.utils.game_profession")
    game_profession.DEFAULT_GAME_PROFESSION = "default_profession"
    game_profession.normalize_game_profession = lambda raw: raw or "default_profession"
    logger_module = types.ModuleType("AutoScriptor.utils.logger")
    logger_module.logger = SimpleNamespace(
        debug=lambda *args, **kwargs: None,
        info=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
        error=lambda *args, **kwargs: None,
    )
    paths = types.ModuleType("AutoScriptor.utils.paths")
    paths.get_data_root = lambda: tmp_root
    paths.get_accounts_dir = lambda: Path(tmp_root) / "accounts"

    module_name = "app_config_under_test"
    spec = importlib.util.spec_from_file_location(
        module_name,
        ROOT / "AutoScriptor/utils/app_config.py",
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {
        "AutoScriptor": autoscriptor,
        "AutoScriptor.crypto": crypto,
        "AutoScriptor.crypto.config_manager": crypto_config,
        "AutoScriptor.utils": utils,
        "AutoScriptor.utils.game_profession": game_profession,
        "AutoScriptor.utils.logger": logger_module,
        "AutoScriptor.utils.paths": paths,
    }):
        assert spec.loader is not None
        spec.loader.exec_module(module)
    return module


def import_watcher_for_test():
    module_name = "config_watcher_under_test"
    spec = importlib.util.spec_from_file_location(
        module_name,
        ROOT / "services/core/watcher.py",
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, autoscriptor_logger_stubs()):
        assert spec.loader is not None
        spec.loader.exec_module(module)
    return module


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

    def _task_registry_stubs(self, registered_paths: set[str]):
        class FakeTaskRegistry:
            def has_task(self, path):
                return path in registered_paths

            def get_param_meta(self, path):
                return {}

            def get_param_keys(self, path):
                return []

            def get_beta(self, path):
                return False

            def get_custom(self, path):
                return False

            def get_debug_mode(self, path):
                return False

            def get_description(self, path):
                return ""

            def get_doc_flow(self, path):
                return []

        task_registry = types.ModuleType("AutoScriptor.utils.task_registry")
        task_registry.task_registry = FakeTaskRegistry()
        scheduler = types.ModuleType("services.core.scheduler")
        scheduler.is_task_due = lambda node, path, now_ts: bool(node.get("on"))
        return {
            "AutoScriptor": types.ModuleType("AutoScriptor"),
            "AutoScriptor.utils": types.ModuleType("AutoScriptor.utils"),
            "AutoScriptor.utils.task_registry": task_registry,
            "services.core.scheduler": scheduler,
        }

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
                    "debug_mode": True,
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

    def test_public_task_projection_hides_unregistered_leaf_tasks(self):
        tasks = {
            "registered": {
                "task": {"on": True, "next_exec_time": 0, "params": {}},
            },
            "stale": {
                "ghost": {"on": True, "next_exec_time": 0, "params": {}},
            },
        }

        with patch.dict(sys.modules, self._task_registry_stubs({"registered/task"})):
            self.service.inject_public_task_fields(tasks)

        self.assertEqual(list(tasks.keys()), ["registered"])
        self.assertIn("_due", tasks["registered"]["task"])

    def test_flatten_tasks_skips_unregistered_leaf_tasks(self):
        tasks = {
            "registered": {
                "task": {"on": True, "next_exec_time": 0, "params": {}},
            },
            "stale": {
                "ghost": {"on": True, "next_exec_time": 0, "params": {}},
            },
        }

        with patch.dict(sys.modules, self._task_registry_stubs({"registered/task"})):
            flat = self.service.flatten_tasks(tasks, now_ts=100)

        self.assertEqual([row["path"] for row in flat], ["registered/task"])

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

    def test_request_stop_does_not_async_raise_into_worker_thread(self):
        content = (ROOT / "services/webui/runtime_controller.py").read_text(encoding="utf-8")

        self.assertNotIn("PyThreadState_SetAsyncExc", content)
        self.assertNotIn("_raise_in_thread", content)


class TestWebUILifecycleServiceContract(unittest.TestCase):
    def setUp(self):
        sys.modules.pop("services.webui.lifecycle_service", None)
        from services.webui.lifecycle_service import WebUILifecycleService

        self.WebUILifecycleService = WebUILifecycleService

    def _service(self, cfg=None, task_tree_service=None, task_manager=None, scheduler=None):
        self.calls = []
        cfg = cfg or SimpleNamespace(
            _config={},
            _account_data={},
            save_config=lambda: self.calls.append("save_config"),
            _save_account_file=lambda: self.calls.append("save_account_file"),
            switch_character=lambda server, character: self.calls.append(("switch_character", server, character)),
            switch_account=lambda name, key: self.calls.append(("switch_account", name, key)),
            set_character_game_profession=lambda server, character, profession: self.calls.append(
                ("set_profession", server, character, profession)
            ),
        )
        task_tree_service = task_tree_service or SimpleNamespace(
            strip_runtime_fields=lambda tasks: deepcopy(tasks),
            normalize_dispatch_queue=lambda queue: queue,
        )

        if task_manager is None:
            class FakeTaskManager:
                @contextmanager
                def config_transaction(inner_self):
                    self.calls.append("lock")
                    yield

                def reload_tasks(inner_self, security_key=None):
                    self.calls.append(("reload_tasks", security_key))

                def switch_character_and_reload(inner_self, server, character):
                    self.calls.append(("switch_character_and_reload", server, character))

            task_manager = FakeTaskManager()

        scheduler = scheduler or SimpleNamespace(
            wake=lambda: self.calls.append("wake"),
            invalidate_login=lambda: self.calls.append("invalidate_login"),
        )

        return self.WebUILifecycleService(
            cfg,
            task_manager,
            scheduler,
            task_tree_service,
            refresh_order_map=lambda: self.calls.append("read_config"),
            mark_config_changed=lambda reason: self.calls.append(("bump", reason)) or 42,
            apply_log_level=lambda: self.calls.append("apply_log_level"),
        ), cfg

    def test_save_tasks_sanitizes_persists_reloads_and_wakes(self):
        def strip_runtime_fields(tasks):
            cleaned = deepcopy(tasks)
            cleaned["group"]["task"].pop("param_meta", None)
            return cleaned

        service, cfg = self._service(
            task_tree_service=SimpleNamespace(strip_runtime_fields=strip_runtime_fields)
        )
        tasks = {"group": {"task": {"on": True, "next_exec_time": 0, "param_meta": {"x": "secret"}}}}

        version = service.save_tasks(tasks)

        self.assertEqual(version, 42)
        self.assertEqual(cfg._config["tasks"], {"group": {"task": {"on": True, "next_exec_time": 0}}})
        self.assertIn("param_meta", tasks["group"]["task"])
        self.assertEqual(
            self.calls,
            ["lock", "save_config", ("reload_tasks", None), "wake", "read_config", ("bump", "save tasks")],
        )

    def test_switch_character_uses_task_manager_boundary_and_invalidates_login(self):
        service, _cfg = self._service()

        version = service.switch_character("s1", "hero", reason="select run character")

        self.assertEqual(version, 42)
        self.assertEqual(
            self.calls,
            [("switch_character_and_reload", "s1", "hero"), "invalidate_login", "read_config", ("bump", "select run character")],
        )

    def test_save_dispatch_queue_normalizes_and_writes_account_file_only(self):
        def normalize(queue):
            return [item for item in queue if item.get("server") == "s1"]

        service, cfg = self._service(
            cfg=SimpleNamespace(
                _config={},
                _account_data={},
                _save_account_file=lambda: self.calls.append("save_account_file"),
            ),
            task_tree_service=SimpleNamespace(normalize_dispatch_queue=normalize),
        )

        queue, version = service.save_dispatch_queue([
            {"server": "s1", "name": "a"},
            {"server": "missing", "name": "x"},
        ])

        self.assertEqual(version, 42)
        self.assertEqual(queue, [{"server": "s1", "name": "a"}])
        self.assertEqual(cfg._account_data["dispatch_queue"], queue)
        self.assertEqual(self.calls, ["lock", "save_account_file", ("bump", "save dispatch queue")])

    def test_delete_character_prunes_dispatch_queue(self):
        def normalize(queue):
            return [item for item in queue if item["name"] != "deleted"]

        def delete_character(server, character):
            self.calls.append(("delete_character", server, character))

        service, cfg = self._service(
            cfg=SimpleNamespace(
                _config={},
                _account_data={
                    "dispatch_queue": [
                        {"server": "s1", "name": "keep"},
                        {"server": "s1", "name": "deleted"},
                    ]
                },
                delete_character=delete_character,
                _save_account_file=lambda: self.calls.append("save_account_file"),
            ),
            task_tree_service=SimpleNamespace(normalize_dispatch_queue=normalize),
        )

        version = service.delete_character("s1", "deleted")

        self.assertEqual(version, 42)
        self.assertEqual(cfg._account_data["dispatch_queue"], [{"server": "s1", "name": "keep"}])
        self.assertEqual(
            self.calls,
            ["lock", ("delete_character", "s1", "deleted"), "save_account_file", ("bump", "delete character")],
        )


class TestConfigLifecycleContract(unittest.TestCase):
    def test_account_can_restore_decrypted_credentials_after_config_only_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            module = import_app_config_for_test(tmp)
            account = module.Account("main", {"characters": {}, "active_character": {}, "encryption": {}})
            account.restore_credentials({"account": "user", "password": "pwd"})

            self.assertEqual(account.credentials, {"account": "user", "password": "pwd"})

    def test_reload_preserving_decrypted_credentials_keeps_verified_account_unlocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            module = import_app_config_for_test(tmp)
            cfg = module.cfg
            cfg.add_account("main", "user", "pwd", "s1", "hero", "key")
            cfg._config["current_account"] = "main"
            cfg.save_config()
            cfg.load_config("key")
            self.assertTrue(cfg.has_decrypted_credentials())

            cfg.reload_preserving_decrypted_credentials()

            self.assertTrue(cfg.has_decrypted_credentials())
            self.assertEqual(cfg._config["game"]["account"], "user")
            self.assertEqual(cfg._config["game"]["password"], "pwd")

    def test_task_manager_reload_uses_config_reload_preserving_credentials(self):
        content = (ROOT / "services/core/task_manager.py").read_text(encoding="utf-8")

        self.assertIn("reload_preserving_decrypted_credentials", content)
        self.assertNotIn("saved_game = cfg._config.get('game'", content)

    def test_config_watcher_tracks_extra_account_file(self):
        watcher_module = import_watcher_for_test()

        with tempfile.TemporaryDirectory() as tmp:
            config_path = os.path.join(tmp, "config.json")
            account_path = os.path.join(tmp, "account.json")
            Path(config_path).write_text("{}", encoding="utf-8")
            Path(account_path).write_text("{}", encoding="utf-8")

            watcher = watcher_module.ConfigWatcher(config_path, extra_paths=lambda: [account_path])
            watcher.start_watching()
            time.sleep(1.1)
            Path(account_path).write_text('{"changed": true}', encoding="utf-8")

            self.assertTrue(watcher.should_reload())

    def test_config_writes_json_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            module = import_app_config_for_test(tmp)
            calls = []
            real_replace = os.replace

            def tracking_replace(src, dst):
                calls.append((Path(src).name, Path(dst).name))
                return real_replace(src, dst)

            with patch.object(module.os, "replace", side_effect=tracking_replace):
                module.cfg._config["app"] = {"name": "ZmxyOL"}
                module.cfg.save_config()

            self.assertTrue((Path(tmp) / "config.json").exists())
            self.assertTrue(calls)
            self.assertEqual(calls[-1][1], "config.json")

    def test_relative_accounts_dir_keeps_data_accounts_compatibility(self):
        with tempfile.TemporaryDirectory() as tmp:
            module = import_app_config_for_test(tmp)
            mgr = module.ConfigManager()
            default_dir = Path(tmp) / "accounts"

            for raw in ("", "accounts", "data/accounts"):
                mgr.global_cfg = {"accounts": {"dir": raw}}
                with self.subTest(raw=raw):
                    self.assertEqual(mgr.resolved_accounts_dir(), default_dir)


class TestWebUIFrontendContract(unittest.TestCase):
    JS_FILES = [
        ROOT / "services/webui/static/js/app.js",
        ROOT / "services/webui/static/js/stores/runtimeStore.js",
        ROOT / "services/webui/static/js/components/DiagnosticsPanel.js",
        ROOT / "services/webui/static/js/components/Overview.js",
        ROOT / "services/webui/static/js/components/TaskPanel.js",
        ROOT / "services/webui/static/js/components/TaskTree.js",
        ROOT / "services/webui/static/js/components/Settings.js",
        ROOT / "services/webui/static/js/components/ErrorArchivesPanel.js",
    ]

    def test_changed_frontend_files_parse_as_javascript(self):
        for path in self.JS_FILES:
            with self.subTest(path=path.name):
                subprocess.run(["node", "--check", str(path)], cwd=ROOT, check=True, capture_output=True, text=True)

    def test_app_uses_single_runtime_snapshot_polling_path(self):
        content = (ROOT / "services/webui/static/js/app.js").read_text(encoding="utf-8")

        self.assertIn("fetchRuntimeSnapshot", content)
        self.assertIn("'/runtime/snapshot'", content)
        self.assertNotIn("LOG_NEEDS_TASK_REFRESH", content)
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

    def test_error_archives_support_shift_range_selection(self):
        content = (ROOT / "services/webui/static/js/components/ErrorArchivesPanel.js").read_text(encoding="utf-8")

        self.assertIn("lastCheckedFolder", content)
        self.assertIn("flatArchiveFolders", content)
        self.assertIn("ev.shiftKey", content)
        self.assertIn("@click.stop=\"setChecked(it.folder, $event)\"", content)

    def test_settings_contains_only_active_settings_ui(self):
        content = (ROOT / "services/webui/static/js/components/Settings.js").read_text(encoding="utf-8")

        self.assertIn("SettingsPanel", content)
        self.assertIn("任务开始时自动启动模拟器和游戏", content)
        self.assertIn("它不是“兼容性越高越慢”的开关", content)
        self.assertIn("MuMu 多开编号", content)
        self.assertIn("MuMuManager 路径", content)
        self.assertIn("只负责启动、关闭、窗口等官方管理动作", content)
        self.assertIn("<diagnostics-panel embedded", content)
        self.assertIn("post_execution", content)
        self.assertIn("value: 'goto_main'", content)
        self.assertNotIn("visibleSections", content)
        self.assertNotIn("兼容自动启动", content)
        self.assertNotIn("notifyConfig", content)
        self.assertNotIn("updateConfig", content)
        self.assertNotIn("remoteConfig", content)
        self.assertNotIn("passwordProtected", content)

    def test_diagnostics_is_embedded_in_settings_not_sidebar_page(self):
        sidebar = (ROOT / "services/webui/static/js/components/AppSidebar.js").read_text(encoding="utf-8")
        app = (ROOT / "services/webui/static/js/app.js").read_text(encoding="utf-8")
        index = (ROOT / "services/webui/static/index.html").read_text(encoding="utf-8")
        settings = (ROOT / "services/webui/static/js/components/Settings.js").read_text(encoding="utf-8")

        self.assertNotIn("id: 'diagnostics'", sidebar)
        self.assertNotIn("启动诊断', icon", sidebar)
        self.assertNotIn("diagnostics: '启动诊断'", app)
        self.assertIn("DiagnosticsPanel", app)
        self.assertIn("app.component('diagnostics-panel', DiagnosticsPanel)", app)
        self.assertNotIn("activeTab==='diagnostics'", index)
        self.assertIn("<diagnostics-panel embedded", settings)
        self.assertIn("DiagnosticsPanel.js", index)

    def test_diagnostics_screenshot_probe_is_explicit(self):
        content = (ROOT / "services/webui/static/js/components/DiagnosticsPanel.js").read_text(encoding="utf-8")

        self.assertIn("mounted()", content)
        self.assertIn("this.refresh(false)", content)
        self.assertIn("includeScreenshot ? '?screenshot=true' : ''", content)
        self.assertIn("@click=\"refresh(true)\"", content)
        self.assertIn("默认轻量检查，不会主动读取模拟器截图", content)


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
            "/api/device/diagnostics",
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

    def test_webui_routes_do_not_bypass_task_lifecycle(self):
        content = (ROOT / "services/webui/server.py").read_text(encoding="utf-8")

        self.assertNotIn("from ZmxyOL.task import load_tasks", content)
        self.assertNotIn("with TASK_MANAGER._cfg_lock", content)

    def test_webui_startup_does_not_initialize_device_controls(self):
        content = (ROOT / "services/webui/server.py").read_text(encoding="utf-8")
        start = content.index("def _do_heavy_init():")
        end = content.index("@app.get(\"/api/init-status\")", start)
        body = content[start:end]

        self.assertNotIn("AutoScriptor.core.api import init", body)
        self.assertNotIn("runtime_ctx.init(", body)
        self.assertIn("runtime_ctx.init_bg()", body)
        self.assertIn("TASK_MANAGER.reload_tasks()", body)

    def test_runtime_startup_is_cancellable_and_execution_owned(self):
        runtime_context = (ROOT / "services/core/runtime_context.py").read_text(encoding="utf-8")
        scheduler = (ROOT / "services/core/scheduler.py").read_text(encoding="utf-8")
        api = (ROOT / "AutoScriptor/core/api.py").read_text(encoding="utf-8")

        self.assertIn("self._refresh_lock", runtime_context)
        self.assertIn("threading.RLock()", runtime_context)
        self.assertIn("def ensure_device_session", runtime_context)
        self.assertIn("def has_device_session", runtime_context)
        self.assertIn("start_emulator=True", runtime_context)
        self.assertIn("launch_app=True", runtime_context)
        self.assertIn("cancel_check=cancel_check", runtime_context)
        self.assertIn("runtime_ctx.refresh(cancel_check=self._check_cancel_requested)", scheduler)
        self.assertIn("_reload_deferred", scheduler)
        self.assertIn("_handle_watched_config_change", scheduler)
        self.assertIn("join_with_cancel", api)
        self.assertIn("sleep_with_cancel", api)

    def test_device_facade_centralizes_manager_adb_nemu_checks(self):
        content = (ROOT / "AutoScriptor/control/MumuAdaptor/device_facade.py").read_text(encoding="utf-8")
        server = (ROOT / "services/webui/server.py").read_text(encoding="utf-8")

        self.assertIn("class DeviceFacade", content)
        self.assertIn("MuMuManager for official lifecycle commands", content)
        self.assertIn("ADB for click/app fallbacks", content)
        self.assertIn("NemuIpc for screenshots", content)
        self.assertIn("diagnostics", content)
        self.assertIn("NemuIpc", content)
        self.assertIn("/api/device/diagnostics", server)

    def test_mumu_manager_remains_lifecycle_channel_not_high_frequency_input(self):
        app_core = (ROOT / "AutoScriptor/control/MumuAdaptor/api/core/app.py").read_text(encoding="utf-8")
        power_core = (ROOT / "AutoScriptor/control/MumuAdaptor/api/core/power.py").read_text(encoding="utf-8")
        adb_core = (ROOT / "AutoScriptor/control/MumuAdaptor/api/adb/Adb.py").read_text(encoding="utf-8")
        settings = (ROOT / "services/webui/static/js/components/Settings.js").read_text(encoding="utf-8")

        self.assertIn("MuMuManager app launch 失败，回退至 ADB monkey", app_core)
        self.assertIn("MuMuManager app close 失败，回退至 ADB force-stop", app_core)
        self.assertIn("MuMuManager launch 失败，但 ADB 已可用", power_core)
        self.assertIn("def click", adb_core)
        self.assertIn("Prefer direct adb.exe for high-frequency input", adb_core)
        self.assertIn("return self._direct_shell_or_manager", adb_core)
        self.assertIn("日常点击输入不会依赖它", settings)

    def test_device_diagnostics_import_does_not_initialize_heavy_runtime(self):
        package_init = (ROOT / "AutoScriptor/__init__.py").read_text(encoding="utf-8")
        mumu_init = (ROOT / "AutoScriptor/control/MumuAdaptor/__init__.py").read_text(encoding="utf-8")
        server = (ROOT / "services/webui/server.py").read_text(encoding="utf-8")

        self.assertIn("def __getattr__", package_init)
        self.assertIn("def __getattr__", mumu_init)
        self.assertNotIn("from AutoScriptor.core import *", package_init)
        self.assertNotIn("from AutoScriptor import *", server)
        self.assertNotIn("from .mumu import Mumu", mumu_init)
        self.assertNotIn("from .api import *", mumu_init)

    def test_editor_device_actions_acquire_runtime_session_on_demand(self):
        content = (ROOT / "services/webui/routes/editor.py").read_text(encoding="utf-8")

        for marker in [
            '_ensure_editor_mixctrl("screenshot")',
            '_ensure_editor_mixctrl("locate").screenshot()',
            '_ensure_editor_mixctrl("remote/click")',
            '_ensure_editor_mixctrl("remote/swipe")',
            '_ensure_editor_mixctrl("execute-code")',
            '_ensure_editor_mixctrl("preview-extract")',
        ]:
            with self.subTest(marker=marker):
                self.assertIn(marker, content)
        self.assertIn("ensure_device_session", content)
        self.assertIn("_require_editor_device_unlock(request)", content)
        self.assertIn("设备会话初始化失败", content)
        self.assertIn("_EditorVirtualMixControl", content)
        self.assertNotIn("ctx.mixctrl", content)

    def test_remote_access_requires_deploy_password(self):
        content = (ROOT / "services/webui/server.py").read_text(encoding="utf-8")
        start = content.index('async def remote_access_toggle_api')
        end = content.index('# ── 多账号 API ──', start)
        body = content[start:end]

        self.assertIn('cfg._config.get("deploy", {}).get("password")', body)
        self.assertIn("deploy_password_required", body)

    def test_account_verify_does_not_start_scheduler(self):
        content = (ROOT / "services/webui/server.py").read_text(encoding="utf-8")
        start = content.index('async def verify_account_api')
        end = content.index('@app.post("/api/account")', start)
        body = content[start:end]

        self.assertIn("_grant_credential_unlock()", body)
        self.assertNotIn("scheduler.activate()", body)
        self.assertNotIn("scheduler.wake()", body)
        self.assertIn("waiting for explicit run", body)

    def test_editor_save_updates_existing_ui_map_rows(self):
        content = (ROOT / "services/webui/routes/editor.py").read_text(encoding="utf-8")

        self.assertIn("_read_ui_map_rows", content)
        self.assertIn("_write_ui_map_rows", content)
        self.assertIn("_unique_filename", content)
        self.assertIn("_clamp_crop_rect", content)
        self.assertIn('existing = next((row for row in rows if row.get("key") == name), None)', content)

    def test_editor_offline_image_paths_do_not_require_device_session(self):
        content = (ROOT / "services/webui/routes/editor.py").read_text(encoding="utf-8")

        locate_start = content.index('async def editor_locate(')
        locate_end = content.index('@router.post("/store-template")', locate_start)
        locate_body = content[locate_start:locate_end]
        self.assertLess(
            locate_body.index("if not text:"),
            locate_body.index('_ensure_editor_mixctrl("locate").screenshot()'),
        )
        self.assertLess(
            locate_body.index("if screenshot is None:"),
            locate_body.index('_ensure_editor_mixctrl("locate").screenshot()'),
        )

        execute_start = content.index('async def editor_execute_code(')
        execute_end = content.index('@router.post("/preview-extract")', execute_start)
        execute_body = content[execute_start:execute_end]
        self.assertIn("if virtual_only and _last_screenshot is not None:", execute_body)
        self.assertIn("_EditorVirtualMixControl(_last_screenshot)", execute_body)

    def test_editor_click_recording_keeps_offset_out_of_target_box(self):
        content = (ROOT / "services/webui/static/js/components/editor/EditorPanel.js").read_text(encoding="utf-8")

        self.assertIn("function buildClickCodeAt(x, y)", content)
        self.assertIn("if (t) {", content)
        self.assertIn("if (useImage.value) return iCode.value;", content)
        self.assertIn("return tCode.value;", content)
        self.assertIn("if (b) return `B(${b.left},${b.top},${b.width},${b.height})`", content)
        self.assertIn("offsetPart = (dx || dy) ? `, offset=(${dx},${dy})` : ''", content)
        self.assertIn("if (tgt.startsWith('B(')) return `click(${tgt})`", content)
        self.assertIn("return `click(${tgt}${offsetPart}, timeout=3)`", content)
        self.assertNotIn(".margin()+(", content)

    def test_editor_custom_executor_supports_grid_templates_validation_and_indent(self):
        frontend = (ROOT / "services/webui/static/js/components/editor/EditorPanel.js").read_text(encoding="utf-8")
        backend = (ROOT / "services/webui/routes/editor.py").read_text(encoding="utf-8")
        api = (ROOT / "AutoScriptor/core/api.py").read_text(encoding="utf-8")

        self.assertIn("counts = extract_info(make_box_grid", frontend)
        self.assertIn("digital=True", frontend)
        self.assertIn("@click=\"validateCustomCode\"", frontend)
        self.assertIn("function onCustomExecKeydown(e)", frontend)
        self.assertIn("if (e.shiftKey)", frontend)
        self.assertIn("line.startsWith('    ')", frontend)

        self.assertIn("from AutoScriptor.utils.box_grid import indexof, make_box_grid", backend)
        self.assertIn('"make_box_grid": make_box_grid', backend)
        self.assertIn('"indexof": indexof', backend)
        self.assertIn('"__import__": _editor_safe_import', backend)
        self.assertIn('return _validate_editor_snippet(data.get("code", ""))', backend)

        self.assertIn("digital: bool | None = None", api)
        self.assertIn("if digital is not None:", api)

    def test_canvas_generated_clicks_are_short_and_swipes_keep_duration(self):
        frontend = (ROOT / "services/webui/static/js/components/canvas/CanvasPanel.js").read_text(encoding="utf-8")
        backend = (ROOT / "services/webui/routes/canvas.py").read_text(encoding="utf-8")

        self.assertIn("{ key: 'timeout',  label: '超时(秒)', type: 'number', default: 3", frontend)
        self.assertIn("parts.push(`timeout=${d.timeout ?? 3}`)", frontend)
        self.assertIn("duration_s=${d.duration_s ?? 1}", frontend)
        self.assertIn("parts.append(f\"timeout={d.get('timeout', 3)}\")", backend)
        self.assertIn("duration_s={dur}", backend)

    def test_editor_save_keeps_template_crop_separate_from_search_box(self):
        backend = (ROOT / "services/webui/routes/editor.py").read_text(encoding="utf-8")
        frontend = (ROOT / "services/webui/static/js/components/editor/EditorPanel.js").read_text(encoding="utf-8")

        self.assertIn("template_left = int(data.get(\"template_left\", left))", backend)
        self.assertIn("cropped = _last_screenshot[template_top:template_bottom, template_left:template_right]", backend)
        self.assertIn("raw_fn = f\"{pinyin_name}@{save_left}#{save_top}#{save_w}#{save_h}.png\"", backend)
        self.assertIn("_is_fullscreen_like_rect", backend)
        self.assertIn("from AutoScriptor.utils.paths import get_assets_dir", backend)
        self.assertIn("assets_root = get_assets_dir()", backend)

        self.assertIn("function templateBox()", frontend)
        self.assertIn("const tb = templateBox();", frontend)
        self.assertIn(
            "template_left: tb.left, template_top: tb.top, template_width: tb.width, template_height: tb.height",
            frontend,
        )

    def test_navigation_waits_use_cancellable_sleep(self):
        for rel in [
            "ZmxyOL/nav/api.py",
            "ZmxyOL/nav/envs/login.py",
            "ZmxyOL/nav/envs/env_trans.py",
            "ZmxyOL/nav/envs/loc_trans.py",
        ]:
            content = (ROOT / rel).read_text(encoding="utf-8")
            self.assertNotIn("time.sleep", content, rel)

    def test_mumu_manager_subprocesses_are_perf_safe(self):
        content = (ROOT / "AutoScriptor/control/MumuAdaptor/utils.py").read_text(encoding="utf-8")
        perf = (ROOT / "AutoScriptor/utils/perf.py").read_text(encoding="utf-8")

        self.assertIn("mumu_safe_subprocess", content)
        self.assertIn("_boost_options", perf)

    def test_mumu_shutdown_does_not_global_taskkill(self):
        content = (ROOT / "AutoScriptor/control/MumuAdaptor/api/core/power.py").read_text(encoding="utf-8")

        self.assertNotIn("[\"taskkill\"", content)
        self.assertNotIn("_force_kill", content)
        self.assertIn("不执行全局", content)


class TestInstallerContract(unittest.TestCase):
    def test_mumu_manager_version_failure_is_warning_when_adb_is_connected(self):
        content = (ROOT / "services/installer/installer.py").read_text(encoding="utf-8")

        self.assertIn("安装器将把 MuMuManager 异常视为警告", content)
        self.assertIn('results["emu_path"]["exists"]', content)
        self.assertIn("_check_configured_adb_device", content)
        self.assertIn('operationReady', content)
        self.assertNotIn('and results["emu_path"]["exists"] and results["emu_path"]["runnable"]', content)

    def test_electron_installer_matches_mumu_manager_fallback_policy(self):
        content = (ROOT / "webapp/mumu-detect.cjs").read_text(encoding="utf-8")
        html = (ROOT / "webapp/renderer/installer.html").read_text(encoding="utf-8")

        self.assertIn('"${emuPath}" version', content)
        self.assertIn("安装器将把 MuMuManager 异常视为警告", content)
        self.assertIn("results.adb_path.runnable", content)
        self.assertIn("checkConfiguredAdbDevice", content)
        self.assertIn("&& results.emu_path.exists", content)
        self.assertNotIn("&& results.emu_path.exists && results.emu_path.runnable", content)
        self.assertIn("const managerRunnable", html)
        self.assertIn("emuAcceptable", html)
        self.assertIn("pv-status warn", html)
        self.assertIn("operationReady", content)
        self.assertIn("启动 MuMu 后请在 WebUI", html)

    def test_packaged_installer_is_transactional_and_preserves_user_data(self):
        installer = (ROOT / "webapp/install-packaged.cjs").read_text(encoding="utf-8")
        main = (ROOT / "webapp/main.js").read_text(encoding="utf-8")
        html = (ROOT / "webapp/renderer/installer.html").read_text(encoding="utf-8")

        for marker in [
            "inspectZip(zipPath)",
            "assertDiskSpace(",
            "verifyBackendDir(stagingDir)",
            "swapBackendDirectory(stagingDir, backendDest, send)",
            "copyPackagedDataPreservingUserFiles",
            "shouldOverwritePackagedData",
            ".backend.new.",
            ".backend.incremental.",
            "彻底卸载造笔.bat",
            "dataRoot: dataDest",
        ]:
            with self.subTest(marker=marker):
                self.assertIn(marker, installer)

        self.assertIn("if (n === 'config.json') return false", installer)
        self.assertIn("if (n.startsWith('accounts/')", installer)
        self.assertIn("if (n.startsWith('custom_task/')", installer)
        self.assertIn("if (n.startsWith('battle_character/')", installer)
        self.assertIn("ProcessId -ne $PID", installer)
        self.assertNotIn("taskkill /F /IM", installer)

        self.assertIn("killStalePort5000([...roots])", main)
        self.assertIn("if ($owned)", main)
        self.assertIn("mode: 'existing'", main)
        self.assertIn("allowManagedExisting: true", main)
        self.assertIn("AUTOSCRIPTOR_DATA_DIR: getRuntimeDataRoot()", main)

        self.assertIn("事务切换", html)
        self.assertIn("保留 <code>config.json</code>", html)

    def test_release_packaging_has_verification_and_optional_signing(self):
        staging = (ROOT / "webapp/electron-builder.staging.config.js").read_text(encoding="utf-8")
        release = (ROOT / "webapp/electron-builder.release.config.js").read_text(encoding="utf-8")
        build = (ROOT / "scripts/build_release.py").read_text(encoding="utf-8")
        prereq = (ROOT / "scripts/verify_packaging_prereqs.py").read_text(encoding="utf-8")
        verify = (ROOT / "webapp/scripts/verify-pack.cjs").read_text(encoding="utf-8")

        for content in [staging, release]:
            self.assertIn("AUTOSCRIPTOR_CODE_SIGN", content)
            self.assertIn("signAndEditExecutable: codeSigningEnabled", content)

        self.assertIn('env.get("AUTOSCRIPTOR_CODE_SIGN") == "1"', build)
        self.assertIn('"verify-pack"', build)
        self.assertIn("打包自检失败", build)
        self.assertIn("leakedMaps", verify)
        self.assertIn("release-update.cjs", verify)
        self.assertIn("assertAsarEntry", verify)
        self.assertIn("validateDataRoot(dataRoot)", verify)
        self.assertIn("packaged data must not contain user account JSON files", verify)
        self.assertIn("backend.zip is missing required runtime files", verify)
        self.assertIn("app.app_to_start", verify)
        self.assertIn("must be generated from config template.json", verify)
        self.assertIn("_check_config_template", prereq)
        self.assertIn("_check_generated_code_templates", prereq)

    def test_packaged_installer_has_dry_run_and_lifecycle_tests(self):
        installer = (ROOT / "webapp/install-packaged.cjs").read_text(encoding="utf-8")
        main = (ROOT / "webapp/main.js").read_text(encoding="utf-8")
        preload = (ROOT / "webapp/preload.js").read_text(encoding="utf-8")
        html = (ROOT / "webapp/renderer/installer.html").read_text(encoding="utf-8")
        package_json = (ROOT / "webapp/package.json").read_text(encoding="utf-8")
        test_script = (ROOT / "webapp/scripts/test-install-packaged.cjs").read_text(encoding="utf-8")

        for marker in [
            "dryRunPackagedInstall",
            "dryRunApplyBackendIncremental",
            "validatePackagedInstallRoot",
            "inspectPackagedRuntimeData",
            "applyConfigDefaultsFromPackagedData",
            "skipMumuConfig",
            "skipRegistry",
        ]:
            with self.subTest(marker=marker):
                self.assertIn(marker, installer)

        dry_handler = main.split("ipcMain.handle('installer:dry-run-packaged'")[1].split("ipcMain.handle('installer:run-packaged'")[0]
        self.assertNotIn("validateInstallDir(", dry_handler)
        self.assertIn("installer:dry-run-packaged", main)
        self.assertIn("installer:dry-run-backend-incremental", main)
        self.assertIn("opts && opts.readOnly", main)
        self.assertIn("dryRunPackagedInstall", preload)
        self.assertIn("dryRunBackendIncremental", preload)
        self.assertIn("btnDryRun", html)
        self.assertIn("runPackagedDryRun", html)
        self.assertIn("readOnly: true", html)
        self.assertIn("Dry run", html)
        self.assertIn('"test:installer"', package_json)

        for marker in [
            "testDryRunAndInvalidTargets",
            "testInstallRepairAndUninstallScript",
            "testIncrementalUpdateAndRollback",
            "parsePowerShellScript",
            "KEEP_INSTALLER_TESTS",
        ]:
            with self.subTest(marker=marker):
                self.assertIn(marker, test_script)


class TestReleaseUpdatePanelContract(unittest.TestCase):
    def test_update_panel_separates_release_manifest_from_source_git(self):
        panel = (ROOT / "services/webui/static/js/components/UpdatePanel.js").read_text(encoding="utf-8")
        main = (ROOT / "webapp/main.js").read_text(encoding="utf-8")
        preload = (ROOT / "webapp/preload.js").read_text(encoding="utf-8")
        release_update = (ROOT / "webapp/release-update.cjs").read_text(encoding="utf-8")
        package_json = (ROOT / "webapp/package.json").read_text(encoding="utf-8")
        prepare = (ROOT / "webapp/scripts/prepare-release-shell.cjs").read_text(encoding="utf-8")
        release_config = (ROOT / "webapp/electron-builder.release.config.js").read_text(encoding="utf-8")

        for marker in [
            "/api/content-update/status",
            "/api/content-update/check",
            "/api/content-update/apply",
            "本地小版本更新包",
            "dryRunPackage",
            "applyPackage",
            "发行版更新",
            "应用内容更新",
            "源码仓库更新",
            "sourceStatus.available === false",
            "/api/update/status",
            "/api/update/check",
            "/api/update/run",
        ]:
            with self.subTest(marker=marker):
                self.assertIn(marker, panel)

        release_section = panel.split('<span class="text-lg font-semibold">发行版更新</span>', 1)[1].split(
            '<span class="text-lg font-semibold">源码仓库更新</span>',
            1,
        )[0]
        self.assertNotIn("/api/update/check", release_section)
        self.assertNotIn("Git 拉取", release_section)
        self.assertIn("用户配置、账号、自定义任务和职业脚本会被保护", release_section)

        for marker in [
            "release-update:dry-run",
            "release-update:apply",
            "stopBackendForUpdate",
            "applyLocalReleaseUpdate",
        ]:
            with self.subTest(marker=marker):
                self.assertIn(marker, main)
        self.assertIn("releaseUpdate", preload)
        self.assertIn("autoscriptor_update_v1", release_update)
        self.assertIn("dryRunLocalReleaseUpdate", release_update)
        self.assertIn("applyLocalReleaseUpdate", release_update)
        self.assertIn("readJsonObjectIfExists", release_update)
        self.assertIn("data/config.json is invalid", release_update)
        self.assertIn("release-update.cjs", prepare)
        self.assertIn("release-update.cjs", release_config)
        self.assertIn('"test:release-update"', package_json)

    def test_minor_update_package_generator_documents_cumulative_engine_updates(self):
        script = (ROOT / "scripts/release/create_minor_update_package.py").read_text(encoding="utf-8")
        docs = (ROOT / "docs/AutoScriptor/release-build-and-run.md").read_text(encoding="utf-8")

        for marker in [
            "autoscriptor_update_v1",
            "minor-cumulative",
            "backend/autoscriptor-engine.exe",
            "--target-version",
            "--include-backend",
            "--copy-if-missing",
        ]:
            with self.subTest(marker=marker):
                self.assertIn(marker, script)
        self.assertIn("1.1.0 -> 1.1.5", docs)
        self.assertIn("AutoScriptor_Update_1.1.5.zip", docs)


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

    def test_git_update_disabled_outside_git_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(sys.modules, autoscriptor_logger_stubs()):
                sys.modules.pop("services.core.updater", None)
                from services.core.updater import Updater

            updater = Updater()
            updater._root = tmp

            status = updater.get_status()

            self.assertFalse(status["available"])
            self.assertEqual(status["state"], "disabled")
            self.assertIn("源码更新不可用", status["last_error"])


class TestZmxyRedeemCollectorContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        module_name = "collect_zmxy_redeem_2026_under_test"
        spec = importlib.util.spec_from_file_location(
            module_name,
            ROOT / "scripts/collect_zmxy_redeem_2026.py",
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        assert spec.loader is not None
        spec.loader.exec_module(module)
        cls.collector = module

    def test_parse_expiry_accepts_range_with_partial_end_date(self):
        text = "兑换码有效时间：2026年5月10日12时----5月12日5时"

        self.assertEqual(
            self.collector.parse_expiry(text, 2026),
            "2026-05-12T05:00:00+08:00",
        )

    def test_parse_expiry_accepts_month_day_cutoff(self):
        text = "兑换码有效时间至9月1日05:00"

        self.assertEqual(
            self.collector.parse_expiry(text, 2026),
            "2026-09-01T05:00:00+08:00",
        )

    def test_extract_codes_covers_official_4399_styles(self):
        samples = "\n".join([
            "祝福奖励：谁言寸草心：莲心*1、青莲炎*1（在“活动”中输入兑换码“谁言寸草心”即可领取福利哦！）",
            "通用兑换码：金炉驱寒气 奖励内容：时装随机礼包",
            "福利码：但愿长闲有诗酒，一溪风月共清明内含：祝福礼包*5",
            "兑换码献上：小小插曲（小月卡（7日）*1）",
        ])

        self.assertEqual(
            self.collector.extract_codes(samples),
            ["谁言寸草心", "金炉驱寒气", "但愿长闲有诗酒，一溪风月共清明", "小小插曲"],
        )

    def test_redeem_codes_use_single_authoritative_file(self):
        content = "\n".join(
            path.read_text(encoding="utf-8", errors="ignore")
            for path in [
                ROOT / "scripts/collect_zmxy_redeem_2026.py",
                ROOT / "services/webui/routes/news.py",
                ROOT / "services/webui/static/js/components/NewsPanel.js",
            ]
        )

        self.assertIn("docs/zmxy_redeem_codes.json", content)
        for old_name in [
            "zmxy_codes.json",
            "zmxy_gift_codes_rows.json",
            "zmxy_redeem_codes_only.txt",
            "zmxy_redeem_codes_only.meta.txt",
            "zmxy_redeem_codes_only_detail.txt",
        ]:
            self.assertNotIn(old_name, content)


if __name__ == "__main__":
    unittest.main()
