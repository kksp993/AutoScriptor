"""Task declarations own the execution precondition, never import-time navigation.

Before this contract, ensure_in was accepted as private cfg data and missing
entries were indistinguishable from current-scene debug tasks. Source audits
include every task file, even files ignored by text-search tools.
"""
from __future__ import annotations

import ast
import copy
import inspect
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[2]
TASK_ROOT = ROOT / "tasks"
VILLAGE = "\u6751\u5e84"
NORTH_VILLAGE = "\u6781\u5317\u6751\u5e84"
HEAVEN_LEFT = "\u5929\u5ead#-1"


class TestTaskEntryRegistration(unittest.TestCase):
    def setUp(self):
        from tasks import task_register

        self.task_register = task_register
        self.registry = task_register.TaskRegistry()
        self.configuration = {"tasks": {"entry_fixture": {
            "on": True, "next_exec_time": 123, "params": {},
            "preferred_locations": [], "private_setting": "preserved",
        }}}
        self.filename = str(TASK_ROOT / "test_group" / "entry_fixture.py")
        self.navigation = Mock()

        def task_body():
            self.navigation()

        self.task_body = task_body
        for patcher in (
            patch.object(task_register, "cfg", self.configuration),
            patch.object(task_register, "task_registry", self.registry),
            patch.object(task_register, "registration_counter", 0),
            patch.object(task_register.inspect, "getfile", return_value=self.filename),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_missing_entry_is_rejected_before_config_access(self):
        configuration_before = copy.deepcopy(self.configuration)
        with self.assertRaisesRegex(TypeError, "ensure_in"):
            self.task_register.register_task(self.task_body)
        with self.assertRaisesRegex(TypeError, "ensure_in"):
            self.task_register.register_task()
        self.assertEqual(self.configuration, configuration_before)
        self.assertEqual(self.registry.all_paths(), [])
        self.assertEqual(self.task_register.registration_counter, 0)

    def test_invalid_entries_are_rejected_before_config_or_registry_changes(self):
        invalid_entries = (
            "", "   ", [], (), [""], [VILLAGE, " "], [VILLAGE, None],
            42, {VILLAGE}, {"entry": VILLAGE}, "unknown-navigation-entry",
            [VILLAGE, "unknown-navigation-entry"],
        )
        configuration_before = copy.deepcopy(self.configuration)
        for entry in invalid_entries:
            for debug in (False, True):
                with self.subTest(entry=entry, debug=debug):
                    with self.assertRaisesRegex(ValueError, "ensure_in"):
                        self.task_register.register_task(
                            self.task_body, ensure_in=entry, debug=debug,
                        )
                    self.assertEqual(self.configuration, configuration_before)
                    self.assertEqual(self.registry.all_paths(), [])
                    self.assertEqual(self.task_register.registration_counter, 0)

    def test_none_is_rejected_including_debug_and_deprecated_tasks(self):
        configuration_before = copy.deepcopy(self.configuration)
        for debug in (False, True, None, "true"):
            for deprecated in (False, True):
                with self.subTest(debug=debug, deprecated=deprecated):
                    with self.assertRaisesRegex(ValueError, "ensure_in"):
                        self.task_register.register_task(
                            self.task_body, ensure_in=None,
                            debug=debug, deprecated=deprecated,
                        )
                    self.assertEqual(self.configuration, configuration_before)
                    self.assertEqual(self.registry.all_paths(), [])

    def test_decorator_factory_validates_before_it_returns(self):
        with self.assertRaisesRegex(ValueError, "ensure_in"):
            self.task_register.register_task(ensure_in=[])
        with self.assertRaisesRegex(ValueError, "ensure_in"):
            self.task_register.register_task(ensure_in=None)

    def test_normalized_entry_is_runtime_only_and_defaults_planning(self):
        self.configuration["tasks"]["entry_fixture"]["ensure_in"] = ["stale-entry"]
        self.task_register.register_task(
            self.task_body, ensure_in=(f" {VILLAGE} ", NORTH_VILLAGE, VILLAGE),
        )
        task_path = "test_group/entry_fixture"
        self.assertEqual(self.registry.get_ensure_in(task_path), [VILLAGE, NORTH_VILLAGE])
        self.assertEqual(self.registry.get_planning_defaults(task_path), {
            "preferred_locations": [VILLAGE, NORTH_VILLAGE], "after_tasks": [],
        })
        saved_entry = self.configuration["tasks"]["entry_fixture"]
        self.assertNotIn("ensure_in", saved_entry)
        self.assertEqual(saved_entry["preferred_locations"], [])
        self.assertEqual(saved_entry["private_setting"], "preserved")
        self.assertIn("ensure_in", self.task_register.OFFICIAL_TASK_FIELDS)
        self.assertNotIn("ensure_in", self.task_register.USER_TASK_FIELDS)
        returned_entry = self.registry.get_ensure_in(task_path)
        returned_entry.clear()
        self.assertEqual(self.registry.get_ensure_in(task_path), [VILLAGE, NORTH_VILLAGE])

    def test_explicit_planning_preferences_override_entry_including_empty(self):
        for preferred_locations in ([], [NORTH_VILLAGE]):
            with self.subTest(preferred_locations=preferred_locations):
                self.task_register.register_task(
                    self.task_body, ensure_in=VILLAGE,
                    preferred_locations=preferred_locations,
                )
                self.assertEqual(
                    self.registry.get_planning_defaults("test_group/entry_fixture")["preferred_locations"],
                    preferred_locations,
                )
                self.assertEqual(self.registry.get_ensure_in("test_group/entry_fixture"), [VILLAGE])

    def test_registration_does_not_navigate_and_returns_the_registered_wrapper(self):
        returned_function = self.task_register.register_task(ensure_in=HEAVEN_LEFT)(self.task_body)
        self.assertIs(returned_function, self.registry.get_fn("test_group/entry_fixture"))
        self.assertIs(returned_function.__wrapped__, self.task_body)
        self.navigation.assert_not_called()
        self.assertEqual(self.registry.get_ensure_in("test_group/entry_fixture"), [HEAVEN_LEFT])

    def test_registered_execution_navigates_once_before_body_on_every_attempt(self):
        from AutoScriptor.core.background import bg
        from AutoScriptor.logging import tracer
        from ZmxyOL.nav import api as navigation_api

        events = []
        self.navigation.side_effect = lambda: events.append("body")
        navigate = Mock(side_effect=lambda target: events.append(target))
        with (
            patch.object(navigation_api, "ensure_in", navigate),
            patch.object(bg, "clear"),
            patch.object(tracer, "clear_debug_screenshots"),
            patch.object(self.task_register, "_apply_task_battle_startup"),
            patch.object(self.task_register, "_clear_task_battle_startup"),
        ):
            self.task_register.register_task(self.task_body, ensure_in=HEAVEN_LEFT)
            self.registry.get_fn("test_group/entry_fixture")()
            self.registry.get_fn("test_group/entry_fixture")()
        self.assertEqual(events, [HEAVEN_LEFT, "body", HEAVEN_LEFT, "body"])
        self.assertEqual(navigate.call_count, 2)

    def test_anywhere_is_explicit_and_not_a_map_preference(self):
        from ZmxyOL import ANYWHERE

        self.task_register.register_task(self.task_body, ensure_in=ANYWHERE)
        self.assertEqual(self.registry.get_ensure_in("test_group/entry_fixture"), [ANYWHERE])
        self.assertEqual(self.registry.get_planning_defaults("test_group/entry_fixture"), {
            "preferred_locations": [], "after_tasks": [],
        })
        self.navigation.assert_not_called()

    def test_internal_fixture_registration_remains_compatible(self):
        from ZmxyOL import ANYWHERE

        self.registry.register("test_group/internal_fixture", self.task_body)
        self.assertEqual(self.registry.get_ensure_in("test_group/internal_fixture"), [ANYWHERE])
        self.assertIsNone(self.registry.get_ensure_in("missing"))
        self.assertEqual(self.registry.get_planning_defaults("test_group/internal_fixture"), {
            "preferred_locations": [], "after_tasks": [],
        })

    def test_validation_uses_current_navigation_registry_after_reload(self):
        import ZmxyOL.nav.map_manager as navigation_module

        replacement_map = SimpleNamespace(locs={"reloaded-entry": object()})
        with patch.object(navigation_module, "mm", replacement_map):
            self.task_register.register_task(self.task_body, ensure_in="reloaded-entry")
            with self.assertRaisesRegex(ValueError, "ensure_in"):
                self.task_register.register_task(self.task_body, ensure_in=VILLAGE)
        self.assertEqual(self.registry.get_ensure_in("test_group/entry_fixture"), ["reloaded-entry"])

    def test_navigation_failure_and_cancellation_skip_body_and_clear_context(self):
        from AutoScriptor.core.background import bg
        from AutoScriptor.logging import tracer
        from AutoScriptor.utils.cancel import TaskCancelled
        from ZmxyOL.nav import api as navigation_api

        for failure in (RuntimeError("unreachable"), TaskCancelled("stop")):
            with self.subTest(failure=type(failure).__name__), ExitStack() as patches:
                patches.enter_context(patch.object(bg, "clear"))
                patches.enter_context(patch.object(tracer, "clear_debug_screenshots"))
                patches.enter_context(patch.object(self.task_register, "_apply_task_battle_startup"))
                clear_context = patches.enter_context(patch.object(self.task_register, "_clear_task_battle_startup"))
                navigate = patches.enter_context(patch.object(navigation_api, "ensure_in", side_effect=failure))
                wrapped = self.task_register.register_task(self.task_body, ensure_in=HEAVEN_LEFT, debug=True)
                with self.assertRaises(type(failure)):
                    wrapped()
                self.navigation.assert_not_called()
                navigate.assert_called_once_with(HEAVEN_LEFT)
                clear_context.assert_called_once_with()

    def test_alternatives_preserve_signature_arguments_and_return_value(self):
        from AutoScriptor.core.background import bg
        from AutoScriptor.logging import tracer
        from ZmxyOL.nav import api as navigation_api

        def parameterized_task(amount: int = 2, *, enabled: bool = True):
            return amount, enabled

        with ExitStack() as patches:
            patches.enter_context(patch.object(bg, "clear"))
            patches.enter_context(patch.object(tracer, "clear_debug_screenshots"))
            patches.enter_context(patch.object(self.task_register, "_apply_task_battle_startup"))
            patches.enter_context(patch.object(self.task_register, "_clear_task_battle_startup"))
            navigate = patches.enter_context(patch.object(navigation_api, "ensure_in"))
            locations = [VILLAGE, NORTH_VILLAGE]
            wrapped = self.task_register.register_task(parameterized_task, ensure_in=locations)
            locations.clear()
            self.assertEqual(inspect.signature(wrapped), inspect.signature(parameterized_task))
            self.assertEqual(wrapped(5, enabled=False), (5, False))
            navigate.assert_called_once_with([VILLAGE, NORTH_VILLAGE])

    def test_anywhere_execution_calls_same_api_without_touching_device_or_map(self):
        from AutoScriptor.core.background import bg
        from AutoScriptor.logging import tracer
        from ZmxyOL import ANYWHERE
        from ZmxyOL.nav import api as navigation_api

        with ExitStack() as patches:
            patches.enter_context(patch.object(bg, "clear"))
            patches.enter_context(patch.object(tracer, "clear_debug_screenshots"))
            patches.enter_context(patch.object(self.task_register, "_apply_task_battle_startup"))
            patches.enter_context(patch.object(self.task_register, "_clear_task_battle_startup"))
            navigate = patches.enter_context(patch.object(navigation_api, "ensure_in", wraps=navigation_api.ensure_in))
            locate_region = patches.enter_context(patch.object(navigation_api, "locate_region"))
            navigation_map = patches.enter_context(patch.object(navigation_api, "mm"))
            wrapped = self.task_register.register_task(self.task_body, ensure_in=ANYWHERE)
            wrapped()
            navigate.assert_called_once_with(ANYWHERE)
            self.navigation.assert_called_once_with()
            for target in (ANYWHERE, [ANYWHERE], (ANYWHERE,)):
                self.assertIsNone(navigation_api.ensure_in(target))
            locate_region.assert_not_called()
            self.assertEqual(navigation_map.mock_calls, [])

    def test_anywhere_must_not_silently_discard_specific_destinations(self):
        from ZmxyOL import ANYWHERE
        from ZmxyOL.nav import api as navigation_api

        for target in ([ANYWHERE, VILLAGE], [VILLAGE, ANYWHERE]):
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, "ANYWHERE"):
                self.task_register.register_task(self.task_body, ensure_in=target)
            with self.assertRaisesRegex(ValueError, "ANYWHERE"), patch.object(navigation_api, "locate_region") as locate_region:
                navigation_api.ensure_in(target)
            locate_region.assert_not_called()


