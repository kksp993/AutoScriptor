"""Exercise the recorded task without importing the registry or touching a device."""

import ast
import runpy
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, call, patch

from AutoScriptor.errors import TaskRequireReTry
from AutoScriptor.utils.text import postnum


TASK_FILE = Path(__file__).resolve().parents[2] / "tasks/每日任务/村庄/天道树.py"


class TiandaoTreeTaskTests(unittest.TestCase):
    def setUp(self):
        self.registration = {}

        def register_task(**metadata):
            self.registration.update(metadata)
            return lambda function: function

        self.actions = Mock()
        self.navigation = self.actions.ensure_in
        self.click = self.actions.click
        self.sequence = self.actions.seq_click
        self.extract = self.actions.extract_info
        self.wait = self.actions.wait_for_appear
        self.hidden = Mock(return_value=True)
        automation = ModuleType("AutoScriptor")
        automation.__dict__.update(
            B=lambda *coordinates: coordinates,
            Box=Mock(),
            T=lambda text, **options: SimpleNamespace(text=text, **options),
            TaskRequireReTry=TaskRequireReTry,
            click=self.click,
            seq_click=self.sequence,
            extract_info=self.extract,
            postnum=postnum,
            ui_T=Mock(return_value=True),
            ui_F=self.hidden,
            wait_for_appear=self.wait,
        )
        game = ModuleType("ZmxyOL")
        game.__dict__.update(ensure_in=self.navigation, register_task=register_task)
        with patch.dict("sys.modules", {"AutoScriptor": automation, "ZmxyOL": game}):
            self.namespace = runpy.run_path(str(TASK_FILE))

    def watering_sequences(self):
        return [invocation for invocation in self.sequence.call_args_list
                if invocation.args[0][0].text == "浇"]

    def test_recognition_targets_are_written_at_their_call_sites(self):
        syntax = ast.parse(TASK_FILE.read_text(encoding="utf-8"))
        hoisted_targets = [
            node.lineno for node in ast.walk(syntax)
            if isinstance(node, (ast.Assign, ast.AnnAssign))
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id in {"T", "I", "B", "Box"}
        ]
        self.assertEqual(hoisted_targets, [], "Write targets directly where they are used")

    def test_daily_task_enters_and_returns_to_village_for_every_initial_amount(self):
        self.assertEqual(self.registration["ensure_in"], "村庄")
        self.assertEqual(self.registration["reschedule"], "daily")
        for initial_amount, expected_clicks in ((1, 2), (5, 1), (10, 0)):
            with self.subTest(initial_amount=initial_amount):
                self.actions.reset_mock()
                self.extract.side_effect = [initial_amount, 10]
                self.namespace["task"]()
                self.assertEqual(self.navigation.call_args_list, [call("村庄"), call("村庄")])
                self.assertEqual(self.actions.mock_calls[0], call.ensure_in("村庄"))
                self.assertEqual(self.actions.mock_calls[-1], call.ensure_in("村庄"))
                switches = [invocation for invocation in self.click.call_args_list
                            if invocation.args[0] == (1163, 630, 61, 53)]
                self.assertEqual(sum(invocation.kwargs.get("repeat", 1) for invocation in switches), expected_clicks)
                self.assertEqual(len(self.watering_sequences()), 2)
                for invocation in self.watering_sequences():
                    self.assertEqual([target.text for target in invocation.args[0]], ["浇", "确定"])
                    self.assertTrue(invocation.kwargs["until"]())
                    self.assertEqual(self.hidden.call_args.args[0].text, "确定")

    def test_unreadable_or_invalid_initial_amount_never_waters(self):
        for amount in (None, 0, 7):
            with self.subTest(amount=amount):
                self.actions.reset_mock()
                self.extract.return_value = amount
                with self.assertRaises(TaskRequireReTry):
                    self.namespace["task"]()
                self.assertEqual(self.watering_sequences(), [])
                self.navigation.assert_called_once_with("村庄")

    def test_switch_waits_for_ten_instead_of_accepting_a_stale_nonempty_value(self):
        self.extract.side_effect = [1, 10]
        self.namespace["task"]()
        read_selected_amount = self.extract.call_args_list[1].kwargs["post_process"]
        self.assertIsNone(read_selected_amount("x1"))
        self.assertIsNone(read_selected_amount("x5"))
        self.assertEqual(read_selected_amount("x10"), 10)
        self.assertTrue(self.extract.call_args_list[1].kwargs["ensure_not_empty"])

    def test_failed_amount_switch_never_waters_or_claims_completion(self):
        self.extract.side_effect = [5, None]
        with self.assertRaises(TaskRequireReTry):
            self.namespace["task"]()
        self.assertEqual(self.watering_sequences(), [])
        self.navigation.assert_called_once_with("村庄")

    def test_failed_confirmation_stops_before_the_next_watering(self):
        self.extract.return_value = 10

        def run_sequence(targets, **options):
            if targets[0].text == "浇":
                raise RuntimeError("confirmation timed out")

        self.sequence.side_effect = run_sequence
        with self.assertRaisesRegex(RuntimeError, "confirmation timed out"):
            self.namespace["task"]()
        self.assertEqual(len(self.watering_sequences()), 1)
        self.navigation.assert_called_once_with("村庄")


if __name__ == "__main__":
    unittest.main()
