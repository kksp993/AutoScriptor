"""
Test Harness: 测试环境搭建
===========================
提供 mock cfg、mock mixctrl、mock 异常类的注入。
使 TaskManager 和 Scheduler 可以脱离真实模拟器运行。

使用方法：
    harness = TestHarness()
    harness.setup()          # 注入 mock 对象
    # ... 运行测试 ...
    harness.teardown()       # 恢复原始状态
"""

import copy
import json
import os
import sys
import time
import tempfile
import shutil
from contextlib import contextmanager
from typing import Dict, Any
from unittest.mock import MagicMock
from AutoScriptor.utils.logger import logger

from services.testing.mock_tasks import (
    MOCK_TASK_REGISTRY,
    MOCK_REGISTRY_ENTRIES,
    MockTaskRequireReTry,
    MockRequestHumanTakeover,
)


def build_test_config(
    max_retry: int = 2,
    restart_on_error: bool = False,
    character_name: str = "测试角色",
    extra_tasks: Dict[str, Any] | None = None,
) -> dict:
    """构建测试用配置字典。

    Args:
        max_retry: 每个任务最大重试次数
        restart_on_error: 是否在错误时重启应用（测试中通常关闭）
        character_name: 模拟角色名（非空表示已验证）
        extra_tasks: 额外的自定义任务配置
    """
    now = time.time()
    tasks = {
        "每日任务": {
            "测试村庄": {
                "立即成功": {
                    "on": True,
                    "next_exec_time": 0,
                    "params": {},
                },
                "慢速成功": {
                    "on": True,
                    "next_exec_time": 0,
                    "params": {},
                },
                "总是失败": {
                    "on": True,
                    "next_exec_time": 0,
                    "params": {},
                },
                "重试后成功": {
                    "on": True,
                    "next_exec_time": 0,
                    "params": {},
                },
                "重试耗尽": {
                    "on": True,
                    "next_exec_time": 0,
                    "params": {},
                },
                "人工接管": {
                    "on": True,
                    "next_exec_time": 0,
                    "params": {},
                },
            },
            "测试参数": {
                "带参数任务": {
                    "on": True,
                    "next_exec_time": 0,
                    "params": {
                        "difficulty": "normal",
                        "region": "village",
                        "loops": 5,
                    },
                },
            },
        },
        "一般任务": {
            "一次性任务": {
                "on": True,
                "next_exec_time": 0,
                "params": {},
            },
        },
        "每周任务": {
            "随机结果": {
                "on": False,
                "next_exec_time": 0,
                "params": {},
            },
        },
    }

    if extra_tasks:
        tasks.update(extra_tasks)

    return {
        "app": {
            "app_to_start": "com.test.mock",
            "auto_start": False,
            "max_retry": max_retry,
            "name": "TestApp",
            "restart_on_error": restart_on_error,
            "run_in_background": False,
            "debug_mode": False,
            "cpu_cores": 4,
        },
        "ocr": {"use_gpu": False},
        "emulator": {
            "index": 0,
            "adb_addr": "127.0.0.1:0",
            "mumu_folder": "",
            "emu_path": "",
            "adb_path": "",
            "post_execution": "NULL",
        },
        "llm": {"use_agent": False, "url": ""},
        "encryption": {},
        "game": {
            "account": "test_account",
            "password": "test_password",
            "character_name": character_name,
        },
        "tasks": tasks,
        "status": {},
    }


class MockMixCtrl:
    """模拟 MixControl，所有操作都是 no-op。"""

    def __init__(self):
        self.app = MockAppControl()
        self.clicks = []
        self.mode = "mock"

    def click(self, x, y):
        self.clicks.append((x, y))

    def swipe(self, x1, y1, x2, y2, duration_s=1):
        pass

    def long_click(self, x, y, duration=1.0):
        pass

    def input_text(self, text):
        pass

    def screenshot(self):
        import numpy as np
        return np.zeros((720, 1280, 3), dtype=np.uint8)

    def release_all_keys(self):
        pass

    def switch_to_mumu(self):
        pass

    def switch_to_nemu(self):
        pass

    def locate(self, tgt_triples, screenshot=None):
        return [[] for _ in tgt_triples]

    class window:
        @staticmethod
        def hidden():
            pass


