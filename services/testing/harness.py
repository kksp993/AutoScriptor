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
from typing import Dict, Any
from unittest.mock import MagicMock
from logzero import logger

from services.testing.mock_tasks import (
    MOCK_TASK_REGISTRY,
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
                    "fn": MOCK_TASK_REGISTRY["task_instant_success"],
                    "on": True,
                    "next_exec_time": 0,
                    "params": {},
                },
                "慢速成功": {
                    "fn": MOCK_TASK_REGISTRY["task_slow_success"],
                    "on": True,
                    "next_exec_time": 0,
                    "params": {},
                },
                "总是失败": {
                    "fn": MOCK_TASK_REGISTRY["task_always_fail"],
                    "on": True,
                    "next_exec_time": 0,
                    "params": {},
                },
                "重试后成功": {
                    "fn": MOCK_TASK_REGISTRY["task_retry_then_succeed"],
                    "on": True,
                    "next_exec_time": 0,
                    "params": {},
                },
                "重试耗尽": {
                    "fn": MOCK_TASK_REGISTRY["task_retry_exhaust"],
                    "on": True,
                    "next_exec_time": 0,
                    "params": {},
                },
                "人工接管": {
                    "fn": MOCK_TASK_REGISTRY["task_human_takeover"],
                    "on": True,
                    "next_exec_time": 0,
                    "params": {},
                },
            },
            "测试参数": {
                "带参数任务": {
                    "fn": MOCK_TASK_REGISTRY["task_with_params"],
                    "on": True,
                    "next_exec_time": 0,
                    "params": {
                        "difficulty": "normal",
                        "region": "village",
                        "loops": 5,
                    },
                    "param_meta": {
                        "difficulty": "services.testing.mock_tasks.MockDifficulty",
                        "region": "services.testing.mock_tasks.MockRegion",
                    },
                },
            },
        },
        "一般任务": {
            "一次性任务": {
                "fn": MOCK_TASK_REGISTRY["task_instant_success"],
                "on": True,
                "next_exec_time": 0,
                "params": {},
            },
        },
        "每周任务": {
            "随机结果": {
                "fn": MOCK_TASK_REGISTRY["task_random_outcome"],
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

    def clear(self, clear_signals=False):
        pass

    def stop(self):
        pass

    def add(self, *a, **kw):
        pass

    def remove(self, name):
        pass

    def signal(self, key, default=None):
        return default

    def set_signal(self, key, value):
        return value

    def get_idfs(self):
        return set()

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
        self._temp_dir = None
        self._patches = {}

    def setup(self):
        """注入 mock 对象，使 services.core 可以脱离真实模拟器运行。"""
        from services.testing.mock_tasks import reset_counters
        reset_counters()

        # 1. 构建测试配置
        test_config = build_test_config(**self._config_kwargs)

        # 2. 创建临时配置文件
        self._temp_dir = tempfile.mkdtemp(prefix="autoscriptor_test_")
        config_path = os.path.join(self._temp_dir, "config.json")
        safe = copy.deepcopy(test_config)
        # 清除 fn（不可序列化）
        self._strip_fn(safe.get("tasks", {}))
        safe.pop("game", None)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(safe, f, ensure_ascii=False, indent=2)

        # 3. 注入 cfg
        from AutoScriptor.utils.constant import cfg
        self._original_cfg_config = copy.deepcopy(cfg._config)
        cfg._config = test_config
        cfg.CONFIG_PATH = config_path

        # 4. 注入 mock 对象到 task_manager 模块的全局命名空间
        import services.core.task_manager as tm_mod
        self._patches = {
            "mixctrl": getattr(tm_mod, "mixctrl", None),
            "bg": getattr(tm_mod, "bg", None),
            "mm": getattr(tm_mod, "mm", None),
            "sleep": getattr(tm_mod, "sleep", None),
            "dismiss_floating_window": getattr(tm_mod, "dismiss_floating_window", None),
            "ensure_app_running": getattr(tm_mod, "ensure_app_running", None),
            "TaskRequireReTry": getattr(tm_mod, "TaskRequireReTry", None),
            "RequestHumanTakeover": getattr(tm_mod, "RequestHumanTakeover", None),
        }

        mock_mixctrl = MockMixCtrl()
        mock_bg = MockBg()
        mock_mm = MockMm()

        tm_mod.mixctrl = mock_mixctrl
        tm_mod.bg = mock_bg
        tm_mod.mm = mock_mm
        tm_mod.sleep = time.sleep  # 使用真实 sleep（时间很短）
        tm_mod.dismiss_floating_window = lambda **kw: True
        tm_mod.ensure_app_running = lambda *a, **kw: (mock_mixctrl, None)
        tm_mod.TaskRequireReTry = MockTaskRequireReTry
        tm_mod.RequestHumanTakeover = MockRequestHumanTakeover

        logger.info("🧪 TestHarness.setup() 完成 — mock 环境已就绪")

    def teardown(self):
        """恢复原始状态。"""
        # 恢复 cfg
        if self._original_cfg_config is not None:
            from AutoScriptor.utils.constant import cfg
            cfg._config = self._original_cfg_config
            cfg.CONFIG_PATH = os.path.join(os.getcwd(), "config.json")

        # 恢复 task_manager 模块的全局变量
        import services.core.task_manager as tm_mod
        for attr, original in self._patches.items():
            if original is not None:
                setattr(tm_mod, attr, original)

        # 清理临时目录
        if self._temp_dir and os.path.isdir(self._temp_dir):
            import shutil
            shutil.rmtree(self._temp_dir, ignore_errors=True)

        logger.info("🧪 TestHarness.teardown() 完成 — 环境已恢复")

    @staticmethod
    def _strip_fn(data):
        """递归移除 dict 中的 fn 键（不可 JSON 序列化）。"""
        if isinstance(data, dict):
            data.pop("fn", None)
            for v in data.values():
                TestHarness._strip_fn(v)