class TestBuiltinTaskEntryDeclarations(unittest.TestCase):
    """Read source only: this audit never imports tasks or initializes a device."""

    def test_all_builtin_decorators_declare_registered_entries(self):
        navigation_source = ROOT / "ZmxyOL/nav/envs/env_locs.py"
        navigation_tree = ast.parse(navigation_source.read_text(encoding="utf-8-sig"))
        groups_source = ROOT / "ZmxyOL/nav/envs/decorators.py"
        groups_tree = ast.parse(groups_source.read_text(encoding="utf-8-sig"))
        entry_groups = {
            node.targets[0].id: ast.literal_eval(node.value)
            for node in groups_tree.body
            if isinstance(node, ast.Assign)
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id in {"HAS_SHEZHI", "HAS_SHIJIEDITU"}
        }
        registered_names = set()
        for node in ast.walk(navigation_tree):
            if not isinstance(node, ast.Call):
                continue
            constructor = getattr(node.func, "id", None)
            if constructor == "Env":
                registered_names.add(ast.literal_eval(node.args[0]))
            elif constructor == "Loc":
                registered_names.add(ast.literal_eval(node.args[1]))

        declarations = {}
        for task_file in sorted(TASK_ROOT.rglob("*.py")):
            if "__pycache__" in task_file.parts:
                continue
            task_tree = ast.parse(task_file.read_text(encoding="utf-8-sig"))
            for node in ast.walk(task_tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for decorator in node.decorator_list:
                    decorator_function = decorator.func if isinstance(decorator, ast.Call) else decorator
                    if getattr(decorator_function, "id", None) != "register_task":
                        continue
                    relative_path = task_file.relative_to(TASK_ROOT).with_suffix("").as_posix()
                    with self.subTest(task=relative_path):
                        self.assertIsInstance(decorator, ast.Call)
                        keywords = {keyword.arg: keyword.value for keyword in decorator.keywords}
                        self.assertIn("ensure_in", keywords, "Entry metadata must never be inferred from a directory")
                        entry_expression = keywords["ensure_in"]
                        if isinstance(entry_expression, ast.Name):
                            if entry_expression.id == "ANYWHERE":
                                self.assertTrue(any(
                                    isinstance(import_node, ast.ImportFrom)
                                    and import_node.module in {"ZmxyOL", "ZmxyOL.nav", "ZmxyOL.nav.api"}
                                    and any(imported.name in {"ANYWHERE", "*"} for imported in import_node.names)
                                    for import_node in task_tree.body
                                ), "ANYWHERE must be imported by the task, not assumed from AutoScriptor")
                                continue
                            self.assertIn(entry_expression.id, entry_groups, "Unknown shared entry group")
                            entry = entry_groups[entry_expression.id]
                        else:
                            entry = ast.literal_eval(entry_expression)
                        declarations[relative_path] = entry
                        self.assertIsNotNone(entry, "Use explicit ANYWHERE instead of None")
                        names = [entry] if isinstance(entry, str) else entry
                        self.assertIsInstance(names, (list, tuple))
                        self.assertTrue(names, "Empty entry declarations are not non-applicable entries")
                        for name in names:
                            self.assertIsInstance(name, str)
                            self.assertTrue(name.strip())
                            self.assertIn(name, registered_names)

        self.assertTrue(declarations, "No built-in task decorators were audited")


if __name__ == "__main__":
    unittest.main()
