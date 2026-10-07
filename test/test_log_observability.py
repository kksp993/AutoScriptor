"""日志可观测性的三条契约，全部来自真实排障踩过的坑。

1. **输入动作历史**：日志里的重复点击按 1 秒节流，历史不节流。
   否则「日志里没有这一行」会被读成「这一步没执行」——排查仙宝炼化时
   我正是这样误判过一次，多花了好几轮才确认点击其实发出去了。
2. **错误归档**：要写清日志来源与条数，且只读文件尾部，别为了 100 行全量读盘。
3. **导航诊断**：认出来了就不能报「未知」；诊断不该顺手启动游戏。
"""
from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class _LogRecorder:
    """替身 logger：只关心哪些行真的写进了日志。"""

    def __init__(self):
        self.infos: list[str] = []
        self.debugs: list[str] = []

    def info(self, message):
        self.infos.append(str(message))

    def debug(self, message):
        self.debugs.append(str(message))

    def warning(self, message, *args):
        pass


class ActionHistoryTest(unittest.TestCase):
    def setUp(self):
        from AutoScriptor.core import control

        self.control = control
        self.control.clear_action_history()
        self.addCleanup(self.control.clear_action_history)

        # 只测 _log_action，绕开设备依赖（它定义在 MixControl 上）。
        proxy = object.__new__(control.MixControl)
        proxy.mode = "nemu"
        proxy._last_action_log = defaultdict(float)
        proxy._action_suppressed = defaultdict(int)
        proxy._action_log_interval = 1.0
        self.proxy = proxy
        self.clock = {"now": 1000.0}

    def _log(self, recorder, x: int, y: int):
        with patch.object(self.control, "logger", recorder), \
             patch.object(self.control.time, "monotonic", lambda: self.clock["now"]):
            self.proxy._log_action("Click", f"{x}, {y}")

    def test_history_keeps_every_action_while_the_log_throttles(self):
        """同一秒里连点三次：日志只有一行，历史必须有三条。"""
        recorder = _LogRecorder()
        for x in (100, 200, 300):
            self._log(recorder, x, 100)

        self.assertEqual(len(recorder.infos), 1, "1 秒内重复点击只应写一行 INFO")
        history = self.control.get_action_history()
        self.assertEqual(len(history), 3)
        self.assertIn("100, 100", history[0])
        self.assertIn("300, 100", history[2])

    def test_suppressed_count_is_reported_on_the_next_log_line(self):
        """被节流掉多少条必须写在日志里，否则读日志会以为没执行。"""
        recorder = _LogRecorder()
        for x in (100, 200, 300):
            self._log(recorder, x, 100)
        self.clock["now"] += 2.0
        self._log(recorder, 400, 100)

        self.assertEqual(len(recorder.infos), 2)
        self.assertIn("另有 2 次同类操作未逐条记录", recorder.infos[1])
        self.assertNotIn("另有", recorder.infos[0])

    def test_history_is_bounded(self):
        recorder = _LogRecorder()
        limit = self.control._ACTION_HISTORY_LIMIT
        for index in range(limit + 25):
            self._log(recorder, index, 0)

        history = self.control.get_action_history()
        self.assertEqual(len(history), limit)
        self.assertNotIn("0, 0", history[0], "最旧的应当被挤掉")

    def test_history_carries_millisecond_timestamps(self):
        """秒级时间戳分不出先后顺序，点击历史必须带毫秒。"""
        self._log(_LogRecorder(), 100, 100)

        first_line = self.control.get_action_history()[0]
        self.assertRegex(first_line, r"^\d{2}:\d{2}:\d{2}\.\d{3} ")

    def test_clear_empties_the_history(self):
        self._log(_LogRecorder(), 100, 100)
        self.assertTrue(self.control.get_action_history())

        self.control.clear_action_history()

        self.assertEqual(self.control.get_action_history(), [])


