import logging
import unittest
from unittest.mock import MagicMock, call, patch

from AutoScriptor.core.targets import B, T
from AutoScriptor.core.box import Box


class ClickOffsetSemanticsTest(unittest.TestCase):
    @patch("AutoScriptor.core.api.cancellable_sleep")
    @patch("AutoScriptor.core.api.mixctrl")
    def test_click_all_clicks_every_match_in_visual_order(self, mock_ctrl, mock_sleep):
        from AutoScriptor.core.api import click_all

        target = T("领取", box=Box(900, 400, 120, 220))
        mock_ctrl.locate.return_value = [[
            Box(930, 520, 60, 30),
            Box(940, 430, 60, 30),
            Box(850, 430, 60, 30),
        ]]

        with patch("AutoScriptor.core.box.random.randint", return_value=0):
            clicked_count = click_all(
                target,
                timeout=0,
                interval=0.2,
                assure_stable=False,
                save_screenshot=False,
            )

        self.assertEqual(clicked_count, 3)
        self.assertEqual(
            mock_ctrl.click.call_args_list,
            [call(880, 445), call(970, 445), call(960, 535)],
        )
        self.assertEqual(mock_sleep.call_args_list, [call(0), call(0.2), call(0.2), call(0.2)])

    @patch("AutoScriptor.core.api.mixctrl")
    def test_click_all_returns_zero_when_optional_target_is_absent(self, mock_ctrl):
        from AutoScriptor.core.api import click_all

        mock_ctrl.locate.return_value = [[]]

        clicked_count = click_all(
            T("领取"),
            timeout=0,
            if_exist=True,
            assure_stable=False,
            save_screenshot=False,
        )

        self.assertEqual(clicked_count, 0)
        mock_ctrl.click.assert_not_called()

    @patch("AutoScriptor.core.api.mixctrl")
    def test_click_offset_does_not_move_locate_target_box(self, mock_ctrl):
        from AutoScriptor.core.api import click

        search_box = Box(1153, 184, 126, 50).margin()
        found_box = Box(100, 200, 50, 40)
        target = T("须弥鼎", box=search_box)
        mock_ctrl.locate.return_value = [[found_box]]
        mock_ctrl.click = MagicMock()

        with patch("AutoScriptor.core.box.random.randint", return_value=0):
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


class ClickLoggingTest(unittest.TestCase):
    def test_repeat_and_until_keep_one_log_record_per_input(self):
        from AutoScriptor.core import api, control

        self.addCleanup(control.clear_action_history)
        for click_options in ({"repeat": 3}, {"until": MagicMock(side_effect=[False, False, True])}):
            with self.subTest(options=click_options), \
                 patch.object(control, "NemuIpcControl"), \
                 patch.object(control.time, "monotonic", return_value=1000.0), \
                 patch.object(api, "cancellable_sleep"):
                controller = control.MixControl(MagicMock())
                control.clear_action_history()
                with patch.object(api, "mixctrl", controller), \
                     self.assertLogs("AutoScriptor", level="DEBUG") as captured:
                    api.click(B(10, 20, 1, 1), **click_options)

                self.assertEqual(controller.nemu_control.click.call_count, 3)
                self.assertEqual(len(control.get_action_history()), 3)
                self.assertEqual(
                    [record.levelno for record in captured.records],
                    [logging.INFO, logging.DEBUG, logging.DEBUG],
                )

    def test_locate_polling_uses_debug_for_single_or_and_targets(self):
        from AutoScriptor.core import api

        target = T("button")
        for search_target in (target, (target,), [target]):
            with self.subTest(target=search_target), \
                 patch.object(api, "_locate_all", return_value=[[Box(10, 20, 30, 40)]]), \
                 self.assertLogs("AutoScriptor", level="DEBUG") as captured:
                for _attempt in range(3):
                    self.assertIsNotNone(api.locate(search_target, timeout=0, assure_stable=False))

            self.assertEqual(len(captured.records), 3)
            self.assertTrue(all(record.levelno == logging.DEBUG for record in captured.records))


if __name__ == "__main__":
    unittest.main()
