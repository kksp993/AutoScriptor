"""What the task set looks like, and when each task is due.

Every function here is a pure query over the task tree and the user's ordering
overlay. Nothing reads or writes files, nothing owns a thread, and nothing talks
to a device -- which is what lets both the scheduler daemon and the UI
projection share one definition of "due" instead of each keeping its own copy.

Three groups, in dependency order:

- ``TaskTree``: node/leaf classification and in-place tree editing.
- ordering: the global ``task_ordering`` overlay and its deterministic projection.
- timing: schedule windows, weekday restrictions, and the due predicate.
"""

from __future__ import annotations

import datetime
import enum
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

import dpath

from AutoScriptor.utils.app_config import cfg


TASK_ORDERING_SCHEMA_VERSION = 1


# ═══════════════════════════════════════════════════════════════════════
#  Task tree shape
# ═══════════════════════════════════════════════════════════════════════

class TaskTree:
    """Pure operations on the cfg task tree. No state, no I/O."""

    # ── 节点判断 ──

    @staticmethod
    def is_leaf(node: dict[str, Any]) -> bool:
        """A leaf is a concrete task, marked by an ``on`` key.

        ``fn`` / ``order`` / ``param_meta`` live in the runtime registry now, so
        the cfg side carries only serializable user config.
        """
        return isinstance(node, dict) and "on" in node

    is_ui_leaf = is_leaf

    @staticmethod
    def is_branch(node: dict[str, Any]) -> bool:
        """A branch is a grouping node: a dict without ``on``."""
        return isinstance(node, dict) and "on" not in node

    # ── 路径操作 ──

    @staticmethod
    def get_node(data: dict[str, Any], path: list[str]) -> dict[str, Any]:
        node = data
        for key in path:
            node = node[key]
        return node

    @staticmethod
    def prune_leaves_not_in_registry(
        branch: dict[str, Any],
        path_prefix: str,
        has_task: Callable[[str], bool],
    ) -> None:
        """Drop leaves whose path is not registered; drop branches left empty."""
        for key, val in list(branch.items()):
            path = f"{path_prefix}/{key}" if path_prefix else key
            if TaskTree.is_leaf(val):
                if not has_task(path):
                    del branch[key]
            elif isinstance(val, dict):
                TaskTree.prune_leaves_not_in_registry(val, path, has_task)
                if not val:
                    del branch[key]

    # ── 状态查询 ──

    @staticmethod
    def is_branch_active(branch: dict[str, Any]) -> bool:
        """True when any leaf below this branch is enabled."""
        for value in branch.values():
            if not isinstance(value, dict):
                continue
            if TaskTree.is_leaf(value):
                if value["on"]:
                    return True
            elif TaskTree.is_branch_active(value):
                return True
        return False

    @staticmethod
    def branch_uncompleted(branch: dict[str, Any], now_ts: float) -> bool:
        """True when any enabled leaf below this branch is due."""
        for value in branch.values():
            if not isinstance(value, dict):
                continue
            if TaskTree.is_leaf(value) and value.get("on", False):
                if now_ts >= value.get("next_exec_time", 0):
                    return True
            elif TaskTree.branch_uncompleted(value, now_ts):
                return True
        return False

    # ── 状态修改 ──

    @staticmethod
    def set_branch_status(branch: dict[str, Any], status: bool) -> None:
        """Enable or disable every leaf below this branch."""
        for value in branch.values():
            if not isinstance(value, dict):
                continue
            if TaskTree.is_leaf(value):
                value["on"] = status
            else:
                TaskTree.set_branch_status(value, status)

    # ── 显示格式化 ──

    @staticmethod
    def display_width(text: str) -> int:
        """Rendered width, counting CJK characters as two columns."""
        return sum(2 if ord(character) > 127 else 1 for character in text)

    @staticmethod
    def format_leaf(key: str, node: dict[str, Any], now_ts: float) -> tuple[str, str]:
        """Return ``(base, suffix)`` for a task row."""
        if not node.get("on", False):
            base = f"[ ] {key}"
            if node.get("params"):
                base += " [可编辑]"
            return base, ""

        base = f"[✔] {key}"
        if node.get("params"):
            base += " [可编辑]"
        done = now_ts < node.get("next_exec_time", 0)
        suffix = " ✅已完成" if done else " ❌未完成"
        return base, suffix

    @staticmethod
    def format_branch(key: str, node: dict[str, Any], now_ts: float) -> tuple[str, str]:
        """Return ``(base, suffix)`` for a group row."""
        active = TaskTree.is_branch_active(node)
        check = "✔" if active else " "
        base = f"[{check}] {key}/"
        suffix = ""
        if active:
            incomplete = TaskTree.branch_uncompleted(node, now_ts)
            suffix = " ❌未完成" if incomplete else " ✅已完成"
        return base, suffix

    @staticmethod
    def format_node(key: str, node: dict[str, Any], now_ts: float) -> tuple[str, str]:
        """Format a node without the caller deciding leaf vs branch first."""
        if TaskTree.is_leaf(node):
            return TaskTree.format_leaf(key, node, now_ts)
        return TaskTree.format_branch(key, node, now_ts)

    @staticmethod
    def build_aligned_items(
        current_node: dict[str, Any],
        now_ts: float,
    ) -> list[tuple[str, str]]:
        """Build ``(key, display_text)`` rows padded to a common width."""
        items = []
        for key, value in current_node.items():
            if not isinstance(value, dict):
                continue
            base, suffix = TaskTree.format_node(key, value, now_ts)
            items.append((key, base, suffix))

        if not items:
            return []

        max_base = max(TaskTree.display_width(base) for _, base, _ in items)
        result = []
        for key, base, suffix in items:
            pad = max_base - TaskTree.display_width(base)
            result.append((key, base + " " * pad + suffix))
        return result

    # ── 搜索辅助 ──

    @staticmethod
    def collect_all_leaves(
        node: dict[str, Any],
        path: list[str] | None = None,
    ) -> list[tuple[list[str], dict[str, Any]]]:
        """Collect ``(path_parts, node)`` for every leaf below this node."""
        if path is None:
            path = []
        results = []
        for key, value in node.items():
            if not isinstance(value, dict):
                continue
            new_path = path + [key]
            if TaskTree.is_leaf(value):
                results.append((new_path, value))
            else:
                results.extend(TaskTree.collect_all_leaves(value, new_path))
        return results