class ActionHistoryRunBoundaryTest(unittest.TestCase):
    """每轮任务开始时清空：归档里只该出现这一轮的操作序列。"""

    def setUp(self):
        import copy

        from AutoScriptor.utils.app_config import cfg
        from tasks.task_register import task_registry

        self._cfg_backup = copy.deepcopy(cfg._config)
        self._reg_backup = dict(task_registry._tasks)
        task_registry.clear()
        cfg._config = {
            "app": {"app_to_start": "com.test.app", "max_attempts": 1, "restart_on_error": False},
            "emulator": {"post_execution": "none"},
            "ocr": {"use_gpu": False},
            "game": {"character_name": "测试角色"},
            "tasks": {"任务": {"on": True, "next_exec_time": 0, "params": {}}},
        }

        def ok():
            return None

        # debug=False：清空与 debug 无关，任何一轮都要清。
        task_registry.register("测试/任务", ok, debug=False)
        self.addCleanup(self._restore, cfg, task_registry)

    def _restore(self, cfg, task_registry):
        cfg._config = self._cfg_backup
        task_registry._tasks = self._reg_backup

    def test_task_run_clears_the_history_before_executing(self):
        from orchestrator import task_manager as tm_mod
        from orchestrator.task_manager import TaskManager

        tm = TaskManager()
        mixctrl = SimpleNamespace(release_all_keys=lambda: None)
        with patch.object(tm_mod.runtime_ctx, "mixctrl", mixctrl), \
             patch.object(tm_mod, "new_task_video_recorder", return_value=None), \
             patch.object(tm_mod, "clear_action_history") as clear:
            tm._execute_single_task("测试/任务")

        clear.assert_called_once_with()


class ArchiveLogTailTest(unittest.TestCase):
    def setUp(self):
        from AutoScriptor.logging import log_archiver

        self.archiver = log_archiver
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.log_path = Path(self._tmp.name) / "webui.log"

    def _write_log(self, line_count: int) -> None:
        with self.log_path.open("w", encoding="utf-8") as handle:
            for index in range(line_count):
                handle.write(f"23:00:00 | INFO | line-{index:06d}\n")

    def _tail(self, limit: int = 100):
        with patch.object(self.archiver, "_current_log_file", return_value=self.log_path):
            return self.archiver._recent_log_lines(limit)

    def test_tail_returns_path_and_last_lines(self):
        self._write_log(30)

        log_path, lines = self._tail(limit=10)

        self.assertEqual(log_path, self.log_path)
        self.assertEqual(len(lines), 10)
        self.assertIn("line-000029", lines[-1])

    def test_tail_drops_a_partially_read_first_line(self):
        """窗口从文件中段开始，首行可能是半行，必须丢掉而不是当成完整日志。"""
        self._write_log(5000)
        self.assertGreater(self.log_path.stat().st_size, 64 * 1024)

        _log_path, lines = self._tail(limit=100)

        self.assertEqual(len(lines), 100)
        self.assertTrue(lines[0].startswith("23:00:00"), f"首行被截断: {lines[0]!r}")
        self.assertIn("line-004999", lines[-1])

    def test_missing_log_file_is_not_an_error(self):
        with patch.object(self.archiver, "_current_log_file", return_value=None):
            log_path, lines = self.archiver._recent_log_lines()

        self.assertIsNone(log_path)
        self.assertEqual(lines, [])

    def test_archive_header_names_the_log_source_and_line_count(self):
        self._write_log(30)
        archive_dir = Path(self._tmp.name) / "archive"
        archive_dir.mkdir()

        with patch.object(self.archiver, "_current_log_file", return_value=self.log_path), \
             patch.object(self.archiver, "collect_default_context", return_value={}):
            self.archiver._write_error_log(
                archive_dir, "260930_000000", "测试/任务", RuntimeError("boom"), None
            )

        content = (archive_dir / "error.log").read_text(encoding="utf-8")
        self.assertIn(f"Recent log lines (tail 30 of {self.log_path})", content)
        self.assertIn("RuntimeError", content)


