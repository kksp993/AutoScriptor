"""账号 / 角色实体与全局配置持久化。"""
from __future__ import annotations

import atexit
import copy
import datetime
import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from AutoScriptor.crypto.config_manager import ConfigManager as CryptoConfigManager
from AutoScriptor.utils.game_profession import DEFAULT_GAME_PROFESSION, normalize_game_profession
from AutoScriptor.utils.logger import logger

_DECRYPT_ERRORS = getattr(
    CryptoConfigManager,
    "DECRYPT_ERRORS",
    (KeyError, TypeError, ValueError),
)
_SECURITY_KEY_CHECK_ERRORS = (OSError, AttributeError) + _DECRYPT_ERRORS

_GLOBAL_KEYS = (
    "app", "ocr", "emulator", "scheduler", "deploy", "notify",
    "update", "remote_access", "task_ordering", "accounts",
)

_TEST_TASK_PATHS = (
    "每日任务/测试村庄/立即成功",
    "每日任务/测试村庄/慢速成功",
    "每日任务/测试村庄/总是失败",
    "每日任务/测试村庄/重试后成功",
    "每日任务/测试村庄/重试耗尽",
    "每日任务/测试村庄/人工接管",
    "每日任务/测试参数/带参数任务",
    "一般任务/一次性任务",
    "每周任务/随机结果",
)


def _atomic_write_json(path: Path, data: Any) -> None:
    """Write JSON via same-directory temp file then atomic replace."""
    start = time.perf_counter()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
            f.write("\n")
            f.flush()
            if _strict_json_fsync_enabled():
                os.fsync(f.fileno())
        os.replace(tmp_path, path)
        elapsed = time.perf_counter() - start
        if elapsed >= 1.0:
            logger.warning("JSON 保存耗时 %.2fs: %s", elapsed, path)
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass


def _strict_json_fsync_enabled() -> bool:
    return str(os.environ.get("AUTOSCRIPTOR_STRICT_FSYNC", "")).strip().lower() in {"1", "true", "yes", "on"}


def _has_task_path(tasks: dict[str, Any], task_path: str) -> bool:
    node: Any = tasks
    for part in task_path.split("/"):
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return isinstance(node, dict) and "on" in node


def _assert_no_testing_tasks_in_production(flat: dict[str, Any]) -> None:
    if os.environ.get("AUTOSCRIPTOR_TESTING") == "1":
        return
    tasks = flat.get("tasks")
    if not isinstance(tasks, dict):
        return
    leaked = [path for path in _TEST_TASK_PATHS if _has_task_path(tasks, path)]
    if leaked:
        raise RuntimeError(
            "Refusing to save testing task tree into a real account file: "
            + ", ".join(leaked[:3])
        )


def _assert_no_testing_tasks_in_account(root: dict[str, Any]) -> None:
    if os.environ.get("AUTOSCRIPTOR_TESTING") == "1":
        return
    chars = root.get("characters") if isinstance(root, dict) else None
    if not isinstance(chars, dict):
        return
    leaked: list[str] = []
    for srv_chars in chars.values():
        if not isinstance(srv_chars, dict):
            continue
        for char_data in srv_chars.values():
            if not isinstance(char_data, dict):
                continue
            tasks = char_data.get("tasks")
            if isinstance(tasks, dict):
                leaked.extend(path for path in _TEST_TASK_PATHS if _has_task_path(tasks, path))
    if leaked:
        raise RuntimeError(
            "Refusing to save account data containing testing tasks: "
            + ", ".join(leaked[:3])
        )


class Character:
    __slots__ = ("server", "name", "_data")

    def __init__(self, server: str, name: str, data: dict[str, Any]):
        self.server = server
        self.name = name
        self._data = data
        data.setdefault("tasks", {})
        data.setdefault("status", {})
        data["game_profession"] = normalize_game_profession(data.get("game_profession"))

    @property
    def tasks(self) -> dict[str, Any]:
        return self._data["tasks"]

    @property
    def status(self) -> dict[str, Any]:
        return self._data["status"]

    @property
    def profession(self) -> str:
        return normalize_game_profession(self._data.get("game_profession"))

    @staticmethod
    def clean_tasks_inplace(data: Any) -> None:
        if isinstance(data, dict):
            for key in (
                "fn", "order", "param_meta", "param_keys", "beta", "custom", "debug_mode",
                "task_description", "task_doc_flow", "_due",
            ):
                data.pop(key, None)
            for v in data.values():
                Character.clean_tasks_inplace(v)

    def to_dict(self) -> dict[str, Any]:
        tasks_copy = copy.deepcopy(self.tasks)
        Character.clean_tasks_inplace(tasks_copy)
        return {
            "tasks": tasks_copy,
            "status": copy.deepcopy(self.status),
            "game_profession": self.profession,
        }


