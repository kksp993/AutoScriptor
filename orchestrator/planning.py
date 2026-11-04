"""Deterministic dependency planning. Inputs are snapshots; no runtime or I/O."""
from __future__ import annotations

from dataclasses import dataclass, field
from math import inf, isfinite


SELECTION_POLICIES = ("nearest_ready", "list_ready")
PLANNING_FIELDS = ("preferred_locations", "after_tasks")


def normalize_names(value, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(name, str) or not name.strip() for name in value
    ):
        raise ValueError(f"{field_name}: expected a list of non-empty names")
    return tuple(dict.fromkeys(name.strip() for name in value))


def normalize_selection_policy(value: str) -> str:
    if value not in SELECTION_POLICIES:
        raise ValueError(f"Unknown selection_policy: {value!r}")
    return value


@dataclass(frozen=True)
class PlanningSpec:
    preferred_locations: tuple[str, ...] = ()
    after_tasks: tuple[str, ...] = ()

    @classmethod
    def from_values(cls, entry: dict, defaults: dict) -> PlanningSpec:
        return cls(**{
            name: normalize_names(entry.get(name, defaults.get(name, ())), name)
            for name in PLANNING_FIELDS
        })


def diagnose_specs(specs: dict[str, PlanningSpec], locations: set[str] | None = None) -> dict[str, str]:
    errors: dict[str, str] = {}
    visited: set[str] = set()
    visiting: list[str] = []

    def visit(task_id: str) -> None:
        if task_id in visiting:
            cycle = visiting[visiting.index(task_id):] + [task_id]
            for member in cycle:
                errors[member] = "Dependency cycle: " + " -> ".join(cycle)
            return
        if task_id in visited:
            return
        visiting.append(task_id)
        specification = specs[task_id]
        if locations is not None:
            unknown = set(specification.preferred_locations) - locations
            if unknown:
                errors[task_id] = f"Unknown locations: {', '.join(sorted(unknown))}"
        for predecessor in specification.after_tasks:
            if predecessor not in specs:
                errors[task_id] = f"Unknown predecessor: {predecessor}"
            else:
                visit(predecessor)
                if predecessor in errors and task_id not in errors:
                    errors[task_id] = f"Invalid predecessor {predecessor}: {errors[predecessor]}"
        visiting.pop()
        visited.add(task_id)

    for task_id in specs:
        visit(task_id)
    return errors


def validate_specs(specs: dict[str, PlanningSpec], locations: set[str] | None = None) -> None:
    errors = diagnose_specs(specs, locations)
    if errors:
        raise ValueError("; ".join(f"{task_id}: {error}" for task_id, error in errors.items()))


@dataclass
class PlanningDecision:
    ranked_ids: list[str]
    blocked_by: dict[str, list[str]]
    errors: dict[str, str] = field(default_factory=dict)


def plan_tasks(
    specs: dict[str, PlanningSpec],
    due_ids: set[str],
    eligible_ids: set[str],
    base_order: list[str],
    *,
    costs: dict[str, float | None] | None = None,
    policy: str = "nearest_ready",
    errors: dict[str, str] | None = None,
) -> PlanningDecision:
    """Filter *after* deriving blockers; exhausted tasks must not release successors."""
    normalize_selection_policy(policy)
    diagnostics = {**diagnose_specs(specs), **(errors or {})}
    # Malformed source metadata must also invalidate its descendants.
    for _iteration in range(len(specs)):
        added = {
            task_id: f"Invalid predecessor: {predecessor}"
            for task_id, specification in specs.items() if task_id not in diagnostics
            for predecessor in specification.after_tasks if predecessor in diagnostics
        }
        if not added:
            break
        diagnostics.update(added)
    blocked = {
        task_id: sorted(set(specs[task_id].after_tasks) & due_ids)
        for task_id in sorted(due_ids) if task_id in specs
    }
    order_map = {task_id: index for index, task_id in enumerate(base_order)}

    def selection_key(task_id: str):
        cost = (costs or {}).get(task_id)
        distance = cost if cost is not None and isfinite(cost) else inf
        # Only ready tasks reach this key; successor priority breaks distance ties only.
        successor_priority = 0 if specs[task_id].after_tasks else 1
        return (
            distance if policy == "nearest_ready" else 0,
            successor_priority if policy == "nearest_ready" else 0,
            order_map.get(task_id, inf),
            task_id,
        )

    ready = sorted(
        (task_id for task_id in due_ids & eligible_ids & specs.keys()
         if not blocked[task_id] and task_id not in diagnostics),
        key=selection_key,
    )
    return PlanningDecision(ready, blocked, diagnostics)
