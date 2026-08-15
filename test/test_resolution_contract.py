import unittest
from unittest.mock import patch

import numpy as np

import AutoScriptor
from AutoScriptor.core.control import MixControl
from AutoScriptor.core.display_contract import EXPECTED_FRAME_SIZE, get_frame_size


class _FakeScreenshotControl:
    def __init__(self, frame):
        self.frame = frame

    def screenshot(self):
        return self.frame


def _make_mix_control(frame) -> MixControl:
    control = MixControl.__new__(MixControl)
    control.nemu_control = _FakeScreenshotControl(frame)
    control.last_screenshot_time = 0
    control.screenshot_interval = 5
    control._last_resolution_warning_at = 0.0
    control._last_resolution_warning_size = None
    control._resolution_warning_interval = 60.0
    return control


class ResolutionContractTests(unittest.TestCase):
    def test_expected_contract_is_1280_by_720_landscape(self):
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)

        self.assertEqual(EXPECTED_FRAME_SIZE, (1280, 720))
        self.assertEqual(get_frame_size(frame), EXPECTED_FRAME_SIZE)

    def test_mismatch_warns_once_and_returns_original_frame(self):
        frame = np.zeros((576, 1024, 3), dtype=np.uint8)
        control = _make_mix_control(frame)

        with (
            patch.object(AutoScriptor, "cfg", {"app": {"debug_mode": False}}),
            patch("AutoScriptor.core.control.time.monotonic", side_effect=[100.0, 110.0]),
            patch("AutoScriptor.core.control.logger.warning") as warning,
        ):
            first_result = control.screenshot()
            second_result = control.screenshot()

        self.assertIs(first_result, frame)
        self.assertIs(second_result, frame)
        warning.assert_called_once()
        warning_template, *warning_arguments = warning.call_args.args
        formatted_warning = warning_template % tuple(warning_arguments)
        self.assertIn("1024x576", formatted_warning)
        self.assertIn("1280x720", formatted_warning)

    def test_new_size_and_recovered_contract_reset_the_warning(self):
        first_frame = np.zeros((576, 1024, 3), dtype=np.uint8)
        second_frame = np.zeros((540, 960, 3), dtype=np.uint8)
        expected_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        control = _make_mix_control(first_frame)

        with (
            patch("AutoScriptor.core.control.time.monotonic", side_effect=[100.0, 101.0, 102.0]),
            patch("AutoScriptor.core.control.logger.warning") as warning,
        ):
            control._warn_if_resolution_mismatch(first_frame)
            control._warn_if_resolution_mismatch(second_frame)
            control._warn_if_resolution_mismatch(expected_frame)
            control._warn_if_resolution_mismatch(second_frame)

        self.assertEqual(warning.call_count, 3)


if __name__ == "__main__":
    unittest.main()
