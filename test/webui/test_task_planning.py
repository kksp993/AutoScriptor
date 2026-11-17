"""Planning writes are atomic; location distances are a device-free graph projection."""
import asyncio
import copy
import json
import shutil
import subprocess
import unittest
from contextlib import ExitStack, nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from orchestrator import projection
from tasks.task_register import task_registry
from ZmxyOL.nav import map_manager


class TestPlanningLocations(unittest.TestCase):
    def setUp(self):
        patches = ExitStack()
        self.addCleanup(patches.close)
        self.world = map_manager.MapManager()
        patches.enter_context(patch.object(map_manager, "mm", self.world))
        for name in ("origin", "detour", "destination", "isolated"):
            map_manager.Env(name)
        map_manager.Loc("origin", "inside", None)
        map_manager.Loc("destination", "target", None)
        map_manager.Loc(["origin", "destination"], "shared", None)
        map_manager.Loc(["isolated", "destination"], "partly_reachable", None)
        map_manager.Loc([], "unknown", None)
        for origin, target in (
            ("inside", "origin"), ("origin", "detour"), ("detour", "destination"),
            ("destination", "target"), ("shared", "origin"), ("shared", "target"),
            ("origin", "shared"), ("partly_reachable", "target"),
        ):
            self.world.register_path(origin, target)(Mock(side_effect=AssertionError("must not navigate")))
        self.tree = projection.TaskTreeService()

    def test_matrix_preserves_directed_costs_and_both_local_legs(self):
        result = self.tree.task_planning_locations()

        self.assertEqual(result["locations"], list(self.world.locs))
        self.assertEqual(list(result["costs"]), result["locations"])
        for destinations in result["costs"].values():
            self.assertEqual(list(destinations), result["locations"])
        self.assertEqual(result["costs"]["inside"]["target"], 4)
        self.assertEqual(result["costs"]["inside"]["inside"], 0)
        self.assertIsNone(result["costs"]["target"]["inside"])
        self.assertIsNone(result["costs"]["isolated"]["target"])
        self.assertTrue(all(value is None for value in result["costs"]["unknown"].values()))
        self.assertTrue(all(destinations["unknown"] is None for destinations in result["costs"].values()))
        json.dumps(result, allow_nan=False)

    def test_shared_locations_use_minimum_reachable_owner_at_both_ends(self):
        result = self.tree.task_planning_locations()

        self.assertEqual(result["costs"]["shared"]["target"], 1)
        self.assertEqual(result["costs"]["partly_reachable"]["target"], 1)
        self.assertEqual(result["costs"]["inside"]["shared"], 2)

    def test_empty_registered_graph_returns_empty_projection(self):
        with patch.object(map_manager, "mm", map_manager.MapManager()):
            self.assertEqual(self.tree.task_planning_locations(), {"locations": [], "costs": {}})

    def test_projection_does_not_observe_move_or_access_configuration(self):
        from ZmxyOL.nav import api

        self.world.set_region("origin", "inside")
        with ExitStack() as guards:
            guards.enter_context(patch.object(projection, "cfg", None))
            guards.enter_context(patch.object(map_manager, "mm", SimpleNamespace(
                locs=self.world.locs, estimate_route_cost=self.world.estimate_route_cost,
            )))
            for method_name in ("get_region", "set_region", "get_nearest_env", "navigate_to"):
                guards.enter_context(patch.object(
                    self.world, method_name, side_effect=AssertionError("must not read or move current position"),
                ))
            guards.enter_context(patch.object(map_manager.Loc, "env", side_effect=AssertionError("must not select current owner")))
            for method_name in ("locate", "probe_region", "locate_region"):
                guards.enter_context(patch.object(api, method_name, side_effect=AssertionError("must not observe device")))
            original_result = self.tree.task_planning_locations()
            self.assertEqual((self.world.cur_env, self.world.cur_loc), ("origin", "inside"))
            self.world.cur_env = "isolated"
            self.world.cur_loc = "isolated"
            self.assertEqual(self.tree.task_planning_locations(), original_result)
            self.assertEqual((self.world.cur_env, self.world.cur_loc), ("isolated", "isolated"))

    def request_locations(self):
        from backend.webui.routes import tasks as tasks_routes

        route = next((route for route in tasks_routes.router.routes
                      if route.path == "/api/task-planning/locations" and "GET" in route.methods), None)
        self.assertIsNotNone(route, "the GET location-planning route must be registered")
        with patch.object(tasks_routes, "orchestrator", SimpleNamespace(
                tree=self.tree, tasks=SimpleNamespace(config_operation=nullcontext))), \
                patch.object(tasks_routes, "cfg", None):
            return asyncio.run(route.endpoint())

    def test_get_route_returns_location_matrix_without_device_observation(self):
        result = self.request_locations()

        self.assertEqual(set(result), {"ok", "locations", "costs"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["locations"], list(self.world.locs))
        self.assertEqual(result["costs"]["inside"]["target"], 4)
        self.assertIsNone(result["costs"]["target"]["inside"])
        json.dumps(result, allow_nan=False)

    def test_get_route_reports_graph_errors_instead_of_empty_success(self):
        with patch.object(self.world, "estimate_route_cost", side_effect=ValueError("invalid registered graph")):
            response = self.request_locations()

        self.assertEqual(response.status_code, 500)
        result = json.loads(response.body)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "task_planning_locations_failed")
        self.assertIn("invalid registered graph", result["message"])


