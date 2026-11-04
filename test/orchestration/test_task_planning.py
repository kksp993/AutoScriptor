"""Device-free regression cases for dependency-constrained nearest selection."""
import unittest

from orchestrator.planning import PlanningSpec, plan_tasks, validate_specs


class TestTaskPlanning(unittest.TestCase):
    def setUp(self):
        self.specs = {
            "before": PlanningSpec(),
            "after": PlanningSpec(after_tasks=("before",)),
            "independent": PlanningSpec(),
        }
        self.order = ["after", "independent", "before"]

    def plan(self, due, eligible=None, **kwargs):
        return plan_tasks(
            self.specs, set(due), set(due if eligible is None else eligible),
            self.order, costs={"before": 2, "after": 0, "independent": 3}, **kwargs,
        )

    def test_near_successor_waits_then_becomes_first(self):
        initial = self.plan(self.order)
        self.assertEqual(initial.ranked_ids, ["before", "independent"])
        self.assertEqual(initial.blocked_by["after"], ["before"])
        self.assertEqual(self.plan(["after", "independent"]).ranked_ids, ["after", "independent"])

    def test_failed_or_exhausted_predecessor_still_blocks(self):
        decision = self.plan(self.order, ["after", "independent"])
        self.assertEqual(decision.ranked_ids, ["independent"])
        self.assertEqual(decision.blocked_by["after"], ["before"])

    def test_list_policy_preserves_dependency_but_not_distance(self):
        self.assertEqual(self.plan(self.order, policy="list_ready").ranked_ids, ["independent", "before"])

    def test_equal_distance_prefers_ready_successor_over_list_order(self):
        due_ids = {"after", "independent"}
        decision = plan_tasks(
            self.specs, due_ids, due_ids, ["independent", "after"],
            costs={"after": 2, "independent": 2},
        )
        self.assertEqual(decision.ranked_ids, ["after", "independent"])
        self.assertEqual(decision.blocked_by["after"], [])

    def test_shorter_distance_beats_ready_successor_priority(self):
        due_ids = {"after", "independent"}
        decision = plan_tasks(
            self.specs, due_ids, due_ids, ["after", "independent"],
            costs={"after": 2, "independent": 1},
        )
        self.assertEqual(decision.ranked_ids, ["independent", "after"])

    def test_list_policy_does_not_prioritize_ready_successor(self):
        due_ids = {"after", "independent"}
        decision = plan_tasks(
            self.specs, due_ids, due_ids, ["independent", "after"],
            costs={"after": 0, "independent": 2}, policy="list_ready",
        )
        self.assertEqual(decision.ranked_ids, ["independent", "after"])

    def test_unknown_distances_share_successor_tie_breaking(self):
        due_ids = {"after", "independent"}
        for unknown_cost in (None, float("inf"), float("-inf"), float("nan")):
            with self.subTest(unknown_cost=unknown_cost):
                decision = plan_tasks(
                    self.specs, due_ids, due_ids, ["independent", "after"],
                    costs={"after": unknown_cost},
                )
                self.assertEqual(decision.ranked_ids, ["after", "independent"])

    def test_same_priority_and_distance_preserve_list_order(self):
        self.specs["other_after"] = PlanningSpec(after_tasks=("before",))
        self.specs["other_independent"] = PlanningSpec()
        base_order = ["independent", "other_after", "other_independent", "after"]
        due_ids = set(base_order)
        decision = plan_tasks(
            self.specs, due_ids, due_ids, base_order,
            costs={task_id: 1 for task_id in due_ids},
        )
        self.assertEqual(decision.ranked_ids, ["other_after", "after", "independent", "other_independent"])

    def test_multiple_predecessors_require_all_to_leave_due(self):
        self.specs["after"] = PlanningSpec(after_tasks=("before", "independent"))
        self.assertEqual(self.plan(["after", "independent"]).ranked_ids, ["independent"])
        self.assertEqual(self.plan(["after"]).ranked_ids, ["after"])

    def test_unknown_cost_falls_back_to_list_and_never_blocks(self):
        decision = plan_tasks(self.specs, set(self.order), set(self.order), self.order)
        self.assertEqual(decision.ranked_ids, ["independent", "before"])

    def test_cycle_and_missing_reference_do_not_block_unrelated_tasks(self):
        self.specs["before"] = PlanningSpec(after_tasks=("after",))
        self.assertEqual(self.plan(self.order).ranked_ids, ["independent"])
        with self.assertRaisesRegex(ValueError, "before.*after|after.*before"):
            validate_specs(self.specs)
        self.specs["before"] = PlanningSpec(after_tasks=("missing",))
        decision = self.plan(self.order)
        self.assertEqual(decision.ranked_ids, ["independent"])
        self.assertIn("after", decision.errors)


if __name__ == "__main__":
    unittest.main()