class Account:
    __slots__ = ("account_name", "root", "characters", "credentials")

    def __init__(self, account_name: str, root: dict[str, Any]):
        self.account_name = account_name
        self.root = root
        self.root.setdefault("encryption", {})
        self.root.setdefault("active_character", {"server": "", "name": ""})
        self.root.setdefault("characters", {})
        self.credentials = {"account": "", "password": ""}
        self.characters: dict[tuple[str, str], Character] = {}
        self.rebind_characters()

    def rebind_characters(self) -> None:
        self.characters.clear()
        for srv, cmap in self.root["characters"].items():
            for cname, cdata in cmap.items():
                self.characters[(srv, cname)] = Character(srv, cname, cdata)

    @property
    def encryption(self) -> dict[str, Any]:
        return self.root["encryption"]

    @property
    def active_info(self) -> dict[str, Any]:
        return self.root["active_character"]

    @active_info.setter
    def active_info(self, v: dict[str, Any]) -> None:
        self.root["active_character"] = v

    def decrypt_credentials(self, pwd: str) -> bool:
        enc = self.encryption
        if pwd and enc.get("encrypted_data"):
            try:
                dec = CryptoConfigManager.decrypt_data(enc, pwd)
                self.credentials = {
                    "account": dec.get("account", ""),
                    "password": dec.get("password", ""),
                }
                return True
            except _DECRYPT_ERRORS as e:
                logger.error(f"解密账号 {self.account_name} 失败: {e}")
        return False

    def restore_credentials(self, credentials: dict[str, Any] | None) -> None:
        """Restore already-decrypted credentials across config-only reloads."""
        if not credentials:
            return
        account = credentials.get("account", "")
        password = credentials.get("password", "")
        if account and password:
            self.credentials = {"account": account, "password": password}

    def get_active_character(self) -> Character | None:
        ac = self.active_info
        return self.characters.get((ac.get("server", ""), ac.get("name", "")))

    def prepare_for_save(self, flat: dict[str, Any] | None) -> None:
        ch = self.get_active_character()
        if flat and ch:
            tasks = flat.get("tasks")
            if isinstance(tasks, dict):
                ch._data["tasks"] = copy.deepcopy(tasks)
            status = flat.get("status")
            if isinstance(status, dict):
                ch._data["status"] = copy.deepcopy(status)
            gp = (flat.get("game") or {}).get("game_profession")
            ch._data["game_profession"] = normalize_game_profession(gp)
        for c in self.characters.values():
            Character.clean_tasks_inplace(c.tasks)
            c._data["game_profession"] = normalize_game_profession(c._data.get("game_profession"))

    def to_persist_dict(self) -> dict[str, Any]:
        return self.root


