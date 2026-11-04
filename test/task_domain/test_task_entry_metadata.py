"""Task entry declarations describe source navigation without performing it.

Before this contract, ensure_in was accepted as private cfg data and missing
entries were indistinguishable from current-scene debug tasks. Source audits
include every task file, even files ignored by text-search tools.
"""
from __future__ import annotations

import ast
import copy
import unittest
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

    def test_none_requires_explicit_debug_true_even_for_deprecated_tasks(self):
        configuration_before = copy.deepcopy(self.configuration)
        for debug in (False, None, "true"):
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

    def test_declaration_never_navigates_or_changes_task_body(self):
        returned_function = self.task_register.register_task(ensure_in=HEAVEN_LEFT)(self.task_body)
        self.assertIs(returned_function, self.task_body)
        self.navigation.assert_not_called()
        returned_function()
        self.navigation.assert_called_once_with()
        self.assertEqual(self.registry.get_ensure_in("test_group/entry_fixture"), [HEAVEN_LEFT])

    def test_registered_execution_does_not_prepend_navigation(self):
        from AutoScriptor.core.background import bg
        from AutoScriptor.logging import tracer
        from ZmxyOL.nav import api as navigation_api

        unexpected_navigation = Mock(side_effect=AssertionError("Metadata must not trigger navigation"))
        with (
            patch.object(self.task_register, "ensure_in", unexpected_navigation, create=True),
            patch.object(navigation_api, "ensure_in", unexpected_navigation),
            patch.object(bg, "clear"),
            patch.object(tracer, "clear_debug_screenshots"),
            patch.object(self.task_register, "_apply_task_battle_startup"),
            patch.object(self.task_register, "_clear_task_battle_startup"),
        ):
            self.task_register.register_task(self.task_body, ensure_in=HEAVEN_LEFT)
            self.registry.get_fn("test_group/entry_fixture")()
        self.navigation.assert_called_once_with()
        unexpected_navigation.assert_not_called()

    def test_scene_debug_task_has_explicit_non_applicable_entry(self):
        self.task_register.register_task(self.task_body, ensure_in=None, debug=True)
        self.assertIsNone(self.registry.get_ensure_in("test_group/entry_fixture"))
        self.assertEqual(self.registry.get_planning_defaults("test_group/entry_fixture"), {
            "preferred_locations": [], "after_tasks": [],
        })
        self.navigation.assert_not_called()

    def test_internal_fixture_registration_remains_compatible(self):
        self.registry.register("test_group/internal_fixture", self.task_body)
        self.assertIsNone(self.registry.get_ensure_in("test_group/internal_fixture"))
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


class TestBuiltinTaskEntryDeclarations(unittest.TestCase):
    """Read source only: this audit never imports tasks or initializes a device."""

    def test_all_builtin_decorators_declare_registered_entries(self):
        navigation_source = ROOT / "ZmxyOL/nav/envs/env_locs.py"
        navigation_tree = ast.parse(navigation_source.read_text(encoding="utf-8-sig"))
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
                        entry = ast.literal_eval(keywords["ensure_in"])
                        declarations[relative_path] = entry
                        if entry is None:
                            self.assertIs(ast.literal_eval(keywords.get("debug", ast.Constant(False))), True)
                            continue
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
