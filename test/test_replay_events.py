"""``replay()``：事件流回放的手指编号校验、坐标换算、窗口、取消与清理。

这些测试不连接模拟器：``mixctrl`` 以 MagicMock 替代，只固化 ``api.replay``
包装层的行为与两条正确性不变量（手指编号越界必须显式报错、中止时不得留下
按住的手指）。
"""

import unittest
from unittest.mock import MagicMock, patch

from AutoScriptor.core import api
from AutoScriptor.utils.cancel import TaskCancelled


def build_two_finger_events():
    """双指同按 → 单指移动 → 双指同抬。"""
    return [
        (0, "down", 1, 0.5, 0.25),
        (0, "down", 2, 0.75, 0.25),
        (60, "move", 1, 0.5, 0.5),
        (120, "up", 1, 0.0, 0.0),
        (120, "up", 2, 0.0, 0.0),
    ]


class ReplayDispatchTestCase(unittest.TestCase):
    def setUp(self):
        self.control = MagicMock()
        patcher = patch.object(api, "mixctrl", self.control)
        patcher.start()
        self.addCleanup(patcher.stop)
        api.setFrameSize((1280, 720))
        self.addCleanup(api.setFrameSize, (1280, 720))

    def recorded_calls(self):
        return [(name, args) for name, args, _kwargs in self.control.method_calls]

    def released_fingers(self):
        return [args for name, args, _kwargs in self.control.method_calls if name == "finger_up"]

    def test_scales_normalized_coordinates_to_frame_pixels(self):
        executed = api.replay([(0, "down", 1, 0.5, 0.25), (10, "up", 1, 0.0, 0.0)])

        self.assertEqual(executed, 2)
        self.control.finger_down.assert_called_once_with(1, 640, 180)
        self.control.finger_up.assert_called_once_with(1)

    def test_same_timestamp_presses_both_fingers_before_any_release(self):
        api.replay(build_two_finger_events())

        self.assertEqual(
            self.recorded_calls(),
            [
                ("finger_down", (1, 640, 180)),
                ("finger_down", (2, 960, 180)),
                ("finger_move", (1, 640, 360)),
                ("finger_up", (1,)),
                ("finger_up", (2,)),
            ],
        )

    def test_clamps_out_of_range_coordinates_into_frame(self):
        api.replay([(0, "down", 1, 1.4, -0.2), (5, "up", 1, 0.0, 0.0)])

        self.control.finger_down.assert_called_once_with(1, 1279, 0)

    def test_returns_executed_touch_event_count_only(self):
        executed = api.replay(build_two_finger_events())

        self.assertEqual(executed, 5)


class ReplayValidationTestCase(unittest.TestCase):
    def setUp(self):
        self.control = MagicMock()
        patcher = patch.object(api, "mixctrl", self.control)
        patcher.start()
        self.addCleanup(patcher.stop)
        api.setFrameSize((1280, 720))
        self.addCleanup(api.setFrameSize, (1280, 720))

    def test_rejects_finger_id_outside_ipc_range(self):
        # 录制槽位号（实测样本出现 19/20）不是 finger_id；越界必须显式报错，
        # 夹取或取模会把手势静默落到错误手指上。
        with self.assertRaises(ValueError) as context:
            api.replay([(0, "down", 19, 0.5, 0.5)])

        self.assertIn("19", str(context.exception))
        self.control.finger_down.assert_not_called()

    def test_rejects_missing_finger_id(self):
        with self.assertRaises(ValueError):
            api.replay([(0, "down", None, 0.5, 0.5)])

    def test_rejects_cross_orientation_recording(self):
        with self.assertRaises(ValueError) as context:
            api.replay(
                [(0, "down", 1, 0.5, 0.5)],
                frame_size=(1280, 720),
                recording_size=(1080, 1920),
            )

        self.assertIn("方向不一致", str(context.exception))
        self.control.finger_down.assert_not_called()

    def test_accepts_same_orientation_recording(self):
        executed = api.replay(
            [(0, "down", 1, 0.5, 0.5), (5, "up", 1, 0.0, 0.0)],
            frame_size=(720, 1280),
            recording_size=(1080, 1920),
        )

        self.assertEqual(executed, 2)
        self.control.finger_down.assert_called_once_with(1, 360, 640)

    def test_rejects_unknown_op(self):
        with self.assertRaises(ValueError):
            api.replay([(0, "tap", 1, 0.5, 0.5)])

    def test_rejects_non_positive_speed(self):
        with self.assertRaises(ValueError):
            api.replay([], speed=0)

    def test_rejects_short_sequence_event(self):
        with self.assertRaises(ValueError):
            api.replay([(0, "down", 1)])


