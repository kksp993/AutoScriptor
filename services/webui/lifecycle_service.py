"""Centralized WebUI config and task lifecycle operations.

Routes should validate HTTP input and shape responses. This service owns the
ordering of side effects: mutate config, persist, reload task registry, refresh
server-side projections, notify scheduler, then bump the public config version.
"""
from __future__ import annotations

from copy import deepcopy
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

MUMU_ADB_BASE_PORT = 16384
MUMU_ADB_PORT_STEP = 32


def default_mumu_adb_addr(index: Any) -> str:
    try:
        n = int(index)
    except (TypeError, ValueError):
        n = 0
    if n < 0:
        n = 0
    return f"127.0.0.1:{MUMU_ADB_BASE_PORT + n * MUMU_ADB_PORT_STEP}"


def normalize_emulator_config(emulator: dict[str, Any]) -> dict[str, Any]:
    data = deepcopy(emulator)
    adb_addr = str(data.get("adb_addr", "") or "").strip()
    if not adb_addr or adb_addr.startswith("YOUR_") or adb_addr.endswith(":0"):
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
        "remote_access",
    )

    def __init__(
        self,
        cfg,
        task_manager,
        scheduler,
        task_tree_service,
        refresh_order_map: Callable[[], None],
        mark_config_changed: Callable[[str], int],
        apply_log_level: Callable[[], None] | None = None,
        clear_background: Callable[[], None] | None = None,
        reload_ui_map: Callable[[], None] | None = None,
    ):
        self.cfg = cfg
        self.task_manager = task_manager
        self.scheduler = scheduler
        self.task_tree_service = task_tree_service
        self.refresh_order_map = refresh_order_map
        self.mark_config_changed = mark_config_changed
        self.apply_log_level = apply_log_level
        self.clear_background = clear_background
        self.reload_ui_map = reload_ui_map

    def reload_tasks(self, security_key: str | None = None, *, reason: str = "reload tasks") -> int:
        return self.reload_all(security_key, reason=reason)

    def reload_task_state(self, *, reason: str = "reload tasks") -> int:
        self._clear_background()
        return self._refresh_task_projection(reason)

    def sync_all_config(self, security_key: str | None = None, *, reason: str = "sync config") -> int:
        self.cfg.reload_preserving_decrypted_credentials(security_key)
        self.refresh_order_map()
        self._apply_log_level()
        return self.mark_config_changed(reason)

    def reload_all(self, security_key: str | None = None, *, reason: str = "reload all") -> int:
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
        return self.reload_all(reason="save config")

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
        cleaned = self.task_tree_service.strip_runtime_fields(tasks)
        old_tasks = deepcopy(self.cfg._config.get("tasks", {}))
        reset_paths = self.task_tree_service.collect_task_reset_paths(old_tasks, cleaned)
        with self.task_manager.config_transaction():
            self.cfg._config["tasks"] = cleaned
            if reset_paths:
                from AutoScriptor.utils.task_state import clear_task_status

                for path in reset_paths:
                    self.task_manager._clear_human_takeover_state(path)
                    clear_task_status(None, task_path=path, save=False)
            self.cfg.save_config()
        self.scheduler.wake()
        return self._refresh_task_projection("save tasks")

    def save_character_task(self, server: str, character: str, task_path: str, task_data: dict[str, Any]) -> int:
        server = (server or "").strip()
        character = (character or "").strip()
        task_path = (task_path or "").strip().replace("\\", "/")
        if not server or not character or not task_path:
            raise ValueError("invalid character task payload")
        chars = self.cfg._account_data.get("characters", {})
        if server not in chars or character not in chars[server]:
            raise KeyError(f"角色 '{server}/{character}' 不存在")

        import dpath

        char_node = chars[server][character]
        tree = deepcopy(char_node.get("tasks") or {})
        old_leaf = deepcopy(dpath.get(tree, task_path))
        self.task_tree_service.apply_character_task_leaf(tree, task_path, task_data)
        cleaned_tree = self.task_tree_service.strip_runtime_fields(tree)
        new_leaf = dpath.get(cleaned_tree, task_path)
        reset_paths = [task_path] if self.task_tree_service.task_leaf_needs_reset(old_leaf, new_leaf) else []
        if reset_paths:
            for key in ("human_takeover", "human_takeover_error", "human_takeover_at", "error"):
                new_leaf.pop(key, None)
            new_leaf["next_exec_time"] = 0
            dpath.set(cleaned_tree, task_path, new_leaf)

        with self.task_manager.config_transaction():
            char_node["tasks"] = cleaned_tree
            ac = self.cfg.active_character()
            if ac.get("server") == server and ac.get("name") == character:
                self.cfg._config["tasks"] = cleaned_tree
                if reset_paths:
                    from AutoScriptor.utils.task_state import clear_task_status

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

    def switch_character(self, server: str, character: str, *, reason: str = "switch character") -> int:
        with self.task_manager.config_transaction():
            self.cfg.switch_character(server, character)
        self.scheduler.invalidate_login()
        return self._refresh_task_projection(reason)

    def switch_account(self, name: str, security_key: str) -> int:
        with self.task_manager.config_transaction():
            self.cfg.switch_account(name, security_key)
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
            self.task_manager.reload_tasks()
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
        self.refresh_order_map()
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
            for key in self.IMPORTABLE_CONFIG_KEYS:
                if key not in incoming:
                    continue
                value = incoming[key]
                if key == "tasks" and isinstance(value, dict):
                    value = self.task_tree_service.strip_runtime_fields(value)
                self.cfg._config[key] = value
            self.cfg.save_config()
        self._mark_tasks_updated()
        self.refresh_order_map()
        self._apply_log_level()
        return self.mark_config_changed("import config")

    def save_notify_settings(self, enabled: bool, config_yaml: str) -> int:
        with self.task_manager.config_transaction():
            self.cfg["notify.enabled"] = enabled
            self.cfg["notify.config_yaml"] = config_yaml
            self._save_global_config()
        return self.mark_config_changed("save notify settings")

    def save_deploy_sections(self, data: dict[str, Any]) -> int:
        with self.task_manager.config_transaction():
            for section in ("deploy", "notify", "update", "remote_access"):
                if section in data:
                    self.cfg._config[section] = deepcopy(data[section])
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
        self.refresh_order_map()
        return self.mark_config_changed(reason)

    def _save_global_config(self) -> None:
        saver = getattr(self.cfg, "save_global_config", None)
        if callable(saver):
            saver()
        else:
            self.cfg.save_config()