class TestPlanningPersistence(unittest.TestCase):
    def setUp(self):
        patches = ExitStack()
        self.addCleanup(patches.close)
        patches.enter_context(patch.object(task_registry, "_tasks", {}))
        task_registry.register("group/before", lambda: None, task_id="before")
        task_registry.register("group/after", lambda: None, task_id="after", after_tasks=["before"])
        self.table = {name: {"on": True, "next_exec_time": 0} for name in ("before", "after")}
        self.config = SimpleNamespace(
            _config={"tasks": self.table, "task_ordering": {"selection_policy": "list_ready"}},
            _account_data={"characters": {"server": {
                "active": {"tasks": self.table},
                "inactive": {"tasks": copy.deepcopy(self.table)},
            }}},
            active_character=lambda: {"server": "server", "name": "active"},
            save_config=Mock(), _save_account_file=Mock(), save_global_config=Mock(),
        )
        patches.enter_context(patch.object(projection, "cfg", self.config))
        patches.enter_context(patch.object(map_manager, "mm", SimpleNamespace(locs={"home": object()})))
        self.tree = projection.TaskTreeService()
        self.scheduler = Mock()
        self.manager = Mock()
        self.manager.config_transaction.side_effect = nullcontext
        self.lifecycle = projection.WebUILifecycleService(
            self.config, self.manager, self.scheduler, self.tree, Mock(return_value=1),
        )
        patches.enter_context(patch.object(self.lifecycle, "_refresh_task_projection", return_value=1))

    def test_active_save_rejects_cycle_before_mutating_or_persisting(self):
        payload = self.tree.build_task_tree()
        payload["group"]["before"]["after_tasks"] = ["after"]
        before = copy.deepcopy(self.config._config)
        with self.assertRaisesRegex(ValueError, "cycle"):
            self.lifecycle.save_tasks(payload)
        self.assertEqual(self.config._config, before)
        self.config.save_config.assert_not_called()
        self.scheduler.wake.assert_not_called()

    def test_inactive_save_checks_other_leaves_and_is_atomic(self):
        before = copy.deepcopy(self.config._account_data)
        with self.assertRaisesRegex(ValueError, "cycle"):
            self.lifecycle.save_character_task(
                "server", "inactive", "group/before", {**self.table["before"], "after_tasks": ["after"]},
            )
        self.assertEqual(self.config._account_data, before)
        self.config._save_account_file.assert_not_called()
        self.scheduler.wake.assert_not_called()

    def test_invalid_locations_and_references_are_rejected(self):
        for changes, message in (({"preferred_locations": ["missing"]}, "location"),
                                 ({"after_tasks": ["missing"]}, "predecessor")):
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, message):
                self.lifecycle.save_character_task(
                    "server", "inactive", "group/before", {**self.table["before"], **changes},
                )
        self.config._save_account_file.assert_not_called()

    def test_restore_author_defaults_removes_overrides_and_projection_fields(self):
        stored = self.config._account_data["characters"]["server"]["inactive"]["tasks"]
        stored["after"].update(after_tasks=[], preferred_locations=["home"])
        self.lifecycle.save_character_task("server", "inactive", "group/after", {
            "on": True, "next_exec_time": 0,
            "planning_defaults": {"after_tasks": ["before"]},
            "planning_effective": {"after_tasks": []}, "planning_status": {"ready": True},
        })
        saved = self.config._account_data["characters"]["server"]["inactive"]["tasks"]["after"]
        self.assertEqual(saved, {"on": True, "next_exec_time": 0})
        self.config._save_account_file.assert_called_once()
        self.config.save_config.assert_not_called()

    def test_required_entrypoint_survives_cleared_scheduling_preferences(self):
        from orchestrator.model import resolve_planning_specs

        task_registry.register("group/before", lambda: None, task_id="before", ensure_in=["home"])
        defaults = task_registry.get_planning_defaults("group/before")
        self.assertEqual(defaults["preferred_locations"], ["home"])
        specifications, errors = resolve_planning_specs(self.table, locations={"home"})
        self.assertEqual(errors, {})
        self.assertEqual(specifications["before"].preferred_locations, ("home",))

        self.table["before"]["preferred_locations"] = []
        public_leaf = self.table["before"].copy()
        self.tree.inject_public_task_leaf(public_leaf, "group/before")
        self.assertEqual(public_leaf["ensure_in"], ["home"])
        self.assertEqual(public_leaf["planning_effective"]["preferred_locations"], [])
        self.assertNotIn("ensure_in", self.table["before"])

    def test_entrypoint_projection_cannot_be_overridden_or_persisted_by_task_save(self):
        task_registry.register("group/before", lambda: None, task_id="before", ensure_in=["home"])
        payload = self.tree.build_task_tree()
        payload["group"]["before"]["ensure_in"] = ["forged"]
        flattened = self.tree.flatten_payload_tasks(payload)
        self.assertNotIn("ensure_in", flattened["before"])

        self.lifecycle.save_character_task("server", "inactive", "group/before", {
            **self.table["before"], "ensure_in": ["forged"],
        })
        stored = self.config._account_data["characters"]["server"]["inactive"]["tasks"]["before"]
        self.assertNotIn("ensure_in", stored)
        self.assertEqual(task_registry.get_ensure_in("group/before"), ["home"])

    def test_inactive_character_editor_reads_source_labels_and_never_persists_them(self):
        from tasks.task_params import describe_signature

        def task_body(difficulty=1):
            return difficulty

        task_registry.register(
            "group/before", task_body, describe_signature(task_body),
            params_doc={"difficulty": "\u96be\u5ea6"},
        )
        stored = self.config._account_data["characters"]["server"]["inactive"]["tasks"]["before"]
        stored["params"] = {"difficulty": 7}
        public_task = self.tree.get_character_task_public("server", "inactive", "group/before")
        self.assertEqual(public_task["params_doc"], {"difficulty": "\u96be\u5ea6"})
        public_task["params_doc"]["difficulty"] = "Forged label"
        public_task["params"]["difficulty"] = 9
        self.lifecycle.save_character_task("server", "inactive", "group/before", public_task)
        stored = self.config._account_data["characters"]["server"]["inactive"]["tasks"]["before"]
        self.assertNotIn("params_doc", stored)
        self.assertEqual(stored["params"], {"difficulty": 9})
        self.assertEqual(task_registry.get_params_doc("group/before"), {"difficulty": "\u96be\u5ea6"})

    def test_legacy_order_save_preserves_policy_and_explicit_policy_roundtrips(self):
        self.lifecycle.save_task_ordering({"user_order": ["group/after", "group/before"]})
        self.assertEqual(self.config._config["task_ordering"]["selection_policy"], "list_ready")
        self.assertEqual(self.config._config["task_ordering"]["user_order"], ["after", "before"])
        self.lifecycle.save_task_ordering({"selection_policy": "nearest_ready", "user_order": ["group/before"]})
        self.assertEqual(self.config._config["task_ordering"]["selection_policy"], "nearest_ready")
        before = copy.deepcopy(self.config._config)
        with self.assertRaises(ValueError):
            self.lifecycle.save_task_ordering({"selection_policy": "invalid"})
        self.assertEqual(self.config._config, before)

    def test_nested_order_compatibility_projection_uses_the_same_identity_space(self):
        from orchestrator.model import retarget_ordering_overlay

        overlay = {"selection_policy": "nearest_ready", "user_order": ["obsolete/path"], "items": [
            {"type": "group", "id": "group-key", "name": "group", "items": [
                {"type": "task", "path": "group/after"},
                {"type": "task", "path": "group/before"},
            ]},
        ]}
        stored = self.tree.ordering_overlay_in_ids(overlay)
        self.assertEqual(stored["user_order"], ["after", "before"])
        self.assertEqual(stored["items"][0]["id"], "group-key")
        renamed = retarget_ordering_overlay(stored, {"after": "moved/after", "before": "moved/before"}, "path")
        self.assertEqual(renamed["user_order"], ["moved/after", "moved/before"])
        self.assertEqual(renamed["selection_policy"], "nearest_ready")


