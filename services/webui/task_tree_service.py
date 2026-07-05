"""Task tree projection, persistence sanitizing and summaries for WebUI.

Storage remains split as:
- data/config.json for shared app settings;
- data/accounts/{account}.json for encrypted account data, dispatch queue and
  per-character tasks/status.

This service only prepares safe public copies and sanitized save payloads.
"""
from __future__ import annotations

import time
from copy import deepcopy
from typing import Any

import dpath
from dpath.exceptions import PathNotFound

from AutoScriptor.utils.app_config import cfg
from AutoScriptor.utils.game_profession import GAME_PROFESSIONS, normalize_game_profession


class TaskTreeService:
    RUNTIME_TASK_FIELDS = (
        "param_meta",
        "param_keys",
        "beta",
        "custom",
        "debug_mode",
        "task_description",
        "task_doc_flow",
        "fn",
        "order",
        "progress",
        "progress_display",
        "_due",
    )

    def read_order_map(self) -> dict[str, int]:
        return {path: i for i, path in enumerate(self.ordered_paths(cfg._config.get("tasks", {})))}

    def ordered_paths(self, data: dict, prefix: str = "") -> list[str]:
        paths: list[str] = []
        for key, value in (data or {}).items():
            current_path = f"{prefix}/{key}" if prefix else key
            if isinstance(value, dict) and "next_exec_time" not in value:
                paths.extend(self.ordered_paths(value, prefix=current_path))
            else:
                paths.append(current_path)
        return paths

    def public_config(self) -> dict:
        config_data = deepcopy(cfg._config)
        for pattern in [
            "**/fn",
            "**/encryption",
            "**/weekday",
            "**/month",
            "**/day",
            "**/year",
            "**/account",
            "**/password",
            "**/security_key",
        ]:
            try:
                dpath.delete(config_data, pattern)
            except PathNotFound:
                pass
        tasks = config_data.get("tasks")
        if isinstance(tasks, dict):
            self.inject_public_task_fields(tasks)
        config_data["active_character"] = cfg.active_character()
        config_data["characters_summary"] = self.characters_summary()
        config_data["game_professions_by_character"] = self.game_professions_by_character()
        config_data["game_profession_options"] = list(GAME_PROFESSIONS)
        return config_data

    def inject_public_task_fields(self, node: dict, prefix: str = "") -> None:
        from AutoScriptor.utils.task_registry import task_registry
        from services.core.scheduler import is_task_due
        from services.core.task_tree import TaskTree

        now_ts = time.time()
        for key, val in list(node.items()):
            if not isinstance(val, dict):
                continue
            path = f"{prefix}/{key}" if prefix else key
            if TaskTree.is_leaf(val):
                if not task_registry.has_task(path):
                    del node[key]
                    continue
                meta = task_registry.get_param_meta(path)
                if meta:
                    val["param_meta"] = meta
                else:
                    val.pop("param_meta", None)
                pkeys = task_registry.get_param_keys(path)
                if pkeys:
                    val["param_keys"] = pkeys
                else:
                    val.pop("param_keys", None)
                if task_registry.get_beta(path):
                    val["beta"] = True
                else:
                    val.pop("beta", None)
                if task_registry.get_custom(path):
                    val["custom"] = True
                else:
                    val.pop("custom", None)
                if task_registry.get_debug_mode(path):
                    val["debug_mode"] = True
                else:
                    val.pop("debug_mode", None)
                val["task_description"] = task_registry.get_description(path)
                val["task_doc_flow"] = task_registry.get_doc_flow(path)
                task_status = ((cfg._config.get("status") or {}).get("tasks") or {}).get(path, {})
                progress = task_status.get("progress") if isinstance(task_status, dict) else None
                if progress is not None:
                    from AutoScriptor.utils.task_state import progress_label

                    val["progress"] = progress
                    val["progress_display"] = progress_label(progress) or str(progress)
                else:
                    val.pop("progress", None)
                    val.pop("progress_display", None)
                val["_due"] = is_task_due(val, path, now_ts)
            else:
                self.inject_public_task_fields(val, path)
                if not val:
                    del node[key]

    def strip_runtime_fields(self, node: dict) -> dict:
        cleaned = deepcopy(node)
        self.strip_runtime_fields_inplace(cleaned)
        return cleaned

    def strip_runtime_fields_inplace(self, node: Any) -> None:
        from services.core.task_tree import TaskTree

        if not isinstance(node, dict):
            return
        for _key, val in list(node.items()):
            if not isinstance(val, dict):
                continue
            if TaskTree.is_leaf(val):
                for field in self.RUNTIME_TASK_FIELDS:
                    val.pop(field, None)
            else:
                self.strip_runtime_fields_inplace(val)

    def collect_task_reset_paths(self, old_node: dict, new_node: dict, prefix: str = "") -> list[str]:
        from services.core.task_tree import TaskTree

        paths: list[str] = []
        for key, new_val in (new_node or {}).items():
            if not isinstance(new_val, dict):
                continue
            path = f"{prefix}/{key}" if prefix else key
            old_val = (old_node or {}).get(key) if isinstance(old_node, dict) else None
            if TaskTree.is_leaf(new_val):
                if not isinstance(old_val, dict):
                    old_val = {}
                was_on = bool(old_val.get("on"))
                now_on = bool(new_val.get("on"))
                if not now_on:
                    continue
                had_error = bool(
                    old_val.get("human_takeover")
                    or old_val.get("human_takeover_error")
                    or old_val.get("error")
                )
                cleared_error = had_error and not (
                    new_val.get("human_takeover")
                    or new_val.get("human_takeover_error")
                    or new_val.get("error")
                )
                if not was_on or cleared_error:
                    paths.append(path)
            else:
                old_sub = old_val if isinstance(old_val, dict) else {}
                paths.extend(self.collect_task_reset_paths(old_sub, new_val, path))
        return paths

    @staticmethod
    def task_leaf_needs_reset(old_leaf: dict, new_leaf: dict) -> bool:
        if not isinstance(new_leaf, dict) or not new_leaf.get("on"):
            return False
        if not isinstance(old_leaf, dict):
            old_leaf = {}
        was_on = bool(old_leaf.get("on"))
        had_error = bool(
            old_leaf.get("human_takeover")
            or old_leaf.get("human_takeover_error")
            or old_leaf.get("error")
        )
        cleared_error = had_error and not (
            new_leaf.get("human_takeover")
            or new_leaf.get("human_takeover_error")
            or new_leaf.get("error")
        )
        return not was_on or cleared_error

    def get_character_task_public(self, server: str, char_name: str, task_path: str) -> dict | None:
        import dpath
        from dpath.exceptions import PathNotFound
        from AutoScriptor.utils.task_registry import task_registry
        from services.core.task_tree import TaskTree

        path = (task_path or "").strip().replace("\\", "/")
        if not path or not task_registry.has_task(path):
            return None
        tree = self._character_tasks_tree(server, char_name)
        if not tree:
            return None
        try:
            node = dpath.get(tree, path)
        except PathNotFound:
            return None
        if not isinstance(node, dict) or not TaskTree.is_leaf(node):
            return None
        mini: dict = {}
        dpath.new(mini, path, deepcopy(node))
        self.inject_public_task_fields(mini)
        try:
            return dpath.get(mini, path)
        except PathNotFound:
            return None

    def apply_character_task_leaf(self, tree: dict, task_path: str, task_data: dict) -> dict:
        import dpath
        from dpath.exceptions import PathNotFound
        from services.core.task_tree import TaskTree

        path = (task_path or "").strip().replace("\\", "/")
        try:
            old_leaf = dpath.get(tree, path)
        except PathNotFound as e:
            raise KeyError(f"任务路径不存在: {path}") from e
        if not isinstance(old_leaf, dict) or not TaskTree.is_leaf(old_leaf):
            raise ValueError(f"无效任务路径: {path}")
        cleaned = deepcopy(task_data)
        if isinstance(cleaned, dict):
            for field in self.RUNTIME_TASK_FIELDS:
                cleaned.pop(field, None)
        next_leaf = {**old_leaf, **cleaned}
        dpath.set(tree, path, next_leaf)
        return next_leaf

    def characters_summary(self) -> dict:
        tree = cfg.list_characters()
        return {srv: list(chars.keys()) for srv, chars in tree.items()} if tree else {}

    def game_professions_by_character(self) -> dict[str, dict[str, str]]:
        tree = cfg.list_characters()
        out: dict[str, dict[str, str]] = {}
        for srv, chars in (tree or {}).items():
            out[srv] = {}
            for name, node in chars.items():
                gp = node.get("game_profession") if isinstance(node, dict) else None
                out[srv][name] = normalize_game_profession(gp)
        return out

    def normalize_dispatch_queue(self, queue) -> list[dict[str, str]]:
        chars = cfg._account_data.get("characters", {}) or {}
        result: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        if not isinstance(queue, list):
            return result
        for item in queue:
            if not isinstance(item, dict):
                continue
            server = (item.get("server") or "").strip()
            name = (item.get("name") or "").strip()
            key = (server, name)
            if not server or not name or key in seen:
                continue
            if server not in chars or name not in chars[server]:
                continue
            seen.add(key)
            result.append({"server": server, "name": name})
        return result

    def task_leaf_status(self, node: dict, path: str, now_ts: float) -> str:
        from services.core.scheduler import is_human_takeover_blocked, is_task_due

        if not node.get("on"):
            return "disabled"
        if node.get("error") or is_human_takeover_blocked(node, now_ts):
            return "error"
        return "pending" if is_task_due(node, path, now_ts) else "scheduled"

    def flatten_tasks(self, node: dict, now_ts: float, prefix: str = "") -> list:
        from AutoScriptor.utils.task_registry import task_registry

        result = []
        for key, val in (node or {}).items():
            if not isinstance(val, dict):
                continue
            path = f"{prefix}/{key}" if prefix else key
            if "on" in val and "next_exec_time" in val:
                if not task_registry.has_task(path):
                    continue
                row = {
                    "path": path,
                    "name": key,
                    "status": self.task_leaf_status(val, path, now_ts),
                    "beta": task_registry.get_beta(path),
                    "debug_mode": task_registry.get_debug_mode(path),
                    "task_description": task_registry.get_description(path),
                    "task_doc_flow": task_registry.get_doc_flow(path),
                }
                task_status = ((cfg._config.get("status") or {}).get("tasks") or {}).get(path, {})
                progress = task_status.get("progress") if isinstance(task_status, dict) else None
                if progress is not None:
                    from AutoScriptor.utils.task_state import progress_label

                    row["progress"] = progress
                    row["progress_display"] = progress_label(progress) or str(progress)
                if val.get("human_takeover_error"):
                    row["human_takeover_error"] = val.get("human_takeover_error")
                    row["human_takeover_at"] = val.get("human_takeover_at")
                if task_registry.get_custom(path):
                    row["custom"] = True
                result.append(row)
            else:
                result.extend(self.flatten_tasks(val, now_ts, path))
        return result

    def _character_tasks_tree(self, server: str, char_name: str) -> dict:
        ac = cfg.active_character()
        if server == ac.get("server", "") and char_name == ac.get("name", ""):
            return cfg._config.get("tasks", {})
        return cfg._account_data.get("characters", {}).get(server, {}).get(char_name, {}).get("tasks", {}) or {}

    def aggregate_stats_all_characters(self, now_ts: float) -> dict:
        chars = cfg._account_data.get("characters", {})
        total = pending = scheduled = error = disabled = 0
        for srv, srv_chars in chars.items():
            for char_name in srv_chars.keys():
                flat = self.flatten_tasks(self._character_tasks_tree(srv, char_name), now_ts)
                for t in flat:
                    total += 1
                    st = t["status"]
                    if st == "disabled":
                        disabled += 1
                    elif st == "pending":
                        pending += 1
                    elif st == "scheduled":
                        scheduled += 1
                    elif st == "error":
                        error += 1
        enabled = pending + scheduled + error
        return {
            "total": total,
            "enabled": enabled,
            "pending": pending,
            "scheduled": scheduled,
            "error": error,
            "disabled": disabled,
        }

    def overall_next_execution_all_characters(self) -> float | None:
        from services.core.scheduler import (
            collect_active_times_from_tasks_tree,
            next_display_timestamp_from_times,
        )

        chars = cfg._account_data.get("characters", {})
        candidates: list[float] = []
        for srv, srv_chars in chars.items():
            for char_name in srv_chars.keys():
                tasks_tree = self._character_tasks_tree(srv, char_name)
                nxt = next_display_timestamp_from_times(collect_active_times_from_tasks_tree(tasks_tree))
                if nxt is not None:
                    candidates.append(nxt)
        return min(candidates) if candidates else None

    def all_characters_tasks_summary(self) -> dict:
        from services.core.scheduler import (
            collect_active_times_from_tasks_tree,
            next_display_timestamp_from_times,
        )

        now_ts = time.time()
        chars = cfg._account_data.get("characters", {})
        result = {}
        for srv, srv_chars in chars.items():
            srv_result = {}
            for char_name in srv_chars.keys():
                tasks_tree = self._character_tasks_tree(srv, char_name)
                flat = self.flatten_tasks(tasks_tree, now_ts)
                counts = {"total": 0, "pending": 0, "scheduled": 0, "error": 0, "disabled": 0}
                for t in flat:
                    counts["total"] += 1
                    counts[t["status"]] += 1
                next_exec = next_display_timestamp_from_times(collect_active_times_from_tasks_tree(tasks_tree))
                srv_result[char_name] = {**counts, "tasks_flat": flat, "next_execution": next_exec}
            result[srv] = srv_result
        return result


task_tree_service = TaskTreeService()
