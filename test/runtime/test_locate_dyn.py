"""locate_dyn: fixed baseline, same-frame boxes, side-length filtering and bounded waits.

Real pixel processing runs against synthetic frames; only capture, time and target
recognition are substituted. No device, OCR model or production config is used.
"""

import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from AutoScriptor.core import api
from AutoScriptor.core.box import Box
from AutoScriptor.core.targets import B, T, ImageTarget, UiEntry
from AutoScriptor.utils.cancel import TaskCancelled


class LocateDynTest(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.now = 0.0
        self.frame = np.zeros((64, 96, 3), dtype=np.uint8)
        self.control = SimpleNamespace(screenshot=Mock(return_value=self.frame), locate=Mock())
        clock = SimpleNamespace(monotonic=lambda: self.now, time=lambda: self.now, perf_counter=lambda: self.now)
        self.stack.enter_context(patch.object(api, "time", clock))
        self.stack.enter_context(patch.object(api, "mixctrl", self.control))
        self.wait = self.stack.enter_context(patch.object(api, "cancellable_sleep", side_effect=self.advance))
        self.stack.enter_context(patch.object(api, "record_recognition_result"))

    def advance(self, seconds):
        self.now += seconds

    def test_fixed_baseline_survives_reused_capture_buffer(self):
        baseline = np.full_like(self.frame, 100)
        intermediate, changed = baseline.copy(), baseline.copy()
        intermediate[15:23, 22:31, 0] = 89
        changed[15:23, 22:31, 0] = 80
        buffer = baseline.copy()
        frames = iter((baseline, intermediate, changed))

        def capture():
            np.copyto(buffer, next(frames))
            return buffer

        self.control.screenshot.side_effect = capture
        result = api.locate_dyn(B(20, 10, 40, 30), 13)

        self.assertEqual(result, [Box(22, 15, 9, 8)])
        self.assertEqual(self.control.screenshot.call_count, 3)
        self.control.locate.assert_not_called()

    def test_collects_all_matches_from_one_frame_across_regions(self):
        changed = self.frame.copy()
        changed[12:20, 12:20] = 20
        changed[12:20, 26:34] = 20
        changed[42:50, 62:70] = 20
        changed[0:8, 0:8] = 255  # Outside every requested region.
        self.control.screenshot.side_effect = [self.frame, changed]

        result = api.locate_dyn([
            B(60, 40, 20, 20), B(10, 10, 30, 20),
            B(10, 10, 30, 20), B(45, 10, 10, 10),
        ], 13)

        self.assertEqual(result, [Box(12, 12, 8, 8), Box(26, 12, 8, 8), Box(62, 42, 8, 8)])
        self.assertEqual(self.control.screenshot.call_count, 2)

    def test_min_area_means_both_side_lengths_with_five_pixel_tolerance(self):
        changed = self.frame.copy()
        changed[5:11, 5:13] = 20  # Exactly 8 by 6.
        changed[20:40, 5:12] = 20  # Width is one pixel too small.
        changed[5:10, 30:50] = 20  # Height is one pixel too small.
        self.control.screenshot.side_effect = [self.frame, changed]

        self.assertEqual(api.locate_dyn(B(0, 0, 96, 64), (13, 11)), [Box(5, 5, 8, 6)])

    def test_eight_connected_sparse_pixels_use_bounding_size_not_pixel_count(self):
        changed = self.frame.copy()
        diagonal = np.arange(8, 15)
        changed[diagonal, diagonal, 2] = 20
        self.control.screenshot.side_effect = [self.frame, changed]

        self.assertEqual(api.locate_dyn(B(0, 0, 96, 64), 12), [Box(8, 8, 7, 7)])

    def test_does_not_accumulate_different_frames(self):
        horizontal, vertical, complete = (self.frame.copy() for _index in range(3))
        horizontal[8:12, 8:16] = 30
        vertical[8:16, 8:12] = 30
        complete[30:38, 40:48] = 30
        self.control.screenshot.side_effect = [self.frame, horizontal, vertical, complete]

        self.assertEqual(api.locate_dyn(B(0, 0, 96, 64), 13), [Box(40, 30, 8, 8)])
        self.assertEqual(self.control.screenshot.call_count, 4)

    def test_resolves_text_image_and_box_once_without_losing_multiple_hits(self):
        changed = self.frame.copy()
        for left in (5, 30, 60):
            changed[10:18, left:left + 8] = 30
        self.control.screenshot.side_effect = [self.frame, changed]
        self.control.locate.return_value = [
            [Box(5, 10, 10, 10), Box(30, 10, 10, 10)],
            [Box(60, 10, 10, 10)], [Box(80, 40, 10, 10)],
        ]
        image_target = ImageTarget(UiEntry(img=np.ones((4, 4, 3), dtype=np.uint8), box=Box(0, 0, 96, 64)))

        result = api.locate_dyn([T("marker"), image_target, B(80, 40, 10, 10)], 13)

        self.assertEqual(result, [Box(5, 10, 8, 8), Box(30, 10, 8, 8), Box(60, 10, 8, 8)])
        self.control.locate.assert_called_once()
        self.assertEqual(self.control.screenshot.call_count, 2)

    def test_single_text_target_keeps_every_located_box(self):
        changed = self.frame.copy()
        changed[10:18, 30:38] = 30
        self.control.screenshot.side_effect = [self.frame, changed]
        self.control.locate.return_value = [[Box(5, 10, 10, 10), Box(30, 10, 10, 10)]]

        self.assertEqual(api.locate_dyn(T("marker"), 13), [Box(30, 10, 8, 8)])
        self.control.locate.assert_called_once()

    def test_target_resolution_uses_the_same_timeout_budget(self):
        def resolve(*arguments, **options):
            self.advance(0.25)
            return [[Box(0, 0, 20, 20)]]

        self.control.locate.side_effect = resolve
        with self.assertRaises(TimeoutError):
            api.locate_dyn(T("marker"), 10, interval=0.2, timeout=0.3)

        self.assertAlmostEqual(self.now, 0.3)
        self.assertEqual(self.control.screenshot.call_count, 1)

    def test_normalization_cannot_extend_the_deadline(self):
        self.control.locate.return_value = [[Box(0, 0, 20, 20)]]

        def convert(box):
            self.advance(0.25)
            return B(box)

        def capture():
            self.advance(0.08)
            return np.full_like(self.frame, 100 * (self.control.screenshot.call_count - 1))

        self.control.screenshot.side_effect = capture
        with patch.object(api, "B", side_effect=convert), self.assertRaises(TimeoutError):
            api.locate_dyn(T("marker"), 10, interval=0.05, timeout=0.3)

    def test_cancellation_during_slow_capture_or_locate_takes_precedence(self):
        cancelled = False

        def cancel_after_delay(result):
            nonlocal cancelled
            self.advance(1)
            cancelled = True
            return result

        def check_cancel():
            if cancelled:
                raise TaskCancelled("stop")

        with patch.object(api, "check_cancel_raise", side_effect=check_cancel):
            for target in (B(0, 0, 20, 20), T("marker")):
                self.now, cancelled = 0.0, False
                self.control.screenshot.side_effect = lambda: cancel_after_delay(self.frame)
                self.control.locate.side_effect = lambda *arguments, **options: cancel_after_delay([[Box(0, 0, 20, 20)]])
                with self.subTest(target=target), self.assertRaises(TaskCancelled):
                    api.locate_dyn(target, 10, timeout=0.3)

    def test_unresolved_target_does_not_start_dynamic_capture(self):
        def resolve(*arguments, **options):
            self.advance(0.1)
            return [[Box(0, 0, 10, 10)], None]

        self.control.locate.side_effect = resolve
        with self.assertRaises(TimeoutError):
            api.locate_dyn([T("present"), T("missing")], 10, timeout=0.25)
        self.control.screenshot.assert_not_called()

    def test_static_frames_time_out_instead_of_returning_empty_list(self):
        with self.assertRaises(TimeoutError):
            api.locate_dyn(B(0, 0, 20, 20), 10, interval=0.1, timeout=0.25)
        self.assertAlmostEqual(self.now, 0.25)

    def test_interval_counts_capture_time_instead_of_adding_an_extra_delay(self):
        changed = self.frame.copy()
        changed[5:13, 5:13] = 30
        frames = iter((self.frame, changed))

        def capture():
            self.advance(0.08)
            return next(frames)

        self.control.screenshot.side_effect = capture
        self.assertEqual(api.locate_dyn(B(0, 0, 20, 20), 13, interval=0.05), [Box(5, 5, 8, 8)])
        self.assertAlmostEqual(self.now, 0.16)

    def test_late_capture_cannot_return_success_after_deadline(self):
        def capture():
            self.advance(0.2)
            return np.full_like(self.frame, 100 * (self.control.screenshot.call_count - 1))

        self.control.screenshot.side_effect = capture
        with self.assertRaises(TimeoutError):
            api.locate_dyn(B(0, 0, 20, 20), 10, interval=0, timeout=0.3)

    def test_cancellation_and_capture_errors_propagate(self):
        self.wait.side_effect = TaskCancelled("stop")
        with self.assertRaises(TaskCancelled):
            api.locate_dyn(B(0, 0, 20, 20), 10)
        self.assertEqual(self.control.screenshot.call_count, 1)

        self.control.screenshot.side_effect = RuntimeError("capture failed")
        with self.assertRaisesRegex(RuntimeError, "capture failed"):
            api.locate_dyn(B(0, 0, 20, 20), 10)

    def test_resolution_change_and_out_of_bounds_regions_fail_visibly(self):
        self.control.screenshot.side_effect = [self.frame, self.frame[:40]]
        with self.assertRaises(ValueError):
            api.locate_dyn(B(0, 0, 20, 20), 10)

        self.control.screenshot.side_effect = None
        for target in (B(-1, 0, 10, 10), B(90, 0, 10, 10), B(0, 0, 0, 10)):
            with self.subTest(target=target), self.assertRaises(ValueError):
                api.locate_dyn(target, 10)

    def test_invalid_parameters_fail_before_capture(self):
        for options in (
            {"min_area": 0}, {"min_area": (10,)}, {"min_area": (10, -1)},
            {"threshold": 0}, {"threshold": 256}, {"threshold": True},
            {"interval": -1}, {"interval": float("nan")},
            {"timeout": 0}, {"timeout": float("inf")},
        ):
            with self.subTest(options=options), self.assertRaises((TypeError, ValueError)):
                api.locate_dyn(B(0, 0, 20, 20), **({"min_area": 10} | options))
        for target in ([], Box(0, 0, 20, 20), [Box(0, 0, 20, 20)]):
            with self.subTest(target=target), self.assertRaises((TypeError, ValueError)):
                api.locate_dyn(target, 10)
        self.control.screenshot.assert_not_called()

    def test_public_export_resolves_to_the_same_function(self):
        import AutoScriptor
        import AutoScriptor.core

        self.assertIn("locate_dyn", AutoScriptor.__all__)
        self.assertIs(AutoScriptor.locate_dyn, api.locate_dyn)
        self.assertIs(AutoScriptor.core.locate_dyn, api.locate_dyn)


if __name__ == "__main__":
    unittest.main()
