"""Real registry/planner/collection with an isolated executor and navigation graph."""
import copy
import unittest
from contextlib import ExitStack
from threading import Event
from unittest.mock import Mock, PropertyMock, patch

from AutoScriptor.utils.app_config import cfg
from orchestrator.model import plan_task_table, resolve_planning_specs
from orchestrator.scheduler import Scheduler, SchedulerState
from tasks.task_register import task_registry
from ZmxyOL.nav import map_manager


class TestSchedulerPlanning(unittest.TestCase):
    def setUp(self):
        self.patches = ExitStack()
        self.addCleanup(self.patches.close)
        self.patches.enter_context(patch.object(task_registry, "_tasks", {}))
        self.world = map_manager.MapManager()
        self.patches.enter_context(patch.object(map_manager, "mm", self.world))
        for name in ("home", "middle", "far"):
            map_manager.Env(name)
        for origin, destination in (("home", "middle"), ("middle", "far"), ("far", "home")):
            self.world.register_path(origin, destination)(Mock())
        task_registry.register("tasks/before", lambda: None, task_id="before", preferred_locations=["middle"])
        task_registry.register("tasks/after", lambda: None, task_id="after", after_tasks=["before"], preferred_locations=["home"])
        task_registry.register("tasks/independent", lambda: None, task_id="independent", preferred_locations=["far"])
        self.table = {name: {"on": True, "next_exec_time": 0} for name in ("before", "after", "independent")}
        self.patches.enter_context(patch.object(cfg, "_config", {
            "tasks": self.table, "app": {"max_attempts": 3}, "game": {"character_name": "test"},
            "emulator": {"post_execution": "none"}, "task_ordering": {},
        }))
        self.patches.enter_context(patch.object(cfg, "active_character", return_value={"server": "test", "name": "hero"}))
        self.patches.enter_context(patch.object(cfg, "save_config"))
        self.scheduler = Scheduler()
        self.scheduler.state = SchedulerState.RUNNING
        self.manager = Mock(_cancel_event=Event())
        self.scheduler.set_task_manager(self.manager)
        self.patches.enter_context(patch.object(self.scheduler, "_iter_characters_schedule_order", side_effect=lambda: iter([("test", "hero")])))
        self.patches.enter_context(patch.object(self.scheduler, "_maybe_daily_restart"))
        self.patches.enter_context(patch.object(self.scheduler, "_ensure_character_logged_in"))
        self.patches.enter_context(patch.object(self.scheduler, "_return_to_first_dispatch_character"))
        self.patches.enter_context(patch.object(self.scheduler, "_post_execution_action"))
        self.patches.enter_context(patch("orchestrator.scheduler.runtime_ctx.refresh"))
        self.patches.enter_context(patch("orchestrator.scheduler.notify_runtime_event"))
        self.patches.enter_context(patch("orchestrator.scheduler.create_character_reports"))
        self.probe = self.patches.enter_context(patch("ZmxyOL.nav.api.probe_region", return_value=("home", "home")))
        self.calls = []

    def execute(self, failures=()):
        def run(tasks, *, max_attempts, attempt_offset):
            name = task_registry.id_of(tasks[0])
            self.calls.append((name, attempt_offset))
            self.assertLess(len(self.calls), 12, "selection loop did not terminate")
            if (name, attempt_offset) in failures:
                return 0, 1
            self.table[name]["on"] = False
            return 1, 0
        self.manager.execute_tasks = run
        self.scheduler._run_task_pipeline()

    def test_newly_ready_near_successor_runs_before_far_independent(self):
        self.execute()
        self.assertEqual(self.calls, [("before", 0), ("after", 0), ("independent", 0)])
        self.assertEqual(self.probe.call_count, 3)

    def test_equal_distance_releases_successor_before_earlier_list_entry(self):
        self.table["before"]["preferred_locations"] = ["home"]
        self.table["after"]["preferred_locations"] = ["middle"]
        self.table["independent"]["preferred_locations"] = ["middle"]
        cfg._config["task_ordering"] = {"user_order": ["independent", "after", "before"]}

        self.execute()

        self.assertEqual(self.calls, [("before", 0), ("after", 0), ("independent", 0)])

    def test_list_policy_keeps_order_when_successor_is_ready(self):
        self.table["before"]["on"] = False
        cfg._config["task_ordering"] = {
            "selection_policy": "list_ready", "user_order": ["independent", "after", "before"],
        }

        self.execute()

        self.assertEqual(self.calls, [("independent", 0), ("after", 0)])
        self.probe.assert_not_called()

    def test_unknown_position_still_prioritizes_ready_successor_on_tie(self):
        self.table["before"]["on"] = False
        cfg._config["task_ordering"] = {"user_order": ["independent", "after", "before"]}
        self.probe.return_value = (None, None)

        self.execute()

        self.assertEqual(self.calls, [("after", 0), ("independent", 0)])

    def test_successor_tie_breaking_preserves_retry_rounds(self):
        self.table["before"]["on"] = False
        self.table["after"]["preferred_locations"] = ["middle"]
        self.table["independent"]["preferred_locations"] = ["middle"]
        cfg._config["task_ordering"] = {"user_order": ["independent", "after"]}

        self.execute({("after", 0), ("after", 1), ("independent", 0)})

        self.assertEqual(self.calls, [
            ("after", 0), ("independent", 0), ("after", 1), ("independent", 1), ("after", 2),
        ])

    def test_retry_success_unlocks_successor_with_its_own_attempt_number(self):
        self.execute({("before", 0)})
        self.assertEqual(self.calls, [("before", 0), ("independent", 0), ("before", 1), ("after", 0)])

    def test_exhausted_predecessor_blocks_without_zero_wait(self):
        self.execute({("before", attempt) for attempt in range(3)})
        self.assertEqual([attempt for name, attempt in self.calls if name == "before"], [0, 1, 2])
        self.assertNotIn("after", [name for name, _attempt in self.calls])
        self.assertEqual(self.scheduler._collect_active_times(), [])
        self.assertGreater(self.scheduler._get_wait_interval(), 0)

    def test_off_future_and_takeover_cooldown_predecessors_do_not_block(self):
        self.table["independent"]["on"] = False
        for changes in ({"on": False}, {"next_exec_time": 200}, {"next_exec_time": 200, "human_takeover": True}):
            with self.subTest(changes=changes):
                self.table["before"] = {"on": True, "next_exec_time": 0, **changes}
                decision, _specifications = plan_task_table(self.table, {}, 100)
                self.assertEqual(decision.ranked_ids, ["after"])
        self.table["before"] = {"on": True, "next_exec_time": 0}
        self.assertEqual(plan_task_table(self.table, {}, 100)[0].ranked_ids, ["before"])

    def test_unknown_position_uses_list_order_without_changing_due(self):
        self.probe.return_value = (None, None)
        before = copy.deepcopy(self.table)
        ranking = self.scheduler._rank_ready_paths(task_registry.all_paths(), observe=True)
        self.assertEqual(ranking, ["tasks/before", "tasks/independent"])
        self.assertEqual(self.table, before)

    def test_explicit_execution_keeps_requested_order_and_bypasses_dependencies(self):
        self.manager.execute_tasks.return_value = (1, 0)
        self.scheduler._run_task_pipeline(explicit_tasks=["tasks/after", "tasks/before"])
        self.assertEqual([call.args[0][0] for call in self.manager.execute_tasks.call_args_list], ["tasks/after", "tasks/before"])
        self.probe.assert_not_called()

    def test_overrides_clear_defaults_and_validation_rejects_cycles(self):
        self.table["after"]["after_tasks"] = []
        specifications, errors = resolve_planning_specs(self.table, strict=True)
        self.assertEqual(specifications["after"].after_tasks, ())
        self.assertEqual(errors, {})
        del self.table["after"]["after_tasks"]
        self.table["before"]["after_tasks"] = ["after"]
        with self.assertRaisesRegex(ValueError, "cycle"):
            resolve_planning_specs(self.table, strict=True)

    def test_blocked_earlier_character_does_not_switch_or_invalidate_current_login(self):
        blocked_table = copy.deepcopy(self.table)
        blocked_table["independent"]["on"] = False
        current = {"server": "test", "name": "hero"}
        self.scheduler._retry_exhausted_tasks[("test", "blocked", "tasks/before")] = 100
        self.scheduler._logged_in_character = ("test", "hero")
        self.scheduler.last_selection = {"ranked_paths": ["tasks/before"]}

        with patch.object(type(cfg), "_account_data", new_callable=PropertyMock, return_value={"characters": {"test": {
            "blocked": {"tasks": blocked_table}, "hero": {"tasks": self.table},
        }}}), patch.object(self.scheduler, "_iter_characters_schedule_order", return_value=iter([
            ("test", "blocked"), ("test", "hero"),
        ])), patch.object(self.scheduler, "_switch_active_character") as switch:
            due = self.scheduler._collect_due_cross_character()

        self.assertEqual(due, ["tasks/before", "tasks/independent"])
        switch.assert_not_called()
        self.assertEqual(cfg.active_character(), current)
        self.assertEqual(self.scheduler._logged_in_character, ("test", "hero"))
        self.assertTrue(self.scheduler.last_selection)

    def test_scanning_completed_characters_leaves_current_configuration_unchanged(self):
        completed_table = {name: {**entry, "on": False} for name, entry in self.table.items()}
        with patch.object(type(cfg), "_account_data", new_callable=PropertyMock, return_value={"characters": {"test": {
            "completed": {"tasks": completed_table},
        }}}), patch.object(self.scheduler, "_iter_characters_schedule_order", return_value=iter([
            ("test", "completed"),
        ])), patch.object(self.scheduler, "_switch_active_character") as switch:
            self.assertEqual(self.scheduler._collect_due_cross_character(), [])
        switch.assert_not_called()

    def test_normal_candidates_use_position_after_login(self):
        self.table["after"]["on"] = False
        self.probe.return_value = ("far", "far")
        events = []
        self.scheduler._maybe_daily_restart.side_effect = lambda _config: events.append("restart")
        self.scheduler._ensure_character_logged_in.side_effect = lambda _config: events.append("login")
        self.probe.side_effect = lambda: (events.append("probe") or ("far", "far"))
        self.execute()
        self.assertEqual(self.calls[0], ("independent", 0))
        self.assertEqual(events[:3], ["restart", "login", "probe"])

    def test_near_debug_candidate_does_not_borrow_normal_startup(self):
        self.table["after"]["on"] = False
        self.table["independent"].update(debug=True, preferred_locations=["home"])
        events = []
        self.scheduler._maybe_daily_restart.side_effect = lambda _config: events.append("restart")
        self.scheduler._ensure_character_logged_in.side_effect = lambda _config: events.append("login")

        def run(tasks, *, max_attempts, attempt_offset):
            name = task_registry.id_of(tasks[0])
            events.append(name)
            self.table[name]["on"] = False
            return 1, 0

        self.manager.execute_tasks = run
        self.scheduler._run_task_pipeline()
        self.assertEqual(events, ["independent", "restart", "login", "before"])