# ═══════════════════════════════════════════════════════════════════════
#  Global task ordering
# ═══════════════════════════════════════════════════════════════════════
#
# The task tree stays the source of task configuration. The global
# ``task_ordering`` section stores a user-controlled ordering list plus optional
# nested groups. Groups are display/execution containers only: reaching a group
# flattens its children in order. Legacy graph fields are normalized away, so
# the WebUI no longer persists partial-order edges or canvas layout.

def normalize_task_path(value: Any) -> str:
    """Return the canonical slash path used by the ordering overlay."""
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
            child_items = _normalize_ordering_items(
                raw_item.get("items") or [], seen_paths, group_counter
            )
            if not child_items:
                continue
            if len(child_items) == 1:
                # A single-child group carries no durable structure; unwrap it.
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

    Legacy graph keys (``hard_edges``, ``layout``, ``group_order``) are ignored
    on purpose. ``items`` is the durable grouped list; ``user_order`` stays as a
    flat compatibility projection and legacy import seed.
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
    """Collect leaf task paths from a cfg task tree, in tree order."""
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
        from tasks.task_registry import task_registry

        return task_registry.get_order(path)
    except Exception:
        return float("inf")


@dataclass
class TaskOrderingProjection:
    """Computed ordering projection shared by API responses and execution."""

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
    """Compute the effective order from the task tree and one user total order."""
    overlay = normalize_task_ordering_overlay(raw_overlay)
    task_paths = collect_task_paths(task_tree)
    task_path_set = set(task_paths)
    legacy_index = {path: index for index, path in enumerate(task_paths)}
    user_index = {path: index for index, path in enumerate(overlay["user_order"])}

    stale_user_order = [path for path in overlay["user_order"] if path not in task_path_set]
    diagnostics: list[dict[str, Any]] = []
    if stale_user_order:
        diagnostics.append(
            {"level": "info", "code": "stale_user_order", "paths": stale_user_order}
        )

    def soft_sort_key(path: str) -> tuple[int, int | float, int | float, str]:
        return (
            user_index.get(path, len(user_index)),
            legacy_index.get(path, float("inf")),
            _legacy_registry_order(path),
            path,
        )

    effective_order = sorted(task_paths, key=soft_sort_key)
    return TaskOrderingProjection(
        overlay=overlay,
        task_paths=task_paths,
        effective_order=effective_order,
        order_map={path: index for index, path in enumerate(effective_order)},
        diagnostics=diagnostics,
        stale_user_order=stale_user_order,
    )


def sort_paths_by_task_ordering(
    paths: Iterable[str],
    task_tree: dict[str, Any],
    raw_overlay: Any,
) -> list[str]:
    """Sort an arbitrary path list by the current effective order."""
    projection = project_task_ordering(task_tree, raw_overlay)
    return sorted(
        [normalize_task_path(path) for path in paths if normalize_task_path(path)],
        key=lambda path: (projection.order_map.get(path, float("inf")), path),
    )


