"""What a task reload may and may not re-import.

Two invariants, both learned the hard way:

1. A reload must keep the modules that own process-wide objects. Re-importing
   ``tasks.task_register`` builds a second, empty registry while the task manager
   and the catalog keep reading the first one.
2. The stale-leaf prune must refuse to act on an empty registry. "No task is
   registered" never means the user's tree is stale; it means registration did
   not reach the registry being read, and pruning there deletes the whole tree.

The second one is a data-loss guard, so it is asserted directly.
"""
from __future__ import annotations

import copy
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import orchestrator.catalog as catalog
from AutoScriptor.utils.app_config import cfg
from tasks.task_register import task_registry


class TestReloadBoundary(unittest.TestCase):
    def test_scripts_and_derived_modules_are_reimported(self):
        for name in (
            "tasks",
            "tasks.battle_task_params",
            "tasks.每日任务.村庄.竞技场",
            "tasks._ct_abc123",
        ):
            with self.subTest(module=name):
                self.assertTrue(catalog.is_reloadable_task_module(name))

    def test_process_wide_owners_survive(self):
        # task_register owns the singleton; task_params compares parameter
        # defaults against TableParam by class identity. Re-importing either
        # makes the reload split the object every reader already holds.
        for name in (
            "tasks.task_params",
            "tasks.task_register",
            "tasks.task_state",
            "tasks.time",
        ):
            with self.subTest(module=name):
                self.assertFalse(catalog.is_reloadable_task_module(name))

    def test_unrelated_packages_are_not_touched(self):
        for name in ("ZmxyOL", "ZmxyOL.battle.table_param", "orchestrator.catalog", "backend.webui.server"):
            with self.subTest(module=name):
                self.assertFalse(catalog.is_reloadable_task_module(name))


class TestPruneGuard(unittest.TestCase):
    """An empty registry must never cost the user their task table."""

    def setUp(self):
        self._cfg_backup = copy.deepcopy(cfg._config)
        self._reg_backup = dict(task_registry._tasks)
        cfg._config["tasks"] = {
            "宠物培养": {"on": True, "next_exec_time": 0},
        }

    def tearDown(self):
        cfg._config = self._cfg_backup
        task_registry._tasks = self._reg_backup

    def test_empty_registry_skips_prune(self):
        task_registry.clear()

        with patch.object(catalog, "_last_custom_load_errors", []):
            self.assertFalse(catalog.prune_stale_tasks())

        self.assertIn("宠物培养", cfg._config["tasks"])

    def test_populated_registry_still_prunes(self):
        task_registry.clear()
        task_registry.register("每日任务/村庄/宠物培养", lambda: None)
        # an entry nobody registers any more is what the prune exists to remove
        cfg._config["tasks"]["已删除任务"] = {"on": True, "next_exec_time": 0}

        with patch.object(catalog, "_last_custom_load_errors", []):
            self.assertTrue(catalog.prune_stale_tasks())

        self.assertIn("宠物培养", cfg._config["tasks"])
        self.assertNotIn("已删除任务", cfg._config["tasks"])

    def test_import_errors_still_skip_prune(self):
        task_registry.clear()
        task_registry.register("每日任务/村庄/宠物培养", lambda: None)

        with patch.object(catalog, "_last_custom_load_errors", [{"path": "x", "error": "y"}]):
            self.assertFalse(catalog.prune_stale_tasks())

        self.assertIn("宠物培养", cfg._config["tasks"])


if __name__ == "__main__":
    unittest.main()