class ReplayWindowAndFormatTestCase(unittest.TestCase):
    def setUp(self):
        self.control = MagicMock()
        patcher = patch.object(api, "mixctrl", self.control)
        patcher.start()
        self.addCleanup(patcher.stop)
        api.setFrameSize((1280, 720))
        self.addCleanup(api.setFrameSize, (1280, 720))

    def test_start_and_end_window_selects_events(self):
        events = [
            (0, "down", 1, 0.1, 0.1),
            (100, "up", 1, 0.0, 0.0),
            (200, "down", 1, 0.2, 0.2),
            (300, "up", 1, 0.0, 0.0),
        ]

        executed = api.replay(events, start_ms=150, end_ms=250)

        self.assertEqual(executed, 1)
        self.control.finger_down.assert_called_once_with(1, 256, 144)

    def test_accepts_dict_events_and_delegates_commands(self):
        seen_commands = []
        events = [
            {"t_ms": 0, "op": "vcontrol", "cmd": "detect_app", "params": {"package": "com.demo"}},
            {"t_ms": 10, "op": "down", "finger": 1, "nx": 0.5, "ny": 0.5},
            {"t_ms": 20, "op": "up", "finger": 1},
        ]

        executed = api.replay(events, on_command=seen_commands.append)

        self.assertEqual(executed, 2)
        self.assertEqual(seen_commands[0]["cmd"], "detect_app")
        self.control.finger_down.assert_called_once_with(1, 640, 360)

    def test_skips_command_events_without_callback(self):
        events = [
            {"t_ms": 0, "op": "command", "cmd": "close_app"},
            {"t_ms": 10, "op": "down", "finger": 1, "nx": 0.5, "ny": 0.5},
            {"t_ms": 20, "op": "up", "finger": 1},
        ]

        executed = api.replay(events)

        self.assertEqual(executed, 2)

    def test_accepts_object_events_using_x_y_field_names(self):
        class RecordedEvent:
            def __init__(self, t_ms, op, finger, x, y):
                self.t_ms = t_ms
                self.op = op
                self.finger = finger
                self.x = x
                self.y = y

        events = [RecordedEvent(0, "down", 1, 0.25, 0.5), RecordedEvent(5, "up", 1, None, None)]

        executed = api.replay(events)

        self.assertEqual(executed, 2)
        self.control.finger_down.assert_called_once_with(1, 320, 360)


class ReplayCleanupTestCase(unittest.TestCase):
    def setUp(self):
        self.control = MagicMock()
        patcher = patch.object(api, "mixctrl", self.control)
        patcher.start()
        self.addCleanup(patcher.stop)
        api.setFrameSize((1280, 720))
        self.addCleanup(api.setFrameSize, (1280, 720))

    def released_fingers(self):
        return [args for name, args, _kwargs in self.control.method_calls if name == "finger_up"]

    def test_releases_pressed_fingers_when_dispatch_fails(self):
        self.control.finger_move.side_effect = RuntimeError("ipc rejected input")

        with self.assertRaises(RuntimeError):
            api.replay(build_two_finger_events())

        # 手指 1、2 已按下，清理必须都抬起，否则屏幕上会留下按住的接触点。
        self.assertIn((1,), self.released_fingers())
        self.assertIn((2,), self.released_fingers())

    def test_cancel_stops_replay_and_releases_fingers(self):
        state = {"checks": 0}

        def cancel_after_two_checks():
            state["checks"] += 1
            if state["checks"] >= 3:
                raise TaskCancelled("任务已终止")

        with self.assertRaises(TaskCancelled):
            api.replay(build_two_finger_events(), cancel_check=cancel_after_two_checks)

        self.assertIn((1,), self.released_fingers())
        self.assertIn((2,), self.released_fingers())

    def test_releases_finger_left_pressed_at_end_of_stream(self):
        api.replay([(0, "down", 3, 0.5, 0.5)])

        self.assertEqual(self.released_fingers(), [(3,)])

    def test_never_releases_fingers_outside_this_replay(self):
        # 任务可能在 replay 之外异步按住别的手指，所以清理只针对本次按下的
        # 编号，不能用 release_all_fingers() 一把清掉。
        api.replay([(0, "down", 3, 0.5, 0.5), (5, "up", 3, 0.0, 0.0)])

        self.control.release_all_fingers.assert_not_called()
        self.assertEqual(self.released_fingers(), [(3,)])

    def test_cleanup_failure_does_not_mask_original_error(self):
        self.control.finger_move.side_effect = RuntimeError("ipc rejected input")
        self.control.finger_up.side_effect = RuntimeError("cleanup also failed")

        with self.assertRaises(RuntimeError) as context:
            api.replay(build_two_finger_events())

        self.assertIn("ipc rejected input", str(context.exception))


class ReplayExportTestCase(unittest.TestCase):
    def test_replay_is_part_of_the_public_dsl(self):
        import AutoScriptor

        self.assertIn("replay", AutoScriptor.__all__)
        self.assertTrue(callable(AutoScriptor.replay))


if __name__ == "__main__":
    unittest.main()