def summarize_ordering_generations(projection: TaskOrderingProjection) -> list[list[str]]:
    """Return the legacy-compatible single generation in total-order sequence."""
    if not projection.effective_order:
        return []
    return [list(projection.effective_order)]


# ═══════════════════════════════════════════════════════════════════════
#  Timing rules
# ═══════════════════════════════════════════════════════════════════════

class NextDate(enum.Enum):
    past = "past"
    today = "today"
    tomorrow = "tomorrow"
    next_week = "next_week"


# Task category prefix -> the day its next run lands on.
CATEGORY_NEXT_DATE = {
    "每日任务": NextDate.tomorrow,
    "活动任务": NextDate.tomorrow,
    "每周任务": NextDate.next_week,
    "自定义任务": NextDate.tomorrow,
}


def calc_next_exec_ts(
    now: datetime.datetime,
    next_date: NextDate = NextDate.today,
    offset_hours: int = 0,
) -> float:
    """Resolve the next execution timestamp for a category rule."""
    if next_date == NextDate.past:
        return 0
    if next_date == NextDate.tomorrow:
        next_day = (now + datetime.timedelta(days=1 if now.hour >= 5 else 0)).date()
    elif next_date == NextDate.next_week:
        days = (7 - now.weekday()) % 7 or 7
        next_day = (now + datetime.timedelta(days=days if now.hour >= 5 else 0)).date()
    else:
        next_day = (now + datetime.timedelta(hours=offset_hours)).date()
    target_time = datetime.time(5, 0) if offset_hours == 0 else datetime.time(0, 0)
    return datetime.datetime.combine(next_day, target_time).timestamp()


def parse_sched_window_hours(task_data: dict) -> tuple[int, int] | None:
    """Parse ``sched_window_hours`` as local-time ``[start_h, end_h)``."""
    window = task_data.get("sched_window_hours")
    if window is None or len(window) != 2:
        return None
    try:
        return int(window[0]), int(window[1])
    except (TypeError, ValueError):
        return None


def parse_allowed_weekdays(task_data: dict) -> list[int] | None:
    """Parse ``allowed_weekdays``, matching ``cfg['weekday']`` (1=Mon … 7=Sun)."""
    weekdays = task_data.get("allowed_weekdays")
    if weekdays is None or not isinstance(weekdays, list) or not weekdays:
        return None
    try:
        return [int(value) for value in weekdays]
    except (TypeError, ValueError):
        return None


def calc_next_allowed_weekday_ts(now: datetime.datetime, allowed: list[int]) -> float:
    """Next allowed day at 05:00 local, searching forward from tomorrow."""
    allowed_set = set(allowed)
    for offset in range(1, 15):
        candidate = now.date() + datetime.timedelta(days=offset)
        if candidate.weekday() + 1 in allowed_set:
            return datetime.datetime.combine(candidate, datetime.time(5, 0)).timestamp()
    return (now + datetime.timedelta(days=7)).timestamp()


def clamp_to_sched_window(ts: float, start_h: int, end_h: int) -> float:
    """Move a timestamp to the nearest window start; return it when already inside."""
    moment = datetime.datetime.fromtimestamp(ts)
    minute_of_day = moment.hour * 60 + moment.minute
    if start_h * 60 <= minute_of_day < end_h * 60:
        return ts
    if minute_of_day < start_h * 60:
        return moment.replace(hour=start_h, minute=0, second=0, microsecond=0).timestamp()
    next_day = moment.date() + datetime.timedelta(days=1)
    return datetime.datetime.combine(next_day, datetime.time(start_h, 0)).timestamp()


# ═══════════════════════════════════════════════════════════════════════
#  Due predicate — the one definition the scheduler and the UI both use
# ═══════════════════════════════════════════════════════════════════════

def is_human_takeover_blocked(val: dict, now_ts: float | None = None) -> bool:
    """Whether a human-takeover mark still suppresses automatic execution.

    The mark is not a permanent freeze: once ``next_exec_time`` passes, the
    scheduler picks the task up again. Without ``now_ts`` the conservative
    answer (blocked) is returned, for pure mark inspection.
    """
    if not bool(val.get("human_takeover") or val.get("human_takeover_error")):
        return False
    if now_ts is None:
        return True
    return now_ts < float(val.get("next_exec_time", 0) or 0)


