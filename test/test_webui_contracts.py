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
import zipfile

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
    paths.is_compiled = lambda: False

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
        scheduler.is_task_due = lambda node, path, now_ts: bool(node.get("on")) and now_ts >= node.get("next_exec_time", 0)
        scheduler.is_human_takeover_blocked = (
            lambda node, now_ts=None: bool(node.get("human_takeover_error"))
            and (now_ts is None or now_ts < node.get("next_exec_time", 0))
        )
        task_state = types.ModuleType("AutoScriptor.utils.task_state")
        task_state.progress_label = lambda value: value if isinstance(value, str) else None
        return {
            "AutoScriptor": types.ModuleType("AutoScriptor"),
            "AutoScriptor.utils": types.ModuleType("AutoScriptor.utils"),
            "AutoScriptor.utils.task_registry": task_registry,
            "AutoScriptor.utils.task_state": task_state,
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

    def test_human_takeover_task_projects_as_error_with_message_before_retry_time(self):
        tasks = {
            "registered": {
                "task": {
                    "on": True,
                    "next_exec_time": 200,
                    "params": {},
                    "human_takeover_error": "验证码弹窗",
                    "human_takeover_at": 123,
                },
            },
        }

        with patch.dict(sys.modules, self._task_registry_stubs({"registered/task"})):
            flat = self.service.flatten_tasks(tasks, now_ts=100)

        self.assertEqual(flat[0]["status"], "error")
        self.assertEqual(flat[0]["human_takeover_error"], "验证码弹窗")

    def test_human_takeover_task_projects_as_pending_after_retry_time(self):
        tasks = {
            "registered": {
                "task": {
                    "on": True,
                    "next_exec_time": 0,
                    "params": {},
                    "human_takeover_error": "验证码弹窗",
                    "human_takeover_at": 123,
                },
            },
        }

        with patch.dict(sys.modules, self._task_registry_stubs({"registered/task"})):
            flat = self.service.flatten_tasks(tasks, now_ts=100)

        self.assertEqual(flat[0]["status"], "pending")
        self.assertEqual(flat[0]["human_takeover_error"], "验证码弹窗")

    def test_task_progress_projects_from_status_tree(self):
        tasks = {
            "registered": {
                "task": {"on": True, "next_exec_time": 0, "params": {}},
            },
        }
        self.module.cfg._config = {
            "status": {"tasks": {"registered/task": {"progress": "5/6"}}}
        }

        with patch.dict(sys.modules, self._task_registry_stubs({"registered/task"})):
            self.service.inject_public_task_fields(tasks)
            flat = self.service.flatten_tasks(tasks, now_ts=100)

        self.assertEqual(tasks["registered"]["task"]["progress_display"], "5/6")
        self.assertEqual(flat[0]["progress_display"], "5/6")

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

    def test_save_runtime_config_normalizes_placeholder_adb_addr(self):
        class FakeConfig:
            def __init__(inner_self):
                inner_self._config = {}

            def __setitem__(inner_self, key, value):
                inner_self._config[key] = value

            def save_config(inner_self):
                self.calls.append("save_config")

        service, cfg = self._service(cfg=FakeConfig())
        payload = {
            "app": {"name": "ZmxyOL"},
            "emulator": {"index": 2, "adb_addr": "YOUR_ADB_ADDR, e.g.127.0.0.1:16384"},
            "ocr": {"use_gpu": False},
        }

        version = service.save_runtime_config(payload)

        self.assertEqual(version, 42)
        self.assertEqual(cfg._config["emulator"]["adb_addr"], "127.0.0.1:16448")
        self.assertEqual(payload["emulator"]["adb_addr"], "YOUR_ADB_ADDR, e.g.127.0.0.1:16384")
        self.assertEqual(self.calls, ["lock", "save_config", "apply_log_level", ("bump", "save config")])

    def test_save_runtime_config_prefers_global_only_persistence(self):
        class FakeConfig:
            def __init__(inner_self):
                inner_self._config = {}

            def __setitem__(inner_self, key, value):
                inner_self._config[key] = value

            def save_global_config(inner_self):
                self.calls.append("save_global_config")

            def save_config(inner_self):
                self.calls.append("save_config")

        service, cfg = self._service(cfg=FakeConfig())
        payload = {
            "app": {"name": "ZmxyOL"},
            "emulator": {"index": 0, "adb_addr": "127.0.0.1:16384"},
            "ocr": {"use_gpu": False},
        }

        version = service.save_runtime_config(payload)

        self.assertEqual(version, 42)
        self.assertEqual(cfg._config["app"], {"name": "ZmxyOL"})
        self.assertEqual(self.calls, ["lock", "save_global_config", "apply_log_level", ("bump", "save config")])

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

    def test_add_account_does_not_fail_when_task_reload_fails(self):
        class FailingTaskManager:
            @contextmanager
            def config_transaction(inner_self):
                self.calls.append("lock")
                yield

            def reload_tasks(inner_self, security_key=None):
                self.calls.append(("reload_tasks", security_key))
                raise RuntimeError("ui map missing")

        cfg = SimpleNamespace(
            add_account=lambda *args: self.calls.append(("add_account",) + args),
            switch_account=lambda name, key: self.calls.append(("switch_account", name, key)),
        )
        service, _cfg = self._service(cfg=cfg, task_manager=FailingTaskManager())

        version = service.add_account("main", "user", "pwd", "s1", "hero", "key")

        self.assertEqual(version, 42)
        self.assertEqual(
            self.calls,
            [
                "lock",
                ("add_account", "main", "user", "pwd", "s1", "hero", "key"),
                ("switch_account", "main", "key"),
                ("reload_tasks", "key"),
                "invalidate_login",
                "read_config",
                ("bump", "add account"),
            ],
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

    def test_clear_decrypted_credentials_keeps_encrypted_account_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            module = import_app_config_for_test(tmp)
            cfg = module.cfg
            cfg.add_account("main", "user", "pwd", "s1", "hero", "key")
            cfg._config["current_account"] = "main"
            cfg.save_config()
            cfg.load_config("key")
            self.assertTrue(cfg.has_decrypted_credentials())
            self.assertTrue(cfg.has_encrypted_credentials())

            cfg.clear_decrypted_credentials()

            self.assertFalse(cfg.has_decrypted_credentials())
            self.assertTrue(cfg.has_encrypted_credentials())
            self.assertNotIn("account", cfg._config["game"])
            self.assertNotIn("password", cfg._config["game"])

            cfg.load_config("key")
            self.assertTrue(cfg.has_decrypted_credentials())

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

    def test_json_persistence_does_not_fsync_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            module = import_app_config_for_test(tmp)
            with patch.dict(os.environ, {"AUTOSCRIPTOR_STRICT_FSYNC": "0"}), \
                    patch.object(module.os, "fsync") as fsync:
                module._atomic_write_json(Path(tmp) / "config.json", {"app": {"name": "ZmxyOL"}})

            fsync.assert_not_called()

    def test_json_persistence_can_enable_strict_fsync(self):
        with tempfile.TemporaryDirectory() as tmp:
            module = import_app_config_for_test(tmp)
            with patch.dict(os.environ, {"AUTOSCRIPTOR_STRICT_FSYNC": "1"}), \
                    patch.object(module.os, "fsync") as fsync:
                module._atomic_write_json(Path(tmp) / "config.json", {"app": {"name": "ZmxyOL"}})

            fsync.assert_called_once()

    def test_global_config_save_does_not_rewrite_account_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            module = import_app_config_for_test(tmp)
            cfg = module.cfg
            cfg.add_account("main", "user", "pwd", "s1", "hero", "key")
            cfg._config["current_account"] = "main"
            cfg.save_global_config()
            cfg.load_config("key")
            calls = []

            with patch.object(module, "_atomic_write_json", side_effect=lambda path, data: calls.append(Path(path).name)):
                cfg._config["app"] = {"name": "ZmxyOL"}
                cfg.save_global_config()

            self.assertEqual(calls, ["config.json"])

    def test_config_save_falls_back_when_atomic_replace_is_denied(self):
        with tempfile.TemporaryDirectory() as tmp:
            module = import_app_config_for_test(tmp)

            with patch.object(module.os, "replace", side_effect=PermissionError("replace denied")):
                module.cfg._config["app"] = {"name": "ZmxyOL"}
                module.cfg.save_config()

            saved = json.loads((Path(tmp) / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["app"]["name"], "ZmxyOL")

    def test_config_load_accepts_utf8_bom(self):
        with tempfile.TemporaryDirectory() as tmp:
            module = import_app_config_for_test(tmp)
            config_path = Path(tmp) / "config.json"
            config_path.write_text(
                json.dumps({"app": {"name": "ZmxyOL"}, "tasks": {}, "current_account": ""}),
                encoding="utf-8-sig",
            )

            module.cfg.load_config()

            self.assertEqual(module.cfg._config["app"]["name"], "ZmxyOL")

    def test_relative_accounts_dir_keeps_data_accounts_compatibility(self):
        with tempfile.TemporaryDirectory() as tmp:
            module = import_app_config_for_test(tmp)
            mgr = module.ConfigManager()
            default_dir = Path(tmp) / "accounts"

            for raw in ("", "accounts", "data/accounts"):
                mgr.global_cfg = {"accounts": {"dir": raw}}
                with self.subTest(raw=raw):
                    self.assertEqual(mgr.resolved_accounts_dir(), default_dir)

    def test_packaged_absolute_accounts_dir_is_migrated_to_data_root(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as legacy:
            legacy_dir = Path(legacy) / "accounts"
            legacy_dir.mkdir()
            (legacy_dir / "old.json").write_text('{"characters": {}}', encoding="utf-8")
            cfg_path = Path(tmp) / "config.json"
            cfg_path.write_text(
                json.dumps({"accounts": {"dir": str(legacy_dir)}, "current_account": ""}),
                encoding="utf-8",
            )
            module = import_app_config_for_test(tmp)

            with patch.dict(os.environ, {"AUTOSCRIPTOR_DATA_DIR": tmp}):
                module.cfg.load_config()

            self.assertEqual(module.cfg._mgr.global_cfg["accounts"]["dir"], "")
            self.assertEqual(module.cfg.ACCOUNTS_DIR, str(Path(tmp) / "accounts"))
            self.assertTrue((Path(tmp) / "accounts" / "old.json").exists())


class TestWebUIFrontendContract(unittest.TestCase):
    JS_FILES = [
        ROOT / "services/webui/static/js/core/api.js",
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
        self.assertIn("params.set('require_app', 'false')", content)
        self.assertIn("device_overall", content)
        self.assertIn("task_overall", content)
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
            "/api/accounts/add",
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

    def test_http_middlewares_do_not_wrap_request_body_with_base_http_middleware(self):
        content = (ROOT / "services/webui/server.py").read_text(encoding="utf-8")

        self.assertNotIn('@app.middleware("http")', content)
        self.assertNotIn("BaseHTTPMiddleware", content)
        self.assertIn("class _AuthAndApiErrorMiddleware", content)
        self.assertIn("class _StaticCacheHeadersMiddleware", content)
        self.assertIn("app.add_middleware(_AuthAndApiErrorMiddleware)", content)

    def test_accounts_add_uses_standard_api_response(self):
        content = (ROOT / "services/webui/server.py").read_text(encoding="utf-8")
        start = content.index("async def accounts_add_api")
        end = content.index("@app.post(\"/api/accounts/delete\")", start)
        body = content[start:end]

        self.assertIn("api_ok(", body)
        self.assertIn("return api_error(400", body)
        self.assertIn("500,", body)
        self.assertIn("diagnostics=_persistence_diagnostics()", body)
        self.assertIn("_attach_credential_unlock_cookie", body)
        self.assertIn('credential={"unlocked"', body)

    def test_accounts_add_switches_to_created_account(self):
        content = (ROOT / "services/webui/lifecycle_service.py").read_text(encoding="utf-8")
        start = content.index("    def add_account(")
        end = content.index("    def delete_account", start)
        body = content[start:end]

        self.assertIn("self.cfg.add_account", body)
        self.assertIn("self.cfg.switch_account(name, security_key)", body)
        self.assertIn("self.task_manager.reload_tasks(security_key)", body)
        self.assertIn("self.scheduler.invalidate_login()", body)

    def test_frontend_api_error_message_accepts_fastapi_detail(self):
        content = (ROOT / "services/webui/static/js/core/api.js").read_text(encoding="utf-8")

        self.assertIn("data.detail", content)
        self.assertIn("JSON.stringify(data.detail)", content)
        self.assertIn("HTTP ${res.status}", content)
        self.assertIn("rawText", content)
        self.assertIn("${path}", content)

    def test_persistence_errors_include_runtime_paths(self):
        content = (ROOT / "services/webui/server.py").read_text(encoding="utf-8")

        self.assertIn("def _persistence_diagnostics()", content)
        self.assertIn("config_path", content)
        self.assertIn("accounts_dir", content)
        self.assertIn("dataRoot=", content)
        self.assertIn("diagnostics=_persistence_diagnostics()", content)
        self.assertIn("unhandled_api_error", content)
        self.assertIn("保存任务失败", content)

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
        self.assertIn("launch_app: bool = True", runtime_context)
        self.assertIn("launch_app=launch_app", runtime_context)
        self.assertIn("launch_app=False", (ROOT / "services/webui/routes/editor.py").read_text(encoding="utf-8"))
        self.assertIn("cancel_check=cancel_check", runtime_context)
        self.assertIn("runtime_ctx.refresh(cancel_check=self._check_cancel_requested)", scheduler)
        self.assertIn("_reload_deferred", scheduler)
        self.assertIn("_handle_watched_config_change", scheduler)
        self.assertIn("join_with_cancel", api)
        self.assertIn("sleep_with_cancel", api)
        self.assertIn("intervals = [1, 2, 3, 3, 3, 3, 3, 3]", api)
        self.assertIn("join_with_cancel(t, 3, cancel_check)", api)
        self.assertNotIn("join_with_cancel(t, 5, cancel_check)", api)

    def test_electron_startup_reports_stages_before_backend_ready(self):
        main = (ROOT / "webapp/main.js").read_text(encoding="utf-8")
        loading = (ROOT / "webapp/renderer/loading.html").read_text(encoding="utf-8")
        gui = (ROOT / "gui.py").read_text(encoding="utf-8")

        for marker in [
            "function reportStartupStep",
            "startupTimers",
            "sendToRenderer('log', line)",
            "checking-port",
            "starting-python",
            "backend-spawned",
            "waiting-webui",
            "setTimeout(() => {",
        ]:
            with self.subTest(marker=marker):
                self.assertIn(marker, main)
        self.assertLess(
            main.index("createMainWindow();"),
            main.index("killStalePort5000();", main.index("createMainWindow();")),
        )
        self.assertIn("statusTextMap", loading)
        self.assertIn("'backend-spawned': 'Python 进程已启动，正在导入依赖...'", loading)
        self.assertIn("def _boot_log", gui)
        self.assertIn("正在导入 WebUI 服务模块", gui)
        self.assertIn("WebUI 子进程已启动", gui)

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
        core_init = (ROOT / "AutoScriptor/core/__init__.py").read_text(encoding="utf-8")
        mumu_init = (ROOT / "AutoScriptor/control/MumuAdaptor/__init__.py").read_text(encoding="utf-8")
        server = (ROOT / "services/webui/server.py").read_text(encoding="utf-8")
        task_manager = (ROOT / "services/core/task_manager.py").read_text(encoding="utf-8")

        self.assertIn("def __getattr__", package_init)
        self.assertIn("def __getattr__", core_init)
        self.assertIn("def __getattr__", mumu_init)
        self.assertNotIn("from AutoScriptor.core import *", package_init)
        self.assertNotIn("from AutoScriptor.core.api import *", core_init)
        self.assertNotIn("from AutoScriptor import *", server)
        self.assertNotIn("from AutoScriptor import *", task_manager)
        self.assertNotIn("from ZmxyOL import *", task_manager)
        self.assertNotIn("from .mumu import Mumu", mumu_init)
        self.assertNotIn("from .api import *", mumu_init)

    def test_webui_server_import_does_not_import_ocr_runtime(self):
        code = r'''
import builtins
import sys

orig = builtins.__import__
blocked = {"paddle", "paddleocr"}

def guard(name, globals=None, locals=None, fromlist=(), level=0):
    if name.split(".")[0] in blocked:
        raise RuntimeError("blocked import " + name)
    return orig(name, globals, locals, fromlist, level)

builtins.__import__ = guard
import services.webui.server
assert "paddle" not in sys.modules
assert "paddleocr" not in sys.modules
print("OK")
'''
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", "-c", code],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("OK", proc.stdout)

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
            "resolveRuntimeDataRoot(rootResolved, userDataPath)",
        ]:
            with self.subTest(marker=marker):
                self.assertIn(marker, installer)

        self.assertIn("if (n === 'config.json') return false", installer)
        self.assertIn("if (n.startsWith('accounts/')", installer)
        self.assertIn("if (n.startsWith('custom_task/')", installer)
        self.assertIn("if (n.startsWith('battle_character/')", installer)
        self.assertIn("ProcessId -ne $PID", installer)
        self.assertIn("ZaoBiUninstall-", installer)
        self.assertIn("registryKey", installer)
        self.assertIn("New-ItemProperty -LiteralPath $key", installer)
        self.assertIn("Set-RegDword 'EstimatedSize'", installer)
        self.assertIn("Set-RegDword 'NoModify' 1", installer)
        self.assertNotIn("Set-ItemProperty -LiteralPath $key -Name DisplayName", installer)
        self.assertNotIn("path.join(rootResolved, 'config.json')", installer)
        self.assertNotIn("taskkill /F /IM", installer)

        self.assertIn("killStalePort5000([...roots])", main)
        self.assertIn("getDefaultInstallRoot()", main)
        self.assertIn("process.env.LOCALAPPDATA", main)
        self.assertNotIn("path.join(app.getPath('documents'), 'AutoScriptor')", main)
        self.assertIn("if ($owned)", main)
        self.assertIn("mode: 'existing'", main)
        self.assertIn("allowManagedExisting: true", main)
        self.assertIn("AUTOSCRIPTOR_DATA_DIR: dataRoot", main)
        self.assertIn("getUserDataRuntimeDataRoot()", main)
        self.assertIn("updateInstallJsonDataRoot(fallback)", main)

        self.assertIn("事务切换", html)
        self.assertIn("保留 <code>config.json</code>", html)

    def test_release_packaging_has_verification_and_optional_signing(self):
        staging = (ROOT / "webapp/electron-builder.staging.config.js").read_text(encoding="utf-8")
        release = (ROOT / "webapp/electron-builder.release.config.js").read_text(encoding="utf-8")
        build = (ROOT / "scripts/build_release.py").read_text(encoding="utf-8")
        gui = (ROOT / "gui.py").read_text(encoding="utf-8")
        prereq = (ROOT / "scripts/verify_packaging_prereqs.py").read_text(encoding="utf-8")
        verify = (ROOT / "webapp/scripts/verify-pack.cjs").read_text(encoding="utf-8")
        spec = importlib.util.spec_from_file_location(
            "build_release_contract",
            ROOT / "scripts/build_release.py",
        )
        build_module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(build_module)

        for content in [staging, release]:
            self.assertIn("AUTOSCRIPTOR_CODE_SIGN", content)
            self.assertIn("signAndEditExecutable: codeSigningEnabled", content)

        self.assertIn('env.get("AUTOSCRIPTOR_CODE_SIGN") == "1"', build)
        self.assertIn("validate_engine_runtime", build)
        self.assertIn("--runtime-import-smoke", build)
        self.assertIn("--no-deployment-flag=self-execution", build)
        self.assertIn("--skip-engine-smoke", build)
        self.assertIn("resolve_runtime_stdlib", build)
        self.assertIn("def get_release_version()", build)
        self.assertIn('f"--file-version={get_release_version()}"', build)
        self.assertIn("write_nuitka_source_stdlib_runner", build)
        self.assertIn("run_nuitka_with_source_stdlib.py", build)
        self.assertIn("source-stdlib-overlay", build)
        self.assertIn("shutil.copytree(stdlib / \"collections\"", build)
        self.assertIn("shutil.copytree(stdlib / \"ctypes\"", build)
        self.assertIn("shutil.copy2(stdlib / \"_collections_abc.py\"", build)
        for stdlib_shell in [
            '"--include-module=_collections"',
            '"--include-module=wave"',
            '"--include-package=http"',
            '"--include-package=email"',
            '"--include-package=html"',
            '"--include-package=urllib"',
            '"--include-package=xml"',
            '"--include-package=xmlrpc"',
            '"--include-package=logging"',
            '"--include-package=asyncio"',
            '"--include-package=concurrent"',
            '"--include-package=json"',
            '"--include-package=unittest"',
            '"--include-package=pydoc_data"',
            '"--include-package=wsgiref"',
        ]:
            self.assertNotIn(stdlib_shell, build)
        self.assertIn("_STDLIB_RUNTIME_NOFOLLOW", build)
        self.assertNotIn("collections", build_module._STDLIB_RUNTIME_NOFOLLOW)
        self.assertNotIn("collections.abc", build_module._STDLIB_RUNTIME_NOFOLLOW)
        self.assertNotIn("_collections_abc", build_module._STDLIB_RUNTIME_NOFOLLOW)
        self.assertNotIn("ctypes", build_module._STDLIB_RUNTIME_NOFOLLOW)
        self.assertNotIn("multiprocessing", build_module._STDLIB_RUNTIME_NOFOLLOW)
        self.assertIn("_STDLIB_RUNTIME_POST_COPY_ONLY", build)
        self.assertIn("multiprocessing", build_module._STDLIB_RUNTIME_POST_COPY_ONLY)
        self.assertIn("_STDLIB_COMPILE_WITH_SOURCE", build)
        self.assertIn("collections", build_module._STDLIB_COMPILE_WITH_SOURCE)
        self.assertIn("_collections_abc", build_module._STDLIB_COMPILE_WITH_SOURCE)
        self.assertIn("ctypes", build_module._STDLIB_COMPILE_WITH_SOURCE)
        self.assertIn("resolve_compile_stdlib_source", build)
        self.assertIn("AUTOSCRIPTOR_STDLIB_SOURCE", build)
        self.assertIn('"--include-package=collections"', build)
        self.assertIn('"--include-module=_collections_abc"', build)
        self.assertIn('"--include-package=ctypes"', build)
        self.assertIn('"--include-module=_ctypes"', build)
        self.assertIn('"--include-module=select"', build)
        self.assertIn("copy_stdlib_extension_modules", build)
        self.assertIn("select.pyd", build)
        self.assertIn("_ctypes.pyd", build)
        self.assertIn("_overlapped.pyd", build)
        self.assertIn("_ssl.pyd", build)
        self.assertIn("pyexpat.pyd", build)
        self.assertIn("libssl-1_1.dll", build)
        self.assertIn("libcrypto-1_1.dll", build)
        self.assertIn("libffi-7.dll", build)
        self.assertIn("sqlite3.dll", build)
        self.assertIn("source-stdlib runner", build)
        self.assertIn("larger stdlib surfaces remain nofollow+post-copy", build)
        for stdlib_name in [
            "contextlib",
            "inspect",
            "ast",
            "argparse",
            "json",
            "logging",
            "asyncio",
            "concurrent",
            "email",
            "html",
            "http",
            "urllib",
            "xml",
            "xmlrpc",
            "unittest",
            "pydoc",
            "pydoc_data",
            "wave",
            "wsgiref",
        ]:
            self.assertIn(f'"{stdlib_name}"', build)
        self.assertIn('"multiprocessing"', build)
        self.assertIn("copy_stdlib_runtime_helpers", build)
        self.assertIn("real CPython source", build)
        self.assertIn("_bootstrap_packaged_stdlib", gui)
        self.assertIn("_bootstrap_packaged_importlib", gui)
        self.assertIn("_bootstrap_packaged_encodings", gui)
        self.assertIn("_bootstrap_packaged_multiprocessing", gui)
        self.assertIn("_patch_packaged_typing_protocol_allowlist", gui)
        self.assertIn("importlib._abc", gui)
        self.assertIn("importlib._common", gui)
        self.assertIn("importlib.readers", gui)
        self.assertIn("importlib.metadata._adapters", gui)
        self.assertIn("importlib.metadata._collections", gui)
        self.assertIn("_PACKAGED_STDLIB_SPEC_FROM_FILE_LOCATION", gui)
        self.assertIn("_PACKAGED_STDLIB_MODULE_FROM_SPEC", gui)
        self.assertIn("_PACKAGED_STDLIB_SOURCE_FILE_LOADER", gui)
        self.assertIn("_PACKAGED_STDLIB_MODULE_SPEC", gui)
        self.assertIn("_frozen_importlib_external", gui)
        self.assertIn("_packaged_stdlib_module_from_source_loader", gui)
        self.assertIn("_preload_packaged_importlib_metadata_helpers", gui)
        self.assertIn("_PACKAGED_IMPORTLIB_METADATA_HELPERS", gui)
        self.assertIn("\"_functools\"", gui)
        self.assertIn("\"_adapters\"", gui)
        self.assertIn("\"_meta\"", gui)
        self.assertIn("spec_from_file_location", gui)
        self.assertIn("module_from_spec", gui)
        self.assertIn("submodule_search_locations", gui)
        self.assertIn("loader.exec_module(module)", gui)
        load_helper = gui[
            gui.index("def _load_packaged_stdlib_module"):
            gui.index("def _drop_broken_package_shell")
        ]
        self.assertNotIn("from importlib.util import", load_helper)
        self.assertIn("[package_dir, *spec_paths]", gui)
        self.assertIn("sys.modules.pop(name, None)", gui)
        self.assertIn("delattr(parent, child_name)", gui)
        self.assertIn("_drop_broken_package_shell", gui)
        self.assertIn("multiprocessing", gui)
        self.assertIn("_load_packaged_stdlib_module", gui)
        self.assertIn("collections_deque", gui)
        self.assertIn('"verify-pack"', build)
        self.assertIn("打包自检失败", build)
        self.assertIn("leakedMaps", verify)
        self.assertIn("allowedNodeModulePayloads", verify)
        self.assertIn("app.asar package.json must not include devDependencies", verify)
        self.assertIn("app.asar contains unexpected npm packages", verify)
        self.assertIn("win-unpacked contains unpacked npm payloads", verify)
        self.assertIn("release-update.cjs", verify)
        self.assertIn("assertAsarEntry", verify)
        self.assertIn("validateDataRoot(dataRoot)", verify)
        self.assertIn("packaged data must not contain user account JSON files", verify)
        self.assertIn("backend.zip is missing required runtime files", verify)
        self.assertIn("prune_release_only_test_fixtures", build)
        self.assertIn("Crypto\") / \"SelfTest", build)
        self.assertIn("app.app_to_start", verify)
        self.assertIn("must be generated from config template.json", verify)
        self.assertIn("_extract_embedded_stdlib_zip", build)
        self.assertIn("python zip", build)
        self.assertIn("wave.pyc", build)
        self.assertIn("_check_config_template", prereq)
        self.assertIn("_check_generated_code_templates", prereq)

    def test_packaged_importlib_bootstrap_falls_back_when_util_helpers_are_missing(self):
        import importlib
        import shutil

        module_name = "gui_importlib_bootstrap_under_test"
        spec = importlib.util.spec_from_file_location(module_name, ROOT / "gui.py")
        module = importlib.util.module_from_spec(spec)
        old_argv = sys.argv[:]
        sys.argv = [str(ROOT / "gui.py")]
        try:
            assert spec.loader is not None
            spec.loader.exec_module(module)
        finally:
            sys.argv = old_argv

        importlib_candidates = [
            Path(os.environ.get("AUTOSCRIPTOR_STDLIB_SOURCE", "")) / "importlib",
            ROOT / ".python310-source" / "Lib" / "importlib",
            ROOT / ".python310" / "Lib" / "importlib",
            Path(sys.base_prefix) / "Lib" / "importlib",
        ]
        lab_cache = Path(os.environ.get("AUTOSCRIPTOR_RELEASE_LAB_CACHE", r"C:\AutoScriptorReleaseLab\cache"))
        if lab_cache.is_dir():
            importlib_candidates.extend(
                lib / "importlib"
                for lib in sorted(lab_cache.glob("python310-nuget-*/tools/Lib"), reverse=True)
            )
        required_importlib_files = ["_abc.py", "abc.py", "_adapters.py", "_common.py", "readers.py", "resources.py"]
        importlib_dir = next(
            (
                candidate
                for candidate in importlib_candidates
                if candidate.is_dir()
                and all((candidate / filename).is_file() for filename in required_importlib_files)
                and (candidate / "metadata" / "__init__.py").is_file()
            ),
            None,
        )
        self.assertIsNotNone(importlib_dir)
        names_to_restore = {
            "importlib._abc",
            "importlib.abc",
            "importlib._adapters",
            "importlib._common",
            "importlib.readers",
            "importlib.resources",
            "importlib.metadata",
            "importlib.metadata._adapters",
            "importlib.metadata._collections",
            "importlib.metadata._functools",
            "importlib.metadata._itertools",
            "importlib.metadata._meta",
            "importlib.metadata._text",
        }
        sentinel = object()
        saved_modules = {name: sys.modules.get(name, sentinel) for name in names_to_restore}
        saved_attrs = {name.rpartition(".")[2]: getattr(importlib, name.rpartition(".")[2], sentinel) for name in names_to_restore}
        saved_path = list(getattr(importlib, "__path__", []) or [])
        saved_locations = list(getattr(importlib.__spec__, "submodule_search_locations", []) or [])

        with tempfile.TemporaryDirectory() as tmp:
            package_dir = Path(tmp) / "importlib"
            package_dir.mkdir()
            for filename in required_importlib_files:
                shutil.copy2(importlib_dir / filename, package_dir / filename)
            shutil.copytree(importlib_dir / "metadata", package_dir / "metadata")

            try:
                module._PACKAGED_STDLIB_MODULE_FROM_SPEC = None
                module._PACKAGED_STDLIB_SPEC_FROM_FILE_LOCATION = None
                for name in names_to_restore:
                    sys.modules.pop(name, None)
                for attr in saved_attrs:
                    if hasattr(importlib, attr):
                        try:
                            delattr(importlib, attr)
                        except Exception:
                            pass

                module._bootstrap_packaged_importlib(tmp)

                self.assertIn("importlib._abc", sys.modules)
                self.assertIn("importlib.readers", sys.modules)
                metadata = sys.modules.get("importlib.metadata")
                self.assertIsNotNone(metadata)
                for helper in module._PACKAGED_IMPORTLIB_METADATA_HELPERS:
                    self.assertIn(f"importlib.metadata.{helper}", sys.modules)
                self.assertTrue(hasattr(metadata, "version"))
                self.assertTrue(hasattr(metadata, "distributions"))
                self.assertTrue(hasattr(metadata, "EntryPoints"))
            finally:
                for name in [key for key in sys.modules if key.startswith("importlib.metadata")]:
                    sys.modules.pop(name, None)
                for name in names_to_restore:
                    saved = saved_modules[name]
                    if saved is sentinel:
                        sys.modules.pop(name, None)
                    else:
                        sys.modules[name] = saved
                for attr, saved in saved_attrs.items():
                    if saved is sentinel:
                        if hasattr(importlib, attr):
                            try:
                                delattr(importlib, attr)
                            except Exception:
                                pass
                    else:
                        setattr(importlib, attr, saved)
                importlib.__path__ = saved_path
                importlib.__spec__.submodule_search_locations = saved_locations

    def test_packaged_bootstrap_loads_copied_multiprocessing_package(self):
        module_name = "gui_multiprocessing_bootstrap_under_test"
        spec = importlib.util.spec_from_file_location(module_name, ROOT / "gui.py")
        module = importlib.util.module_from_spec(spec)
        old_argv = sys.argv[:]
        sys.argv = [str(ROOT / "gui.py")]
        try:
            assert spec.loader is not None
            spec.loader.exec_module(module)
        finally:
            sys.argv = old_argv

        saved_modules = {
            name: value
            for name, value in sys.modules.items()
            if name == "multiprocessing" or name.startswith("multiprocessing.")
        }
        with tempfile.TemporaryDirectory() as tmp:
            package_dir = Path(tmp) / "multiprocessing"
            package_dir.mkdir()
            (package_dir / "__init__.py").write_text(
                "INIT_EXECUTED = True\nraise RuntimeError('init should not execute during bootstrap')\n",
                encoding="utf-8",
            )
            (package_dir / "context.py").write_text(
                "IN_PROGRESS = True\n"
                "from . import process\n"
                "from . import reduction\n"
                "class SpawnProcess(process.Process):\n"
                "    @staticmethod\n"
                "    def _Popen(process_obj):\n"
                "        from .popen_spawn_win32 import Popen\n"
                "        return Popen(process_obj)\n"
                "class DefaultContext:\n"
                "    Process = SpawnProcess\n"
                "    def Event(self):\n"
                "        from . import synchronize\n"
                "        return synchronize.Event()\n"
                "    def Manager(self):\n"
                "        return 'manager'\n"
                "    def freeze_support(self):\n"
                "        return 'freeze'\n"
                "    def allow_connection_pickling(self):\n"
                "        from . import connection\n"
                "        return connection.READY\n"
                "    AuthenticationError = RuntimeError\n"
                "    BufferTooShort = BufferError\n"
                "_default_context = DefaultContext()\n",
                encoding="utf-8",
            )
            (package_dir / "process.py").write_text(
                "class Process:\n"
                "    def start(self):\n"
                "        self._popen = self._Popen(self)\n"
                "        return self._popen\n"
                "class Event: pass\n",
                encoding="utf-8",
            )
            (package_dir / "util.py").write_text(
                "from . import process\nSAW_PROCESS = process.Process\n"
                "def register_after_fork(*args):\n"
                "    return 'registered'\n",
                encoding="utf-8",
            )
            (package_dir / "reduction.py").write_text(
                "from . import context\nSAW_CONTEXT = context.IN_PROGRESS\n",
                encoding="utf-8",
            )
            (package_dir / "connection.py").write_text(
                "from . import util, AuthenticationError, BufferTooShort\n"
                "from .context import reduction\n"
                "READY = bool(util.SAW_PROCESS and AuthenticationError and BufferTooShort and reduction.SAW_CONTEXT)\n",
                encoding="utf-8",
            )
            (package_dir / "synchronize.py").write_text(
                "from . import context, process, util\n"
                "class Event:\n"
                "    def __init__(self):\n"
                "        self.ready = context.IN_PROGRESS and process.Process and util.SAW_PROCESS\n",
                encoding="utf-8",
            )
            (package_dir / "spawn.py").write_text(
                "from . import util\nSAW_UTIL = util.SAW_PROCESS\n",
                encoding="utf-8",
            )
            (package_dir / "popen_spawn_win32.py").write_text(
                "from . import reduction, spawn, util\n"
                "class Popen:\n"
                "    def __init__(self, process_obj):\n"
                "        self.ready = reduction.SAW_CONTEXT and spawn.SAW_UTIL and util.SAW_PROCESS\n",
                encoding="utf-8",
            )
            class BlockAutomaticProcessImport:
                def find_spec(self, fullname, path=None, target=None):
                    blocked = {
                        "multiprocessing.connection",
                        "multiprocessing.popen_spawn_win32",
                        "multiprocessing.process",
                        "multiprocessing.spawn",
                        "multiprocessing.synchronize",
                        "multiprocessing.util",
                    }
                    if fullname in blocked and fullname not in sys.modules:
                        raise ImportError(f"compiled runtime did not resolve {fullname} automatically")
                    return None

            blocker = BlockAutomaticProcessImport()
            try:
                for name in list(sys.modules):
                    if name == "multiprocessing" or name.startswith("multiprocessing."):
                        sys.modules.pop(name, None)
                stale_pkg = types.ModuleType("multiprocessing")
                stale_pkg.__file__ = "stale"
                stale_context = types.ModuleType("multiprocessing.context")
                sys.modules["multiprocessing"] = stale_pkg
                sys.modules["multiprocessing.context"] = stale_context
                sys.meta_path.insert(0, blocker)

                module._bootstrap_packaged_multiprocessing(tmp)

                loaded = sys.modules.get("multiprocessing")
                self.assertIsNotNone(loaded)
                self.assertEqual(Path(loaded.__file__).name, "__init__.py")
                self.assertTrue(hasattr(loaded, "Manager"))
                self.assertTrue(hasattr(loaded, "Process"))
                self.assertTrue(hasattr(loaded, "Event"))
                self.assertFalse(hasattr(loaded, "INIT_EXECUTED"))
                self.assertEqual(loaded.Manager(), "manager")
                self.assertEqual(loaded.freeze_support(), "freeze")
                self.assertIs(sys.modules.get("multiprocessing.process"), loaded.process)
                self.assertIs(sys.modules.get("multiprocessing.spawn"), loaded.spawn)
                self.assertIs(sys.modules.get("multiprocessing.synchronize"), loaded.synchronize)
                self.assertIs(sys.modules.get("multiprocessing.connection"), loaded.connection)
                self.assertIs(sys.modules.get("multiprocessing.util"), loaded.util)
                self.assertTrue(loaded.Event().ready)
                self.assertTrue(loaded.Process().start().ready)
                self.assertTrue(loaded.allow_connection_pickling())
                from multiprocessing.util import register_after_fork

                self.assertEqual(register_after_fork(), "registered")
                self.assertIsNot(sys.modules.get("multiprocessing.context"), stale_context)
                self.assertIs(sys.modules.get("multiprocessing.context"), loaded.context)
                self.assertIs(sys.modules.get("multiprocessing.popen_spawn_win32"), loaded.popen_spawn_win32)
                reduction = sys.modules.get("multiprocessing.reduction")
                self.assertIsNotNone(reduction)
                self.assertTrue(getattr(reduction, "SAW_CONTEXT", False))
            finally:
                if blocker in sys.meta_path:
                    sys.meta_path.remove(blocker)
                for name in list(sys.modules):
                    if name == "multiprocessing" or name.startswith("multiprocessing."):
                        sys.modules.pop(name, None)
                sys.modules.update(saved_modules)

    def test_packaged_bootstrap_mounts_copied_encodings_idna(self):
        module_name = "gui_encodings_bootstrap_under_test"
        spec = importlib.util.spec_from_file_location(module_name, ROOT / "gui.py")
        module = importlib.util.module_from_spec(spec)
        old_argv = sys.argv[:]
        sys.argv = [str(ROOT / "gui.py")]
        try:
            assert spec.loader is not None
            spec.loader.exec_module(module)
        finally:
            sys.argv = old_argv

        import encodings

        saved_idna = sys.modules.get("encodings.idna")
        saved_path = list(getattr(encodings, "__path__", []) or [])
        saved_locations = list(getattr(encodings.__spec__, "submodule_search_locations", []) or [])
        with tempfile.TemporaryDirectory() as tmp:
            package_dir = Path(tmp) / "encodings"
            package_dir.mkdir()
            (package_dir / "idna.py").write_text("COPIED_IDNA = True\n", encoding="utf-8")
            try:
                sys.modules.pop("encodings.idna", None)
                encodings.__path__ = []
                encodings.__spec__.submodule_search_locations = []

                module._bootstrap_packaged_encodings(tmp)
                import encodings.idna as idna

                self.assertTrue(idna.COPIED_IDNA)
                self.assertIn(str(package_dir), list(encodings.__path__))
            finally:
                sys.modules.pop("encodings.idna", None)
                if saved_idna is not None:
                    sys.modules["encodings.idna"] = saved_idna
                    setattr(encodings, "idna", saved_idna)
                elif hasattr(encodings, "idna"):
                    delattr(encodings, "idna")
                encodings.__path__ = saved_path
                encodings.__spec__.submodule_search_locations = saved_locations

    def test_packaged_typing_allowlist_accepts_collections_abc_source_names(self):
        import typing

        module_name = "gui_typing_bootstrap_under_test"
        spec = importlib.util.spec_from_file_location(module_name, ROOT / "gui.py")
        module = importlib.util.module_from_spec(spec)
        old_argv = sys.argv[:]
        sys.argv = [str(ROOT / "gui.py")]
        try:
            assert spec.loader is not None
            spec.loader.exec_module(module)
        finally:
            sys.argv = old_argv

        allowlist = typing._PROTO_ALLOWLIST
        saved_collections = list(allowlist.get("collections.abc", []))
        saved_private = allowlist.get("_collections_abc")
        try:
            allowlist["collections.abc"] = []
            allowlist.pop("_collections_abc", None)

            module._patch_packaged_typing_protocol_allowlist()

            for module_key in ("collections.abc", "_collections_abc"):
                with self.subTest(module_key=module_key):
                    self.assertIn("Awaitable", allowlist[module_key])
                    self.assertIn("AsyncContextManager", allowlist[module_key])
        finally:
            allowlist["collections.abc"] = saved_collections
            if saved_private is None:
                allowlist.pop("_collections_abc", None)
            else:
                allowlist["_collections_abc"] = saved_private

    def test_release_build_accepts_embedded_python_pyc_stdlib(self):
        spec = importlib.util.spec_from_file_location(
            "build_release_under_test",
            ROOT / "scripts/build_release.py",
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            fake_home = tmp_root / "python-home"
            fake_home.mkdir()
            for name in [*module.STDLIB_WINDOWS_EXTENSION_FILES, *module.STDLIB_WINDOWS_DLL_FILES]:
                (fake_home / name).write_bytes(name.encode("ascii"))
            with zipfile.ZipFile(fake_home / "python310.zip", "w") as zf:
                for name in [
                    "collections/__init__.pyc",
                    "distutils/__init__.pyc",
                    "encodings/__init__.pyc",
                    "_collections_abc.pyc",
                    "contextlib.pyc",
                    "site.pyc",
                    "pydoc.pyc",
                    "unittest/__init__.pyc",
                    "multiprocessing/__init__.pyc",
                    "wave.pyc",
                ]:
                    zf.writestr(name, b"\0\0\0\0")

            out_dir = tmp_root / "dist" / "gui.dist"
            out_dir.mkdir(parents=True)
            (out_dir / "python310.dll").write_bytes(b"")

            with patch.object(module, "PROJECT_ROOT", tmp_root), \
                    patch.object(module, "NUITKA_OUT", out_dir), \
                    patch.object(module, "NUITKA_USER_CACHE", tmp_root / ".nuitka-cache"), \
                    patch.object(module, "_stdlib_source_candidates", lambda: []), \
                    patch.object(module, "_venv_home_from_cfg", lambda: fake_home), \
                    patch.object(module, "_python_home_version", lambda _home: (3, 10)), \
                    patch.object(module.sysconfig, "get_path", lambda _name: str(tmp_root / "missing-lib")), \
                    patch.object(module.sys, "base_prefix", str(tmp_root / "missing-base")), \
                    patch.object(module.sys, "executable", str(tmp_root / "Scripts" / "python.exe")):
                stdlib = module.resolve_runtime_stdlib(("distutils", "site.py", "pydoc.py", "unittest", "wave.py"))
                self.assertTrue((stdlib / "site.pyc").is_file())
                self.assertTrue(module._stdlib_entry_exists(stdlib, "wave.py"))

                module.copy_stdlib_distutils()
                module.copy_stdlib_wave()
                module.copy_stdlib_runtime_helpers()
                module.copy_stdlib_extension_modules()

            self.assertTrue((out_dir / "distutils" / "__init__.pyc").is_file())
            self.assertTrue((out_dir / "collections" / "__init__.pyc").is_file())
            self.assertTrue((out_dir / "_collections_abc.pyc").is_file())
            self.assertTrue((out_dir / "contextlib.pyc").is_file())
            self.assertTrue((out_dir / "multiprocessing" / "__init__.pyc").is_file())
            self.assertTrue((out_dir / "wave.pyc").is_file())
            self.assertTrue((out_dir / "site.pyc").is_file())
            if os.name == "nt":
                for name in [*module.STDLIB_WINDOWS_EXTENSION_FILES, *module.STDLIB_WINDOWS_DLL_FILES]:
                    self.assertTrue((out_dir / name).is_file())

    def test_release_build_prefers_source_stdlib_for_nuitka_collections(self):
        spec = importlib.util.spec_from_file_location(
            "build_release_source_stdlib_test",
            ROOT / "scripts/build_release.py",
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            source_lib = tmp_root / "python-source" / "Lib"
            (source_lib / "collections").mkdir(parents=True)
            (source_lib / "collections" / "__init__.py").write_text("# collections\n", encoding="utf-8")
            (source_lib / "ctypes").mkdir()
            (source_lib / "ctypes" / "__init__.py").write_text("# ctypes\n", encoding="utf-8")
            for name in ["_collections_abc.py", "contextlib.py", "inspect.py", "site.py", "pydoc.py", "wave.py"]:
                (source_lib / name).write_text("# stdlib\n", encoding="utf-8")
            (source_lib / "distutils").mkdir()
            (source_lib / "distutils" / "__init__.py").write_text("# distutils\n", encoding="utf-8")
            (source_lib / "unittest").mkdir()
            (source_lib / "unittest" / "__init__.py").write_text("# unittest\n", encoding="utf-8")

            with patch.dict(
                os.environ,
                {
                    "AUTOSCRIPTOR_STDLIB_SOURCE": str(source_lib),
                    "AUTOSCRIPTOR_RELEASE_LAB_CACHE": str(tmp_root / "missing-cache"),
                },
            ), patch.object(module, "_python_home_version", lambda _home: (3, 10)):
                self.assertEqual(module.resolve_compile_stdlib_source(), source_lib)
                stdlib = module.resolve_runtime_stdlib(("collections/__init__.py", "contextlib.py"))
                self.assertEqual(stdlib, source_lib)

    def test_mumu_acceptance_checks_packaged_runtime_webui_and_device(self):
        script = (ROOT / "scripts/release/mumu_device_acceptance.ps1").read_text(encoding="utf-8")
        gui = (ROOT / "gui.py").read_text(encoding="utf-8")
        panel = (ROOT / "services/webui/static/js/components/DiagnosticsPanel.js").read_text(encoding="utf-8")

        for marker in [
            "--runtime-import-smoke",
            "--mumu-runtime-probe",
            "--mumu-probe-start",
            "SkipStartProbe",
            "Get-Port5000Owners",
            "Stop-ProcessTree",
            "/api/refresh",
            "/api/runtime/snapshot",
            "/api/overview",
            "/api/device/diagnostics",
            "device_overall",
            "task_overall",
        ]:
            with self.subTest(marker=marker):
                self.assertIn(marker, script)

        for marker in [
            "AutoScriptor.core.control",
            "AutoScriptor.control.NemuIpc.device.method.nemu_ipc",
            "AutoScriptor.recognition.digit_rec",
            "AutoScriptor.utils.box_grid",
            "editor_safe_import_box_grid",
            "editor_grid_extract_validation",
        ]:
            with self.subTest(marker=marker):
                self.assertIn(marker, gui)

        self.assertIn("params.set('require_app', 'false')", panel)
        self.assertIn("device_overall", panel)
        self.assertIn("task_overall", panel)

    def test_packaged_windows_multiprocessing_uses_frozen_executable_before_single_instance(self):
        spec = importlib.util.spec_from_file_location(
            "gui_multiprocessing_spawn_test",
            ROOT / "gui.py",
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)

        original_executable = sys.executable
        had_frozen = hasattr(sys, "frozen")
        original_frozen = getattr(sys, "frozen", None)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                engine = Path(tmp) / "autoscriptor-engine.exe"
                engine.write_bytes(b"")
                with patch.object(module, "_COMPILED", True), patch.object(module.os, "name", "nt"), patch.object(
                    module,
                    "_windows_current_executable_path",
                    lambda: str(engine),
                ):
                    module._configure_packaged_multiprocessing_spawn()
                    self.assertTrue(getattr(sys, "frozen", False))
                    self.assertEqual(sys.executable, str(engine))
        finally:
            sys.executable = original_executable
            if had_frozen:
                setattr(sys, "frozen", original_frozen)
            elif hasattr(sys, "frozen"):
                delattr(sys, "frozen")

        main = (ROOT / "gui.py").read_text(encoding="utf-8").split("def main() -> int:", 1)[1].split(
            "if __name__ == '__main__':",
            1,
        )[0]
        self.assertLess(main.index("_configure_packaged_multiprocessing_spawn()"), main.index("ensure_single_instance()"))
        self.assertLess(main.index("multiprocessing.freeze_support()"), main.index("ensure_single_instance()"))
        self.assertIn("multiprocessing.set_executable(sys.executable)", main)

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
            "testWindowsAppsUninstallEntryCanUninstall",
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
        docs = (ROOT / "docs/AutoScriptor/release/build-and-run.md").read_text(encoding="utf-8")

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

    def test_release_build_bundles_gift_code_runtime_assets(self):
        script = (ROOT / "scripts/build_release.py").read_text(encoding="utf-8")

        for marker in [
            "docs\" / \"zmxy_redeem_codes.json",
            "assets\" / \"redeem_codes\" / \"zmxy_redeem_codes.json",
            "shutil.copy2(redeem_codes_src, redeem_codes_dst)",
            "[data] assets/redeem_codes/zmxy_redeem_codes.json",
        ]:
            with self.subTest(marker=marker):
                self.assertIn(marker, script)

    def test_plain_portable_package_excludes_backend_docs_and_keeps_light_update(self):
        builder = (ROOT / "packaging/plain_portable/build_plain_portable.py").read_text(encoding="utf-8")
        config = (ROOT / "packaging/plain_portable/electron-builder.plain.config.js").read_text(encoding="utf-8")

        for marker in [
            "ensure_runtime_data_assets",
            "assets\" / \"redeem_codes\" / \"zmxy_redeem_codes.json",
            "backend/autoscriptor-engine.exe",
            "verify_update_zip",
            "create_portable_zip",
            "low.startswith(\"data/accounts/\")",
        ]:
            with self.subTest(marker=marker):
                self.assertIn(marker, builder)
        for marker in [
            "to: 'backend'",
            "!docs/**",
            "to: 'data'",
            "!accounts/**/*.json",
            "AUTOSCRIPTOR_PLAIN_NSIS",
            "AutoScriptor_Zao_Plain_Install_${version}.exe",
        ]:
            with self.subTest(marker=marker):
                self.assertIn(marker, config)

    def test_source_portable_uses_pyz_backend_update_branch(self):
        builder = (ROOT / "packaging/source_portable/build_source_portable.py").read_text(encoding="utf-8")
        electron_main = (ROOT / "webapp/main.js").read_text(encoding="utf-8")
        release_update = (ROOT / "webapp/release-update.cjs").read_text(encoding="utf-8")
        docs = (ROOT / "docs/AutoScriptor/release/build-and-run.md").read_text(encoding="utf-8")

        for marker in [
            "BACKEND_PYZ",
            "write_backend_pyz",
            "backend.pyz",
            "EXTERNAL_WEB_ASSET_DIRS",
            "pyz-cumulative",
            "Path(\"services/webui/static\")",
            "Path(\"services/webui/vendor\")",
        ]:
            with self.subTest(marker=marker):
                self.assertIn(marker, builder)
        self.assertIn("getPackagedPyzBackend", electron_main)
        self.assertIn("AUTOSCRIPTOR_APP_ROOT", electron_main)
        self.assertIn("currentPyzBackend", electron_main)
        self.assertIn("backend', 'backend.pyz", electron_main)
        self.assertIn("fs.existsSync(pyz)", electron_main)
        self.assertIn("backend/backend.pyz", release_update)
        self.assertIn("backend/backend.pyz", docs)


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

    def test_recent_posts_are_limited_to_ten_days_and_fifteen_posts(self):
        current = self.collector.datetime(2026, 6, 1, 12, 0, tzinfo=self.collector.TZ_CN)
        posts = [
            {"post_id": str(i), "date": f"2026-05-{31 - i:02d}", "url": f"https://bbs.4399.cn/thread-tid-{i}"}
            for i in range(20)
        ]

        recent = self.collector.recent_posts_from_list(
            posts,
            current=current,
            max_age_days=10,
            max_posts=15,
        )

        self.assertLessEqual(len(recent), 15)
        self.assertEqual(recent[0]["post_id"], "0")
        self.assertTrue(all(p["date"] >= "2026-05-22" for p in recent))

    def test_incremental_collector_skips_checked_posts_and_keeps_active_rows(self):
        current = self.collector.datetime(2026, 6, 1, 12, 0, tzinfo=self.collector.TZ_CN)
        posts = [
            {
                "post_id": "old-post",
                "title": "[福利码]已查",
                "summary": "",
                "url": "https://bbs.4399.cn/thread-tid-old",
                "date": "2026-06-01",
            },
            {
                "post_id": "new-post",
                "title": "[福利码]新增",
                "summary": "",
                "url": "https://bbs.4399.cn/thread-tid-new",
                "date": "2026-05-30",
            },
            {
                "post_id": "too-old",
                "title": "[福利码]过旧",
                "summary": "",
                "url": "https://bbs.4399.cn/thread-tid-too-old",
                "date": "2026-05-10",
            },
        ]
        existing = {
            "rows": [
                {
                    "title": "[福利码]已查",
                    "code": "旧码仍有效",
                    "expires_at": "2026-06-05T05:00:00+08:00",
                    "url": "https://bbs.4399.cn/thread-tid-old",
                    "source": "4399官方论坛",
                    "kind": "public_code",
                    "status": "active",
                    "note": "",
                }
            ],
            "checked_post_ids": ["old-post"],
            "checked_post_urls": ["https://bbs.4399.cn/thread-tid-old"],
            "inspected_posts": [
                {
                    "post_id": "old-post",
                    "title": "[福利码]已查",
                    "url": "https://bbs.4399.cn/thread-tid-old",
                    "date": "2026-06-01",
                    "active": True,
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "codes.json"
            output.write_text(json.dumps(existing, ensure_ascii=False), encoding="utf-8")
            with patch.object(self.collector, "_scrape_posts", return_value=posts), patch.object(
                self.collector,
                "collect_thread",
                return_value=(
                    "[福利码]新增",
                    "福利码：新码内含：祝福礼包*5\n兑换码有效时间至6月8日05:00",
                    2026,
                    True,
                    "",
                ),
            ) as collect_thread:
                payload = self.collector.collect_incremental(
                    output,
                    config_path=Path(tmp) / "missing.json",
                    username="u",
                    password="p",
                    max_age_days=10,
                    max_posts=15,
                    current=current,
                )

        self.assertEqual(collect_thread.call_count, 1)
        self.assertEqual(collect_thread.call_args.args[0]["post_id"], "new-post")
        self.assertEqual([row["code"] for row in payload["rows"]], ["旧码仍有效", "新码"])
        self.assertIn("old-post", payload["checked_post_ids"])
        self.assertIn("new-post", payload["checked_post_ids"])
        self.assertNotIn("too-old", payload["checked_post_ids"])

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
        self.assertIn('"assets" / "redeem_codes" / "zmxy_redeem_codes.json"', content)
        for old_name in [
            "zmxy_codes.json",
            "zmxy_gift_codes_rows.json",
            "zmxy_redeem_codes_only.txt",
            "zmxy_redeem_codes_only.meta.txt",
            "zmxy_redeem_codes_only_detail.txt",
        ]:
            self.assertNotIn(old_name, content)

    def test_gift_dialog_uses_local_redeem_codes_page(self):
        panel = (ROOT / "services/webui/static/js/components/NewsPanel.js").read_text(
            encoding="utf-8",
            errors="ignore",
        )
        index = (ROOT / "services/webui/static/index.html").read_text(
            encoding="utf-8",
            errors="ignore",
        )

        self.assertIn("const NEWS_GIFT_CODES_PAGE_URL = '/api/news/gift_codes/page';", panel)
        self.assertIn("giftFrameSrc: NEWS_GIFT_CODES_PAGE_URL", panel)
        self.assertIn(':src="giftFrameSrc"', panel)
        self.assertIn("/api/news/gift_codes?refresh=1", panel)
        self.assertNotIn("NEWS_REDEEM_PAGE_URL", panel)
        self.assertNotIn("5054399.com", panel)
        self.assertNotIn("5054399.com", index)
        self.assertNotIn("openGiftExternal", panel)

    def test_gift_codes_page_supports_direct_redeem_flow(self):
        route = (ROOT / "services/webui/routes/news.py").read_text(
            encoding="utf-8",
            errors="ignore",
        )
        server = (ROOT / "services/webui/server.py").read_text(
            encoding="utf-8",
            errors="ignore",
        )
        scheduler = (ROOT / "services/core/scheduler.py").read_text(
            encoding="utf-8",
            errors="ignore",
        )
        task_manager = (ROOT / "services/core/task_manager.py").read_text(
            encoding="utf-8",
            errors="ignore",
        )

        for marker in [
            "font-size:14px",
            "font-size:20px",
            "class=\\\"expires\\\"",
            "<th>序号</th><th>兑换码</th><th>到期时间</th><th>来源链接</th><th>操作</th>",
            ">复制</button>",
            ">前往兑换</button>",
            '<label for="redeemAccount">账号</label>',
            '<label for="redeemRole">角色</label>',
            '<button type="button" class="btn btn-redeem" id="confirmRedeem">确认</button>',
            '<button type="button" class="btn btn-cancel" id="cancelRedeem">取消</button>',
            '<button type="button" class="btn btn-secondary" id="batchRedeem" disabled>兑换选中</button>',
            "function setChecked(cb,ev)",
            "ev.shiftKey&&lastCheckedCode",
            "function openBatchRedeem()",
            "setPageStatus((codes.length>1?codes.length+' 个兑换码':'兑换码')+'正在兑换中',false)",
            "closeRedeem();",
            "redeem_codes:codes",
            "/api/news/redeem_targets",
            "/api/news/gift_codes/redeem",
        ]:
            with self.subTest(marker=marker):
                self.assertIn(marker, route)

        self.assertNotIn("<th>类型</th>", route)
        self.assertIn('label": f"{server}:{char_name}"', server)
        redeem_task = (ROOT / "ZmxyOL/task/normal_task/huodong/redeem_gift.py").read_text(
            encoding="utf-8",
            errors="ignore",
        )
        manifest = (ROOT / "ZmxyOL/task/_manifest.py").read_text(
            encoding="utf-8",
            errors="ignore",
        )
        translations = (ROOT / "ZmxyOL/task/translations.py").read_text(
            encoding="utf-8",
            errors="ignore",
        )

        self.assertIn('_GIFT_REDEEM_TASK_PATH = "一般任务/活动/兑换豪礼礼品兑换"', server)
        self.assertIn("未找到兑换码任务，请确认一般任务已加载", server)
        self.assertIn("ZmxyOL.task.normal_task.huodong.redeem_gift", manifest)
        self.assertIn("'兑换豪礼礼品兑换': 'redeem_gift'", translations)
        self.assertIn("def task(redeem_code: str | list[str] = \"1111\")", redeem_task)
        self.assertFalse((ROOT / "data/custom_task/zmxy_activity_redeem.py").exists())
        self.assertIn('task_runs = [', server)
        self.assertIn('"id": "redeem:batch"', server)
        self.assertIn('"params": {"redeem_code": redeem_codes if len(redeem_codes) > 1 else redeem_codes[0]}', server)
        self.assertIn("scheduler.run_direct_sequence(runs, force_login=True)", server)
        self.assertIn("force_login: bool = False", scheduler)
        self.assertIn("explicit_task_runs: list[dict] | None = None", scheduler)
        self.assertIn("def run_direct_sequence(", scheduler)
        self.assertIn("param_overrides: dict[str, dict] | None = None", scheduler)
        self.assertIn("param_override: dict[str, Any] | None = None", task_manager)

    def test_news_page_refreshes_immediately_after_auth_or_reopen(self):
        panel = (ROOT / "services/webui/static/js/components/NewsPanel.js").read_text(
            encoding="utf-8",
            errors="ignore",
        )
        app = (ROOT / "services/webui/static/js/app.js").read_text(
            encoding="utf-8",
            errors="ignore",
        )
        index = (ROOT / "services/webui/static/index.html").read_text(
            encoding="utf-8",
            errors="ignore",
        )

        self.assertIn("refreshKey: { type: Number, default: 0 }", panel)
        self.assertIn("refreshKey()", panel)
        self.assertIn("this.fetchPosts(true);", panel)
        self.assertIn("const newsRefreshKey = ref(0);", app)
        self.assertIn("function refreshNewsImmediately()", app)
        self.assertIn("if (activeTab.value === 'news') refreshNewsImmediately();", app)
        self.assertIn('@navigate="navigateTo"', index)
        self.assertIn(':refresh-key="newsRefreshKey"', index)

    def test_news_public_credentials_are_explicitly_scoped(self):
        session = (ROOT / "services/webui/routes/news_4399_session.py").read_text(
            encoding="utf-8",
            errors="ignore",
        )
        route = (ROOT / "services/webui/routes/news.py").read_text(
            encoding="utf-8",
            errors="ignore",
        )

        self.assertIn('PUBLIC_NEWS_ACCOUNT = "85rwm3janyyc"', session)
        self.assertIn('PUBLIC_NEWS_PASSWORD = "123456"', session)
        self.assertIn("def is_public_news_credential", session)
        self.assertIn("from AutoScriptor.utils.app_config import cfg", session)
        self.assertIn('if "news" not in cfg._config:', session)
        self.assertNotIn("from services.webui import server", session)
        self.assertIn("_news_credentials_for_request", route)
        self.assertIn("is_public_news_credential", route)
        self.assertIn("validate_credential_unlock", route)


if __name__ == "__main__":
    unittest.main()
