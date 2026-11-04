"""Mail collection finishes only after five additional single-page claims."""

import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

from AutoScriptor.core.box import Box
from AutoScriptor.utils.cancel import TaskCancelled
from orchestrator import catalog
from tasks import task_register


TASK_FILE = Path(__file__).resolve().parents[2] / "tasks/其他任务/特殊功能/领取邮件.py"
TASK_PATH = "其他任务/特殊功能/领取邮件"


class MailTaskTests(unittest.TestCase):
    def setUp(self):
        self.saved_entry = {"on": True, "next_exec_time": 123, "params": {}}
        self.configuration = {"tasks": {"领取邮件": self.saved_entry.copy()}}
        self.registry = task_register.TaskRegistry()
        self.namespace = {"__name__": "mail_task_regression"}
        with patch.object(task_register, "cfg", self.configuration), patch.object(
            task_register, "task_registry", self.registry
        ), patch.object(task_register, "registration_counter", 0):
            exec(compile(TASK_FILE.read_text(encoding="utf-8"), str(TASK_FILE), "exec"), self.namespace)
        self.navigate = Mock()
        self.click = Mock(return_value=True)
        self.sleep = Mock()
        self.page_check = Mock(return_value=True)
        self.namespace.update(
            ensure_in=self.navigate, click=self.click, sleep=self.sleep,
            _is_single_mail_page=self.page_check, monotonic=Mock(return_value=0),
            logger=Mock(),
        )

    def claim_clicks(self):
        return [
            invocation for invocation in self.click.call_args_list
            if getattr(invocation.args[0].ui, "text", None) == "键领取"
        ]

    def test_builtin_mail_task_registers_and_preserves_existing_identity(self):
        self.assertIn(TASK_FILE, catalog.gather_py_files())
        self.assertEqual(self.registry.get_path("领取邮件"), TASK_PATH)
        self.assertTrue(self.registry.has_task(TASK_PATH))
        self.assertIsNotNone(self.registry.get_fn(TASK_PATH))
        self.assertTrue(self.registry.get_debug_default(TASK_PATH))
        saved_configuration = self.configuration["tasks"]["领取邮件"]
        self.assertEqual(saved_configuration["on"], self.saved_entry["on"])
        self.assertEqual(saved_configuration["next_exec_time"], self.saved_entry["next_exec_time"])

    def test_initial_single_page_receives_five_claims_and_final_check(self):
        self.namespace["task"]()
        self.navigate.assert_called_once_with("村庄")
        self.assertEqual(len(self.claim_clicks()), 5)
        self.assertEqual(self.page_check.call_count, 6)
        self.assertEqual(self.sleep.call_args_list, [call(3)] * 5)
        self.assertEqual(self.click.call_args.args[0].ui.name, "邮件-关闭")

    def test_slow_multiple_pages_do_not_use_the_five_extra_claims(self):
        self.page_check.side_effect = [False] * 8 + [True] * 6
        self.namespace["task"]()
        self.assertEqual(len(self.claim_clicks()), 13)
        self.assertEqual(self.sleep.call_count, 13)

    def test_page_rebound_resets_extra_claim_counter(self):
        self.page_check.side_effect = [True, True, False] + [True] * 6
        self.namespace["task"]()
        self.assertEqual(len(self.claim_clicks()), 8)

    def test_timeout_does_not_close_mail_or_report_completion(self):
        self.page_check.return_value = False
        self.namespace["monotonic"] = Mock(side_effect=[0, 0, 601])
        with self.assertRaisesRegex(RuntimeError, "600"):
            self.namespace["task"]()
        self.assertEqual(len(self.claim_clicks()), 1)
        self.assertFalse(any(
            invocation.args[0].ui.name == "邮件-关闭"
            for invocation in self.click.call_args_list
        ))

    def test_slow_wait_remains_cancellable(self):
        self.sleep.side_effect = TaskCancelled("stop")
        with self.assertRaises(TaskCancelled):
            self.namespace["task"]()
        self.assertEqual(len(self.claim_clicks()), 1)


class MailPageRecognitionTests(unittest.TestCase):
    def setUp(self):
        self.namespace = {"__name__": "mail_page_regression"}
        with patch.object(task_register, "cfg", {"tasks": {}}), patch.object(
            task_register, "task_registry", task_register.TaskRegistry()
        ), patch.object(task_register, "registration_counter", 0):
            exec(compile(TASK_FILE.read_text(encoding="utf-8"), str(TASK_FILE), "exec"), self.namespace)

    def test_page_text_is_validated_not_substring_matched(self):
        for text, expected in (
            ("1/1", True), (" 1 / 1 ", True), ("1/10", False),
            ("11/1", False), ("", False), (None, False),
        ):
            with self.subTest(text=text):
                self.namespace.update(
                    locate=Mock(return_value=[[Box(600, 500, 30, 20)]]),
                    extract_info=Mock(return_value=text),
                )
                self.assertEqual(self.namespace["_is_single_mail_page"](), expected)

    def test_missing_page_is_not_treated_as_single_page(self):
        self.namespace.update(locate=Mock(return_value=[None]), extract_info=Mock())
        self.assertFalse(self.namespace["_is_single_mail_page"]())
        self.namespace["extract_info"].assert_not_called()


if __name__ == "__main__":
    unittest.main()