def is_task_due(val: dict, path: str, now_ts: float) -> bool:
    """Whether a task leaf qualifies for collection right now. No side effects."""
    from tasks.task_registry import task_registry

    if not val.get("on"):
        return False
    if is_human_takeover_blocked(val, now_ts):
        return False
    if not task_registry.has_task(path):
        return False
    if now_ts < val.get("next_exec_time", 0):
        return False
    schedule_window = parse_sched_window_hours(val)
    if schedule_window is not None:
        if clamp_to_sched_window(now_ts, *schedule_window) > now_ts:
            return False
    allowed_weekdays = parse_allowed_weekdays(val)
    if allowed_weekdays is not None:
        weekday = datetime.datetime.fromtimestamp(now_ts).weekday() + 1
        if weekday not in set(allowed_weekdays):
            return False
    return True


def is_task_debug_mode(task_path: str, task_data: dict | None = None) -> bool:
    """Debug-run policy: registry first, explicit task data second, cfg last.

    Kept free of task-runtime imports so it stays usable from the scheduler and
    the UI projection alike.
    """
    from tasks.task_registry import task_registry

    if task_registry.get_debug_mode(task_path):
        return True
    if isinstance(task_data, dict):
        return bool(task_data.get("debug_mode") or task_data.get("debug"))
    try:
        data = dpath.get(cfg["tasks"], task_path)
    except Exception:
        return False
    return isinstance(data, dict) and bool(data.get("debug_mode") or data.get("debug"))


def calc_effective_next_time(val: dict, now_ts: float) -> float:
    """The next execution time as displayed, after window and weekday clamps."""
    nxt = float(val.get("next_exec_time", 0) or 0)
    schedule_window = parse_sched_window_hours(val)
    effective = (
        clamp_to_sched_window(max(nxt, now_ts), *schedule_window)
        if schedule_window
        else (nxt or now_ts)
    )
    allowed_weekdays = parse_allowed_weekdays(val)
    if allowed_weekdays is not None:
        now_dt = datetime.datetime.fromtimestamp(now_ts)
        weekday = now_dt.weekday() + 1
        if effective <= now_ts and weekday not in set(allowed_weekdays):
            effective = calc_next_allowed_weekday_ts(now_dt, allowed_weekdays)
        elif effective > now_ts:
            target_dt = datetime.datetime.fromtimestamp(effective)
            if (target_dt.weekday() + 1) not in set(allowed_weekdays):
                effective = calc_next_allowed_weekday_ts(target_dt, allowed_weekdays)
    return effective


def collect_active_times_from_tasks_tree(tasks: dict) -> list[float]:
    """Effective next-run times for enabled, registered tasks in one tree."""
    from tasks.task_registry import task_registry

    now_ts = datetime.datetime.now().timestamp()
    result: list[float] = []

    def _walk(node: dict, prefix: str = "") -> None:
        for key, val in node.items():
            if not isinstance(val, dict):
                continue
            path = f"{prefix}/{key}" if prefix else key
            if "on" in val:
                if val.get("on") and task_registry.has_task(path):
                    result.append(calc_effective_next_time(val, now_ts))
            else:
                _walk(val, path)

    _walk(tasks or {})
    return result


def iter_dispatch_characters(cfg_obj) -> Iterable[tuple[str, str]]:
    """Yield valid dispatch-queue characters in the configured order."""
    chars = cfg_obj._account_data.get("characters", {}) or {}
    seen: set[tuple[str, str]] = set()
    for item in cfg_obj._account_data.get("dispatch_queue", []) or []:
        server = (item.get("server") or "").strip()
        name = (item.get("name") or "").strip()
        if not server or not name:
            continue
        key = (server, name)
        if key in seen:
            continue
        if server not in chars or name not in chars[server]:
            continue
        seen.add(key)
        yield key


def collect_active_times_from_all_characters(
    cfg_obj, dispatch_only: bool = False
) -> list[float]:
    """Effective next-run times across the characters of the current account."""
    active = cfg_obj.active_character()
    active_server = active.get("server", "")
    active_name = active.get("name", "")
    chars = cfg_obj._account_data.get("characters", {}) or {}
    result: list[float] = []
    if dispatch_only:
        char_keys = list(iter_dispatch_characters(cfg_obj))
    else:
        char_keys = [
            (server, char_name)
            for server, server_chars in chars.items()
            for char_name in server_chars.keys()
        ]
    for server, char_name in char_keys:
        if server == active_server and char_name == active_name:
            tasks_tree = cfg_obj._config.get("tasks", {})
        else:
            tasks_tree = chars.get(server, {}).get(char_name, {}).get("tasks", {}) or {}
        result.extend(collect_active_times_from_tasks_tree(tasks_tree))
    return result


def next_display_timestamp_from_times(times: list[float]) -> float | None:
    """Match ``Scheduler.get_next_execution_timestamp`` for display."""
    now = datetime.datetime.now().timestamp()
    if not times:
        return None
    if any(moment <= now for moment in times):
        return now
    return min(times)
