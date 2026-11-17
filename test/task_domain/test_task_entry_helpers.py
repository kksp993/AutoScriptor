"""Confirmed task entries skip only initial navigation, never later stages/recovery."""
import ast
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch


ROOT = Path(__file__).resolve().parents[2]


class TaskEntryHelperTests(unittest.TestCase):
    def test_multi_stage_combat_reuses_only_the_first_entry(self):
        from ZmxyOL.battle import tasks as battle_tasks

        stages = {
            "first": {"location": ("first-map", 1), "target": Mock(), "idx": 0},
            "second": {"location": ("second-map", 2), "target": Mock(), "idx": 0},
        }
        for entry_ready in (False, True):
            with self.subTest(entry_ready=entry_ready), ExitStack() as patches:
                patches.enter_context(patch.object(battle_tasks, "get_task_table", return_value=stages))
                navigate = patches.enter_context(patch.object(battle_tasks, "ensure_in"))
                patches.enter_context(patch.object(battle_tasks, "click"))
                patches.enter_context(patch.object(battle_tasks, "wait_for_appear"))
                patches.enter_context(patch.object(battle_tasks, "ui_T", return_value=False))
                battle_tasks.battle_tasks(SimpleNamespace(), list(stages), entry_ready=entry_ready)
                expected_calls = [call("second-map", 2)] if entry_ready else [call("first-map", 1), call("second-map", 2)]
                self.assertEqual(navigate.call_args_list, expected_calls)

    def test_kunlunshan_keeps_reward_navigation_after_reusing_entry(self):
        from ZmxyOL.battle.procedure import kunlunshan

        for entry_ready in (False, True):
            with self.subTest(entry_ready=entry_ready), ExitStack() as patches:
                navigate = patches.enter_context(patch.object(kunlunshan, "ensure_in"))
                enter = patches.enter_context(patch.object(kunlunshan, "enter_kunlunshan"))
                battle = patches.enter_context(patch.object(kunlunshan, "kunlunshan_battle"))
                patches.enter_context(patch.object(kunlunshan, "sleep"))
                patches.enter_context(patch.object(kunlunshan, "click"))
                kunlunshan.kunlunshan_task(SimpleNamespace(), battle_loop=3, entry_ready=entry_ready)
                self.assertEqual(navigate.call_args_list, [call("天庭", 1)] * (1 if entry_ready else 2))
                enter.assert_called_once_with()
                battle.assert_called_once_with(num=3, equipment="诛仙剑阵")

    def test_lingqi_probe_keeps_default_navigation_for_standalone_callers(self):
        from ZmxyOL.battle.procedure import chaos
        from ZmxyOL.nav import api as navigation_api

        with patch.object(chaos, "click"), patch.object(chaos, "extract_info", return_value="金"), patch.object(navigation_api, "ensure_in") as navigate:
            self.assertEqual(chaos.check_linggen(SimpleNamespace(), entry_ready=True), "金")
            navigate.assert_not_called()
            chaos.check_linggen(SimpleNamespace())
            navigate.assert_called_once_with(["极北", "极寒深渊"], [-1, None])

    def test_costume_choice_propagates_confirmed_entry_and_none_remains_noop(self):
        from ZmxyOL.battle import utils as battle_utils

        with patch.object(battle_utils, "wear_item") as wear_item:
            battle_utils.wear_shizhuang_choice(None, entry_ready=True)
            wear_item.assert_not_called()
            battle_utils.wear_shizhuang_choice(battle_utils.WuQi.风虎之怒, entry_ready=True)
            self.assertTrue(wear_item.call_args.kwargs["entry_ready"])
        with patch.object(battle_utils, "ensure_in") as navigate, patch.object(battle_utils, "find_in_bag"), patch.object(battle_utils, "click"), patch.object(battle_utils, "sleep"):
            item = {"bag_class": "bag", "item_name": "costume"}
            battle_utils.wear_item(item, entry_ready=True)
            navigate.assert_not_called()
            battle_utils.wear_item(item)
            navigate.assert_called_once_with("背包")

    def test_builtin_tasks_never_begin_with_unconditional_navigation(self):
        for filename in (ROOT / "tasks").rglob("*.py"):
            tree = ast.parse(filename.read_text(encoding="utf-8-sig"))
            for function in ast.walk(tree):
                if not isinstance(function, ast.FunctionDef) or not any(
                    isinstance(decorator, ast.Call) and getattr(decorator.func, "id", None) == "register_task"
                    for decorator in function.decorator_list
                ):
                    continue
                statements = function.body
                if isinstance(statements[0], ast.Expr) and isinstance(statements[0].value, ast.Constant):
                    statements = statements[1:]
                if not statements:
                    continue
                first_statement = statements[0]
                call_expression = first_statement.value if isinstance(first_statement, ast.Expr) else None
                if not isinstance(call_expression, ast.Call) or getattr(call_expression.func, "id", None) != "ensure_in":
                    continue
                with self.subTest(task=filename.relative_to(ROOT).as_posix()):
                    self.fail("Declare the actual entry in register_task instead of navigating again before any task actions")


if __name__ == "__main__":
    unittest.main()
