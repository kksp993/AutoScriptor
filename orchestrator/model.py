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


def retarget_ordering_overlay(
    raw_overlay: Any,
    key_map: dict[str, str],
    leaf_key: str,
) -> dict[str, Any]:
    """Rewrite every ordering leaf key through ``key_map``, dropping unmapped ones.

    ``task_ordering`` is stored keyed by task id, so rename keeps the user's
    order; the projection and the WebUI speak display paths. This is the one
    place those two key spaces meet. A leaf is read from whichever field it
    carries, so an overlay written before ids existed still loads as long as its
    ``path`` equals the id -- true for every task that never moved.

    ``leaf_key`` names the field to write: ``"path"`` when handing the overlay to
    the projection, ``"id"`` when putting it back into storage. The surrounding
    shape (groups, ``expanded``, ``schema_version``) passes through untouched so
    ``normalize_task_ordering_overlay`` still does the deduping and unwrapping.
    """
    overlay = raw_overlay if isinstance(raw_overlay, dict) else {}

    def retarget_item(item: Any) -> dict[str, Any] | None:
        if not isinstance(item, dict):
            return None
        if item.get("type") == "group" or isinstance(item.get("items"), list):
            children = [
                child
                for child in (retarget_item(raw) for raw in (item.get("items") or []))
                if child
            ]
            if not children:
                return None
            return {**item, "items": children}
        source = normalize_task_path(item.get("id") or item.get("path") or item.get("task_path"))
        target = key_map.get(source)
        return {"type": "task", leaf_key: target} if target else None

    raw_items = overlay.get("items")
    if isinstance(raw_items, list):
        return {
            **overlay,
            "items": [item for item in (retarget_item(raw) for raw in raw_items) if item],
        }
    return {
        **overlay,
        "user_order": [
            target
            for target in (
                key_map.get(normalize_task_path(value))
                for value in (overlay.get("user_order") or [])
            )
            if target
        ],
    }


def collect_task_paths(task_tree: dict[str, Any], prefix: str = "") -> list[str]:
    """Display paths of the tasks in one flat cfg table, in registration order.

    The table is keyed by task id, so the paths come from the registry. Ordering
    by the registry's registration sequence is what makes the default order equal
    the import order, which is the contract the WebUI and the scheduler both
    fall back to.
    """
    from tasks.task_register import task_registry

    paths: list[str] = []
    for task_id in task_tree or {}:
        path = task_registry.get_path(task_id)
        if not path:
            continue
        if prefix and path != prefix and not path.startswith(prefix + "/"):
            continue
        paths.append(path)
    return sorted(paths, key=lambda path: (task_registry.get_sequence(path), path))


def _registry_sequence(path: str) -> int | float:
    try:
        from tasks.task_register import task_registry

        return task_registry.get_sequence(path)
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
            _registry_sequence(path),
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
    """Sort an arbitrary path list by the current effective order.

    ``raw_overlay`` is the stored overlay, which is keyed by task id; the
    projection speaks display paths, so it is retargeted here -- this is the
    entry point the scheduler uses, and it never has a path-keyed overlay.
    """
    from tasks.task_register import task_registry

    projection = project_task_ordering(
        task_tree,
        retarget_ordering_overlay(raw_overlay, task_registry.id_to_path_map(), "path"),
    )
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

def resolve_reschedule(task_path: str, entry: dict | None) -> dict:
    """该任务当前生效的调度规则，已归一为 ``mode/hours/window/weekdays``。

    用户覆盖优先：cfg 里有 ``reschedule`` 就用它；没有才用作者声明的默认值；
    两者都没有就是一次性。所以同一个字段既让作者定默认，也让用户改。
    """
    from tasks.task_register import task_registry
    from tasks.task_schedule import normalize_reschedule

    if isinstance(entry, dict) and "reschedule" in entry:
        raw = entry["reschedule"]
    else:
        raw = task_registry.get_reschedule_default(task_path)
    return normalize_reschedule(raw)


