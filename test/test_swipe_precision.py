import unittest
from threading import RLock
from unittest.mock import call, patch

from AutoScriptor.control.NemuIpc.device.method.nemu_ipc import NemuIpc
from AutoScriptor.core.targets import B, T
from AutoScriptor.utils.box import Box


class PreciseSwipeTest(unittest.TestCase):
    @patch("AutoScriptor.core.api.cancellable_sleep")
    @patch("AutoScriptor.core.api.mixctrl")
    @patch("AutoScriptor.core.api.locate")
    def test_precise_swipe_uses_box_centers_without_random_offset(
        self,
        mock_locate,
        mock_ctrl,
        mock_sleep,
    ):
        from AutoScriptor.core.api import swipe_precise

        mock_locate.side_effect = [Box(100, 200, 80, 40), Box(500, 300, 60, 20)]

        swipe_precise(T("起点"), T("终点"), duration_s=0.75)

        self.assertEqual(
            mock_ctrl.swipe_precise.call_args,
            call(140, 220, 530, 310, 0.75),
        )
        self.assertEqual(mock_sleep.call_args_list, [call(0), call(0.75)])

    @patch("AutoScriptor.core.api.cancellable_sleep")
    @patch("AutoScriptor.core.api.mixctrl")
    def test_precise_swipe_uses_literal_box_points(self, mock_ctrl, mock_sleep):
        from AutoScriptor.core.api import swipe_precise

        swipe_precise(B(10, 20, 1, 1), B(300, 400, 1, 1), duration_s=0.2)

        mock_ctrl.swipe_precise.assert_called_once_with(10, 20, 300, 400, 0.2)
        mock_sleep.assert_has_calls([call(0), call(0.2)])

    def test_precise_swipe_rejects_non_positive_duration(self):
        from AutoScriptor.core.api import swipe_precise

        with self.assertRaises(ValueError):
            swipe_precise(B(10, 20, 1, 1), B(300, 400, 1, 1), duration_s=0)

    @patch("AutoScriptor.control.NemuIpc.device.method.nemu_ipc.time.sleep")
    def test_nemu_precise_swipe_follows_a_deterministic_line(self, mock_sleep):
        class FakeNemuIpc:
            def __init__(self):
                self.events = []

            def down(self, x, y):
                self.events.append(("down", x, y))

            def up(self):
                self.events.append(("up",))

        fake_nemu_ipc = FakeNemuIpc()
        control = NemuIpc.__new__(NemuIpc)
        control.nemu_ipc = fake_nemu_ipc
        control._ipc_lock = RLock()

        control.swipe_precise_nemu_ipc((10, 20), (20, 30), duration_s=0.02)

        self.assertEqual(
            fake_nemu_ipc.events,
            [("down", 10, 20), ("down", 15, 25), ("down", 20, 30), ("up",)],
        )
        self.assertGreaterEqual(mock_sleep.call_count, 1)


if __name__ == "__main__":
    unittest.main()
