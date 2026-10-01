"""What the WebUI may see, and how it changes it.

Two halves of one contract, which is why they share a module: the read side prepares
safe public copies of the task tree (runtime fields stripped, runtime flags
re-injected, ordering projected), and the write side owns the order of side effects
-- mutate config, persist, reload the task registry, refresh the projection, wake
the scheduler, then bump the public version.

Nothing here decides when a task runs; that is the scheduler's job.
"""
from __future__ import annotations

from copy import deepcopy
from contextlib import contextmanager
import logging
import time
from threading import Lock, RLock, local
from typing import Any

import dpath
from dpath.exceptions import PathNotFound

from AutoScriptor.utils.app_config import cfg
from AutoScriptor.utils.mumu_discovery import default_mumu_adb_addr, is_placeholder_adb_addr
from ZmxyOL.accounts.account_store import INJECTED_TASK_FIELDS
from ZmxyOL.character.profession import GAME_PROFESSIONS, normalize_game_profession
from orchestrator.model import (
    collect_task_paths,
    normalize_task_ordering_overlay,
    project_task_ordering,
    retarget_ordering_overlay,
    summarize_ordering_generations,
)

logger = logging.getLogger(__name__)


class TaskTreeService:
    # 读写两侧共用一张名单：account_store 保存时删它，投影和保存接口读它。
    RUNTIME_TASK_FIELDS = INJECTED_TASK_FIELDS

    def task_table(self) -> dict:
        """The flat, id-keyed user config table for the current character."""
        table = cfg._config.get("tasks")
        return table if isinstance(table, dict) else {}

    def build_task_tree(self, task_table: dict | None = None) -> dict:
        """Lay the flat table out as the tree the WebUI renders.

        Grouping comes from each task's display path, so it follows the source
        layout and nothing else -- re-grouping a task never touches user data.
        Each leaf carries ``id`` because that is what the save path keys by: the
        tree is a view, the table is storage.
        """
        from tasks.task_register import task_registry

        table = self.task_table() if task_table is None else task_table
        tree: dict = {}
        for task_id, leaf in (table or {}).items():
            if not isinstance(leaf, dict):
                continue
            path = task_registry.get_path(task_id)
            if not path:
                continue
            parts = [part for part in path.split("/") if part]
            if not parts:
                continue
            node = tree
            blocked = False
            for part in parts[:-1]:
                child = node.get(part)
                if child is None:
                    child = node[part] = {}
                elif not isinstance(child, dict) or "on" in child:
                    # A task file and a folder claim the same name. Only one can be
                    # shown, so the task loses and the naming clash is reported.
                    logger.error("任务路径与已有任务同名，无法显示: %s", path)
                    blocked = True
                    break
                node = child
            if blocked:
                continue
            existing = node.get(parts[-1])
            if isinstance(existing, dict) and "on" not in existing:
                logger.error("任务路径与已有分组同名，无法显示: %s", path)
                continue
            node[parts[-1]] = {**leaf, "id": task_id}
        return tree

    def flatten_payload_tasks(self, task_tree: dict) -> dict[str, dict]:
        """Turn the WebUI's path-keyed tree back into the flat, id-keyed table.

        The leaf body is stored as sent, minus the wire-only runtime fields. A leaf
        with no ``id`` has never been registered, so its display path is the only
        identity it can have.
        """
        from orchestrator.model import TaskTree

        flat: dict[str, dict] = {}
        for parts, leaf in TaskTree.collect_all_leaves(task_tree or {}):
            cleaned = deepcopy(leaf)
            task_id = str(cleaned.pop("id", "") or "").strip() or "/".join(parts)
            for field in self.RUNTIME_TASK_FIELDS:
                cleaned.pop(field, None)
            flat[task_id] = cleaned
        return flat

    def ordering_overlay_in_paths(self, raw_overlay: dict | None = None) -> dict:
        """The stored overlay (id-keyed) re-expressed for the projection and WebUI."""
        from tasks.task_register import task_registry

        stored = cfg._config.get("task_ordering", {}) if raw_overlay is None else raw_overlay
        return retarget_ordering_overlay(stored, task_registry.id_to_path_map(), "path")

    def ordering_overlay_in_ids(self, path_overlay: dict) -> dict:
        """A path-keyed overlay from the WebUI re-expressed for storage."""
        from tasks.task_register import task_registry

        return retarget_ordering_overlay(path_overlay, task_registry.path_to_id_map(), "id")

    def task_ordering_projection(self, task_table: dict | None = None):
        """Return the current global task-ordering projection for a task table."""
        source = self.task_table() if task_table is None else (task_table or {})
        return project_task_ordering(source, self.ordering_overlay_in_paths())

    def task_ordering_projection_with_overlay(self, raw_overlay: dict[str, Any], task_table: dict | None = None):
        """Return a projection for a candidate path-keyed overlay without mutating cfg."""
        source = self.task_table() if task_table is None else (task_table or {})
        return project_task_ordering(source, raw_overlay)

    def read_order_map(self) -> dict[str, int]:
        return self.task_ordering_projection().order_map

    def sort_task_paths(self, paths: list[str]) -> list[str]:
        """Order an explicit task list by the current effective order.

        The HTTP layer gets "run these, in execution order" without keeping its
        own copy of the order map; the projection is computed on demand.
        """
        order_map = self.read_order_map()
        return sorted(paths, key=lambda path: order_map.get(path, float("inf")))

    def ordered_paths(self, task_table: dict | None = None, prefix: str = "") -> list[str]:
        if prefix:
            return collect_task_paths(task_table or {}, prefix)
        return self.task_ordering_projection(task_table).effective_order

    def apply_effective_order_to_tree(self, tasks: dict) -> Any:
        """Reorder a public task tree by effective order without changing shape."""
        from orchestrator.model import TaskTree

        # The order map is path-keyed, so it comes from the table, not the view.
        projection = self.task_ordering_projection()
        order_map = projection.order_map

        def minimum_order(node: dict, path: str) -> int | float:
            if TaskTree.is_leaf(node):
                return order_map.get(path, float("inf"))
            child_orders: list[int | float] = []
            for child_key, child_value in node.items():
                if not isinstance(child_value, dict):
                    continue
                child_path = f"{path}/{child_key}" if path else str(child_key)
                child_orders.append(minimum_order(child_value, child_path))
            return min(child_orders) if child_orders else float("inf")

        def reorder_node(node: dict, prefix: str = "") -> None:
            for child_key, child_value in list(node.items()):
                if not isinstance(child_value, dict) or TaskTree.is_leaf(child_value):
                    continue
                child_path = f"{prefix}/{child_key}" if prefix else str(child_key)
                reorder_node(child_value, child_path)
            sorted_items = sorted(
                node.items(),
                key=lambda item: (
                    minimum_order(item[1], f"{prefix}/{item[0]}" if prefix else str(item[0]))
                    if isinstance(item[1], dict)
                    else float("inf"),
                    str(item[0]),
                ),
            )
            node.clear()
            node.update(sorted_items)

        if isinstance(tasks, dict):
            reorder_node(tasks)
        return projection

    def public_config(self) -> dict:
        config_data = deepcopy(cfg._config)
        qq_settings = config_data.get("notify", {}).get("qq")
        if isinstance(qq_settings, dict):
            qq_settings["token_set"] = bool(qq_settings.pop("access_token", ""))
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
        task_table = config_data.get("tasks")
        if isinstance(task_table, dict):
            # Storage is the flat table; the WebUI gets the tree its paths imply,
            # with an ``id`` on every leaf so a save can find its way back.
            tasks = self.build_task_tree(task_table)
            config_data["tasks"] = tasks
            self.inject_public_task_fields(tasks)
            ordering_projection = self.apply_effective_order_to_tree(tasks)
            config_data["task_ordering_projection"] = ordering_projection.to_public_dict()
            config_data["task_ordering_generations"] = summarize_ordering_generations(ordering_projection)
        config_data["active_character"] = cfg.active_character()
        config_data["characters_summary"] = self.characters_summary()
        config_data["game_professions_by_character"] = self.game_professions_by_character()
        config_data["game_profession_options"] = list(GAME_PROFESSIONS)
        try:
            from orchestrator.catalog import get_custom_task_load_errors

            custom_task_load_errors = get_custom_task_load_errors()
        except Exception:
            custom_task_load_errors = []
        if custom_task_load_errors:
            config_data["custom_task_load_errors"] = custom_task_load_errors
        else:
            config_data.pop("custom_task_load_errors", None)
        return config_data

    def inject_public_task_fields(self, node: dict, prefix: str = "") -> None:
        from tasks.task_register import task_registry
        from orchestrator.model import TaskTree

        now_ts = time.time()
        for key, val in list(node.items()):
            if not isinstance(val, dict):
                continue
            path = f"{prefix}/{key}" if prefix else key
            if TaskTree.is_leaf(val):
                if not task_registry.has_task(path):
                    del node[key]
                    continue
                self.inject_public_task_leaf(val, path, now_ts)
            else:
                self.inject_public_task_fields(val, path)
                if not val:
                    del node[key]

    def inject_public_task_leaf(self, leaf: dict, path: str, now_ts: float | None = None) -> None:
        """Add the runtime-derived fields one WebUI leaf carries.

        Everything here is computed from the registry and cfg, never stored: the
        leaf on disk holds user config only, and this is what makes it renderable.
        """
        from tasks.task_register import task_registry
        from orchestrator.model import is_task_debug_mode, is_task_due, resolve_reschedule

        if now_ts is None:
            now_ts = time.time()
        meta = task_registry.get_param_meta(path)
        if meta:
            leaf["param_meta"] = meta
        else:
            leaf.pop("param_meta", None)
        pkeys = task_registry.get_param_keys(path)
        if pkeys:
            leaf["param_keys"] = pkeys
        else:
            leaf.pop("param_keys", None)
        if task_registry.get_custom(path):
            leaf["custom"] = True
        else:
            leaf.pop("custom", None)
        # 生效值单独投影：cfg 里存的仍是用户覆盖值，作者改默认不会被这次投影固化。
        leaf["debug_effective"] = is_task_debug_mode(path)
        leaf["reschedule_effective"] = resolve_reschedule(path, leaf)
        leaf["task_description"] = task_registry.get_description(path)
        leaf["task_doc_flow"] = task_registry.get_doc_flow(path)
        task_status = ((cfg._config.get("status") or {}).get("tasks") or {}).get(path, {})
        progress = task_status.get("progress") if isinstance(task_status, dict) else None
        if progress is not None:
            from tasks.task_state import progress_label

            leaf["progress"] = progress
            leaf["progress_display"] = progress_label(progress) or str(progress)
        else:
            leaf.pop("progress", None)
            leaf.pop("progress_display", None)
        leaf["_due"] = is_task_due(leaf, path, now_ts)

    def strip_runtime_fields(self, node: dict) -> dict:
        cleaned = deepcopy(node)
        self.strip_runtime_fields_inplace(cleaned)
        return cleaned

    def strip_runtime_fields_inplace(self, node: Any) -> None:
        from orchestrator.model import TaskTree

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

    def collect_task_reset_paths(self, old_table: dict, new_table: dict) -> list[str]:
        """Paths of the tasks the save just re-enabled or revived from an error.

        Both tables are flat and id-keyed, so this is one pass and the comparison
        is against the same task even when its display path moved.
        """
        from tasks.task_register import task_registry

        paths: list[str] = []
        for task_id, new_leaf in (new_table or {}).items():
            if not isinstance(new_leaf, dict):
                continue
            old_leaf = (old_table or {}).get(task_id)
            if not isinstance(old_leaf, dict):
                old_leaf = {}
            if not self.task_leaf_needs_reset(old_leaf, new_leaf):
                continue
            path = task_registry.get_path(task_id)
            if path:
                paths.append(path)
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
        from tasks.task_register import task_registry

        path = (task_path or "").strip().replace("\\", "/")
        if not path or not task_registry.has_task(path):
            return None
        task_id = task_registry.id_of(path)
        leaf = self._character_task_table(server, char_name).get(task_id)
        if not isinstance(leaf, dict) or "on" not in leaf:
            return None
        public_leaf = {**deepcopy(leaf), "id": task_id}
        self.inject_public_task_leaf(public_leaf, path)
        return public_leaf

    def apply_character_task_leaf(self, task_table: dict, task_path: str, task_data: dict) -> dict:
        from tasks.task_register import task_registry

        path = (task_path or "").strip().replace("\\", "/")
        task_id = task_registry.id_of(path)
        old_leaf = task_table.get(task_id)
        if not isinstance(old_leaf, dict) or "on" not in old_leaf:
            raise ValueError(f"无效任务路径: {path}")
        cleaned = deepcopy(task_data)
        if isinstance(cleaned, dict):
            for field in self.RUNTIME_TASK_FIELDS:
                cleaned.pop(field, None)
        next_leaf = {**old_leaf, **cleaned}
        task_table[task_id] = next_leaf
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

    def account_role_options(self) -> list[dict]:
        """Account → role choices for a picker, credential-free.

        Covers every account on disk, not just the current one: the redeem flow
        has to be able to target another account, and reading that account's
        file is the account domain's job (``cfg.account_character_names``), not
        the HTTP layer's.
        """
        current = cfg.current_account()
        options = []
        for name in cfg.list_accounts():
            roles = [
                {"server": str(server), "name": str(character), "label": f"{server}:{character}"}
                for server, characters in (cfg.account_character_names(name) or {}).items()
                if isinstance(characters, dict)
                for character in characters
            ]
            options.append({"name": name, "current": name == current, "roles": roles})
        return options

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
        from orchestrator.model import is_human_takeover_blocked, is_task_due

        if not node.get("on"):
            return "disabled"
        if node.get("error") or is_human_takeover_blocked(node, now_ts):
            return "error"
        return "pending" if is_task_due(node, path, now_ts) else "scheduled"

    def flatten_tasks(self, task_table: dict, now_ts: float) -> list:
        """One row per registered task in a flat cfg table, with its display path."""
        from tasks.task_register import task_registry
        from orchestrator.model import is_task_debug_mode

        result = []
        for task_id, val in (task_table or {}).items():
            if not isinstance(val, dict) or "on" not in val or "next_exec_time" not in val:
                continue
            path = task_registry.get_path(task_id)
            if not path or not task_registry.has_task(path):
                continue
            row = {
                "id": task_id,
                "path": path,
                "name": path.split("/")[-1],
                "status": self.task_leaf_status(val, path, now_ts),
                "debug": is_task_debug_mode(path),
                "task_description": task_registry.get_description(path),
                "task_doc_flow": task_registry.get_doc_flow(path),
            }
            task_status = ((cfg._config.get("status") or {}).get("tasks") or {}).get(path, {})
            progress = task_status.get("progress") if isinstance(task_status, dict) else None
            if progress is not None:
                from tasks.task_state import progress_label

                row["progress"] = progress
                row["progress_display"] = progress_label(progress) or str(progress)
            if val.get("human_takeover_error"):
                row["human_takeover_error"] = val.get("human_takeover_error")
                row["human_takeover_at"] = val.get("human_takeover_at")
            if task_registry.get_custom(path):
                row["custom"] = True
            result.append(row)
        return result

    def _character_task_table(self, server: str, char_name: str) -> dict:
        """The flat task table of any character, current one included."""
        ac = cfg.active_character()
        if server == ac.get("server", "") and char_name == ac.get("name", ""):
            return cfg._config.get("tasks", {})
        return cfg._account_data.get("characters", {}).get(server, {}).get(char_name, {}).get("tasks", {}) or {}

    def aggregate_stats_all_characters(self, now_ts: float) -> dict:
        chars = cfg._account_data.get("characters", {})
        total = pending = scheduled = error = disabled = 0
        for srv, srv_chars in chars.items():
            for char_name in srv_chars.keys():
                flat = self.flatten_tasks(self._character_task_table(srv, char_name), now_ts)
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
        from orchestrator.model import (
            collect_active_times_from_task_table,
            next_display_timestamp_from_times,
        )

        chars = cfg._account_data.get("characters", {})
        candidates: list[float] = []
        for srv, srv_chars in chars.items():
            for char_name in srv_chars.keys():
                task_table = self._character_task_table(srv, char_name)
                nxt = next_display_timestamp_from_times(collect_active_times_from_task_table(task_table))
                if nxt is not None:
                    candidates.append(nxt)
        return min(candidates) if candidates else None

    def all_characters_tasks_summary(self) -> dict:
        from orchestrator.model import (
            collect_active_times_from_task_table,
            next_display_timestamp_from_times,
        )

        now_ts = time.time()
        chars = cfg._account_data.get("characters", {})
        result = {}
        for srv, srv_chars in chars.items():
            srv_result = {}
            for char_name in srv_chars.keys():
                task_table = self._character_task_table(srv, char_name)
                flat = self.flatten_tasks(task_table, now_ts)
                counts = {"total": 0, "pending": 0, "scheduled": 0, "error": 0, "disabled": 0}
                for t in flat:
                    counts["total"] += 1
                    counts[t["status"]] += 1
                next_exec = next_display_timestamp_from_times(collect_active_times_from_task_table(task_table))
                srv_result[char_name] = {**counts, "tasks_flat": flat, "next_execution": next_exec}
            result[srv] = srv_result
        return result


