"""NemuIpc 快速路径：ROI 截图、多指 API、点击时长参数化、输入回退。

这些测试不连接模拟器：IPC 实现以最小 fake 替代，只固化包装层的行为。
"""

import threading
import unittest
from unittest.mock import MagicMock, call, patch

import numpy as np

from AutoScriptor.control.NemuIpc.device.method.nemu_ipc import NemuIpc, NemuIpcError
from AutoScriptor.core.control import MixControl


def build_bottom_up_bgra_frame(height, width):
    """空白 bottom-up BGRA 帧（与 nemu_capture_display 的输出布局一致）。"""
    return np.zeros((height, width, 4), dtype=np.uint8)


class FakeCaptureImpl:
    """NemuIpcImpl 的最小替身，供包装层快速路径测试使用。"""

    def __init__(self, frame):
        self.io_lock = threading.RLock()
        self.frame = frame
        self.calls = []

    def screenshot(self):
        return self.frame

    def down(self, x, y):
        self.calls.append(("down", x, y))

    def up(self):
        self.calls.append(("up",))

    def finger_touch_down(self, finger_id, x, y):
        self.calls.append(("finger-down", finger_id, x, y))

    def finger_touch_up(self, finger_id):
        self.calls.append(("finger-up", finger_id))


def build_wrapper(frame):
    control = NemuIpc.__new__(NemuIpc)
    control.nemu_ipc = FakeCaptureImpl(frame)
    return control


class TestScreenshotRegion(unittest.TestCase):
    def test_region_slice_maps_screen_coordinates_on_bottom_up_frame(self):
        # 高度 4 的 bottom-up 帧：raw 行 r 对应屏幕行 y = 3 - r。
        frame = build_bottom_up_bgra_frame(4, 4)
        frame[3, 0] = [50, 100, 200, 255]   # 屏幕 (0, 0)：BGRA → RGB (200, 100, 50)
        frame[2, 0] = [3, 2, 1, 255]        # 屏幕 (0, 1)：BGRA → RGB (1, 2, 3)

        control = build_wrapper(frame)
        region = control.screenshot_region_nemu_ipc((0, 0, 1, 2))

        self.assertEqual(region.shape, (2, 1, 3))
        # 输出为翻正后的屏幕方向：行 0 是屏幕上方、行 1 是屏幕下方。
        self.assertEqual(tuple(region[0, 0]), (200, 100, 50))
        self.assertEqual(tuple(region[1, 0]), (1, 2, 3))

    def test_region_uses_full_frame_only_beyond_slice(self):
        frame = build_bottom_up_bgra_frame(4, 4)
        control = build_wrapper(frame)
        region = control.screenshot_region_nemu_ipc((1, 1, 2, 2))
        self.assertEqual(region.shape, (2, 2, 3))

    def test_region_outside_frame_raises(self):
        frame = build_bottom_up_bgra_frame(4, 4)
        control = build_wrapper(frame)
        with self.assertRaises(ValueError):
            control.screenshot_region_nemu_ipc((3, 3, 2, 1))
        with self.assertRaises(ValueError):
            control.screenshot_region_nemu_ipc((0, 0, 0, 1))

    def test_region_accepts_box_like_tuple(self):
        frame = build_bottom_up_bgra_frame(4, 4)
        control = build_wrapper(frame)
        region = control.screenshot_region_nemu_ipc((0, 0, 4, 4))
        self.assertEqual(region.shape, (4, 4, 3))


