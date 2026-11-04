"""Sequence clicks reuse transition detections without touching a real device."""

import inspect
import unittest
from contextlib import ExitStack
from unittest.mock import Mock, call, patch

from AutoScriptor.core import api
from AutoScriptor.core.box import Box
from AutoScriptor.core.targets import B, T
from AutoScriptor.utils.cancel import TaskCancelled


class SequenceClickTests(unittest.TestCase):
    def setUp(self):
        patches = ExitStack()
        self.addCleanup(patches.close)
        self.controller = patches.enter_context(patch.object(api, "mixctrl"))
        self.sleep = patches.enter_context(patch.object(api, "cancellable_sleep"))
        self.capture = patches.enter_context(patch.object(api, "save_debug_screenshot"))
        patches.enter_context(patch.object(api, "_box_click_trace", []))
        patches.enter_context(patch("AutoScriptor.core.box.random.randint", return_value=0))
        self.targets = [T("first"), T("second"), T("third")]
        self.boxes = [Box(10, 10, 20, 20), Box(100, 100, 20, 20), Box(200, 200, 20, 20)]

    def test_signature_and_public_exports_match_click(self):
        import AutoScriptor
        import AutoScriptor.core

        click_parameters = inspect.signature(api.click).parameters
        sequence_parameters = inspect.signature(api.seq_click).parameters
        self.assertEqual(list(sequence_parameters), list(click_parameters))
        for name, parameter in click_parameters.items():
            self.assertEqual(sequence_parameters[name].kind, parameter.kind)
            expected_default = 10 if name == "timeout" else parameter.default
            self.assertEqual(sequence_parameters[name].default, expected_default)
        self.assertIs(AutoScriptor.seq_click, api.seq_click)
        self.assertIs(AutoScriptor.core.seq_click, api.seq_click)

    def test_timeout_is_per_step_and_defaults_to_ten_seconds(self):
        for options, expected_timeout in (({}, 10), ({"timeout": 2}, 2)):
            with self.subTest(options=options), patch.object(api, "_click", return_value=True) as click:
                self.assertTrue(api.seq_click(self.targets, **options))
                self.assertEqual([entry.kwargs["timeout"] for entry in click.call_args_list],
                                 [expected_timeout] * len(self.targets))

    def test_each_transition_gets_a_fresh_timeout_budget(self):
        elapsed = 0

        def advance_clock(duration):
            nonlocal elapsed
            elapsed += duration

        self.sleep.side_effect = advance_clock
        with patch.object(api.time, "monotonic", side_effect=lambda: elapsed), patch.object(
            api, "locate", side_effect=[
                self.boxes[0], None, self.boxes[0], self.boxes[1],
                None, self.boxes[1], self.boxes[2],
            ]
        ):
            self.assertTrue(api.seq_click(self.targets, interval=4, save_screenshot=False))
        self.assertEqual(elapsed, 20)
        self.assertEqual(self.controller.click.call_count, 5)

    def test_expired_step_does_not_send_an_extra_retry(self):
        with patch.object(api.time, "monotonic", side_effect=[0, 10, 10]), patch.object(
            api, "locate", side_effect=[self.boxes[0], None]
        ):
            with self.assertRaisesRegex(RuntimeError, "until"):
                api.seq_click(self.targets, save_screenshot=False)
        self.controller.click.assert_called_once_with(20, 20)

    def test_plain_box_until_is_immediately_true_without_recognition(self):
        self.assertTrue(api.click(B(5, 10), until=lambda: api.ui_T(B(20, 30))))
        self.assertFalse(api.ui_F(B(20, 30)))
        self.controller.click.assert_called_once_with(5, 10)
        self.controller.locate.assert_not_called()
        self.controller.screenshot.assert_not_called()

    def test_plain_box_successor_needs_no_stability_detection(self):
        api.seq_click([B(5, 10), B(20, 30)])
        self.assertEqual(self.controller.click.call_args_list, [call(5, 10), call(20, 30)])
        self.controller.locate.assert_not_called()

    def test_colored_box_condition_still_requires_recognition(self):
        self.controller.locate.return_value = [[]]
        self.assertFalse(api.ui_T(B(5, 10, 20, 20, color="red")))
        self.controller.locate.assert_called_once()

    def test_empty_sequence_is_a_noop(self):
        self.assertTrue(api.seq_click([]))
        self.controller.click.assert_not_called()
        self.controller.locate.assert_not_called()

    def test_transition_boxes_are_located_once_and_clicked_in_order(self):
        events = []

        def locate(targets, **options):
            name = targets[0][0]
            events.append(("locate", name))
            return [[self.boxes[["first", "second", "third"].index(name)]]]

        self.controller.locate.side_effect = locate
        self.controller.click.side_effect = lambda *point: events.append(("click", point))
        self.assertTrue(api.seq_click(self.targets, assure_stable=False, save_screenshot=False))
        self.assertEqual(events, [
            ("locate", "first"), ("click", (20, 20)),
            ("locate", "second"), ("click", (110, 110)),
            ("locate", "third"), ("click", (210, 210)),
        ])
        self.controller.screenshot.assert_not_called()

    def test_stability_adds_only_one_detection_per_target(self):
        self.controller.locate.side_effect = [
            [self.boxes[0:1]], [self.boxes[0:1]],
            [self.boxes[1:2]], [self.boxes[1:2]],
        ]
        api.seq_click(self.targets[:2], save_screenshot=False)
        self.assertEqual(self.controller.locate.call_count, 4)
        self.assertEqual(self.controller.click.call_args_list, [call(20, 20), call(110, 110)])

    def test_disappearing_successor_is_not_treated_as_stable(self):
        moved_box = Box(300, 300, 20, 20)
        self.controller.locate.side_effect = [
            [[self.boxes[0]]], [[self.boxes[0]]],
            [[self.boxes[1]]], [[]], [[moved_box]], [[moved_box]],
        ]
        api.seq_click(self.targets[:2], save_screenshot=False)
        self.assertEqual(self.controller.click.call_args_list, [call(20, 20), call(310, 310)])

    def test_retry_relocates_current_target_and_final_until_only_runs_at_end(self):
        moved_box = Box(30, 30, 20, 20)
        self.controller.locate.side_effect = [
            [[self.boxes[0]]], [[]], [[moved_box]], [[self.boxes[1]]], [[moved_box]],
        ]
        final_until = Mock(side_effect=[False, True])
        api.seq_click(self.targets[:2], until=final_until, assure_stable=False, save_screenshot=False)
        self.assertEqual(self.controller.click.call_args_list, [
            call(20, 20), call(40, 40), call(110, 110), call(40, 40),
        ])
        self.assertEqual(final_until.call_count, 2)
        self.capture.assert_not_called()

    def test_cached_click_preserves_target_screenshot_annotations(self):
        self.controller.locate.side_effect = [[[box]] for box in self.boxes[:2]]
        api.seq_click(self.targets[:2], assure_stable=False)
        self.assertEqual(self.controller.locate.call_count, 2)
        self.assertEqual([entry.args[0] for entry in self.capture.call_args_list], self.targets[:2])
        self.assertEqual([entry.args[2] for entry in self.capture.call_args_list], self.boxes[:2])

    def test_final_until_is_not_called_for_intermediate_targets(self):
        self.controller.locate.side_effect = [[[box]] for box in self.boxes]

        def final_until():
            self.assertEqual(self.controller.click.call_count, 3)
            return True

        api.seq_click(self.targets, until=final_until, assure_stable=False, save_screenshot=False)

    def test_successor_can_be_an_or_group(self):
        self.controller.locate.side_effect = [[[self.boxes[0]]], [[], [self.boxes[1]]]]
        api.seq_click([self.targets[0], tuple(self.targets[1:])], assure_stable=False, save_screenshot=False)
        self.assertEqual(self.controller.click.call_args_list, [call(20, 20), call(110, 110)])

    def test_long_click_repeat_offset_resize_and_delay_are_preserved(self):
        self.controller.locate.side_effect = [[[box]] for box in self.boxes[:2]]
        api.seq_click(
            self.targets[:2], 2, repeat=2, delay=0.1, interval=0.2,
            offset=(5, -5), resize=(10, 10), assure_stable=False, save_screenshot=False,
        )
        self.assertEqual(self.controller.long_click.call_args_list, [
            call(20, 10, duration=2), call(20, 10, duration=2),
            call(110, 100, duration=2), call(110, 100, duration=2),
        ])
        self.assertEqual(self.sleep.call_args_list, [
            call(0.1), call(0.2), call(0.2), call(0.1), call(0.2), call(0.2),
        ])

    def test_optional_missing_first_target_stops_the_chain(self):
        with patch.object(api, "locate", return_value=None) as locate:
            self.assertFalse(api.seq_click(self.targets, if_exist=True, save_screenshot=False))
        self.assertEqual(locate.call_count, 1)
        self.controller.click.assert_not_called()

    def test_transition_timeout_never_clicks_later_targets(self):
        with patch.object(api, "locate", side_effect=[self.boxes[0], None, None]):
            with self.assertRaisesRegex(RuntimeError, "until"):
                api.seq_click(self.targets, timeout=0, interval=0, save_screenshot=False)
        self.controller.click.assert_called_once_with(20, 20)

    def test_cancellation_between_steps_prevents_next_input(self):
        def locate(targets, **options):
            if targets[0][0] == "second":
                raise TaskCancelled()
            return [[self.boxes[0]]]

        self.controller.locate.side_effect = locate
        with self.assertRaises(TaskCancelled):
            api.seq_click(self.targets, assure_stable=False, save_screenshot=False)
        self.controller.click.assert_called_once_with(20, 20)

    def test_single_box_target_matches_plain_click(self):
        api.seq_click([B(5, 10)], repeat=2, save_screenshot=False)
        self.assertEqual(self.controller.click.call_args_list, [call(5, 10), call(5, 10)])
        self.controller.locate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