class ConfigManager:
    _instance: ConfigManager | None = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized"):
            return
        from AutoScriptor.utils.paths import get_accounts_dir, get_config_path, get_editable_data_root
        self.data_root = Path(get_editable_data_root())
        self.default_accounts_dir = Path(get_accounts_dir())
        self._config_path: Path = Path(get_config_path())
        self.global_cfg: dict[str, Any] = {}
        self.current_acc: Account | None = None
        self._initialized = True

    @property
    def config_path(self) -> Path:
        return self._config_path

    @config_path.setter
    def config_path(self, p: Path | str) -> None:
        self._config_path = Path(p)

    @staticmethod
    def _is_under_path(child: Path, parent: Path) -> bool:
        try:
            child.resolve().relative_to(parent.resolve())
            return True
        except (OSError, ValueError):
            return False

    def _force_default_accounts_dir(self) -> bool:
        return bool(os.environ.get("AUTOSCRIPTOR_DATA_DIR"))

    def _load_default_global_config(self) -> dict[str, Any]:
        template = self.config_path.with_name("config.template.json")
        if not template.exists():
            return {k: {} for k in _GLOBAL_KEYS}
        with open(template, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {k: {} for k in _GLOBAL_KEYS}

    def _merge_global_defaults(self) -> None:
        def merge(dst: dict[str, Any], src: dict[str, Any]) -> None:
            for key, value in src.items():
                if key not in dst:
                    dst[key] = copy.deepcopy(value)
                elif isinstance(dst[key], dict) and isinstance(value, dict):
                    merge(dst[key], value)

        merge(self.global_cfg, self._load_default_global_config())

    def _migrate_external_accounts_dir(self, source: Path) -> None:
        if not source.is_dir():
            return
        try:
            self.default_accounts_dir.mkdir(parents=True, exist_ok=True)
            for src in source.glob("*.json"):
                dst = self.default_accounts_dir / src.name
                if not dst.exists():
                    shutil.copy2(src, dst)
        except OSError as e:
            logger.warning("迁移旧账号目录失败: %s -> %s (%s)", source, self.default_accounts_dir, e)

    def _normalize_accounts_dir_config(self) -> None:
        accounts = self.global_cfg.setdefault("accounts", {})
        raw = str((accounts or {}).get("dir") or "").strip()
        if not raw:
            return
        p = Path(raw)
        if p.is_absolute() and self._force_default_accounts_dir() and not self._is_under_path(p, self.data_root):
            self._migrate_external_accounts_dir(p)
            accounts["dir"] = ""
            logger.warning("账号目录已切回 dataRoot/accounts: %s -> %s", p, self.default_accounts_dir)

    def resolved_accounts_dir(self) -> Path:
        raw = (self.global_cfg.get("accounts") or {}).get("dir") or ""
        raw = str(raw).strip()
        if not raw:
            return self.default_accounts_dir
        p = Path(raw)
        if p.is_absolute():
            return p
        normalized = p.as_posix().strip("/")
        if normalized in {"accounts", "data/accounts"}:
            return self.default_accounts_dir
        return self.default_accounts_dir.parent / p

    @staticmethod
    def _default_account_payload(name: str) -> dict[str, Any]:
        char_name = name
        return {
            "encryption": {},
            "active_character": {"server": "默认服务器", "name": char_name},
            "characters": {
                "默认服务器": {
                    char_name: {
                        "tasks": {},
                        "status": {},
                        "game_profession": DEFAULT_GAME_PROFESSION,
                    }
                }
            },
        }

    def load_account(self, name: str, pwd: str = "") -> None:
        acc_dir = self.resolved_accounts_dir()
        path = acc_dir / f"{name}.json"
        if not path.exists():
            acc_dir.mkdir(parents=True, exist_ok=True)
            _atomic_write_json(path, self._default_account_payload(name))
            logger.info(f"已创建默认账号文件: {path}")
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        self.current_acc = Account(name, data)
        self.current_acc.decrypt_credentials(pwd)

    def load_all(self, pwd: str = "") -> None:
        if not self.config_path.exists():
            self.global_cfg = self._load_default_global_config()
        else:
            with open(self.config_path, "r", encoding="utf-8-sig") as f:
                self.global_cfg = json.load(f)
            self._merge_global_defaults()
        self.global_cfg.setdefault("tasks", {})
        self.global_cfg.setdefault("status", {})
        self.global_cfg.setdefault("game", {})
        self.global_cfg.setdefault("scheduler", {})
        self.global_cfg["scheduler"].setdefault("auto_start", False)
        self.global_cfg.setdefault("accounts", {})
        self.global_cfg["accounts"].setdefault("dir", "")
        self.global_cfg.setdefault("ocr", {})
        self.global_cfg["ocr"].setdefault("use_gpu", False)
        self._normalize_accounts_dir_config()
        acc_name = self.global_cfg.get("current_account", "")
        if acc_name:
            self.load_account(acc_name, pwd)
        else:
            self.current_acc = None
        self._update_runtime_dates()

    def _update_runtime_dates(self) -> None:
        now = datetime.datetime.now()
        self.global_cfg["year"] = now.year
        self.global_cfg["month"] = now.month
        self.global_cfg["day"] = now.day
        self.global_cfg["weekday"] = now.weekday() + 1

    def build_flat_runtime_config(self) -> dict[str, Any]:
        flat = copy.deepcopy(self.global_cfg)
        char = self.current_acc.get_active_character() if self.current_acc else None
        if self.current_acc and char:
            flat["tasks"] = char.tasks
            flat["status"] = char.status
            flat["game"] = {
                **self.current_acc.credentials,
                "character_name": char.name,
                "server_name": char.server,
                "game_profession": char.profession,
            }
        else:
            flat.setdefault("tasks", {})
            flat.setdefault("status", {})
            flat.setdefault("game", {})
        return flat

    def save_all(self, flat: dict[str, Any]) -> None:
        _assert_no_testing_tasks_in_production(flat)
        for k in _GLOBAL_KEYS:
            if k in flat:
                self.global_cfg[k] = copy.deepcopy(flat[k])
        self.global_cfg["current_account"] = flat.get("current_account", self.global_cfg.get("current_account", ""))
        self._update_runtime_dates()
        _atomic_write_json(self.config_path, self._persistable_global_config())
        if self.current_acc:
            self.current_acc.prepare_for_save(flat)
            _assert_no_testing_tasks_in_account(self.current_acc.root)
            acc_dir = self.resolved_accounts_dir()
            _atomic_write_json(acc_dir / f"{self.current_acc.account_name}.json", self.current_acc.to_persist_dict())

    def save_global_only(self, flat: dict[str, Any]) -> None:
        for k in _GLOBAL_KEYS:
            if k in flat:
                self.global_cfg[k] = copy.deepcopy(flat[k])
        self.global_cfg["current_account"] = flat.get("current_account", self.global_cfg.get("current_account", ""))
        self._update_runtime_dates()
        _atomic_write_json(self.config_path, self._persistable_global_config())

    def _persistable_global_config(self) -> dict[str, Any]:
        safe_cfg = {k: self.global_cfg.get(k, {}) for k in _GLOBAL_KEYS}
        safe_cfg["current_account"] = self.global_cfg.get("current_account", "")
        return safe_cfg

    def save_account_file_only(self) -> None:
        if not self.current_acc:
            return
        self.current_acc.prepare_for_save(None)
        _assert_no_testing_tasks_in_account(self.current_acc.root)
        acc_dir = self.resolved_accounts_dir()
        _atomic_write_json(acc_dir / f"{self.current_acc.account_name}.json", self.current_acc.to_persist_dict())


class AutoConfig:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized"):
            return
        from AutoScriptor.utils.paths import get_accounts_dir, get_config_path
        self.CONFIG_PATH = str(get_config_path())
        self.ACCOUNTS_DIR = str(get_accounts_dir())
        self._mgr = cfg_manager
        self._config: dict[str, Any] = {}
        self._initialized = True

    @property
    def _account_data(self) -> dict[str, Any]:
        if self._mgr.current_acc:
            return self._mgr.current_acc.root
        return {}

    def _refresh_flat_config(self) -> None:
        self._config = self._mgr.build_flat_runtime_config()

    def _account_path(self, name: str) -> str:
        return os.path.join(self.ACCOUNTS_DIR, f"{name}.json")

    def load_config(self, pwd: str = "") -> None:
        self._mgr.config_path = Path(self.CONFIG_PATH)
        self._mgr.load_all(pwd)
        self.ACCOUNTS_DIR = str(self._mgr.resolved_accounts_dir())
        self._refresh_flat_config()

    def reload_preserving_decrypted_credentials(self, pwd: str = "") -> None:
        current_account = self.current_account()
        saved_credentials = None
        if not pwd and self._mgr.current_acc:
            saved_credentials = copy.deepcopy(self._mgr.current_acc.credentials)
        self.load_config(pwd)
        if not pwd and saved_credentials and self.current_account() == current_account and self._mgr.current_acc:
            self._mgr.current_acc.restore_credentials(saved_credentials)
            self._refresh_flat_config()

    def save_config(self, *, quiet: bool = False) -> None:
        os.makedirs(os.path.dirname(self.CONFIG_PATH), exist_ok=True)
        self._mgr.config_path = Path(self.CONFIG_PATH)
        try:
            self._mgr.save_all(self._config)
        except OSError as e:
            if quiet:
                logger.debug("退出时保存配置失败，已忽略: %s", e)
                return
            raise

    def save_global_config(self, *, quiet: bool = False) -> None:
        os.makedirs(os.path.dirname(self.CONFIG_PATH), exist_ok=True)
        self._mgr.config_path = Path(self.CONFIG_PATH)
        try:
            self._mgr.save_global_only(self._config)
        except OSError as e:
            if quiet:
                logger.debug("退出时保存全局配置失败，已忽略: %s", e)
                return
            raise

    def _save_account_file(self) -> None:
        self._mgr.save_account_file_only()

    def update_current_account_credentials(self, account: str, password: str, security_key: str) -> None:
        self._account_data["encryption"] = CryptoConfigManager.encrypt_data(
            {"account": account, "password": password},
            security_key,
        )
        self._save_account_file()

    def has_encrypted_credentials(self) -> bool:
        return bool((self._account_data.get("encryption") or {}).get("encrypted_data"))

    def has_decrypted_credentials(self) -> bool:
        game = self._config.get("game") or {}
        return bool(game.get("account") and game.get("password"))

    def clear_decrypted_credentials(self) -> None:
        """Clear in-memory plaintext credentials without touching encrypted account data."""
        if self._mgr.current_acc:
            self._mgr.current_acc.credentials = {"account": "", "password": ""}
        game = self._config.setdefault("game", {})
        game.pop("account", None)
        game.pop("password", None)

    def verify_account_security_key(self, name: str, security_key: str) -> bool:
        """Return whether the security key can decrypt the named account credentials."""
        name = (name or "").strip()
        security_key = (security_key or "").strip()
        if not name or not security_key:
            return False
        path = Path(self._account_path(name))
        if not path.exists():
            return False
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            enc = data.get("encryption") or {}
            if not enc.get("encrypted_data"):
                return True
            dec = CryptoConfigManager.decrypt_data(enc, security_key)
            return bool(dec.get("account") and dec.get("password"))
        except _SECURITY_KEY_CHECK_ERRORS:
            return False

    def __setitem__(self, key, value):
        if isinstance(key, str) and "." in key:
            parts = key.split(".")
            cfg_dict = self._config
            for part in parts[:-1]:
                if part not in cfg_dict or not isinstance(cfg_dict[part], dict):
                    cfg_dict[part] = {}
                cfg_dict = cfg_dict[part]
            cfg_dict[parts[-1]] = value
            return
        self._config[key] = value

    def __getitem__(self, key):
        if isinstance(key, str) and "." in key:
            value = self._config
            for part in key.split("."):
                value = value[part]
            return value
        return self._config[key]

    def get(self, key, default=None):
        try:
            return self.__getitem__(key)
        except (KeyError, TypeError):
            return default

    def set(self, key, value) -> None:
        self.__setitem__(key, value)
        self.save_config()
        logger.info("配置已更新: %s = %s", key, value)

    def list_accounts(self) -> list[str]:
        if not os.path.isdir(self.ACCOUNTS_DIR):
            return []
        names = [f[:-5] for f in os.listdir(self.ACCOUNTS_DIR) if f.endswith(".json")]
        return sorted(names)

    def current_account(self) -> str:
        return self._config.get("current_account", "")

    def active_character(self) -> dict[str, Any]:
        return self._account_data.get("active_character", {})

    def list_characters(self) -> dict[str, Any]:
        return self._account_data.get("characters", {})

    def switch_account(self, target: str, security_key: str = "") -> None:
        if not os.path.exists(self._account_path(target)):
            raise KeyError(f"账号 '{target}' 不存在")
        self.save_config()
        self._mgr.global_cfg["current_account"] = target
        self._mgr.load_account(target, security_key)
        self._mgr._update_runtime_dates()
        self.ACCOUNTS_DIR = str(self._mgr.resolved_accounts_dir())
        self._refresh_flat_config()
        self.save_config()
        logger.info("已切换到账号: %s", target)

    def switch_character(self, server: str, character: str) -> None:
        if not self.current_account():
            raise ValueError("当前没有加载任何账号")
        chars = self._account_data.get("characters", {})
        if server not in chars or character not in chars[server]:
            raise KeyError(f"角色 '{server}/{character}' 不存在")
        acc = self._mgr.current_acc
        if not acc:
            raise ValueError("当前没有加载任何账号")
        acc.active_info = {"server": server, "name": character}
        self._refresh_flat_config()
        self.save_config()
        logger.info("已切换到角色: %s/%s", server, character)

    def set_character_game_profession(self, server: str, character: str, profession: str) -> None:
        if not self.current_account():
            raise ValueError("当前没有加载任何账号")
        server = (server or "").strip()
        character = (character or "").strip()
        gp = normalize_game_profession(profession)
        chars = self._account_data.get("characters", {})
        if server not in chars or character not in chars[server]:
            raise KeyError(f"角色 '{server}/{character}' 不存在")
        chars[server][character]["game_profession"] = gp
        ac = self.active_character()
        if ac.get("server") == server and ac.get("name") == character:
            self._config.setdefault("game", {})["game_profession"] = gp
        self._save_account_file()
        logger.info("游戏职业已更新: %s/%s -> %s", server, character, gp)

    def add_account(self, name: str, account: str, password: str, server: str, character_name: str, security_key: str):
        name = (name or "").strip()
        account = (account or "").strip()
        password = (password or "").strip()
        server = (server or "").strip()
        character_name = (character_name or "").strip()
        security_key = (security_key or "").strip()
        if not name:
            raise ValueError("账号名称不能为空")
        if not account:
            raise ValueError("游戏账号不能为空")
        if not password:
            raise ValueError("游戏密码不能为空")
        if not server:
            raise ValueError("服务器不能为空")
        if not character_name:
            raise ValueError("角色名不能为空")
        if not security_key:
            raise ValueError("安全密码不能为空")
        if os.path.exists(self._account_path(name)):
            raise ValueError(f"账号 '{name}' 已存在")
        enc = CryptoConfigManager.encrypt_data({"account": account, "password": password}, security_key)
        account_data = {
            "encryption": enc,
            "active_character": {"server": server, "name": character_name},
            "characters": {server: {character_name: {"tasks": {}, "status": {}, "game_profession": DEFAULT_GAME_PROFESSION}}},
        }
        _atomic_write_json(Path(self._account_path(name)), account_data)
        logger.info("已创建账号: %s", name)

    def delete_account(self, name: str) -> None:
        if name == self.current_account():
            raise ValueError("不能删除当前正在使用的账号")
        target = self._account_path(name)
        if os.path.exists(target):
            os.remove(target)
            logger.info("已删除账号: %s", name)

    def add_character(self, server: str, character_name: str) -> None:
        if not self.current_account():
            raise ValueError("当前没有加载任何账号")
        if not server or not character_name:
            raise ValueError("服务器名和角色名不能为空")
        chars = self._account_data.setdefault("characters", {})
        server_node = chars.setdefault(server, {})
        if character_name in server_node:
            raise ValueError(f"角色 '{server}/{character_name}' 已存在")
        server_node[character_name] = {"tasks": {}, "status": {}, "game_profession": DEFAULT_GAME_PROFESSION}
        if self._mgr.current_acc:
            self._mgr.current_acc.rebind_characters()
        self._save_account_file()
        logger.info("已添加角色: %s/%s", server, character_name)

    def delete_character(self, server: str, character_name: str) -> None:
        if not self.current_account():
            raise ValueError("当前没有加载任何账号")
        ac = self.active_character()
        if ac.get("server") == server and ac.get("name") == character_name:
            raise ValueError("不能删除当前正在使用的角色")
        chars = self._account_data.get("characters", {})
        server_node = chars.get(server, {})
        if character_name not in server_node:
            raise KeyError(f"角色 '{server}/{character_name}' 不存在")
        del server_node[character_name]
        if not server_node:
            del chars[server]
        if self._mgr.current_acc:
            self._mgr.current_acc.rebind_characters()
        self._save_account_file()
        logger.info("已删除角色: %s/%s", server, character_name)

    def __str__(self):
        return json.dumps(self._config, ensure_ascii=False, indent=4)


cfg_manager = ConfigManager()
cfg = AutoConfig()
cfg.load_config()
atexit.register(lambda: cfg.save_config(quiet=True))