class TestRegionProbe(unittest.TestCase):
    def setUp(self):
        from ZmxyOL.nav import api

        self.api = api
        patches = ExitStack()
        self.addCleanup(patches.close)
        self.world = map_manager.MapManager()
        patches.enter_context(patch.object(map_manager, "mm", self.world))
        patches.enter_context(patch.object(api, "mm", self.world))
        map_manager.Env("home", "home-image")
        map_manager.Env("other", "other-image")
        map_manager.Loc(["home", "other"], "shared", ("shared-image", "shared-text"))
        map_manager.Loc("home", "home#-1", "indexed-text")
        self.world.set_region("other", "other")
        self.visible = set()

        def locate(identifiers, **kwargs):
            self.assertIsInstance(identifiers, list, "mixed image/text query must not short-circuit")
            return [object() if identifier in self.visible else None for identifier in identifiers]

        patches.enter_context(patch.object(api, "locate", side_effect=locate))
        patches.enter_context(patch.object(api, "locate_region", side_effect=AssertionError("must not launch or navigate")))

    def test_shared_location_alternative_uses_visible_owner_without_mutating_cache(self):
        self.visible.update({"home-image", "shared-text"})
        self.assertEqual(self.api.probe_region(), ("home", "shared"))
        self.assertEqual(self.world.get_region(), ("other", "other"))

    def test_indexed_location_without_root_marker_and_unknown_scene(self):
        self.visible.add("indexed-text")
        self.assertEqual(self.api.probe_region(), ("home", "home#-1"))
        self.visible.clear()
        self.assertEqual(self.api.probe_region(), (None, None))

    def test_ambiguous_sublocations_do_not_guess_from_registration_order(self):
        self.visible.update({"home-image", "shared-text", "indexed-text"})
        self.assertEqual(self.api.probe_region(), (None, None))

    def test_ambiguous_sublocations_remain_unknown_without_environment_markers(self):
        self.visible.update({"shared-text", "indexed-text"})
        self.assertEqual(self.api.probe_region(), (None, None))

    def test_shared_location_with_multiple_or_missing_owner_markers_is_unknown(self):
        for visible in ({"home-image", "other-image", "shared-text"}, {"shared-text"}):
            with self.subTest(visible=visible):
                self.visible.clear()
                self.visible.update(visible)
                self.assertEqual(self.api.probe_region(), (None, None))
                self.assertEqual(self.world.get_region(), ("other", "other"))

    def test_environment_only_falls_back_when_exactly_one_is_visible(self):
        self.visible.add("home-image")
        self.assertEqual(self.api.probe_region(), ("home", "home"))
        self.assertEqual(self.world.get_region(), ("other", "other"))
        self.visible.add("other-image")
        self.assertEqual(self.api.probe_region(), (None, None))

    def test_conflicting_location_and_environment_do_not_guess_environment_fallback(self):
        self.visible.update({"other-image", "indexed-text"})
        self.assertEqual(self.api.probe_region(), (None, None))

    def test_location_with_one_matching_owner_disambiguates_environment_markers(self):
        self.visible.update({"home-image", "other-image", "indexed-text"})
        self.assertEqual(self.api.probe_region(), ("home", "home#-1"))


class TestNavigationCosts(unittest.TestCase):
    def test_route_cost_includes_both_local_legs_and_never_moves(self):
        world = map_manager.MapManager()
        with patch.object(map_manager, "mm", world):
            for name in ("origin", "unused", "destination"):
                map_manager.Env(name)
            map_manager.Loc("origin", "inside", None)
            map_manager.Loc("destination", "target", None)
            for origin, destination in (("inside", "origin"), ("origin", "destination"), ("destination", "target")):
                world.register_path(origin, destination)(Mock(side_effect=AssertionError("must not navigate")))
            world.set_region("origin", "inside")
            self.assertEqual(world.estimate_route_cost(world.get_region(), "target"), 3)
            self.assertEqual(world.estimate_route_cost(world.get_region(), "inside"), 0)
            self.assertEqual(world.get_nearest_env(["unused", "destination"]), "destination")
            self.assertEqual(world.estimate_route_cost((None, None), "target"), float("inf"))
            self.assertEqual(world.get_region(), ("origin", "inside"))


if __name__ == "__main__":
    unittest.main()