class MockAppControl:
    """模拟 mixctrl.app 接口。"""

    def __init__(self):
        self._state = "running"

    def launch(self, package):
        self._state = "running"
        logger.debug(f"[mock] app.launch({package})")

    def close(self, package):
        self._state = "stopped"
        logger.debug(f"[mock] app.close({package})")

    def state(self, package):
        return self._state


class MockBg:
    """模拟 BackgroundMonitor (bg)。"""

    def __init__(self):
        self._callbacks = {}
        self._signals = {}

    def clear(self, clear_signals=False):
        self._callbacks.clear()
        if clear_signals:
            self._signals.clear()

    def clear_signals(self):
        self._signals.clear()

    def stop(self):
        pass

    def add(self, name=None, identifier=None, callback=None, **kw):
        if name is None:
            raise TypeError("MockBg.add() missing required argument: 'name'")
        self._callbacks[name] = {
            "idf": identifier,
            "cb": callback,
            **kw,
        }
        return name

    def remove(self, name, expected_info=None):
        if expected_info is not None and self._callbacks.get(name) is not expected_info:
            return
        self._callbacks.pop(name, None)

    def signal(self, key, default=None):
        return self._signals.get(key, default)

    def set_signal(self, key, value):
        self._signals[key] = value
        return value

    def wait_signal(self, key, expected=True, *, timeout=None, interval=0.2, default=None):
        start = time.time()
        while True:
            current = self.signal(key, default)
            matched = expected(current) if callable(expected) else current == expected
            if matched:
                return current
            if timeout is not None and time.time() - start >= timeout:
                raise TimeoutError(f"MockBg wait_signal timeout: {key} != {expected!r}")
            time.sleep(interval)

    @contextmanager
    def scope(self, prefix=None, *, clear_signals=False):
        items = []

        class Scope:
            def _name(scope_self, name):
                raw = str(name)
                if not prefix or raw.startswith(f"{prefix}:"):
                    return raw
                return f"{prefix}:{raw}"

            def add(scope_self, name, identifier, callback, **kwargs):
                full_name = scope_self._name(name)
                self.add(full_name, identifier, callback, **kwargs)
                items.append((full_name, self._callbacks.get(full_name)))
                return full_name

            def remove(scope_self, name):
                full_name = scope_self._name(name)
                remaining = []
                for item_name, info in items:
                    if item_name == full_name:
                        self.remove(item_name, expected_info=info)
                    else:
                        remaining.append((item_name, info))
                items[:] = remaining

            def signal(scope_self, key, default=None):
                return self.signal(key, default)

            def set_signal(scope_self, key, value):
                return self.set_signal(key, value)

            def wait_signal(scope_self, *args, **kwargs):
                return self.wait_signal(*args, **kwargs)

        try:
            yield Scope()
        finally:
            for name, info in reversed(items):
                self.remove(name, expected_info=info)
            if clear_signals:
                self.clear_signals()

    @contextmanager
    def protect_clear(self):
        yield self

    def get_idfs(self):
        return set(self._callbacks)

    @property
    def running(self):
        return True


class MockMm:
    """模拟 MapManager (mm)。"""

    def set_region(self, region):
        logger.debug(f"[mock] mm.set_region({region})")