def is_task_debug_mode(task_path: str) -> bool:
    """任务当前是否处于调试直跑模式。

    ``debug`` 是用户属性：cfg 里有就用用户的，没有才回落到作者声明的默认值。
    """
    from tasks.task_register import task_registry
    from AutoScriptor.utils.app_config import cfg

    entry = (cfg._config.get("tasks") or {}).get(task_registry.id_of(task_path))
    if isinstance(entry, dict) and "debug" in entry:
        return bool(entry["debug"])
    return task_registry.get_debug_default(task_path)


# 周期型规则 -> 下一个执行日。当天 5 点前算今天，5 点后算下一轮。
def _next_daily_day(now: datetime.datetime) -> datetime.date:
    return (now + datetime.timedelta(days=1 if now.hour >= 5 else 0)).date()


def _next_weekly_day(now: datetime.datetime) -> datetime.date:
    days = (7 - now.weekday()) % 7 or 7
    return (now + datetime.timedelta(days=days if now.hour >= 5 else 0)).date()


_PERIODIC_NEXT_DAY = {
    "daily": _next_daily_day,
    "weekly": _next_weekly_day,
}


def next_exec_ts_for_spec(now: datetime.datetime, spec: dict) -> float | None:
    """按调度规则算出执行后的下一个时间点。一次性任务返回 None，表示不排下一次。"""
    mode = spec["mode"]
    if mode == "once":
        return None
    if mode == "offset":
        return (now + datetime.timedelta(hours=int(spec["hours"]))).timestamp()
    next_day_of = _PERIODIC_NEXT_DAY.get(mode)
    if next_day_of is None:
        raise ValueError(f"调度模式没有对应的时间规则: {mode!r}")
    return datetime.datetime.combine(next_day_of(now), datetime.time(5, 0)).timestamp()


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
    from tasks.task_register import task_registry

    if not val.get("on"):
        return False
    if is_human_takeover_blocked(val, now_ts):
        return False
    if not task_registry.has_task(path):
        return False
    if now_ts < val.get("next_exec_time", 0):
        return False
    spec = resolve_reschedule(path, val)
    if spec["window"] is not None:
        if clamp_to_sched_window(now_ts, *spec["window"]) > now_ts:
            return False
    if spec["weekdays"] is not None:
        weekday = datetime.datetime.fromtimestamp(now_ts).weekday() + 1
        if weekday not in set(spec["weekdays"]):
            return False
    return True


def calc_effective_next_time(val: dict, now_ts: float, spec: dict) -> float:
    """The next execution time as displayed, after window and weekday clamps."""
    nxt = float(val.get("next_exec_time", 0) or 0)
    effective = (
        clamp_to_sched_window(max(nxt, now_ts), *spec["window"])
        if spec["window"]
        else (nxt or now_ts)
    )
    allowed_weekdays = spec["weekdays"]
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


def collect_active_times_from_task_table(task_table: dict) -> list[float]:
    """Effective next-run times for the enabled, registered tasks in one table."""
    from tasks.task_register import task_registry

    now_ts = datetime.datetime.now().timestamp()
    result: list[float] = []
    for task_id, val in (task_table or {}).items():
        if not isinstance(val, dict) or not val.get("on"):
            continue
        path = task_registry.get_path(task_id) or ""
        if not task_registry.has_task(path):
            continue
        result.append(calc_effective_next_time(val, now_ts, resolve_reschedule(path, val)))
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
            task_table = cfg_obj._config.get("tasks", {})
        else:
            task_table = chars.get(server, {}).get(char_name, {}).get("tasks", {}) or {}
        result.extend(collect_active_times_from_task_table(task_table))
    return result


def next_display_timestamp_from_times(times: list[float]) -> float | None:
    """Match ``Scheduler.get_next_execution_timestamp`` for display."""
    now = datetime.datetime.now().timestamp()
    if not times:
        return None
    if any(moment <= now for moment in times):
        return now
    return min(times)