class ArchiveContextTest(unittest.TestCase):
    def test_action_history_reaches_the_archive_context(self):
        from AutoScriptor.core import control
        from AutoScriptor.logging import log_archiver

        control.clear_action_history()
        self.addCleanup(control.clear_action_history)
        control._action_history.append("23:22:59.014 【nemu】Click: 725, 440")

        context = log_archiver.collect_default_context({
            "bg_active_callbacks": False,
            "bg_signals": False,
            "bg_event_history": False,
            "recognition_trace": False,
            "python_version": False,
            "timestamp": False,
            "mm_current_region": False,
            "locate_region_result": False,
        })

        self.assertIn("action_history", context)
        self.assertIn("Click: 725, 440", str(context["action_history"]))


class NavDiagnosticTest(unittest.TestCase):
    """`locate_region(check_only=True)` 是错误归档的位置诊断。"""

    def setUp(self):
        from ZmxyOL.nav import api as nav_api

        self.nav_api = nav_api

    class _FakeEnvironment:
        name = "极北村庄"

    class _FakeLocation:
        def __init__(self, environments):
            self.envs = environments
            self.name = "法相"

    class _ExplodingCoreApi:
        """一碰就报错：诊断不该启动游戏。"""

        def __getattr__(self, name):
            raise AssertionError(f"归档诊断不该访问 mixctrl（触发了 {name}）")

    def _fake_mm(self):
        location = self._FakeLocation([self._FakeEnvironment()])
        return SimpleNamespace(
            get_region=lambda: ("极北村庄", None),
            set_region=lambda env, loc=None: (env, loc),
            envs={},
            locs={"法相": location},
        )

    def test_recognized_region_is_returned_instead_of_unknown(self):
        """第 1.4 步认出来了就必须报出来；曾经无条件报「未知」造成假阴性。"""
        with patch.object(self.nav_api, "mm", self._fake_mm()), \
             patch.object(self.nav_api, "check_loc_idx", lambda names: 0), \
             patch.object(self.nav_api, "check_env_idx", lambda names: -1), \
             patch.object(self.nav_api, "_core_api", self._ExplodingCoreApi()):
            result = self.nav_api.locate_region(cnt=1, check_only=True)

        self.assertEqual(result, ("极北村庄", "法相"))

    def test_unknown_message_is_factual(self):
        with patch.object(self.nav_api, "mm", self._fake_mm()), \
             patch.object(self.nav_api, "check_loc_idx", lambda names: -1), \
             patch.object(self.nav_api, "check_env_idx", lambda names: -1), \
             patch.object(self.nav_api, "_core_api", self._ExplodingCoreApi()):
            result = self.nav_api.locate_region(cnt=1, check_only=True)

        self.assertEqual(result, "当前位置未知")
        self.assertNotIn("本工具", result)
        self.assertNotIn("自行判断", result)

    def test_diagnostic_does_not_launch_the_game(self):
        """cnt=1 跳过冷启动分支；否则每次写归档都会启动游戏并 sleep 2 秒。"""
        with patch.object(self.nav_api, "mm", self._fake_mm()), \
             patch.object(self.nav_api, "check_loc_idx", lambda names: -1), \
             patch.object(self.nav_api, "check_env_idx", lambda names: -1), \
             patch.object(self.nav_api, "sleep") as sleep, \
             patch.object(self.nav_api, "_core_api", self._ExplodingCoreApi()):
            self.nav_api.locate_region(cnt=1, check_only=True)

        sleep.assert_not_called()


class WebUILogRotationTest(unittest.TestCase):
    def test_webui_log_file_is_bounded(self):
        from logging.handlers import RotatingFileHandler

        from backend.webui import log_stream

        handler = log_stream._FILE_HANDLER
        self.assertIsInstance(handler, RotatingFileHandler)
        self.assertEqual(handler.maxBytes, 8 * 1024 * 1024)
        self.assertEqual(handler.backupCount, 3)
        self.assertTrue(str(handler.baseFilename).endswith("webui.log"))


if __name__ == "__main__":
    unittest.main()
