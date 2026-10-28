"""Playback monitoring with a fake clock; never import device/OCR controls."""

import sys
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

from test.manual import shuake
from test.manual.dom_parser import DomParser, MediaState


class TestPlaybackMonitor(unittest.TestCase):
    def setUp(self):
        self.clock_patch = patch.object(shuake, "monotonic", return_value=0)
        self.clock = self.clock_patch.start()
        self.addCleanup(self.clock_patch.stop)
        self.dom = MagicMock(spec=DomParser)
        self.state = MediaState(
            source="https://example.test/video", current_time=12, duration=90,
            paused=False, ended=False, seeking=False, ready_state=4,
            network_state=1, error_code=None,
        )
        self.dom.read_media.return_value = self.state
        self.monitor = shuake.PlaybackMonitor(self.dom)

    def test_progress_uses_media_seconds_and_preserves_unknown_duration(self):
        self.assertEqual(shuake.progress(self.dom), (12, 90))
        self.dom.read_media.return_value = replace(self.state, duration=None)
        self.assertEqual(shuake.progress(self.dom), (12, None))
        self.dom.play_media.assert_not_called()

    def test_short_buffering_waits_and_persistent_stall_has_two_retries(self):
        self.monitor.check()
        self.clock.return_value = 29
        self.monitor.check()
        self.dom.play_media.assert_not_called()
        for checked_at in (30, 60):
            self.clock.return_value = checked_at
            with self.assertLogs(shuake.logger.name, level="WARNING"):
                self.monitor.check()
        self.assertEqual(self.dom.pause_media.call_count, 2)
        self.assertEqual(self.dom.play_media.call_count, 2)
        self.clock.return_value = 90
        with self.assertRaisesRegex(RuntimeError, "readyState=4, networkState=1"):
            self.monitor.check()
        self.assertEqual(self.dom.play_media.call_count, 2)

    def test_real_progress_and_source_change_reset_stall_budget(self):
        self.monitor.check()
        self.clock.return_value = 30
        with self.assertLogs(shuake.logger.name, level="WARNING"):
            self.monitor.check()
        self.clock.return_value = 40
        self.dom.read_media.return_value = replace(self.state, current_time=13)
        self.monitor.check()
        self.assertEqual(self.monitor.recovery_attempts, 0)
        self.clock.return_value = 69
        self.monitor.check()
        self.assertEqual(self.dom.play_media.call_count, 1)
        self.clock.return_value = 70
        self.dom.read_media.return_value = replace(self.state, source="https://example.test/new")
        self.monitor.check()
        self.assertEqual(self.monitor.last_progress_at, 70)
        self.assertEqual(self.dom.play_media.call_count, 1)

    def test_ended_is_not_replayed_and_media_error_fails_without_retries(self):
        self.monitor.check()
        self.clock.return_value = 100
        self.dom.read_media.return_value = replace(self.state, ended=True, paused=True)
        self.monitor.check()
        self.dom.play_media.assert_not_called()
        self.dom.read_media.return_value = replace(self.state, error_code=2)
        with self.assertRaisesRegex(RuntimeError, "code=2"):
            self.monitor.check()
        self.dom.pause_media.assert_not_called()

    def test_paused_recovery_failure_propagates_without_reload_or_retry_loop(self):
        self.dom.read_media.return_value = replace(self.state, paused=True)
        self.monitor.check()
        self.clock.return_value = 30
        self.dom.play_media.side_effect = RuntimeError("autoplay denied")
        with self.assertLogs(shuake.logger.name, level="WARNING"):
            with self.assertRaisesRegex(RuntimeError, "autoplay denied"):
                self.monitor.check()
        self.assertEqual(self.dom.method_calls[-2:], [call.pause_media(), call.play_media()])


class TestTaskDomLifecycle(unittest.TestCase):
    def setUp(self):
        self.controls = SimpleNamespace(
            init=MagicMock(), cfg={"emulator": {"adb_path": "adb.exe"}},
            sleep=MagicMock(),
        )
        self.connection = MagicMock()
        self.watch_course = MagicMock()

    def run_task(self):
        with (
            patch.dict(sys.modules, {"AutoScriptor": self.controls}),
            patch.object(shuake, "connect_android_dom", return_value=self.connection),
            patch.object(shuake, "watch_course", self.watch_course),
        ):
            shuake.task(1)

    def test_course_loop_uses_open_connection_and_cancellable_wait(self):
        self.watch_course.side_effect = lambda *args, **kwargs: self.connection.__exit__.assert_not_called()
        self.run_task()
        self.watch_course.assert_called_once_with(
            self.connection.__enter__.return_value, 1, wait=self.controls.sleep,
        )
        self.controls.init.assert_called_once_with(emulator_index=2)
        self.connection.__exit__.assert_called_once()

    def test_course_failure_propagates_and_exits_connection(self):
        self.watch_course.side_effect = RuntimeError("stuck")
        with self.assertRaisesRegex(RuntimeError, "stuck"):
            self.run_task()
        self.connection.__exit__.assert_called_once()


if __name__ == "__main__":
    unittest.main()