class TestTaskListQueueExecution(unittest.TestCase):
    """A graph-derived range must reach the executor without being sorted again."""

    def setUp(self):
        from backend.webui.routes import tasks as tasks_routes

        self.routes = tasks_routes
        self.paths = ["group/before", "group/after", "group/peer"]
        self.execution = SimpleNamespace(
            direct_run_alive=Mock(return_value=False),
            is_busy=Mock(return_value=False), start_direct=Mock(),
        )
        self.tree = SimpleNamespace(sort_task_paths=Mock(return_value=list(reversed(self.paths))))
        self.scheduler = Mock()
        patches = ExitStack()
        self.addCleanup(patches.close)
        patches.enter_context(patch.object(tasks_routes, "orchestrator", SimpleNamespace(
            execution=self.execution, scheduler=self.scheduler, tree=self.tree,
        )))
        patches.enter_context(patch.object(tasks_routes, "cfg", SimpleNamespace(
            _config={"game": {"character_name": "test-character"}},
        )))
        self.credentials = patches.enter_context(patch.object(
            tasks_routes, "require_credential_unlock", return_value=None,
        ))

    def request_run(self, execution_source):
        request = SimpleNamespace(json=AsyncMock(return_value={
            "tasks": self.paths, "activate_scheduler": False,
            "execution_source": execution_source,
        }))
        return asyncio.run(self.routes.run_tasks_api(request))

    def test_task_list_preserves_graph_queue_in_response_and_execution(self):
        response = self.request_run("task_list")

        self.assertEqual(response["tasks"], self.paths)
        self.tree.sort_task_paths.assert_not_called()
        self.credentials.assert_called_once()
        runner, paths = self.execution.start_direct.call_args.args
        self.assertEqual(paths, self.paths)
        runner(paths)
        self.scheduler.run_direct.assert_called_once_with(self.paths, skip_character_login=True)
        self.scheduler.activate.assert_not_called()

    def test_other_direct_sources_keep_existing_sorting(self):
        response = self.request_run("")

        self.tree.sort_task_paths.assert_called_once_with(self.paths)
        self.assertEqual(response["tasks"], list(reversed(self.paths)))

    def test_task_list_still_requires_credentials_and_idle_gate(self):
        from fastapi.responses import JSONResponse

        self.credentials.return_value = JSONResponse(status_code=403, content={"error": "locked"})
        self.assertEqual(self.request_run("task_list").status_code, 403)
        self.execution.start_direct.assert_not_called()
        self.credentials.return_value = None
        self.execution.is_busy.return_value = True
        with patch.object(self.routes, "busy_response", return_value=JSONResponse(
                status_code=409, content={"error": "busy"})):
            self.assertEqual(self.request_run("task_list").status_code, 409)
        self.execution.start_direct.assert_not_called()


class TestPlanningFrontend(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is required for frontend interaction checks")
    def test_task_hierarchy_views_and_actions(self):
        result = subprocess.run(
            ["node", "--test", str(Path(__file__).with_name("task_hierarchy.cjs"))],
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for frontend interaction checks")
    def test_task_planning_controls_and_save_queue(self):
        result = subprocess.run(
            ["node", str(Path(__file__).with_name("task_planning.cjs"))],
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
