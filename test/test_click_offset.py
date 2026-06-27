import unittest
from unittest.mock import MagicMock, call, patch

from AutoScriptor.core.targets import B, T
from AutoScriptor.utils.box import Box


class ClickOffsetSemanticsTest(unittest.TestCase):
    @patch("AutoScriptor.core.api.mixctrl")
    def test_click_offset_does_not_move_locate_target_box(self, mock_ctrl):
        from AutoScriptor.core.api import click

        search_box = Box(1153, 184, 126, 50).margin()
        found_box = Box(100, 200, 50, 40)
        target = T("须弥鼎", box=search_box)
        mock_ctrl.locate.return_value = [[found_box]]
        mock_ctrl.click = MagicMock()

        with patch("AutoScriptor.utils.box.random.randint", return_value=0):
            click(
                target,
                timeout=0,
                offset=(0, -20),
                assure_stable=False,
                save_screenshot=False,
            )

        triples = mock_ctrl.locate.call_args.args[0]
        self.assertEqual(triples[0][1], search_box)
        mock_ctrl.click.assert_called_once_with(125, 200)

    @patch("AutoScriptor.core.api.cancellable_sleep")
    @patch("AutoScriptor.core.api.mixctrl")
    def test_click_until_omitted_interval_defaults_to_half_second(self, mock_ctrl, mock_sleep):
        from AutoScriptor.core.api import click

        click(B(10, 20, 1, 1), until=lambda: True, timeout=1)

        self.assertIn(call(0.5), mock_sleep.call_args_list)

    @patch("AutoScriptor.core.api.cancellable_sleep")
    @patch("AutoScriptor.core.api.mixctrl")
    def test_plain_click_and_explicit_zero_interval_stay_zero(self, mock_ctrl, mock_sleep):
        from AutoScriptor.core.api import click

        click(B(10, 20, 1, 1))
        click(B(10, 20, 1, 1), until=lambda: True, timeout=1, interval=0)

        self.assertNotIn(call(0.5), mock_sleep.call_args_list)


class BoxOffsetCompatibilityTest(unittest.TestCase):
    def test_box_add_accepts_legacy_tuple_offset(self):
        self.assertEqual(Box(10, 20, 30, 40) + (5, -7), Box(15, 13, 30, 40))

    def test_box_add_accepts_named_offset_resize_delta(self):
        delta = {"offset": (5, -7), "resize": (12, 13)}
        self.assertEqual(Box(10, 20, 30, 40) + delta, Box(15, 13, 12, 13))


if __name__ == "__main__":
    unittest.main()
