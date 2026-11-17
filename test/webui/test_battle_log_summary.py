"""Browser battle summaries must not erase diagnostic logs or hide other phases."""
from __future__ import annotations

import io
import logging
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, nullcontext
from queue import Empty, Queue
from unittest.mock import patch

from AutoScriptor.core.background import BG_SIGNALS
from AutoScriptor.core.targets import T
from AutoScriptor.logging.logger import logger
from AutoScriptor.utils.cancel import TaskCancelled
from backend.webui.log_stream import QueueHandler
from ZmxyOL.character import hero as hero_module


class BattleBackground:
    def __init__(self):
        self.signals = {}

    def scope(self, *args, **kwargs):
        return nullcontext(self)

    def interval(self, seconds):
        return nullcontext()

    def protect_clear(self):
        return nullcontext()

    def add(self, *args, **kwargs):
        pass

    def signal(self, name, default=None):
        return self.signals.get(name, default)

    def set_signal(self, name, value):
        self.signals[name] = value


class BattleLogSummaryTest(unittest.TestCase):
    def setUp(self):
        patches = ExitStack()
        self.addCleanup(patches.close)
        self.messages = Queue()
        self.browser_handler = QueueHandler(self.messages, level=logging.DEBUG)
        self.diagnostics = io.StringIO()
        self.diagnostic_handler = logging.StreamHandler(self.diagnostics)
        self.diagnostic_handler.setLevel(logging.DEBUG)
        patches.enter_context(patch.object(
            logger, "handlers", [self.browser_handler, self.diagnostic_handler],
        ))
        self.background = BattleBackground()
        patches.enter_context(patch.object(hero_module, "bg", self.background))
        patches.enter_context(patch.object(hero_module, "switch_base"))
        patches.enter_context(patch.object(hero_module, "sleep"))
        patches.enter_context(patch.object(hero_module, "check_cancel_raise"))
        patches.enter_context(patch.object(
            hero_module, "click", side_effect=lambda *args, **kwargs: logger.info("combo input"),
        ))
        self.hero = hero_module.Hero()

    def browser_messages(self):
        messages = []
        while True:
            try:
                messages.append(self.messages.get_nowait())
            except Empty:
                return "\n".join(messages)

    def run_flow(self, callback):
        with patch.object(self.hero, "_resolve_flow", return_value=callback):
            self.hero.battle_loop(max_duration=10)

    def test_many_combos_have_one_browser_summary_but_all_diagnostics(self):
        rounds = []

        def flow(hero):
            rounds.append(1)
            hero.battle()
            logger.debug("combo debug detail")
            if len(rounds) == 3:
                self.background.set_signal(BG_SIGNALS.TRY_EXIT, True)

        self.run_flow(flow)
        browser = self.browser_messages()
        diagnostics = self.diagnostics.getvalue()
        self.assertEqual(len(rounds), 3)
        self.assertEqual(browser.count("自动战斗中..."), 1)
        self.assertNotIn("combo input", browser)
        self.assertNotIn("combo debug detail", browser)
        self.assertGreater(diagnostics.count("combo input"), 3)
        self.assertEqual(diagnostics.count("combo debug detail"), 3)
        self.assertIn("battle_loop 开始", browser)
        self.assertIn("battle_loop 结束", browser)

    def test_custom_flow_keeps_warnings_and_other_thread_logs_visible(self):
        def flow(hero):
            logger.info("custom attack detail")
            logger.warning("combat warning")
            logger.error("combat error")
            try:
                raise ValueError("diagnostic traceback")
            except ValueError:
                logger.info("exception context", exc_info=True)
            with ThreadPoolExecutor(max_workers=1) as worker:
                worker.submit(logger.info, "background milestone").result(timeout=5)
            self.background.set_signal(BG_SIGNALS.TRY_EXIT, True)

        self.run_flow(flow)
        browser = self.browser_messages()
        self.assertEqual(browser.count("自动战斗中..."), 1)
        self.assertNotIn("custom attack detail", browser)
        self.assertIn("combat warning", browser)
        self.assertIn("combat error", browser)
        self.assertIn("ValueError: diagnostic traceback", browser)
        self.assertIn("background milestone", browser)
        self.assertIn("custom attack detail", self.diagnostics.getvalue())

    def test_advance_and_exit_remain_visible_without_repeating_summary(self):
        rounds = []

        def advance():
            logger.info("advance movement")
            return self.hero

        def flow(hero):
            rounds.append(1)
            hero.battle()
            if len(rounds) == 1:
                self.background.set_signal(BG_SIGNALS.BUILTIN_ADVANCE, True)
            else:
                hero.way_to_exit(until=T("test exit"), no_travel=True)
                self.background.set_signal(BG_SIGNALS.TRY_EXIT, True)

        with (
            patch.object(self.hero, "travel", side_effect=advance),
            patch.object(hero_module, "wait_for_signal", return_value=True),
        ):
            self.run_flow(flow)
        browser = self.browser_messages()
        self.assertEqual(browser.count("自动战斗中..."), 1)
        self.assertIn("前进", browser)
        self.assertIn("advance movement", browser)
        self.assertIn("离开关卡 12", browser)
        self.assertIn("离开关卡 3.1", browser)
        self.assertNotIn("combo input", browser)

    def test_failure_and_cancellation_restore_browser_logging_for_next_run(self):
        for error in (RuntimeError("combo failed"), TaskCancelled("cancelled")):
            with self.subTest(error=type(error).__name__):
                def failing_flow(hero):
                    logger.info("failing combo input")
                    raise error

                with self.assertRaises(type(error)):
                    self.run_flow(failing_flow)
                logger.info("after battle")
                browser = self.browser_messages()
                self.assertEqual(browser.count("自动战斗中..."), 1)
                self.assertNotIn("failing combo input", browser)
                self.assertIn("after battle", browser)

    def test_direct_battle_hides_inputs_and_respects_browser_warning_level(self):
        self.hero.battle()
        browser = self.browser_messages()
        self.assertEqual(browser.count("自动战斗中..."), 1)
        self.assertNotIn("combo input", browser)
        self.browser_handler.setLevel(logging.WARNING)

        def flow(hero):
            logger.warning("visible warning")
            self.background.set_signal(BG_SIGNALS.TRY_EXIT, True)

        self.run_flow(flow)
        browser = self.browser_messages()
        self.assertEqual(browser, "visible warning")

    def test_yuxu_background_combos_share_one_summary_and_keep_exit_logs(self):
        from ZmxyOL.battle.procedure import kunlunshan

        def read_enemy_count(*args, **kwargs):
            logger.info("enemy count detail")
            return next(enemy_counts)

        enemy_counts = iter([3, 2, 2])
        with (
            patch.object(kunlunshan, "h", self.hero),
            patch.object(kunlunshan, "bg", self.background),
            patch.object(kunlunshan, "extract_info", side_effect=read_enemy_count),
            patch.object(kunlunshan, "wait_for_disappear"),
            patch.object(hero_module, "wait_for_signal", return_value=True),
            patch("tasks.task_state.set_task_status"),
        ):
            kunlunshan.kls_yxd_callback(self.background, task_path="test/kunlunshan")

        browser = self.browser_messages()
        self.assertEqual(browser.count("自动战斗中..."), 1)
        self.assertNotIn("enemy count detail", browser)
        self.assertEqual(self.diagnostics.getvalue().count("enemy count detail"), 3)
        self.assertIn("离开关卡", browser)
        self.assertIn("hero 倍速恢复", browser)


if __name__ == "__main__":
    unittest.main()