class TestHarness:
    """
    测试环境管理器。

    setup() 注入 mock 对象到 sys.modules 和关键模块。
    teardown() 恢复原始状态。

    用法：
        harness = TestHarness(max_retry=2)
        harness.setup()
        # 此时 TaskManager / Scheduler 可以正常使用
        harness.teardown()
    """

    def __init__(self, **config_kwargs):
        self._config_kwargs = config_kwargs
        self._original_cfg_config = None
        self._original_cfg_config_path = None
        self._original_cfg_accounts_dir = None
        self._original_mgr_state = None
        self._original_registry = None
        self._original_env_testing = None
        self._temp_dir = None
        self._patches = {}

    def setup(self):
        """注入 mock 对象，使 services.core 可以脱离真实模拟器运行。"""
        from services.testing.mock_tasks import reset_counters
        reset_counters()

        # 1. 构建测试配置
        test_config = build_test_config(**self._config_kwargs)

        # 2. 创建临时配置文件和临时账号文件。cfg.save_config() 会经由
        # ConfigManager 写入账号文件，必须把 accounts 也隔离出去。
        self._temp_dir = tempfile.mkdtemp(prefix="autoscriptor_test_")
        accounts_dir = os.path.join(self._temp_dir, "accounts")
        os.makedirs(accounts_dir, exist_ok=True)
        config_path = os.path.join(self._temp_dir, "config.json")
        account_name = "test_account"
        server_name = "测试服务器"
        character_name = test_config.get("game", {}).get("character_name") or "测试角色"

        safe = {
            key: copy.deepcopy(test_config.get(key, {}))
            for key in ("app", "ocr", "emulator", "llm")
        }
        safe.update({
            "scheduler": {"auto_start": False},
            "deploy": {},
            "notify": {},
            "update": {},
            "remote_access": {},
            "accounts": {"dir": accounts_dir},
            "current_account": account_name,
        })
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(safe, f, ensure_ascii=False, indent=2)

        account_payload = {
            "encryption": {},
            "active_character": {"server": server_name, "name": character_name},
            "dispatch_queue": [{"server": server_name, "name": character_name}],
            "characters": {
                server_name: {
                    character_name: {
                        "tasks": copy.deepcopy(test_config["tasks"]),
                        "status": copy.deepcopy(test_config.get("status", {})),
                        "game_profession": "通用",
                    },
                },
            },
        }
        self._strip_fn(account_payload)
        with open(os.path.join(accounts_dir, f"{account_name}.json"), "w", encoding="utf-8") as f:
            json.dump(account_payload, f, ensure_ascii=False, indent=2)

        # 3. 注入 cfg
        from AutoScriptor.utils.app_config import cfg
        self._original_env_testing = os.environ.get("AUTOSCRIPTOR_TESTING")
        self._original_cfg_config = copy.deepcopy(cfg._config)
        self._original_cfg_config_path = cfg.CONFIG_PATH
        self._original_cfg_accounts_dir = cfg.ACCOUNTS_DIR
        self._original_mgr_state = {
            "data_root": cfg._mgr.data_root,
            "default_accounts_dir": cfg._mgr.default_accounts_dir,
            "config_path": cfg._mgr.config_path,
            "global_cfg": copy.deepcopy(cfg._mgr.global_cfg),
            "current_acc": cfg._mgr.current_acc,
        }
        os.environ["AUTOSCRIPTOR_TESTING"] = "1"
        cfg.CONFIG_PATH = config_path
        cfg.load_config()
        if cfg._mgr.current_acc:
            cfg._mgr.current_acc.credentials = {
                "account": test_config.get("game", {}).get("account", ""),
                "password": test_config.get("game", {}).get("password", ""),
            }
            cfg._refresh_flat_config()

        # 3.5 注入 TaskRegistry
        from AutoScriptor.utils.task_registry import task_registry
        self._original_registry = dict(task_registry._tasks)
        task_registry.clear()
        for path, entry in MOCK_REGISTRY_ENTRIES.items():
            task_registry.register(
                path,
                entry["fn"],
                entry["order"],
                entry.get("param_meta", {}),
                debug_mode=entry.get("debug_mode", False),
            )

        # 4. 注入 mock 对象到 task_manager 模块的全局命名空间
        import services.core.task_manager as tm_mod
        import services.core.scheduler as sched_mod
        import services.core.runtime_context as rt_mod
        self._patches = {
            "mixctrl": getattr(tm_mod, "mixctrl", None),
            "bg": getattr(tm_mod, "bg", None),
            "mm": getattr(tm_mod, "mm", None),
            "sleep": getattr(tm_mod, "sleep", None),
            "dismiss_floating_window": getattr(tm_mod, "dismiss_floating_window", None),
            "ensure_app_running": getattr(tm_mod, "ensure_app_running", None),
            "TaskRequireReTry": getattr(tm_mod, "TaskRequireReTry", None),
            "RequestHumanTakeover": getattr(tm_mod, "RequestHumanTakeover", None),
            "TaskManager.reload_tasks": tm_mod.TaskManager.reload_tasks,
            "TaskManager._archive_error": tm_mod.TaskManager._archive_error,
            "Scheduler._ensure_character_logged_in": sched_mod.Scheduler._ensure_character_logged_in,
            "runtime_ctx.mixctrl": rt_mod.runtime_ctx.mixctrl,
            "runtime_ctx.mumu": rt_mod.runtime_ctx.mumu,
            "runtime_ctx.refresh": rt_mod.runtime_ctx.refresh,
        }

        mock_mixctrl = MockMixCtrl()
        mock_bg = MockBg()
        mock_mm = MockMm()
        mock_mumu = MagicMock()

        tm_mod.mixctrl = mock_mixctrl
        tm_mod.bg = mock_bg
        tm_mod.mm = mock_mm
        tm_mod.sleep = time.sleep  # 使用真实 sleep（时间很短）
        tm_mod.dismiss_floating_window = lambda **kw: True
        tm_mod.ensure_app_running = lambda *a, **kw: (mock_mixctrl, None)
        tm_mod.TaskRequireReTry = MockTaskRequireReTry
        tm_mod.RequestHumanTakeover = MockRequestHumanTakeover
        rt_mod.runtime_ctx.mixctrl = mock_mixctrl
        rt_mod.runtime_ctx.mumu = mock_mumu

        def _mock_refresh(*args, **kwargs):
            rt_mod.runtime_ctx.mixctrl = mock_mixctrl
            rt_mod.runtime_ctx.mumu = mock_mumu
            return mock_mixctrl, mock_mumu

        rt_mod.runtime_ctx.refresh = _mock_refresh

        def _mock_reload_tasks(_self, security_key=None):
            task_registry.clear()
            for path, entry in MOCK_REGISTRY_ENTRIES.items():
                task_registry.register(
                    path,
                    entry["fn"],
                    entry["order"],
                    entry.get("param_meta", {}),
                    debug_mode=entry.get("debug_mode", False),
                )

        tm_mod.TaskManager.reload_tasks = _mock_reload_tasks
        tm_mod.TaskManager._archive_error = lambda _self, task, exc: None
        sched_mod.Scheduler._ensure_character_logged_in = lambda _self, cfg: None

        logger.info("🧪 TestHarness.setup() 完成 — mock 环境已就绪")

    def teardown(self):
        """恢复原始状态。"""
        # 恢复 TaskRegistry
        if self._original_registry is not None:
            from AutoScriptor.utils.task_registry import task_registry
            task_registry._tasks = self._original_registry

        # 恢复 cfg
        if self._original_cfg_config is not None:
            from AutoScriptor.utils.app_config import cfg
            cfg._config = self._original_cfg_config
            cfg.CONFIG_PATH = self._original_cfg_config_path
            cfg.ACCOUNTS_DIR = self._original_cfg_accounts_dir
            if self._original_mgr_state:
                cfg._mgr.data_root = self._original_mgr_state["data_root"]
                cfg._mgr.default_accounts_dir = self._original_mgr_state["default_accounts_dir"]
                cfg._mgr.config_path = self._original_mgr_state["config_path"]
                cfg._mgr.global_cfg = self._original_mgr_state["global_cfg"]
                cfg._mgr.current_acc = self._original_mgr_state["current_acc"]
            if self._original_env_testing is None:
                os.environ.pop("AUTOSCRIPTOR_TESTING", None)
            else:
                os.environ["AUTOSCRIPTOR_TESTING"] = self._original_env_testing

        # 恢复 task_manager 模块的全局变量
        import services.core.task_manager as tm_mod
        import services.core.scheduler as sched_mod
        import services.core.runtime_context as rt_mod
        for attr, original in self._patches.items():
            if attr == "TaskManager.reload_tasks":
                tm_mod.TaskManager.reload_tasks = original
                continue
            if attr == "TaskManager._archive_error":
                tm_mod.TaskManager._archive_error = original
                continue
            if attr == "Scheduler._ensure_character_logged_in":
                sched_mod.Scheduler._ensure_character_logged_in = original
                continue
            if attr == "runtime_ctx.mixctrl":
                rt_mod.runtime_ctx.mixctrl = original
                continue
            if attr == "runtime_ctx.mumu":
                rt_mod.runtime_ctx.mumu = original
                continue
            if attr == "runtime_ctx.refresh":
                rt_mod.runtime_ctx.refresh = original
                continue
            if original is not None:
                setattr(tm_mod, attr, original)

        # 清理临时目录
        if self._temp_dir and os.path.isdir(self._temp_dir):
            shutil.rmtree(self._temp_dir, ignore_errors=True)

        logger.info("🧪 TestHarness.teardown() 完成 — 环境已恢复")

    @staticmethod
    def _strip_fn(data):
        """递归移除 dict 中的 fn 键（不可 JSON 序列化）。"""
        if isinstance(data, dict):
            data.pop("fn", None)
            for v in data.values():
                TestHarness._strip_fn(v)