task_tree_service = TaskTreeService()


def normalize_emulator_config(emulator: dict[str, Any]) -> dict[str, Any]:
    """把没有信息量的 ADB 地址补成实例号对应的默认值；手填的地址一律不动。"""
    data = deepcopy(emulator)
    if is_placeholder_adb_addr(data.get("adb_addr")):
        data["adb_addr"] = default_mumu_adb_addr(data.get("index", 0))
    return data


class WebUILifecycleService:
    IMPORTABLE_CONFIG_KEYS = (
        "app",
        "emulator",
        "ocr",
        "scheduler",
        "tasks",
        "deploy",
        "notify",
        "update",
        "task_ordering",
    )

    def __init__(
        self,
        cfg,
        task_manager,
        scheduler,
        task_tree_service,
        mark_config_changed: Callable[[str], int],
        apply_log_level: Callable[[], None] | None = None,
        clear_background: Callable[[], None] | None = None,
        reload_ui_map: Callable[[], None] | None = None,
    ):
        self.cfg = cfg
        self.task_manager = task_manager
        self.scheduler = scheduler
        self.task_tree_service = task_tree_service
        self.mark_config_changed = mark_config_changed
        self.apply_log_level = apply_log_level
        self.clear_background = clear_background
        self.reload_ui_map = reload_ui_map
        self._config_operation_lock = RLock()
        self._config_operation_state = local()

    @contextmanager
    def config_operation(self):
        """Serialize WebUI config reload/save lifecycles.

        Task saves, task-order saves and config sync all touch the shared cfg
        object and the same persistence files.  Keep the whole lifecycle
        atomic from cfg mutation through UI projection refresh so concurrent
        requests cannot validate against one tree and persist against another.
        """
        if getattr(self._config_operation_state, "depth", 0) > 0:
            self._config_operation_state.depth += 1
            try:
                yield
            finally:
                self._config_operation_state.depth -= 1
            return

        with self._config_operation_lock:
            with self.task_manager.config_transaction():
                self._config_operation_state.depth = 1
                try:
                    yield
                finally:
                    self._config_operation_state.depth = 0

    def reload_tasks(self, security_key: str | None = None, *, reason: str = "reload tasks") -> int:
        return self.reload_all(security_key, reason=reason)

    def reload_task_state(self, *, reason: str = "reload tasks") -> int:
        with self.config_operation():
            self._clear_background()
            return self._refresh_task_projection(reason)

    def sync_all_config(self, security_key: str | None = None, *, reason: str = "sync config") -> int:
        with self.config_operation():
            self.cfg.reload_preserving_decrypted_credentials(security_key)
            self._apply_log_level()
            return self.mark_config_changed(reason)

    def reload_all(self, security_key: str | None = None, *, reason: str = "reload all") -> int:
        with self.config_operation():
            self.task_manager.reload_tasks(security_key)
            self._reload_ui_map_cache()
            self._clear_background()
            return self._refresh_task_projection(reason)

    def save_runtime_config(self, data: dict[str, Any]) -> int:
        missing = [key for key in ("app", "emulator", "ocr") if key not in data]
        if missing:
            raise ValueError(f"missing config sections: {', '.join(missing)}")
        with self.task_manager.config_transaction():
            self.cfg["app"] = deepcopy(data["app"])
            if isinstance(data.get("scheduler"), dict):
                self.cfg["scheduler"] = deepcopy(data["scheduler"])
            self.cfg["emulator"] = normalize_emulator_config(data["emulator"])
            self.cfg["ocr"] = deepcopy(data["ocr"])
            self._save_global_config()
        self._apply_log_level()
        return self.mark_config_changed("save config")

    def apply_discovered_emulator_config(self, emulator: dict[str, Any]) -> int:
        if not isinstance(emulator, dict):
            raise ValueError("invalid emulator payload")
        allowed = {"index", "adb_addr", "mumu_folder", "emu_path", "adb_path", "post_execution"}
        next_emulator = deepcopy(self.cfg["emulator"])
        for key in allowed:
            if key in emulator:
                next_emulator[key] = emulator[key]
        with self.task_manager.config_transaction():
            self.cfg["emulator"] = normalize_emulator_config(next_emulator)
            self._save_global_config()
        return self.reload_all(reason="apply device discovery")

    def save_tasks(self, tasks: dict[str, Any]) -> int:
        with self.config_operation():
            # The WebUI sends the tree it was shown; storage is the flat table.
            cleaned = self.task_tree_service.flatten_payload_tasks(tasks)
            old_tasks = deepcopy(self.cfg._config.get("tasks", {}))
            reset_paths = self.task_tree_service.collect_task_reset_paths(old_tasks, cleaned)
            self.cfg._config["tasks"] = cleaned
            if reset_paths:
                from tasks.task_state import clear_task_status

                for path in reset_paths:
                    self.task_manager._clear_human_takeover_state(path)
                    clear_task_status(None, task_path=path, save=False)
            self.cfg.save_config()
            self.scheduler.wake()
            return self._refresh_task_projection("save tasks")

    def save_task_ordering(self, raw_overlay: dict[str, Any]) -> int:
        """Persist one global task order without rewriting account task data."""
        with self.config_operation():
            if not isinstance(raw_overlay, dict):
                raise ValueError("invalid task ordering payload")
            next_overlay = normalize_task_ordering_overlay(raw_overlay)

            current_tasks = self.cfg._config.get("tasks", {})
            projection = self.task_tree_service.task_ordering_projection(current_tasks)
            candidate_projection = self.task_tree_service.task_ordering_projection_with_overlay(next_overlay, current_tasks)
            if projection.task_paths != candidate_projection.task_paths:
                raise ValueError("task tree changed while saving ordering")

            # 落盘时换成 id 键：顺序跟身份走，任务改名后拖拽结果不会丢。
            self.cfg._config["task_ordering"] = self.task_tree_service.ordering_overlay_in_ids(next_overlay)
            self._save_global_config()
            self.scheduler.wake()
            return self._refresh_task_projection("save task ordering")

    def save_task_ordering_layout(self, raw_layout: dict[str, Any]) -> int:
        """Deprecated graph-layout endpoint; keep a no-op for older clients."""
        with self.config_operation():
            if not isinstance(raw_layout, dict):
                raise ValueError("invalid task ordering layout payload")
            # Nothing to save: just re-normalize the stored overlay in its own key
            # space (id), which is what round-tripping through the path view does.
            current_overlay = self.task_tree_service.ordering_overlay_in_ids(
                normalize_task_ordering_overlay(self.task_tree_service.ordering_overlay_in_paths())
            )
            self.cfg._config["task_ordering"] = current_overlay
            self._save_global_config()
            return self.mark_config_changed("save task ordering layout")

    def save_character_task(self, server: str, character: str, task_path: str, task_data: dict[str, Any]) -> int:
        with self.config_operation():
            from tasks.task_register import task_registry

            server = (server or "").strip()
            character = (character or "").strip()
            task_path = (task_path or "").strip().replace("\\", "/")
            if not server or not character or not task_path:
                raise ValueError("invalid character task payload")
            chars = self.cfg._account_data.get("characters", {})
            if server not in chars or character not in chars[server]:
                raise KeyError(f"角色 '{server}/{character}' 不存在")

            char_node = chars[server][character]
            task_table = deepcopy(char_node.get("tasks") or {})
            task_id = task_registry.id_of(task_path)
            old_leaf = deepcopy(task_table.get(task_id))
            new_leaf = self.task_tree_service.apply_character_task_leaf(task_table, task_path, task_data)
            reset_paths = [task_path] if self.task_tree_service.task_leaf_needs_reset(old_leaf, new_leaf) else []
            if reset_paths:
                for key in ("human_takeover", "human_takeover_error", "human_takeover_at", "error"):
                    new_leaf.pop(key, None)
                new_leaf["next_exec_time"] = 0

            char_node["tasks"] = task_table
            ac = self.cfg.active_character()
            if ac.get("server") == server and ac.get("name") == character:
                self.cfg._config["tasks"] = task_table
                if reset_paths:
                    from tasks.task_state import clear_task_status

                    for path in reset_paths:
                        self.task_manager._clear_human_takeover_state(path)
                        clear_task_status(None, task_path=path, save=False)
                self.cfg.save_config()
            else:
                if reset_paths:
                    status_tasks = char_node.setdefault("status", {}).setdefault("tasks", {})
                    for path in reset_paths:
                        status_tasks.pop(path, None)
                self.cfg._save_account_file()
            self.scheduler.wake()
            return self._refresh_task_projection("save character task")

    def _ensure_current_character_entries(self) -> None:
        """切换之后，当前角色的任务表必须认领每一个已注册任务。

        注册只在「那个角色是当前角色」时写配置，所以新增账号、新建角色、切到历史空角色
        之后，表可能还没有这些条目，WebUI 会显示成空任务树。这里就地补齐，省掉一次
        任务模块重载，也省掉用户手动重启。

        调用方必须已经持有 config_transaction。
        """
        from orchestrator.catalog import ensure_task_entries

        task_table = self.cfg._config.get("tasks")
        if isinstance(task_table, dict) and ensure_task_entries(task_table):
            self.cfg._save_account_file()

    def switch_character(
        self,
        server: str,
        character: str,
        *,
        reason: str = "switch character",
        invalidate_login: bool = True,
    ) -> int:
        with self.task_manager.config_transaction():
            self.cfg.switch_character(server, character)
            self._ensure_current_character_entries()
        if invalidate_login:
            self.scheduler.invalidate_login()
        return self._refresh_task_projection(reason)

    def switch_account(self, name: str, security_key: str) -> int:
        with self.task_manager.config_transaction():
            self.cfg.switch_account(name, security_key)
            self._ensure_current_character_entries()
        self.scheduler.invalidate_login()
        return self._refresh_task_projection("switch account")

    def save_dispatch_queue(self, raw_queue) -> tuple[list[dict[str, str]], int]:
        queue = self.task_tree_service.normalize_dispatch_queue(raw_queue)
        with self.task_manager.config_transaction():
            self.cfg._account_data["dispatch_queue"] = queue
            self.cfg._save_account_file()
        version = self.mark_config_changed("save dispatch queue")
        return queue, version

    def set_character_profession(self, server: str, character: str, profession: str) -> int:
        with self.task_manager.config_transaction():
            self.cfg.set_character_game_profession(server, character, profession)
        return self.mark_config_changed("change character profession")

    def add_account(
        self,
        name: str,
        account: str,
        password: str,
        server: str,
        character_name: str,
        security_key: str,
    ) -> int:
        with self.task_manager.config_transaction():
            self.cfg.add_account(name, account, password, server, character_name, security_key)
            self.cfg.switch_account(name, security_key)
            self._ensure_current_character_entries()
        self.scheduler.invalidate_login()
        return self._refresh_task_projection("add account")

    def delete_account(self, name: str) -> int:
        with self.task_manager.config_transaction():
            self.cfg.delete_account(name)
        return self.mark_config_changed("delete account")

    def add_character(self, server: str, character: str) -> int:
        with self.task_manager.config_transaction():
            self.cfg.add_character(server, character)
            self.cfg.switch_character(server, character)
            self._ensure_current_character_entries()
        self.scheduler.invalidate_login()
        return self._refresh_task_projection("add character")

    def delete_character(self, server: str, character: str) -> int:
        with self.task_manager.config_transaction():
            self.cfg.delete_character(server, character)
            queue = self.task_tree_service.normalize_dispatch_queue(
                self.cfg._account_data.get("dispatch_queue", [])
            )
            self.cfg._account_data["dispatch_queue"] = queue
            self.cfg._save_account_file()
        return self.mark_config_changed("delete character")

    def reload_verified_account(self, security_key: str) -> str:
        self.cfg.reload_preserving_decrypted_credentials(security_key)
        character_name = self.ensure_active_character_in_game()
        return character_name

    def update_account_credentials(self, account: str, password: str, security_key: str) -> tuple[str, int]:
        with self.task_manager.config_transaction():
            self.cfg.update_current_account_credentials(account, password, security_key)
        version = self._refresh_task_projection("update account credentials")
        character_name = self.cfg._config.get("game", {}).get("character_name", "")
        return character_name, version

    def import_config(self, data: dict[str, Any]) -> int:
        incoming = deepcopy(data)
        for key in (
            "encryption",
            "current_profile",
            "current_account",
            "profiles",
            "game",
            "active_character",
            "characters_summary",
        ):
            incoming.pop(key, None)
        deploy = incoming.get("deploy")
        if isinstance(deploy, dict):
            for secret_key in ("password", "ssl_key", "ssl_cert"):
                deploy.pop(secret_key, None)

        with self.task_manager.config_transaction():
            incoming_notify = incoming.get("notify")
            if isinstance(incoming_notify, dict):
                from dataclasses import asdict

                incoming_notify["qq"] = asdict(self.prepare_qq_settings(incoming_notify.get("qq", {})))
            for key in self.IMPORTABLE_CONFIG_KEYS:
                if key not in incoming:
                    continue
                value = incoming[key]
                if key == "tasks" and isinstance(value, dict):
                    value = self.task_tree_service.strip_runtime_fields(value)
                self.cfg._config[key] = value
            self.cfg.save_config()
        self._mark_tasks_updated()
        self._apply_log_level()
        return self.mark_config_changed("import config")

    def prepare_qq_settings(self, payload: dict, *, require_target: bool = False):
        from orchestrator.delivery import QQSettings

        if not isinstance(payload, dict):
            raise ValueError("QQ settings must be an object")
        with self.task_manager.config_transaction():
            merged = deepcopy(self.cfg.get("notify.qq", {}))
        if not isinstance(merged, dict):
            raise ValueError("Stored QQ settings must be an object")
        merged.update(payload)
        return QQSettings.parse(merged, require_target=require_target)

    def save_qq_settings(self, payload: dict) -> int:
        from dataclasses import asdict

        with self.config_operation():
            settings = self.prepare_qq_settings(payload)
            previous_notify = deepcopy(self.cfg.get("notify", {}))
            with self.task_manager.config_transaction():
                self.cfg["notify.qq"] = asdict(settings)
                try:
                    self._save_global_config()
                except (OSError, ValueError, TypeError):
                    self.cfg["notify"] = previous_notify
                    raise
            return self.mark_config_changed("save QQ notifications")

    def save_deploy_sections(self, data: dict[str, Any]) -> int:
        """保存 deploy 段：WebUI 访问密码、日志级别、主题等。

        notify 走 QQ 接口，update 走 /api/update/*，所以这里只认 deploy。
        """
        deploy = data.get("deploy")
        if not isinstance(deploy, dict):
            raise ValueError("missing deploy section")
        with self.task_manager.config_transaction():
            self.cfg._config["deploy"] = deepcopy(deploy)
            self._save_global_config()
        self._apply_log_level()
        return self.mark_config_changed("save deploy settings")

    def ensure_active_character_in_game(self) -> str:
        self.cfg._config.setdefault("game", {})
        game = self.cfg._config["game"]
        active = self.cfg.active_character()
        if not game.get("character_name") and active.get("name"):
            game["character_name"] = active["name"]
        if not game.get("server_name") and active.get("server"):
            game["server_name"] = active["server"]
        return game.get("character_name", "")

    def _apply_log_level(self) -> None:
        if self.apply_log_level is not None:
            self.apply_log_level()

    def _clear_background(self) -> None:
        if self.clear_background is not None:
            self.clear_background()
            return
        from AutoScriptor.core.background import bg

        bg.clear(clear_signals=True)

    def _reload_ui_map_cache(self) -> None:
        if self.reload_ui_map is not None:
            self.reload_ui_map()
            return
        from AutoScriptor.utils.ui_map import reload_ui_map

        reload_ui_map()

    def _mark_tasks_updated(self) -> None:
        marker = getattr(self.scheduler, "mark_tasks_updated", None)
        if callable(marker):
            marker()
            return
        event = getattr(self.scheduler, "_tasks_updated", None)
        if event is not None and hasattr(event, "set"):
            event.set()

    def _refresh_task_projection(self, reason: str) -> int:
        self._mark_tasks_updated()
        return self.mark_config_changed(reason)

    def _save_global_config(self) -> None:
        saver = getattr(self.cfg, "save_global_config", None)
        if callable(saver):
            saver()
        else:
            self.cfg.save_config()


# ── config version ──

_state_version_lock = Lock()
_state_version = 1


def bump_version(_reason: str = "") -> int:
    """Announce that the public config snapshot changed."""
    global _state_version
    with _state_version_lock:
        _state_version += 1
        return _state_version


def current_version() -> int:
    with _state_version_lock:
        return _state_version