class TestFingerApi(unittest.TestCase):
    def test_finger_events_forward_to_impl(self):
        control = build_wrapper(build_bottom_up_bgra_frame(2, 2))
        control.finger_down_nemu_ipc(2, 10, 20)
        control.finger_move_nemu_ipc(2, 30, 40)
        control.finger_up_nemu_ipc(2)
        self.assertEqual(
            control.nemu_ipc.calls,
            [("finger-down", 2, 10, 20), ("finger-down", 2, 30, 40), ("finger-up", 2)],
        )

    def test_release_all_fingers_is_best_effort(self):
        control = build_wrapper(build_bottom_up_bgra_frame(2, 2))
        impl = control.nemu_ipc
        original_up = impl.finger_touch_up

        def flaky_up(finger_id):
            original_up(finger_id)
            if finger_id == 3:
                raise NemuIpcError("not pressed")

        impl.finger_touch_up = flaky_up

        control.release_all_fingers_nemu_ipc()  # 不得抛出

        released = [call[1] for call in impl.calls if call[0] == "finger-up"]
        self.assertEqual(sorted(released), list(range(1, 11)))

    def test_release_all_fingers_noop_without_connection(self):
        control = NemuIpc.__new__(NemuIpc)
        control.release_all_fingers_nemu_ipc()  # nemu_ipc 未初始化：直接返回


class TestClickTiming(unittest.TestCase):
    @patch("AutoScriptor.control.NemuIpc.device.method.nemu_ipc.time.sleep")
    def test_default_click_keeps_legacy_total_duration(self, mock_sleep):
        control = build_wrapper(build_bottom_up_bgra_frame(2, 2))
        control.click_nemu_ipc(10, 20)
        delays = [call_args.args[0] for call_args in mock_sleep.call_args_list]
        self.assertEqual(len(delays), 2)
        self.assertAlmostEqual(delays[0] + delays[1], 0.050, places=6)

    @patch("AutoScriptor.control.NemuIpc.device.method.nemu_ipc.time.sleep")
    def test_minimal_latency_click_mode(self, mock_sleep):
        control = build_wrapper(build_bottom_up_bgra_frame(2, 2))
        control.click_nemu_ipc(10, 20, press_s=0.001, tail_s=0)
        self.assertEqual(mock_sleep.call_args_list, [call(0.001), call(0)])
        self.assertEqual(
            control.nemu_ipc.calls,
            [("down", 10, 20), ("up",)],
        )


class TestMixControlNemuFallback(unittest.TestCase):
    def build_mix(self):
        mumu = MagicMock()
        mix = MixControl(mumu, serial="127.0.0.1:16416")
        return mix, mumu

    def test_default_mode_is_nemu(self):
        mix, _ = self.build_mix()
        self.assertEqual(mix.mode, "nemu")

    def test_click_falls_back_to_adb_when_nemu_input_fails(self):
        mix, mumu = self.build_mix()
        mix.nemu_control.click = MagicMock(side_effect=NemuIpcError("boom"))

        mix.click(10, 20)
        mumu.adb.click.assert_called_once_with(10, 20)

        # 回退后不再反复尝试 nemu：后续点击直接走 ADB。
        mix.click(30, 40)
        self.assertEqual(mix.nemu_control.click.call_count, 1)
        mumu.adb.click.assert_called_with(30, 40)

    def test_switch_to_nemu_rearms_the_fast_path(self):
        mix, mumu = self.build_mix()
        mix.nemu_control.click = MagicMock(side_effect=NemuIpcError("boom"))
        mix.click(10, 20)
        self.assertEqual(mumu.adb.click.call_count, 1)

        mix.nemu_control.click = MagicMock()
        mix.switch_to_nemu()
        mix.click(30, 40)

        mix.nemu_control.click.assert_called_once_with(30, 40)
        self.assertEqual(mumu.adb.click.call_count, 1)  # 仅第一次回退

    def test_input_text_falls_back_to_adb(self):
        mix, mumu = self.build_mix()
        mix.nemu_control.input_text = MagicMock(side_effect=NemuIpcError("boom"))
        mix.input_text("hello")
        mumu.adb.input_text.assert_called_once_with("hello")

    def test_multi_finger_down_presses_each_finger_once(self):
        mix, _ = self.build_mix()
        mix.nemu_control.finger_down = MagicMock()
        mix.multi_finger_down([(1, 100, 200), (2, 300, 400)])
        self.assertEqual(
            mix.nemu_control.finger_down.call_args_list,
            [call(1, 100, 200), call(2, 300, 400)],
        )


if __name__ == "__main__":
    unittest.main()
