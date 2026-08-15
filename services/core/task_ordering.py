"""Global task ordering overlay and deterministic list/group helpers.

The task tree remains the source of task configuration.  The global
``task_ordering`` section stores a user-controlled ordering list and optional
nested groups.  Groups are display/execution containers only: when execution
reaches a group, its children are flattened in order.  Old graph fields are
normalized away so the WebUI no longer persists partial-order edges or canvas
layout.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Iterable


TASK_ORDERING_SCHEMA_VERSION = 1


def normalize_task_path(value: Any) -> str:
    """Return the canonical task path used by the first ordering overlay."""
    return str(value or "").strip().replace("\\", "/").strip("/")


def _dedupe_paths(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        path = normalize_task_path(value)
        if not path or path in seen:
            continue
        seen.add(path)
        result.append(path)
    return result


def _make_task_ordering_node(path: str) -> dict[str, Any]:
    return {"type": "task", "path": path}


def _flatten_ordering_items(items: Iterable[dict[str, Any]]) -> list[str]:
    paths: list[str] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "group":
            paths.extend(_flatten_ordering_items(item.get("items") or []))
            continue
        path = normalize_task_path(item.get("path"))
        if path:
            paths.append(path)
    return paths


def _normalize_group_name(value: Any) -> str:
    name = str(value or "").strip()
    return name or "分组"


def _normalize_group_id(value: Any, fallback_index: int) -> str:
    identifier = str(value or "").strip()
    return identifier or f"group-{fallback_index}"


def _normalize_ordering_items(
    raw_items: Iterable[Any],
    seen_paths: set[str],
    group_counter: list[int],
) -> list[dict[str, Any]]:
    normalized_items: list[dict[str, Any]] = []
    for raw_item in raw_items or []:
        if isinstance(raw_item, str):
            path = normalize_task_path(raw_item)
            if path and path not in seen_paths:
                seen_paths.add(path)
                normalized_items.append(_make_task_ordering_node(path))
            continue

        if not isinstance(raw_item, dict):
            continue

        is_group = raw_item.get("type") == "group" or isinstance(raw_item.get("items"), list)
        if is_group:
            group_counter[0] += 1
            child_items = _normalize_ordering_items(raw_item.get("items") or [], seen_paths, group_counter)
            if not child_items:
                continue
            if len(child_items) == 1:
                # Singleton groups are not durable structure; break the child out.
                normalized_items.append(child_items[0])
                continue
            normalized_items.append(
                {
                    "type": "group",
                    "id": _normalize_group_id(raw_item.get("id"), group_counter[0]),
                    "name": _normalize_group_name(raw_item.get("name")),
                    "expanded": bool(raw_item.get("expanded", True)),
                    "items": child_items,
                }
            )
            continue

        path = normalize_task_path(raw_item.get("path") or raw_item.get("task_path"))
        if path and path not in seen_paths:
            seen_paths.add(path)
            normalized_items.append(_make_task_ordering_node(path))
    return normalized_items


def normalize_task_ordering_overlay(raw_overlay: Any) -> dict[str, Any]:
    """Return a stable, JSON-safe ordering overlay.

    Older graph keys such as ``hard_edges``, ``layout``, and ``group_order`` are
    intentionally ignored.  ``items`` is the durable grouped list; ``user_order``
    remains as a flat compatibility projection and legacy import seed.
    """
    overlay = raw_overlay if isinstance(raw_overlay, dict) else {}
    seen_paths: set[str] = set()
    group_counter = [0]

    if isinstance(overlay.get("items"), list):
        items = _normalize_ordering_items(overlay.get("items") or [], seen_paths, group_counter)
        user_order = _flatten_ordering_items(items)
    else:
        user_order = _dedupe_paths(overlay.get("user_order") or [])
        items = [_make_task_ordering_node(path) for path in user_order]

    return {
        "schema_version": TASK_ORDERING_SCHEMA_VERSION,
        "user_order": user_order,
        "items": items,
    }


def collect_task_paths(task_tree: dict[str, Any], prefix: str = "") -> list[str]:
    """Collect leaf task paths from a cfg task tree in current tree order."""
    from services.core.task_tree import TaskTree

    paths: list[str] = []
    if not isinstance(task_tree, dict):
        return paths
    for key, value in task_tree.items():
        if not isinstance(value, dict):
            continue
        path = f"{prefix}/{key}" if prefix else str(key)
        if TaskTree.is_leaf(value):
            paths.append(path)
        else:
            paths.extend(collect_task_paths(value, path))
    return paths


def _legacy_registry_order(path: str) -> int | float:
    try:
        from AutoScriptor.utils.task_registry import task_registry

        return task_registry.get_order(path)
    except Exception:
        return float("inf")


@dataclass
class TaskOrderingProjection:
    """Computed ordering projection returned to API and internal consumers."""

    overlay: dict[str, Any]
    task_paths: list[str]
    effective_order: list[str]
    order_map: dict[str, int]
    diagnostics: list[dict[str, Any]] = field(default_factory=list)
    stale_user_order: list[str] = field(default_factory=list)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "schema_version": TASK_ORDERING_SCHEMA_VERSION,
            "overlay": deepcopy(self.overlay),
            "task_paths": list(self.task_paths),
            "effective_order": list(self.effective_order),
            "order_map": dict(self.order_map),
            "diagnostics": deepcopy(self.diagnostics),
            "stale_user_order": list(self.stale_user_order),
        }


def project_task_ordering(task_tree: dict[str, Any], raw_overlay: Any) -> TaskOrderingProjection:
    """Compute effective order from the task tree and one user total order."""
    overlay = normalize_task_ordering_overlay(raw_overlay)
    task_paths = collect_task_paths(task_tree)
    task_path_set = set(task_paths)
    legacy_index = {path: index for index, path in enumerate(task_paths)}
    user_index = {path: index for index, path in enumerate(overlay["user_order"])}

    stale_user_order = [path for path in overlay["user_order"] if path not in task_path_set]
    diagnostics: list[dict[str, Any]] = []
    if stale_user_order:
        diagnostics.append({"level": "info", "code": "stale_user_order", "paths": stale_user_order})

    def soft_sort_key(path: str) -> tuple[int, int | float, int | float, str]:
        return (
            user_index.get(path, len(user_index)),
            legacy_index.get(path, float("inf")),
            _legacy_registry_order(path),
            path,
        )

    effective_order = sorted(task_paths, key=soft_sort_key)

    order_map = {path: index for index, path in enumerate(effective_order)}
    return TaskOrderingProjection(
        overlay=overlay,
        task_paths=task_paths,
        effective_order=effective_order,
        order_map=order_map,
        diagnostics=diagnostics,
        stale_user_order=stale_user_order,
    )


def sort_paths_by_task_ordering(
    paths: Iterable[str],
    task_tree: dict[str, Any],
    raw_overlay: Any,
) -> list[str]:
    """Sort an arbitrary task path list by the current effective order."""
    projection = project_task_ordering(task_tree, raw_overlay)
    return sorted(
        [normalize_task_path(path) for path in paths if normalize_task_path(path)],
        key=lambda path: (projection.order_map.get(path, float("inf")), path),
    )


def summarize_ordering_generations(projection: TaskOrderingProjection) -> list[list[str]]:
    """Return a legacy-compatible single generation in total-order sequence."""
    if not projection.effective_order:
        return []
    return [list(projection.effective_order)]
