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
    paths = types.ModuleType("AutoScriptor.utils.paths")
    paths.get_app_root = lambda: ROOT
    return {
        "AutoScriptor": autoscriptor,
        "AutoScriptor.utils": utils,
        "AutoScriptor.utils.logger": logger_module,
        "AutoScriptor.utils.paths": paths,
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
    paths.get_editable_data_root = lambda: Path(tmp_root)
    paths.get_config_path = lambda: Path(tmp_root) / "config.json"
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
        self.config = json.loads((ROOT / "data/config.template.json").read_text(encoding="utf-8"))

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

    def test_collect_task_reset_paths_detects_reenable_and_error_clear(self):
        old = {
            "group": {
                "off": {"on": False, "next_exec_time": 0},
                "err": {"on": True, "next_exec_time": 200, "human_takeover_error": "需要人工"},
                "ok": {"on": True, "next_exec_time": 0},
            },
        }
        new = {
            "group": {
                "off": {"on": True, "next_exec_time": 0},
                "err": {"on": True, "next_exec_time": 0},
                "ok": {"on": True, "next_exec_time": 0},
            },
        }

        paths = self.service.collect_task_reset_paths(old, new)

        self.assertEqual(sorted(paths), ["group/err", "group/off"])

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
            reload_preserving_decrypted_credentials=lambda key=None: self.calls.append(("reload_config", key)),
            switch_character=lambda server, character: self.calls.append(("switch_character", server, character)),
            switch_account=lambda name, key: self.calls.append(("switch_account", name, key)),
            add_account=lambda *args: self.calls.append(("add_account",) + args),
            update_current_account_credentials=lambda account, password, key: self.calls.append(
                ("update_credentials", account, password, key)
            ),
            active_character=lambda: {},
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
            mark_tasks_updated=lambda: self.calls.append("mark_tasks_updated"),
        )

        return self.WebUILifecycleService(
            cfg,
            task_manager,
            scheduler,
            task_tree_service,
            refresh_order_map=lambda: self.calls.append("read_config"),
            mark_config_changed=lambda reason: self.calls.append(("bump", reason)) or 42,
            apply_log_level=lambda: self.calls.append("apply_log_level"),
            clear_background=lambda: self.calls.append("bg_clear"),
            reload_ui_map=lambda: self.calls.append("reload_ui_map"),
        ), cfg

    def test_reload_task_state_clears_background_and_refreshes_projection_only(self):
        service, _cfg = self._service()

        version = service.reload_task_state(reason="manual light reload")

        self.assertEqual(version, 42)
        self.assertEqual(
            self.calls,
            ["bg_clear", "mark_tasks_updated", "read_config", ("bump", "manual light reload")],
        )
        self.assertNotIn(("reload_tasks", None), self.calls)

    def test_sync_all_config_reloads_config_without_clearing_background(self):
        service, _cfg = self._service()

        version = service.sync_all_config("key", reason="sync config")

        self.assertEqual(version, 42)
        self.assertEqual(
            self.calls,
            [("reload_config", "key"), "read_config", "apply_log_level", ("bump", "sync config")],
        )
        self.assertNotIn("bg_clear", self.calls)
        self.assertNotIn(("reload_tasks", "key"), self.calls)

    def test_add_character_switches_reload_tasks_and_refreshes_projection(self):
        cfg = SimpleNamespace(
            _config={},
            _account_data={},
            add_character=lambda server, character: self.calls.append(("add_character", server, character)),
            switch_character=lambda server, character: self.calls.append(("switch_character", server, character)),
        )
        service, _cfg = self._service(cfg=cfg)

        version = service.add_character("server", "hero")

        self.assertEqual(version, 42)
        self.assertEqual(
            self.calls,
            [
                "lock",
                ("add_character", "server", "hero"),
                ("switch_character", "server", "hero"),
                ("reload_tasks", None),
                "invalidate_login",
                "mark_tasks_updated",
                "read_config",
                ("bump", "add character"),
            ],
        )

    def test_reload_all_uses_full_task_reload_refreshes_ui_map_and_clears_background(self):
        service, _cfg = self._service()

        version = service.reload_all("key", reason="full reload")

        self.assertEqual(version, 42)
        self.assertEqual(
            self.calls,
            [
                ("reload_tasks", "key"),
                "reload_ui_map",
                "bg_clear",
                "mark_tasks_updated",
                "read_config",
                ("bump", "full reload"),
            ],
        )

    def test_save_tasks_sanitizes_persists_refreshes_and_wakes(self):
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
            ["lock", "save_config", "wake", "mark_tasks_updated", "read_config", ("bump", "save tasks")],
        )

    def test_save_tasks_clears_status_for_reactivated_or_error_reset_paths(self):
        from services.webui.task_tree_service import TaskTreeService

        class FakeTaskManager:
            cleared = []

            @contextmanager
            def config_transaction(inner_self):
                self.calls.append("lock")
                yield

            def _clear_human_takeover_state(inner_self, path):
                inner_self.cleared.append(path)

        task_manager = FakeTaskManager()
        cfg = SimpleNamespace(
            _config={
                "tasks": {
                    "group": {
                        "task": {
                            "on": True,
                            "next_exec_time": 200,
                            "human_takeover_error": "需要人工",
                        },
                    },
                },
                "status": {"tasks": {"group/task": {"progress": "3/6"}}},
            },
            _account_data={},
            save_config=lambda: self.calls.append("save_config"),
        )
        service, _cfg = self._service(
            cfg=cfg,
            task_manager=task_manager,
            task_tree_service=TaskTreeService(),
        )

        cleared = []
        with patch("AutoScriptor.utils.task_state.clear_task_status", side_effect=lambda *a, **k: cleared.append((a, k))):
            service.save_tasks({"group": {"task": {"on": True, "next_exec_time": 0}}})

        self.assertEqual(task_manager.cleared, ["group/task"])
        self.assertEqual(len(cleared), 1)
        self.assertIsNone(cleared[0][0][0])
        self.assertEqual(cleared[0][1]["task_path"], "group/task")
        self.assertFalse(cleared[0][1]["save"])

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

    def test_switch_character_refreshes_projection_and_invalidates_login(self):
        service, _cfg = self._service()

        version = service.switch_character("s1", "hero", reason="select run character")

        self.assertEqual(version, 42)
        self.assertEqual(
            self.calls,
            [
                "lock",
                ("switch_character", "s1", "hero"),
                "invalidate_login",
                "mark_tasks_updated",
                "read_config",
                ("bump", "select run character"),
            ],
        )

    def test_switch_account_refreshes_projection_without_full_reload(self):
        service, _cfg = self._service()

        version = service.switch_account("main", "key")

        self.assertEqual(version, 42)
        self.assertEqual(
            self.calls,
            [
                "lock",
                ("switch_account", "main", "key"),
                "invalidate_login",
                "mark_tasks_updated",
                "read_config",
                ("bump", "switch account"),
            ],
        )
        self.assertNotIn(("reload_tasks", "key"), self.calls)

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

    def test_add_account_switches_and_refreshes_without_full_reload(self):
        service, _cfg = self._service()

        version = service.add_account("main", "user", "pwd", "s1", "hero", "key")

        self.assertEqual(version, 42)
        self.assertEqual(
            self.calls,
            [
                "lock",
                ("add_account", "main", "user", "pwd", "s1", "hero", "key"),
                ("switch_account", "main", "key"),
                "invalidate_login",
                "mark_tasks_updated",
                "read_config",
                ("bump", "add account"),
            ],
        )
        self.assertNotIn(("reload_tasks", "key"), self.calls)

    def test_update_account_credentials_refreshes_projection_without_full_reload(self):
        service, cfg = self._service()
        cfg._config["game"] = {"character_name": "hero"}

        character_name, version = service.update_account_credentials("user", "pwd", "key")

        self.assertEqual(character_name, "hero")
        self.assertEqual(version, 42)
        self.assertEqual(
            self.calls,
            [
                "lock",
                ("update_credentials", "user", "pwd", "key"),
                "mark_tasks_updated",
                "read_config",
                ("bump", "update account credentials"),
            ],
        )
        self.assertNotIn(("reload_tasks", "key"), self.calls)

    def test_import_config_refreshes_projection_without_full_reload(self):
        def strip_runtime_fields(tasks):
            cleaned = deepcopy(tasks)
            cleaned["leaf"].pop("param_meta", None)
            return cleaned

        service, cfg = self._service(
            task_tree_service=SimpleNamespace(strip_runtime_fields=strip_runtime_fields)
        )

        version = service.import_config({
            "tasks": {"leaf": {"on": True, "param_meta": {"x": "secret"}}},
            "deploy": {"log_level": "warning", "password": "secret"},
            "current_account": "should-not-import",
        })

        self.assertEqual(version, 42)
        self.assertEqual(cfg._config["tasks"], {"leaf": {"on": True}})
        self.assertEqual(cfg._config["deploy"], {"log_level": "warning"})
        self.assertEqual(
            self.calls,
            ["lock", "save_config", "mark_tasks_updated", "read_config", "apply_log_level", ("bump", "import config")],
        )
        self.assertNotIn(("reload_tasks", None), self.calls)


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

    def test_config_watcher_can_mark_runtime_config_write_seen(self):
        watcher_module = import_watcher_for_test()

        with tempfile.TemporaryDirectory() as tmp:
            config_path = os.path.join(tmp, "config.json")
            script_path = os.path.join(tmp, "hero.py")
            Path(config_path).write_text("{}", encoding="utf-8")
            Path(script_path).write_text("hero = 1\n", encoding="utf-8")

            watcher = watcher_module.ConfigWatcher(config_path, extra_paths=lambda: [script_path])
            watcher.start_watching()
            time.sleep(1.1)
            Path(config_path).write_text('{"runtime": true}', encoding="utf-8")
            watcher.mark_seen([config_path])

            self.assertFalse(watcher.should_reload())

            time.sleep(1.1)
            Path(script_path).write_text("hero = 2\n", encoding="utf-8")

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

    def test_config_save_reports_atomic_replace_denied(self):
        with tempfile.TemporaryDirectory() as tmp:
            module = import_app_config_for_test(tmp)

            with patch.object(module.os, "replace", side_effect=PermissionError("replace denied")):
                module.cfg._config["app"] = {"name": "ZmxyOL"}
                with self.assertRaises(PermissionError):
                    module.cfg.save_config()

            self.assertFalse((Path(tmp) / "config.json").exists())

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

    def test_config_load_merges_template_defaults_for_sparse_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            module = import_app_config_for_test(tmp)
            config_path = Path(tmp) / "config.json"
            template_path = Path(tmp) / "config.template.json"
            template_path.write_text(json.dumps({
                "app": {"app_to_start": "org.yjmobile.zmxy", "max_retry": 2},
                "emulator": {"adb_addr": "127.0.0.1:16384"},
                "ocr": {"use_gpu": False},
            }), encoding="utf-8")
            config_path.write_text(json.dumps({"app": {}, "emulator": {}, "current_account": ""}), encoding="utf-8")

            module.cfg.load_config()

            self.assertEqual(module.cfg._config["app"]["app_to_start"], "org.yjmobile.zmxy")
            self.assertEqual(module.cfg._config["app"]["max_retry"], 2)
            self.assertEqual(module.cfg._config["emulator"]["adb_addr"], "127.0.0.1:16384")
            self.assertFalse(module.cfg._config["ocr"]["use_gpu"])

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
        ROOT / "services/webui/static/js/core/api.js",
        ROOT / "services/webui/static/js/app.js",
        ROOT / "services/webui/static/js/stores/runtimeStore.js",
        ROOT / "services/webui/static/js/components/DiagnosticsPanel.js",
        ROOT / "services/webui/static/js/components/Overview.js",
        ROOT / "services/webui/static/js/components/SchedulerPanel.js",
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

    def test_frontend_stop_does_not_wait_for_full_runtime_snapshot(self):
        content = (ROOT / "services/webui/static/js/app.js").read_text(encoding="utf-8")
        start = content.index("    async function unifiedStop()")
        end = content.index("    async function verifyAccount", start)
        body = content[start:end]

        self.assertIn("API.request('POST', '/stop'", body)
        self.assertIn("applyRuntimeSnapshotPayload({ runtime: data.runtime", body)
        self.assertIn("scheduler: data.runtime.scheduler", body)
        self.assertIn("scheduleRuntimeRefreshAfterStop();", body)
        self.assertNotIn("await refreshRuntimePanels()", body)
        self.assertNotIn("await fetchRuntimeSnapshot", body)

    def test_task_and_scheduler_stop_buttons_use_overview_stop_action(self):
        index = (ROOT / "services/webui/static/index.html").read_text(encoding="utf-8")
        task_panel = (ROOT / "services/webui/static/js/components/TaskPanel.js").read_text(encoding="utf-8")
        scheduler_panel = (ROOT / "services/webui/static/js/components/SchedulerPanel.js").read_text(encoding="utf-8")

        self.assertIn('@stop-dispatch="stopDispatch"', index)
        self.assertNotIn('@stop-run="stopRun"', index)
        self.assertNotIn("function stopRun()", (ROOT / "services/webui/static/js/app.js").read_text(encoding="utf-8"))
        self.assertIn("'stop-dispatch'", task_panel)
        self.assertIn("'stop-dispatch'", scheduler_panel)
        self.assertIn("$emit('stop-dispatch')", task_panel)
        self.assertIn("$emit('stop-dispatch')", scheduler_panel)
        self.assertNotIn("'stop-run'", task_panel)
        self.assertNotIn("'stop-run'", scheduler_panel)
        self.assertNotIn("$emit('stop-run')", task_panel)
        self.assertNotIn("$emit('stop-run')", scheduler_panel)

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
        self.assertIn("自动定位 MuMu", content)
        self.assertIn("/device/discover?probe_adb=true", content)
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
            "/api/config/sync",
            "/api/tasks/reload-all",
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
        self.assertNotIn("self.task_manager.reload_tasks(security_key)", body)
        self.assertIn("self.scheduler.invalidate_login()", body)

    def test_reload_routes_use_split_lifecycle_methods(self):
        content = (ROOT / "services/webui/server.py").read_text(encoding="utf-8")

        start = content.index("@app.post(\"/api/tasks/reload\")")
        end = content.index("@app.post(\"/api/config\")", start)
        light_reload_body = content[start:end]
        self.assertIn("lifecycle_service.reload_task_state", light_reload_body)
        self.assertNotIn("lifecycle_service.reload_tasks", light_reload_body)

        start = content.index("@app.post(\"/api/config/sync\")")
        end = content.index("@app.post(\"/api/tasks/reload-all\")", start)
        sync_body = content[start:end]
        self.assertIn("lifecycle_service.sync_all_config", sync_body)
        self.assertNotIn("_guard_runtime_idle", sync_body)

        start = content.index("@app.post(\"/api/tasks/reload-all\")")
        end = content.index("@app.post(\"/api/config\")", start)
        full_reload_body = content[start:end]
        self.assertIn("lifecycle_service.reload_all", full_reload_body)

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
        self.assertNotIn("except Exception", body)
        self.assertIn("runtime_ctx.init_bg()", body)
        self.assertIn("TASK_MANAGER.reload_tasks()", body)

    def test_webui_background_init_failure_is_visible(self):
        content = (ROOT / "services/webui/server.py").read_text(encoding="utf-8")
        start = content.index("async def _deferred_heavy_init():")
        end = content.index("def _do_heavy_init():", start)
        body = content[start:end]
        except_block = body[body.index("except Exception as e:"):]

        self.assertIn("_init_error", body)
        self.assertIn("logger.exception(\"后台初始化失败\")", body)
        self.assertNotIn("_init_done = True", except_block)
        self.assertIn("payload[\"error\"] = _init_error", content)

    def test_enum_options_fail_instead_of_empty_fallback(self):
        content = (ROOT / "services/webui/server.py").read_text(encoding="utf-8")
        start = content.index("@app.post(\"/api/enum-options\")")
        end = content.index("@app.get(\"/api/ocr-status\")", start)
        body = content[start:end]

        self.assertNotIn("result[p] = []", body)
        self.assertIn("return api_error(400, 'paths must be a list'", body)
        self.assertIn("invalid enum path", body)
        self.assertIn("return api_error(500, str(e), code='enum_options_failed')", body)

    def test_ocr_status_fail_instead_of_probe_defaults(self):
        content = (ROOT / "services/webui/server.py").read_text(encoding="utf-8")
        start = content.index("@app.get(\"/api/ocr-status\")")
        end = content.index("@app.get(\"/api/scheduler/status\")", start)
        body = content[start:end]

        self.assertNotIn("def _safe", body)
        self.assertNotIn("\"unknown\"", body)
        self.assertIn("paddle.device.is_compiled_with_cuda()", body)
        self.assertIn("paddle.device.cuda.device_count()", body)
        self.assertIn("ocr_manager.is_ready()", body)
        self.assertIn("return api_error(500, str(e), code=\"ocr_status_failed\")", body)

    def test_frontend_enum_loader_honors_http_status(self):
        content = (ROOT / "services/webui/static/js/app.js").read_text(encoding="utf-8")
        start = content.index("    function openEditModal")
        end = content.index("    function _initTableRowsCache", start)
        body = content[start:end]

        self.assertIn("API.request('POST', '/enum-options'", body)
        self.assertNotIn("API.post('/enum-options'", body)
        self.assertIn("if (!ok)", body)
        self.assertIn("showApiError(map, '加载参数选项失败')", body)
        self.assertIn("throw new Error(`枚举选项缺失: ${enumPath}`)", body)
        self.assertNotIn("map[p] || []", body)
        self.assertNotIn("_initTableRowsCache(meta); editModalVisible.value = true; });", body)

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
        gui = (ROOT / "services/webui/gui.py").read_text(encoding="utf-8")

        for marker in [
            "function reportStartupStep",
            "startupTimers",
            "AUTOSCRIPTOR_ELECTRON_RENDER_MODE",
            "DEFAULT_ELECTRON_RENDER_MODE = 'software'",
            "configureElectronRendering();",
            "app.disableHardwareAcceleration()",
            "disable-gpu-compositing",
            "disable-gpu-rasterization",
            "disable-zero-copy",
            "app.commandLine.appendSwitch('use-angle', 'd3d11')",
            "app.getGPUFeatureStatus()",
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
        self.assertLess(
            main.index("configureElectronRendering();"),
            main.index("app.whenReady().then("),
        )
        self.assertNotIn("chcp", main)
        self.assertIn("Port 5000 cleanup failed", main)
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
        self.assertIn("/api/device/discover", server)
        self.assertIn("discover_mumu_setup", server)

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
            '_ensure_editor_mixctrl("execute-code", cancel_check=check_cancel_raise)',
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
        self.assertIn("if not (virtual_only and _last_screenshot is not None):", execute_body)
        self.assertIn("asyncio.to_thread(_execute_editor_code_sync", execute_body)
        helper_start = content.index("def _execute_editor_code_sync(")
        helper_end = content.index('@router.post("/validate-code")', helper_start)
        helper_body = content[helper_start:helper_end]
        self.assertIn("if virtual_only and _last_screenshot is not None:", helper_body)
        self.assertIn("_EditorVirtualMixControl(_last_screenshot)", helper_body)

    def test_editor_click_recording_keeps_offset_out_of_target_box(self):
        content = (ROOT / "services/webui/static/js/components/editor/EditorPanel.js").read_text(encoding="utf-8")

        self.assertIn("function buildClickCodeAt(x, y)", content)
        self.assertIn("if (t) {", content)
        self.assertIn("if (useImage.value) return iCode.value;", content)
        self.assertIn("return tCode.value;", content)
        self.assertIn("if (b) return `B(${b.left},${b.top},${b.width},${b.height})`", content)
        self.assertIn("offsetPart = (dx || dy) ? `, offset=(${dx},${dy})` : ''", content)
        self.assertIn("if (tgt.startsWith('B(')) return `click(${tgt})`", content)
        self.assertIn("return `click(${tgt}${offsetPart})`", content)
        self.assertIn("const line = buildClickCodeAt(x, y) || `click(B(${x},${y}))`", content)
        self.assertIn("clearSelection();", content)
        self.assertIn("swipe(B(${x1},${y1}), B(${x2},${y2}), duration_s=1)", content)
        self.assertIn("swipe(B(${pts.x1},${pts.y1}), B(${pts.x2},${pts.y2}), duration_s=1)", content)
        self.assertNotIn("timeout=3", content)
        self.assertNotIn("B(${x},${y},1,1)", content)
        self.assertNotIn(".margin()+(", content)

    def test_editor_custom_executor_supports_grid_templates_stop_and_indent(self):
        frontend = (ROOT / "services/webui/static/js/components/editor/EditorPanel.js").read_text(encoding="utf-8")
        backend = (ROOT / "services/webui/routes/editor.py").read_text(encoding="utf-8")
        api = (ROOT / "AutoScriptor/core/api.py").read_text(encoding="utf-8")

        self.assertIn("counts = extract_info(make_box_grid", frontend)
        self.assertIn("digital=True", frontend)
        self.assertIn("@click=\"stopCustomCodeExecution\"", frontend)
        self.assertIn("apiPost('/execute-code/stop'", frontend)
        self.assertIn("stopCustomLoading", frontend)
        self.assertIn("function onCustomExecKeydown(e)", frontend)
        self.assertIn("if (e.shiftKey)", frontend)
        self.assertIn("line.startsWith('    ')", frontend)

        self.assertIn("from AutoScriptor.utils.box_grid import indexof, make_box_grid", backend)
        self.assertIn('"make_box_grid": make_box_grid', backend)
        self.assertIn('"indexof": indexof', backend)
        self.assertIn('"__import__": _editor_safe_import', backend)
        self.assertIn('@router.post("/execute-code/stop")', backend)
        self.assertIn("configure_editor_execution_controls", backend)
        self.assertIn("TaskCancelled", backend)
        self.assertIn("check_cancel_raise", backend)
        self.assertIn("asyncio.to_thread(_execute_editor_code_sync", backend)

        self.assertIn("digital: bool | None = None", api)
        self.assertIn("if digital is not None:", api)

    def test_editor_draft_cache_and_save_custom_script_contract(self):
        frontend = (ROOT / "services/webui/static/js/components/editor/EditorPanel.js").read_text(encoding="utf-8")
        index = (ROOT / "services/webui/static/index.html").read_text(encoding="utf-8")
        backend = (ROOT / "services/webui/routes/editor.py").read_text(encoding="utf-8")
        server = (ROOT / "services/webui/server.py").read_text(encoding="utf-8")
        api_contract = (ROOT / "docs/AutoScriptor/webui/api-contract.md").read_text(encoding="utf-8")
        authoring = (ROOT / "docs/AutoScriptor/tasks/script-authoring.md").read_text(encoding="utf-8")

        self.assertIn("const EDITOR_DRAFT_CACHE = {", frontend)
        self.assertIn("recordedCode: ''", frontend)
        self.assertIn("customExecCode: ''", frontend)
        self.assertIn("ref(EDITOR_DRAFT_CACHE.recordedCode || '')", frontend)
        self.assertIn("ref(EDITOR_DRAFT_CACHE.customExecCode || '')", frontend)
        self.assertIn("watch(recordedCode", frontend)
        self.assertIn("EDITOR_DRAFT_CACHE.recordedCode = value || ''", frontend)
        self.assertIn("watch(customExecCode", frontend)
        self.assertIn("EDITOR_DRAFT_CACHE.customExecCode = value || ''", frontend)

        self.assertIn("保存脚本", frontend)
        self.assertIn("saveScriptLoading", frontend)
        self.assertIn("saveScriptDisabled", frontend)
        self.assertIn("async function saveCustomScript()", frontend)
        self.assertIn("saveScriptDialogVisible", frontend)
        self.assertIn("saveScriptForm", frontend)
        self.assertIn("submitSaveCustomScript", frontend)
        self.assertIn("文件名称", frontend)
        self.assertIn("脚本名称", frontend)
        self.assertIn("description（描述）", frontend)
        self.assertIn("task_docs", frontend)
        self.assertIn("参数设置", frontend)
        self.assertIn("字段名称", frontend)
        self.assertIn("字段类型", frontend)
        self.assertIn("字段解释", frontend)
        self.assertIn("Enum(单选)", frontend)
        self.assertIn("Enum(多选)", frontend)
        self.assertIn("const sections = []", frontend)
        self.assertIn("sections.join('\\n\\n')", frontend)
        self.assertIn("apiPost('/save-custom-task'", frontend)
        self.assertIn("filename:", frontend)
        self.assertIn("task_path:", frontend)
        self.assertIn("description:", frontend)
        self.assertIn("task_doc:", frontend)
        self.assertIn("params:", frontend)
        self.assertIn("enum_options", frontend)
        self.assertIn("code,", frontend)
        self.assertNotIn("apiPost('/custom-scripts'", frontend)
        self.assertNotIn("recorded_code: recordedCode.value || ''", frontend)
        self.assertNotIn("custom_exec_code: customExecCode.value || ''", frontend)
        self.assertIn("EditorPanel.js?v=30", index)

        self.assertIn('@router.post("/save-custom-task")', backend)
        self.assertIn("def _normalize_editor_custom_task_filename", backend)
        self.assertIn("def _normalize_editor_task_path", backend)
        self.assertIn("def _normalize_editor_param_specs", backend)
        self.assertIn("from AutoScriptor.utils.paths import get_custom_task_dir", backend)
        self.assertIn("os.replace(tmp_path, target_path)", backend)
        self.assertIn("api_ok(", backend)
        self.assertIn("api_error(", backend)
        self.assertIn("description=description", backend)
        self.assertIn("task_doc=final_task_doc", backend)
        self.assertIn("enum_options", backend)
        self.assertIn("enum_multi", backend)
        self.assertIn("configure_editor_custom_task_save_controls", backend)
        self.assertIn("configure_editor_custom_task_save_controls", server)
        self.assertIn('reload_custom_tasks=lambda: lifecycle_service.reload_all(reason="save editor custom task")', server)
        self.assertIn("_editor_nav_namespace", backend)
        self.assertIn("from ZmxyOL.nav import api as nav_api", backend)
        self.assertIn("from ZmxyOL.nav.envs import decorators as nav_decorators", backend)
        self.assertIn('symbols["ensure_in"] = nav_api.ensure_in', backend)
        self.assertIn('symbols["LOC_ENV"] = nav_decorators.LOC_ENV', backend)
        self.assertIn("ns.update(_editor_nav_namespace())", backend)

        self.assertIn("POST /api/editor/save-custom-task", api_contract)
        self.assertIn("data/custom_task", api_contract)
        self.assertIn('"filename": "custom_task.py"', api_contract)
        self.assertIn('"task_path": "自定义任务/示例/操作设置"', api_contract)
        self.assertIn('"description": "一句话描述"', api_contract)
        self.assertIn('"task_doc": "补充说明正文"', api_contract)
        self.assertIn('"type": "enum_multi"', api_contract)
        self.assertIn('"enum_options": ["普通", "困难"]', api_contract)
        self.assertIn('自定义任务/<name>', api_contract)
        self.assertIn('POST /api/editor/save-custom-task', api_contract)
        self.assertIn('WebUI Editor 的“保存脚本”接口', authoring)
        self.assertIn('/api/editor/save-custom-task', authoring)
        self.assertIn('文件名称', authoring)
        self.assertIn('脚本名称', authoring)
        self.assertIn('Enum(单选)', authoring)
        self.assertIn('Enum(多选)', authoring)
        self.assertIn('@register_task(path_cn="自定义任务/...")', authoring)

    def test_editor_save_custom_task_metadata_codegen_contract(self):
        from services.webui.routes import editor

        source, wrapped, task_path = editor._prepare_editor_custom_task_source(
            "cleanup.py",
            "click(T('确定'))",
            {
                "task_path": "自定义任务/示例/操作设置",
                "description": "一句话描述",
                "task_doc": "补充说明正文",
                "params": [
                    {"name": "times", "type": "int", "description": "执行次数"},
                    {"name": "mode", "type": "enum", "description": "单选模式", "enum_options": ["普通", "困难"]},
                    {"name": "areas", "type": "enum_multi", "description": "多选区域", "enum_options": '["左侧", "右侧"]'},
                ],
            },
        )

        self.assertTrue(wrapped)
        self.assertEqual(task_path, "自定义任务/示例/操作设置")
        self.assertIn("import enum", source)
        self.assertIn("class EditorParam1Enum(str, enum.Enum):", source)
        self.assertIn("class EditorParam2Enum(str, enum.Enum):", source)
        self.assertIn("@register_task(", source)
        self.assertIn("path_cn='自定义任务/示例/操作设置'", source)
        self.assertIn("description='一句话描述'", source)
        self.assertIn("task_doc=", source)
        self.assertIn("参数说明:", source)
        self.assertIn("- times: 执行次数", source)
        self.assertIn("times: int = 0", source)
        self.assertIn("mode: EditorParam1Enum = EditorParam1Enum.OPTION_1", source)
        self.assertIn("areas: list = [EditorParam2Enum.OPTION_1]", source)
        compile(source, "generated_editor_custom_task.py", "exec")

        with self.assertRaisesRegex(ValueError, "Enum"):
            editor._prepare_editor_custom_task_source(
                "bad_enum",
                "pass",
                {"params": [{"name": "mode", "type": "enum", "enum_options": "not-json"}]},
            )

    def test_editor_recorder_snippets_and_tab_indent_contract(self):
        frontend = (ROOT / "services/webui/static/js/components/editor/EditorPanel.js").read_text(encoding="utf-8")
        css = (ROOT / "services/webui/static/css/style.css").read_text(encoding="utf-8")
        trajectories = (ROOT / "docs/AutoScriptor/webui/user-trajectories.md").read_text(encoding="utf-8")

        self.assertIn('ref="recordedCodeInput"', frontend)
        self.assertIn('@keydown="onRecordedCodeKeydown"', frontend)
        self.assertIn("function handleTextareaTab(e, modelRef)", frontend)
        self.assertIn("const hasSelection = end > start", frontend)
        self.assertIn("if (e.shiftKey)", frontend)
        self.assertIn("line.startsWith('    ')", frontend)
        self.assertIn("ta.setSelectionRange(nextStart, nextEnd)", frontend)
        self.assertIn("ta.setSelectionRange(start + 4, end + 4 * lines.length)", frontend)
        self.assertIn("function onRecordedCodeKeydown(e)", frontend)
        self.assertIn("function onCustomExecKeydown(e)", frontend)

        self.assertIn("判断存在", frontend)
        self.assertIn("function appendUiExists()", frontend)
        self.assertIn("const tgt = buildTarget();", frontend)
        self.assertIn("const line = tgt ? `if ui_T(${tgt}):` : 'if ui_T():'", frontend)
        self.assertIn("appendRecordedSnippet(line, tgt ? null : line.indexOf('(') + 1)", frontend)
        self.assertIn("recordedTextareaElement()", frontend)
        self.assertIn("ta.focus()", frontend)
        self.assertIn("appendUiExists", frontend)

        self.assertRegex(css, r"\.editor-recorder-actions\s*\{[^}]*min-height:\s*0;")
        self.assertRegex(css, r"\.editor-recorder-actions\s*\{[^}]*overflow-y:\s*auto;")
        self.assertRegex(css, r"\.editor-recorder-actions\s*\{[^}]*overflow-x:\s*hidden;")

        self.assertIn("代码编辑器式 Tab 缩进", trajectories)
        self.assertIn("`if ui_T():`", trajectories)
        self.assertIn("有框选时复用 click 的 T/I/B 目标", trajectories)
        self.assertIn("右侧按钮列内部滚动", trajectories)

    def test_editor_custom_executor_uses_current_target_helpers(self):
        backend = (ROOT / "services/webui/routes/editor.py").read_text(encoding="utf-8")

        self.assertIn("from AutoScriptor.core.targets import B, I, T", backend)
        self.assertIn('"B": B', backend)
        self.assertIn('"T": T', backend)
        self.assertIn('"I": I', backend)

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

    def test_navigation_uses_current_runtime_mixctrl(self):
        content = (ROOT / "ZmxyOL/nav/api.py").read_text(encoding="utf-8")
        self.assertIn("import AutoScriptor.core.api as _core_api", content)
        self.assertIn("_core_api.mixctrl.app.launch", content)
        self.assertNotIn(
            "mixctrl.app.launch",
            content.replace("_core_api.mixctrl.app.launch", ""),
        )

    def test_runtime_perf_module_is_removed(self):
        adapter_utils = (ROOT / "AutoScriptor/control/MumuAdaptor/utils.py").read_text(encoding="utf-8")
        package_init = (ROOT / "AutoScriptor/__init__.py").read_text(encoding="utf-8")

        self.assertFalse((ROOT / "AutoScriptor/utils/perf.py").exists())
        self.assertNotIn("mumu_safe_subprocess", adapter_utils)
        self.assertNotIn("perf_boost", package_init)

    def test_electron_shell_does_not_use_host_performance_fallbacks(self):
        main = (ROOT / "webapp/main.js").read_text(encoding="utf-8")

        for marker in [
            "powercfg",
            "SetPriorityClass",
            "wmic process",
            "Start-Process -Priority",
            "ProcessorAffinity",
            "SetThreadPriority",
            "SetProcessAffinityMask",
            "Win32_PowerPlan",
        ]:
            with self.subTest(marker=marker):
                self.assertNotIn(marker, main)

    def test_mumu_shutdown_does_not_global_taskkill(self):
        content = (ROOT / "AutoScriptor/control/MumuAdaptor/api/core/power.py").read_text(encoding="utf-8")

        self.assertNotIn("[\"taskkill\"", content)
        self.assertNotIn("_force_kill", content)
        self.assertIn("不执行全局", content)


class TestSourceDistributionContract(unittest.TestCase):
    def test_cli_installer_and_release_files_are_removed(self):
        removed_paths = [
            "services/main_cli",
            "scripts/launcher-cli -l.bat",
            "scripts/launcher-l.bat",
            "scripts/release_autoscriptor_locks.ps1",
            "services/installer",
            "scripts/release",
            "scripts/build_release.py",
            "scripts/verify_packaging_prereqs.py",
            "scripts/npm-postinstall.js",
            "release_locks.bat",
            "docs/AutoScriptor/release",
            "webapp/install-packaged.cjs",
            "webapp/release-update.cjs",
            "webapp/mumu-detect.cjs",
            "webapp/renderer/installer.html",
            "webapp/scripts/prepare-release-shell.cjs",
            "webapp/scripts/verify-pack.cjs",
            "webapp/scripts/test-install-packaged.cjs",
            "webapp/scripts/test-release-update.cjs",
            "webapp/scripts/gen_icon.py",
            "webapp/scripts/ensure-ico.cjs",
            "services/core/binary_delta.py",
            "services/core/content_delta_update.py",
            "services/core/content_update_security.py",
            "AutoScriptor/utils/filter.py",
            "AutoScriptor/crypto/update_config.py",
        ]

        for rel in removed_paths:
            with self.subTest(path=rel):
                self.assertFalse((ROOT / rel).exists())

    def test_electron_shell_is_source_only(self):
        main = (ROOT / "webapp/main.js").read_text(encoding="utf-8")
        preload = (ROOT / "webapp/preload.js").read_text(encoding="utf-8")
        start_dev = (ROOT / "webapp/scripts/start-dev.cjs").read_text(encoding="utf-8")
        package_json = json.loads((ROOT / "webapp/package.json").read_text(encoding="utf-8"))

        self.assertIn("'services', 'webui', 'gui.py'", main)
        self.assertIn("--electron", main)
        self.assertIn(".venv", main)
        self.assertIn("Missing source Python venv", main)
        self.assertNotIn(".python310", main)
        self.assertNotIn("install-packaged", main)
        self.assertNotIn("release-update", main)
        self.assertNotIn("installer:", main)
        self.assertNotIn("release-update:", main)
        self.assertNotIn("mumu-detect", main)

        exposed = list(package_json["scripts"].keys())
        self.assertEqual(exposed, ["start"])
        self.assertEqual(set(package_json["dependencies"].keys()), {"tree-kill"})
        self.assertEqual(set(package_json["devDependencies"].keys()), {"electron"})
        self.assertEqual(package_json["engines"]["node"], ">=22.12.0")
        self.assertIn("require('electron')", start_dev)
        self.assertNotIn("dist', 'electron.exe", start_dev)
        self.assertNotIn('dist", "electron.exe', start_dev)

        self.assertIn("windowClose", preload)
        self.assertNotIn("releaseUpdate", preload)
        self.assertNotIn("dryRunPackagedInstall", preload)

    def test_update_panel_uses_source_git_only(self):
        panel = (ROOT / "services/webui/static/js/components/UpdatePanel.js").read_text(encoding="utf-8")
        server = (ROOT / "services/webui/server.py").read_text(encoding="utf-8")
        security = (ROOT / "services/webui/security.py").read_text(encoding="utf-8")

        for marker in ["/api/update/status", "/api/update/check", "/api/update/run", "source-git"]:
            with self.subTest(marker=marker):
                self.assertIn(marker, panel)
        for marker in ["remote_branch", "ahead_count", "behind_count", "本地比远端 ${remoteBranch} 新 ${aheadCount} 个提交"]:
            with self.subTest(marker=marker):
                self.assertIn(marker, panel)
        self.assertIn("Git fetch/pull --ff-only", panel)
        self.assertIn("scripts\\\\install.bat", panel)
        self.assertNotIn("依赖安装", panel)

        for stale in [
            "/api/content-update",
            "content-update",
            "releaseUpdate",
            "dryRunPackage",
            "applyPackage",
            "backend_incremental",
        ]:
            with self.subTest(stale=stale):
                self.assertNotIn(stale, panel)
                self.assertNotIn(stale, server)
                self.assertNotIn(stale, security)

    def test_source_scripts_are_split_and_source_only(self):
        install = (ROOT / "scripts/install.ps1").read_text(encoding="utf-8")
        run = (ROOT / "scripts/run.ps1").read_text(encoding="utf-8")
        update = (ROOT / "scripts/update.ps1").read_text(encoding="utf-8")
        launcher = (ROOT / "scripts/launcher.ps1").read_text(encoding="utf-8")
        updater = (ROOT / "services/core/updater.py").read_text(encoding="utf-8")
        bootstrap = (ROOT / "scripts/bootstrap-python310.ps1").read_text(encoding="utf-8")
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        package_init = (ROOT / "AutoScriptor/__init__.py").read_text(encoding="utf-8")

        for rel in [
            "scripts/install.bat",
            "scripts/install.ps1",
            "scripts/run.bat",
            "scripts/run.ps1",
            "scripts/update.bat",
            "scripts/update.ps1",
            "start.bat",
            "local_start.bat",
        ]:
            with self.subTest(path=rel):
                self.assertTrue((ROOT / rel).exists())

        self.assertIn("requirements.txt", install)
        self.assertIn(".venv", install)
        self.assertIn("bootstrap-python310.ps1", install)
        self.assertIn("Git.Git", install)
        self.assertIn("OpenJS.NodeJS.LTS", install)
        self.assertIn("astral-sh.uv", install)
        self.assertIn("Set-ExecutionPolicy", install)
        self.assertIn("uv venv --python", install)
        self.assertIn("uv pip install", install)
        self.assertIn("npm install", install)
        self.assertIn("services\\webui\\gui.py", run)
        self.assertIn("npm start", run)
        self.assertIn("git", update)
        self.assertIn("pull", update)
        self.assertIn("--ff-only", update)
        self.assertIn("pull", updater)
        self.assertIn("--ff-only", updater)
        self.assertNotIn("reset", update)
        self.assertNotIn("stash", update)
        self.assertNotIn("pip install", update)
        for stale_update in ["stash", "reset --hard", "pip install"]:
            with self.subTest(stale_update=stale_update):
                self.assertNotIn(stale_update, updater)
        self.assertNotIn("time.sleep", updater)
        self.assertNotIn("range(3)", updater)
        self.assertIn("run.ps1", launcher)
        self.assertIn("uv python install", bootstrap)
        self.assertIn("3.10.15", bootstrap)

        for stale in [
            "services\\installer",
            "services/installer",
            "main_cli",
            "install-only",
            "wheelhouse\\python",
            "questionary",
            "prompt_toolkit",
            "bsdiff4",
            "set_config",
            "verify_config",
        ]:
            with self.subTest(stale=stale):
                self.assertNotIn(stale, install)
                self.assertNotIn(stale, run)
                self.assertNotIn(stale, update)
                self.assertNotIn(stale, launcher)
                self.assertNotIn(stale, updater)
                self.assertNotIn(stale, bootstrap)
                self.assertNotIn(stale, requirements)
                self.assertNotIn(stale, package_init)


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

    def test_git_fetch_failure_keeps_precise_stderr_for_main(self):
        with patch.dict(sys.modules, autoscriptor_logger_stubs()):
            sys.modules.pop("services.core.updater", None)
            from services.core.updater import Updater

        updater = Updater()
        updater._root = str(ROOT)
        updater._git = "git"
        fetch_calls = []

        def fake_run(cmd, **kwargs):
            git_args = cmd[3:]
            if git_args == ["rev-parse", "--is-inside-work-tree"]:
                return subprocess.CompletedProcess(cmd, 0, stdout="true\n", stderr="")
            if git_args == ["rev-parse", "--abbrev-ref", "HEAD"]:
                return subprocess.CompletedProcess(cmd, 0, stdout="src\n", stderr="")
            if git_args[:2] == ["fetch", "origin"]:
                fetch_calls.append(git_args)
                return subprocess.CompletedProcess(cmd, 128, stdout="", stderr="fatal: authentication failed")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with patch("services.core.updater.subprocess.run", side_effect=fake_run):
            has_update = updater.check_update()

        self.assertFalse(has_update)
        self.assertEqual(fetch_calls, [["fetch", "origin", "main"]])
        self.assertEqual(updater.state, "failed")
        self.assertIn("git fetch origin main failed", updater.last_error)
        self.assertIn("fatal: authentication failed", updater.last_error)

    def test_git_check_reports_local_ahead_of_origin_main_as_latest(self):
        with patch.dict(sys.modules, autoscriptor_logger_stubs()):
            sys.modules.pop("services.core.updater", None)
            from services.core.updater import Updater

        updater = Updater()
        updater._root = str(ROOT)
        updater._git = "git"
        local = "aaaaaaaa11111111222222223333333344444444"
        remote = "bbbbbbbb11111111222222223333333344444444"

        def fake_run(cmd, **kwargs):
            git_args = cmd[3:]
            if git_args == ["rev-parse", "--is-inside-work-tree"]:
                return subprocess.CompletedProcess(cmd, 0, stdout="true\n", stderr="")
            if git_args == ["rev-parse", "--abbrev-ref", "HEAD"]:
                return subprocess.CompletedProcess(cmd, 0, stdout="src\n", stderr="")
            if git_args == ["fetch", "origin", "main"]:
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            if git_args == ["rev-parse", "HEAD"]:
                return subprocess.CompletedProcess(cmd, 0, stdout=f"{local}\n", stderr="")
            if git_args == ["rev-parse", "origin/main"]:
                return subprocess.CompletedProcess(cmd, 0, stdout=f"{remote}\n", stderr="")
            if git_args == ["rev-list", "--left-right", "--count", "HEAD...origin/main"]:
                return subprocess.CompletedProcess(cmd, 0, stdout="3\t0\n", stderr="")
            return subprocess.CompletedProcess(cmd, 99, stdout="", stderr=f"unexpected git args: {git_args}")

        with patch("services.core.updater.subprocess.run", side_effect=fake_run):
            has_update = updater.check_update()
            status = updater.get_status()

        self.assertFalse(has_update)
        self.assertEqual(updater.state, "idle")
        self.assertEqual(status["remote_branch"], "main")
        self.assertEqual(status["ahead_count"], 3)
        self.assertEqual(status["behind_count"], 0)
        self.assertEqual(status["remote_version"], remote[:8])
        self.assertEqual(status["changelog"], "")

    def test_git_run_reports_local_ahead_of_origin_main_as_latest_without_pull(self):
        with patch.dict(sys.modules, autoscriptor_logger_stubs()):
            sys.modules.pop("services.core.updater", None)
            from services.core.updater import Updater

        updater = Updater()
        updater._root = str(ROOT)
        updater._git = "git"
        local = "aaaaaaaa11111111222222223333333344444444"
        remote = "bbbbbbbb11111111222222223333333344444444"
        git_calls = []

        def fake_run(cmd, **kwargs):
            git_args = cmd[3:]
            git_calls.append(git_args)
            if git_args == ["rev-parse", "--is-inside-work-tree"]:
                return subprocess.CompletedProcess(cmd, 0, stdout="true\n", stderr="")
            if git_args == ["rev-parse", "--abbrev-ref", "HEAD"]:
                return subprocess.CompletedProcess(cmd, 0, stdout="src\n", stderr="")
            if git_args == ["status", "--porcelain"]:
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            if git_args == ["fetch", "origin", "main"]:
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            if git_args == ["rev-parse", "HEAD"]:
                return subprocess.CompletedProcess(cmd, 0, stdout=f"{local}\n", stderr="")
            if git_args == ["rev-parse", "origin/main"]:
                return subprocess.CompletedProcess(cmd, 0, stdout=f"{remote}\n", stderr="")
            if git_args == ["rev-list", "--left-right", "--count", "HEAD...origin/main"]:
                return subprocess.CompletedProcess(cmd, 0, stdout="2\t0\n", stderr="")
            return subprocess.CompletedProcess(cmd, 99, stdout="", stderr=f"unexpected git args: {git_args}")

        with patch("services.core.updater.subprocess.run", side_effect=fake_run):
            success = updater.run_update()
            status = updater.get_status()

        self.assertTrue(success)
        self.assertEqual(updater.state, "done")
        self.assertNotIn(["pull", "--ff-only", "origin", "main"], git_calls)
        self.assertEqual(status["remote_branch"], "main")
        self.assertEqual(status["ahead_count"], 2)
        self.assertEqual(status["behind_count"], 0)
        self.assertEqual(status["remote_version"], remote[:8])


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

    def test_collector_rejects_invalid_runtime_cache_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "codes.json"
            output.write_text("{", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "兑换码缓存 JSON 无效"):
                self.collector.load_payload(output)

    def test_collector_rejects_invalid_config_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.json"
            config.write_text("{", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "配置 JSON 无效"):
                self.collector.load_credentials(config)

    def test_redeem_codes_use_single_authoritative_file(self):
        content = "\n".join(
            path.read_text(encoding="utf-8", errors="ignore")
            for path in [
                ROOT / "scripts/collect_zmxy_redeem_2026.py",
                ROOT / "services/webui/routes/news.py",
                ROOT / "services/webui/static/js/components/NewsPanel.js",
            ]
        )

        self.assertIn('get_logs_root() / "zmxy_redeem_codes.json"', content)
        self.assertNotIn("docs/zmxy_redeem_codes.json", content)
        self.assertNotIn('"assets" / "redeem_codes" / "zmxy_redeem_codes.json"', content)
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
        translations = (ROOT / "ZmxyOL/task/translations.py").read_text(
            encoding="utf-8",
            errors="ignore",
        )

        self.assertIn('_GIFT_REDEEM_TASK_PATH = "一般任务/活动/兑换豪礼礼品兑换"', server)
        self.assertIn("未找到兑换码任务，请确认一般任务已加载", server)
        self.assertFalse((ROOT / "ZmxyOL/task/_manifest.py").exists())
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
