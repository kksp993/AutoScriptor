"""Task-local parameter labels survive reload/projection, never user persistence."""
from __future__ import annotations

import copy
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


class TestTaskParameterDocumentation(unittest.TestCase):
    def setUp(self):
        from tasks import task_register

        self.registration = task_register
        self.registry = task_register.TaskRegistry()
        self.task_path = "label_group/label_fixture"
        self.configuration = {"tasks": {"label_fixture": {
            "on": True, "next_exec_time": 123,
            "params": {"difficulty": 7, "enabled": False},
            "private_setting": "preserved",
        }}}
        self.filename = str(Path(__file__).resolve().parents[2] / "tasks/label_group/label_fixture.py")

        def task_body(difficulty=1, *, enabled=True):
            return difficulty, enabled

        self.task_body = task_body
        for patcher in (
            patch.object(task_register, "cfg", self.configuration),
            patch.object(task_register, "task_registry", self.registry),
            patch.object(task_register, "registration_counter", 0),
            patch.object(task_register.inspect, "getfile", return_value=self.filename),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def register_task(self, **metadata):
        return self.registration.register_task(ensure_in=self.registration.ANYWHERE, debug=True, **metadata)(self.task_body)

    def test_labels_are_metadata_and_do_not_change_saved_parameters(self):
        labels = {"difficulty": "\u96be\u5ea6", "enabled": "\u542f\u7528\u6311\u6218"}
        self.configuration["tasks"]["label_fixture"]["params_doc"] = {"stale": "old label"}
        returned_function = self.register_task(params_doc=labels)

        stored = self.configuration["tasks"]["label_fixture"]
        self.assertNotIn("params_doc", stored)
        self.assertEqual(stored["params"], {"difficulty": 7, "enabled": False})
        self.assertEqual(stored["next_exec_time"], 123)
        self.assertEqual(stored["private_setting"], "preserved")
        self.assertIs(returned_function.__wrapped__, self.task_body)
        self.assertEqual(self.registry.get_params_doc(self.task_path), labels)
        self.assertIn("params_doc", self.registration.OFFICIAL_TASK_FIELDS)
        self.assertNotIn("params_doc", self.registration.USER_TASK_FIELDS)

        labels.clear()
        returned_labels = self.registry.get_params_doc(self.task_path)
        returned_labels.clear()
        self.assertEqual(self.registry.get_params_doc(self.task_path)["difficulty"], "\u96be\u5ea6")

    def test_invalid_labels_fail_before_configuration_or_registry_changes(self):
        original = copy.deepcopy(self.configuration)
        for labels in ([], "label", 1, {"unknown": "label"}, {1: "label"},
                       {"difficulty": ""}, {"difficulty": "   "}, {"difficulty": None},
                       {"difficulty": ["label"]}):
            with self.subTest(labels=labels), self.assertRaisesRegex(ValueError, "params_doc"):
                self.register_task(params_doc=labels)
            self.assertEqual(self.configuration, original)
            self.assertEqual(self.registry.all_paths(), [])
            self.assertEqual(self.registration.registration_counter, 0)

    def test_optional_partial_labels_and_reload_use_current_source(self):
        self.register_task(params_doc={"difficulty": " Old label "})
        self.assertEqual(self.registry.get_params_doc(self.task_path), {"difficulty": "Old label"})
        self.register_task(params_doc={"enabled": "New label"})
        self.assertEqual(self.registry.get_params_doc(self.task_path), {"enabled": "New label"})
        self.register_task()
        self.assertEqual(self.registry.get_params_doc(self.task_path), {})
        self.assertEqual(self.registry.get_params_doc("missing"), {})
        self.assertEqual(self.configuration["tasks"]["label_fixture"]["params"]["difficulty"], 7)

    def test_internal_registration_validates_labels_and_hides_deprecated_tasks(self):
        specifications = self.registration.describe_signature(self.task_body)
        with self.assertRaisesRegex(ValueError, "params_doc"):
            self.registry.register(self.task_path, self.task_body, specifications,
                                   params_doc={"unknown": "label"})
        self.assertEqual(self.registry.all_paths(), [])
        self.register_task(params_doc={"difficulty": "Label"}, deprecated=True)
        self.assertEqual(self.registry.get_params_doc(self.task_path), {})
        self.assertEqual(self.registry._tasks[self.task_path]["params_doc"], {"difficulty": "Label"})

    def test_projection_and_both_save_boundaries_strip_labels(self):
        from orchestrator import projection
        from ZmxyOL.accounts.account_store import Character

        self.register_task(params_doc={"difficulty": "\u96be\u5ea6"})
        configuration = SimpleNamespace(_config=self.configuration)
        tree_service = projection.TaskTreeService()
        with patch.object(projection, "cfg", configuration):
            public_tree = tree_service.build_task_tree()
            leaf = public_tree["label_group"]["label_fixture"]
            tree_service.inject_public_task_leaf(leaf, self.task_path)
            self.assertEqual(leaf["params_doc"], {"difficulty": "\u96be\u5ea6"})
            leaf["params_doc"]["difficulty"] = "Forged label"
            self.assertEqual(self.registry.get_params_doc(self.task_path), {"difficulty": "\u96be\u5ea6"})

            flattened = tree_service.flatten_payload_tasks(public_tree)
            stripped = tree_service.strip_runtime_fields(public_tree)
            self.assertNotIn("params_doc", flattened["label_fixture"])
            self.assertNotIn("params_doc", stripped["label_group"]["label_fixture"])
            self.assertEqual(flattened["label_fixture"]["params"], {"difficulty": 7, "enabled": False})
            character = Character("server", "role", {"tasks": {"label_fixture": leaf}})
            persisted = character.to_dict()["tasks"]["label_fixture"]
            self.assertNotIn("params_doc", persisted)
            self.assertEqual(persisted["params"], {"difficulty": 7, "enabled": False})

            self.register_task(params_doc={"difficulty": "New label"})
            tree_service.inject_public_task_leaf(leaf, self.task_path)
            self.assertEqual(leaf["params_doc"], {"difficulty": "New label"})
            self.register_task()
            tree_service.inject_public_task_leaf(leaf, self.task_path)
            self.assertEqual(leaf.get("params_doc", {}), {})


if __name__ == "__main__":
    unittest.main()
