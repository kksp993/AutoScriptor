"""Keep API helper extraction compatible with legacy shapes, mutation and imports.

These cases pin behavior that a cleanup could accidentally change: empty AND is
true, simple() replaces matrix slots in place, and zero/False are OCR information.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from AutoScriptor.core import api
from AutoScriptor.core.box import Box
from AutoScriptor.core.targets import B, T
from AutoScriptor.utils.cancel import TaskCancelled


class LegacyHelperBehaviorTests(unittest.TestCase):
    def test_result_shapes_and_empty_conventions(self):
        matched_box = Box(10, 20, 30, 40)
        self.assertIsNone(api.first(None))
        self.assertIsNone(api.first([]))
        self.assertIs(api.first(matched_box), matched_box)
        self.assertIs(api.first([matched_box]), matched_box)
        self.assertIs(api.first([None, [], [matched_box]]), matched_box)
        self.assertIsNone(api.simple([]))
        self.assertTrue(api.full([]))
        self.assertFalse(api.full([[], [matched_box]]))
        self.assertEqual(api.count([None, [], [matched_box, matched_box], matched_box]), [0, 0, 2, 1])
        self.assertEqual(api.index([]), -1)
        self.assertEqual(api.index([None, [], [matched_box]]), 2)

    def test_simple_replaces_slots_without_mutating_original_match_list(self):
        first_box, second_box = Box(10, 20, 30, 40), Box(80, 20, 30, 40)
        matches = [first_box, second_box]
        matrix = [matches, None, []]

        self.assertEqual(api.simple(matrix), [first_box, None, None])
        self.assertEqual(matrix, [[first_box], None, []])
        self.assertEqual(matches, [first_box, second_box])

    def test_stability_preserves_missing_slots_counts_and_overlap(self):
        matched_box = Box(10, 20, 30, 40)
        self.assertFalse(api.stable([], []))
        self.assertTrue(api.stable([None], [[]]))
        self.assertTrue(api.stable([[matched_box]], [[Box(11, 20, 30, 40)]]))
        self.assertFalse(api.stable([[matched_box]], [[Box(100, 20, 30, 40)]]))
        self.assertFalse(api.stable([[matched_box]], [[matched_box, matched_box]]))
        with self.assertRaises(AssertionError):
            api.stable([[matched_box]], [[matched_box], None])

    def test_nested_match_paths_and_fallback_indices(self):
        targets = (T("first"), (B(10, 20, 30, 40), [T("third")]))
        flattened = api._flatten_target_paths(targets)
        self.assertEqual([path for path, _target in flattened], [(0,), (1, 0), (1, 1, 0)])
        self.assertIs(flattened[2][1], targets[1][1][0])
        self.assertEqual(api._format_match_path(()), "[?]")
        self.assertEqual(api._first_hit_path([None, None, [Box(1, 2, 3, 4)]], targets), "[1.1.0]")
        self.assertEqual(api._first_hit_path([None, [Box(1, 2, 3, 4)]], targets), "[1]")
        with self.assertRaises(TypeError):
            api._flatten_target_paths((T("first"), 123))

    def test_legacy_validation_does_not_become_more_restrictive(self):
        for timeout in (-1, 0, float("nan"), float("inf")):
            self.assertIsNone(api._validate_timeout(timeout, "locate"))
        for timeout in (True, "1", T("target")):
            with self.subTest(timeout=timeout), self.assertRaises(TypeError):
                api._validate_timeout(timeout, "locate")
        with self.assertRaises(TypeError):
            api._validate_target(Box(10, 20, 30, 40), "locate")
        with self.assertRaises(ValueError):
            api._validate_swipe_duration(0, "swipe_precise")
        self.assertIsNone(api._validate_swipe_duration(0.01, "swipe_precise"))

    def test_extract_info_accepts_zero_false_and_nested_information(self):
        control = SimpleNamespace(screenshot=Mock(return_value=np.zeros((20, 20, 3), dtype=np.uint8)))
        with patch.object(api, "mixctrl", control), patch.object(api, "record_recognition_result"):
            for value in (0, False, [None, ("", 0)]):
                with self.subTest(value=value), patch.object(api, "ocr_for_box", return_value=value) as recognize:
                    result = api.extract_info(B(0, 0, 10, 10), max_retries=2, ocr_ttl=0, save_screenshot=False)
                    self.assertEqual(result, value)
                    recognize.assert_called_once()
            with patch.object(api, "ocr_for_box", side_effect=[[None, " "], "ready"]) as recognize:
                self.assertEqual(api.extract_info(B(0, 0, 10, 10), max_retries=2, ocr_ttl=0, save_screenshot=False), "ready")
                self.assertEqual(recognize.call_count, 2)


class CoreUtilsBoundaryTests(unittest.TestCase):
    def test_existing_public_imports_share_the_extracted_helpers(self):
        import AutoScriptor
        from AutoScriptor.core import utils

        for name in ("first", "simple", "full", "count"):
            with self.subTest(name=name):
                self.assertIs(getattr(AutoScriptor, name), getattr(utils, name))
                self.assertIs(getattr(api, name), getattr(utils, name))
        for name in ("index", "stable", "_validate_timeout", "_validate_target", "_validate_swipe_duration",
                     "_format_match_path", "_flatten_target_paths", "_first_hit_path"):
            with self.subTest(name=name):
                self.assertIs(getattr(api, name), getattr(utils, name))

    def test_deadline_check_uses_caller_clock_and_prioritizes_cancellation(self):
        from AutoScriptor.core.utils import make_deadline_check

        clock = Mock(side_effect=[7.5, 9.0])
        cancel_check = Mock()
        check_deadline = make_deadline_check(9.0, "expired", clock=clock, cancel_check=cancel_check)
        clock.assert_not_called()
        cancel_check.assert_not_called()
        self.assertEqual(check_deadline(), 1.5)
        with self.assertRaisesRegex(TimeoutError, "expired"):
            check_deadline()
        cancel_check.side_effect = TaskCancelled("stop")
        with self.assertRaises(TaskCancelled):
            check_deadline()
        self.assertEqual(clock.call_count, 2)

    def test_utility_import_does_not_load_api_devices_config_or_ocr(self):
        source = """
import sys
import AutoScriptor.core.utils
for name in ('AutoScriptor.core.api', 'AutoScriptor.core.control',
             'AutoScriptor.core.runtime_context', 'AutoScriptor.utils.app_config',
             'AutoScriptor.recognition.ocr_rec'):
    assert name not in sys.modules, name
"""
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, "-X", "utf8", "-c", source],
                cwd=Path(__file__).resolve().parents[2],
                env=dict(os.environ, AUTOSCRIPTOR_DATA_DIR=directory),
                capture_output=True, text=True, encoding="utf-8", timeout=20,
            )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
