"""通用配置（data/config.json）读写层。

只负责通用配置段：app / ocr / emulator / deploy / notify / update /
task_ordering / accounts / news，以及同目录临时文件 + 原子替换的持久化。

``_GLOBAL_KEYS`` 决定哪些顶层段会被写回，因此模板里存在的段必须同时登记在这里，
否则用户设置会在下一次保存时被静默丢弃。

账号与角色数据不在本层定义；运行时通过 ``set_account_backend()`` 注入实现。
没有注册 backend 时，账号相关查询返回空值、写入方法明确报错，不会伪装成功。
"""
from __future__ import annotations

import atexit
import copy
import datetime
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Protocol

from AutoScriptor.logging.logger import logger
from AutoScriptor.utils.json_io import write_json_atomic


_GLOBAL_KEYS = (
    "app", "ocr", "emulator", "deploy", "notify",
    "update", "task_ordering", "accounts", "news",
)

# 曾经属于全局配置、现在已经没有功能的段。加载时直接丢弃：保存路径只写
# ``_GLOBAL_KEYS``，所以文件里不会再有它们，但旧 config.json 会一直带着，
# 留在内存里只会让 WebUI 公开配置多出一个空壳段。
# ``scheduler`` 里只有 ``auto_start``，而它从未接通过：启动时要求账号已解密，
# 而刚启动必然未解密；等到用户在 WebUI 输密码时，那条路径又刻意不激活调度
# （见 test_account_verify_does_not_start_scheduler）。所以它是个不起作用的
# 死开关，整段退役；调度的启停仍由 WebUI 的运行/停止按钮负责。
_RETIRED_GLOBAL_KEYS = ("remote_access", "scheduler")


# The atomic writer lives in a module with no import-time side effects, so a
# script that only needs to write JSON never triggers a config load. Kept as a
# private alias here because the manager below writes through it.
_atomic_write_json = write_json_atomic


class AccountBackend(Protocol):
    """账号域注入契约。

    AutoScriptor 只依赖这些原语；谁来实现、账号文件长什么样，都由调用方决定。
    编排（切账号、存盘顺序等）留在 ``AutoConfig``，backend 只提供原子操作。
    """

    default_accounts_dir: Path

    def normalize_accounts_dir(self, global_cfg: dict[str, Any]) -> None: ...

    def resolved_accounts_dir(self, global_cfg: dict[str, Any]) -> Path: ...

    def account_path(self, name: str, global_cfg: dict[str, Any]) -> Path: ...

    def load_account(self, name: str, pwd: str, global_cfg: dict[str, Any], writer) -> None: ...

    def save(self, flat: dict[str, Any], global_cfg: dict[str, Any], writer) -> None: ...

    def save_account_file(self, global_cfg: dict[str, Any], writer) -> None: ...

    def flat_overlay(self) -> dict[str, Any]: ...

    @property
    def account_data(self) -> dict[str, Any]: ...

    def list_accounts(self, global_cfg: dict[str, Any]) -> list[str]: ...

    def read_character_names(self, name: str, global_cfg: dict[str, Any]) -> dict[str, Any]: ...

    def verify_security_key(self, name: str, security_key: str, global_cfg: dict[str, Any]) -> bool: ...

    def add_account(
        self, name: str, account: str, password: str, server: str,
        character_name: str, security_key: str, global_cfg: dict[str, Any], writer,
    ) -> None: ...

    def delete_account(self, name: str, current_account: str, global_cfg: dict[str, Any]) -> None: ...

    def update_credentials(self, account: str, password: str, security_key: str, saver) -> None: ...

    def switch_character(self, server: str, character: str) -> None: ...

    def set_character_game_profession(self, server: str, character: str, profession: str) -> None: ...

    def add_character(self, server: str, character_name: str) -> None: ...

    def delete_character(self, server: str, character_name: str) -> None: ...

    def rebind_characters(self) -> None: ...

    def restore_credentials(self, credentials: dict[str, Any] | None) -> None: ...

    def clear_credentials(self) -> None: ...

    def current_credentials(self) -> dict[str, Any]: ...


_account_backend: AccountBackend | None = None


def set_account_backend(backend: AccountBackend | None) -> None:
    """Register the account-domain implementation.

    Re-loads config so an already-initialized ``cfg`` picks up the new backend.
    """
    global _account_backend
    if _account_backend is backend:
        return
    _account_backend = backend
    if cfg._initialized:
        cfg.load_config()


def get_account_backend() -> AccountBackend | None:
    return _account_backend


def _require_backend(action: str) -> AccountBackend:
    if _account_backend is None:
        raise RuntimeError(
            f"账号功能需要注册 account backend 才能使用（{action}）；"
            "运行时请确认已调用 set_account_backend()。"
        )
    return _account_backend


# 曾经叫 ``max_retry``（重试次数）。语义换成「最多尝试几次」后，同一个数字的含义
# 从「失败后再来几次」变成「总共跑几次」，直接复用会让每个任务都少跑一遍，所以按
# ``attempts = retry + 1`` 换算一次，然后丢掉旧键。
_RENAMED_APP_KEYS = {"max_retry": "max_attempts"}


class ConfigManager:
    """全局配置的读写；账号域通过 backend 委托。"""

    _instance: "ConfigManager | None" = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized"):
            return
        from AutoScriptor.utils.paths import get_config_path

        self._config_path: Path = Path(get_config_path())
        self.data_root: Path = self._config_path.parent
        self.global_cfg: dict[str, Any] = {}
        self._initialized = True

    # ── 路径 ──

    @property
    def config_path(self) -> Path:
        return self._config_path

    @config_path.setter
    def config_path(self, p: Path | str) -> None:
        self._config_path = Path(p)

    @property
    def default_accounts_dir(self) -> Path:
        if _account_backend is not None:
            return _account_backend.default_accounts_dir
        from AutoScriptor.utils.paths import get_config_path

        return Path(get_config_path()).parent / "accounts"

    @default_accounts_dir.setter
    def default_accounts_dir(self, p: Path | str) -> None:
        if _account_backend is not None:
            _account_backend.default_accounts_dir = Path(p)

    @property
    def current_acc(self):
        return getattr(_account_backend, "current_acc", None) if _account_backend else None

    @current_acc.setter
    def current_acc(self, value) -> None:
        if _account_backend is not None:
            _account_backend.current_acc = value

    def resolved_accounts_dir(self) -> Path:
        if _account_backend is not None:
            return _account_backend.resolved_accounts_dir(self.global_cfg)
        return self.default_accounts_dir

    # ── 全局配置 ──

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

    def _migrate_renamed_app_keys(self) -> None:
        """把 ``app`` 段里改过名字的键换算过来，并清掉旧键。

        ``max_retry``（重试次数）→ ``max_attempts``（最多尝试几次）：同一个数字的含义
        变了，所以必须 ``attempts = retry + 1`` 换算；直接沿用会让每个任务少跑一遍。
        新键已经存在时不覆盖——那说明配置已经迁过，旧键只是残留。
        """
        app = self.global_cfg.get("app")
        if not isinstance(app, dict):
            return
        for old_key, new_key in _RENAMED_APP_KEYS.items():
            if old_key not in app:
                continue
            legacy = app.pop(old_key)
            if new_key in app:
                continue
            try:
                app[new_key] = max(1, int(legacy) + 1)
            except (TypeError, ValueError):
                continue
            logger.info(
                "配置已迁移: app.%s=%s → app.%s=%s（语义从「重试次数」改为「最多尝试次数」）",
                old_key, legacy, new_key, app[new_key],
            )

    def load_global(self) -> None:
        if not self.config_path.exists():
            self.global_cfg = self._load_default_global_config()
        else:
            with open(self.config_path, "r", encoding="utf-8-sig") as f:
                self.global_cfg = json.load(f)
            # 改名迁移必须在合并模板默认值**之前**：模板里已经有 max_attempts 的默认值，
            # 先合并会让它看起来像「用户已经设过了」，迁移就此跳过，旧数字被模板值吞掉
            # （max_retry=0 本该是 1 次，结果变成模板的 3 次）。
            self._migrate_renamed_app_keys()
            self._merge_global_defaults()
        for retired_key in _RETIRED_GLOBAL_KEYS:
            self.global_cfg.pop(retired_key, None)
        self.global_cfg.setdefault("tasks", {})
        self.global_cfg.setdefault("status", {})
        self.global_cfg.setdefault("game", {})
        self.global_cfg.setdefault("accounts", {})
        self.global_cfg["accounts"].setdefault("dir", "")
        self.global_cfg.setdefault("ocr", {})
        self.global_cfg["ocr"].setdefault("use_gpu", False)
        if _account_backend is not None:
            _account_backend.normalize_accounts_dir(self.global_cfg)

    def _update_runtime_dates(self) -> None:
        self.global_cfg.update(self._runtime_dates())

    @staticmethod
    def _runtime_dates() -> dict[str, int]:
        """Today's date, for the flat config view only.

        The date block is deliberately never persisted: ``_GLOBAL_KEYS`` does not
        list it, so a saved file cannot carry a stale calendar into the next run.
        """
        now = datetime.datetime.now()
        return {
            "year": now.year,
            "month": now.month,
            "day": now.day,
            "weekday": now.weekday() + 1,
        }

    def _persistable_global_config(self) -> dict[str, Any]:
        safe_cfg = {k: self.global_cfg.get(k, {}) for k in _GLOBAL_KEYS}
        safe_cfg["current_account"] = self.global_cfg.get("current_account", "")
        return safe_cfg

    def persist_global(self) -> None:
        _atomic_write_json(self.config_path, self._persistable_global_config())

    # ── 账号文件（委托 backend）──

    def load_account(self, name: str, pwd: str = "") -> None:
        if _account_backend is None:
            return
        _account_backend.load_account(name, pwd, self.global_cfg, write_json_atomic)

    def load_accounts(self, name: str, pwd: str = "") -> None:
        if name:
            self.load_account(name, pwd)
        elif _account_backend is not None:
            _account_backend.current_acc = None

    def save_account_file_only(self) -> None:
        if _account_backend is None:
            return
        _account_backend.save_account_file(self.global_cfg, write_json_atomic)

    def save_all(self, flat: dict[str, Any]) -> None:
        for k in _GLOBAL_KEYS:
            if k in flat:
                self.global_cfg[k] = copy.deepcopy(flat[k])
        self.global_cfg["current_account"] = flat.get(
            "current_account", self.global_cfg.get("current_account", "")
        )
        self._update_runtime_dates()
        if _account_backend is not None:
            _account_backend.save(flat, self.global_cfg, write_json_atomic)
        self.persist_global()

    def save_global_only(self, flat: dict[str, Any]) -> None:
        for k in _GLOBAL_KEYS:
            if k in flat:
                self.global_cfg[k] = copy.deepcopy(flat[k])
        self.global_cfg["current_account"] = flat.get(
            "current_account", self.global_cfg.get("current_account", "")
        )
        self._update_runtime_dates()
        self.persist_global()


class AutoConfig:
    _instance: "AutoConfig | None" = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized"):
            return
        from AutoScriptor.utils.paths import get_config_path

        self.CONFIG_PATH = str(get_config_path())
        self._mgr = cfg_manager
        self._config: dict[str, Any] = {}
        self._initialized = True

    # ── 账号域只读 ──

    @property
    def ACCOUNTS_DIR(self) -> str:
        """Resolved account directory; empty string when no backend is registered."""
        if _account_backend is None:
            return ""
        return str(_account_backend.resolved_accounts_dir(self._mgr.global_cfg))

    @ACCOUNTS_DIR.setter
    def ACCOUNTS_DIR(self, value: str) -> None:
        if _account_backend is not None:
            _account_backend.default_accounts_dir = Path(value)

    @property
    def _account_data(self) -> dict[str, Any]:
        if _account_backend is None:
            return {}
        return _account_backend.account_data

    def _account_path(self, name: str) -> str:
        if _account_backend is None:
            raise RuntimeError("账号功能需要注册 account backend 才能使用")
        return str(_account_backend.account_path(name, self._mgr.global_cfg))

    def _refresh_flat_config(self) -> None:
        """Rebuild the flat view. This is the only place ``_config`` is assigned.

        The runtime date block is applied here rather than left to whoever last
        saved, so read-only consumers (task code checking ``cfg["weekday"]``) get
        a valid calendar immediately after load, not only once some later save
        happened to run first.
        """
        flat = copy.deepcopy(self._mgr.global_cfg)
        flat.update(self._mgr._runtime_dates())
        if _account_backend is not None:
            flat.update(_account_backend.flat_overlay())
        else:
            flat.setdefault("tasks", {})
            flat.setdefault("status", {})
            flat.setdefault("game", {})
        self._config = flat

    # ── 生命周期 ──

    def load_config(self, pwd: str = "") -> None:
        self._mgr.config_path = Path(self.CONFIG_PATH)
        self._mgr.load_global()
        acc_name = self._mgr.global_cfg.get("current_account", "")
        self._mgr.load_accounts(acc_name, pwd)
        self._refresh_flat_config()

    def reload_preserving_decrypted_credentials(self, pwd: str = "") -> None:
        current_account = self.current_account()
        saved_credentials = None
        if not pwd and _account_backend is not None:
            saved_credentials = _account_backend.current_credentials()
        self.load_config(pwd)
        if not pwd and saved_credentials and self.current_account() == current_account:
            if _account_backend is not None:
                _account_backend.restore_credentials(saved_credentials)
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

    # ── 凭据 ──

    def update_current_account_credentials(self, account: str, password: str, security_key: str) -> None:
        backend = _require_backend("更新账号凭据")
        backend.update_credentials(account, password, security_key, self._save_account_file)

    def has_encrypted_credentials(self) -> bool:
        return bool((self._account_data.get("encryption") or {}).get("encrypted_data"))

    def has_decrypted_credentials(self) -> bool:
        game = self._config.get("game") or {}
        return bool(game.get("account") and game.get("password"))

    def clear_decrypted_credentials(self) -> None:
        """Clear in-memory plaintext credentials without touching encrypted account data."""
        if _account_backend is not None:
            _account_backend.clear_credentials()
        game = self._config.setdefault("game", {})
        game.pop("account", None)
        game.pop("password", None)

    def verify_account_security_key(self, name: str, security_key: str) -> bool:
        """Return whether the security key can decrypt the named account credentials."""
        if _account_backend is None:
            return False
        return _account_backend.verify_security_key(name, security_key, self._mgr.global_cfg)

    # ── 通用读写 ──

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

    # ── 账号域（委托）──

    def list_accounts(self) -> list[str]:
        if _account_backend is None:
            return []
        return _account_backend.list_accounts(self._mgr.global_cfg)

    def current_account(self) -> str:
        return self._config.get("current_account", "")

    def active_character(self) -> dict[str, Any]:
        return self._account_data.get("active_character", {})

    def list_characters(self) -> dict[str, Any]:
        return self._account_data.get("characters", {})

    def account_character_names(self, name: str) -> dict[str, Any]:
        """某账号的角色名单。当前账号直接取内存，其它账号交给账号域只读读取。"""
        if name == self.current_account():
            return self._account_data.get("characters", {}) or {}
        backend = _require_backend("读取账号角色名单")
        return backend.read_character_names(name, self._mgr.global_cfg)

    def switch_account(self, target: str, security_key: str = "") -> None:
        backend = _require_backend("切换账号")
        if not backend.account_path(target, self._mgr.global_cfg).exists():
            raise KeyError(f"账号 '{target}' 不存在")
        self.save_config()
        self._mgr.global_cfg["current_account"] = target
        backend.load_account(target, security_key, self._mgr.global_cfg, write_json_atomic)
        self._mgr._update_runtime_dates()
        self._refresh_flat_config()
        self.save_config()
        logger.info("已切换到账号: %s", target)

    def switch_character(self, server: str, character: str) -> None:
        backend = _require_backend("切换角色")
        if not self.current_account():
            raise ValueError("当前没有加载任何账号")
        chars = self._account_data.get("characters", {})
        if server not in chars or character not in chars[server]:
            raise KeyError(f"角色 '{server}/{character}' 不存在")
        backend.switch_character(server, character)
        self._refresh_flat_config()
        self.save_config()
        logger.info("已切换到角色: %s/%s", server, character)

    def set_character_game_profession(self, server: str, character: str, profession: str) -> None:
        backend = _require_backend("设置游戏职业")
        if not self.current_account():
            raise ValueError("当前没有加载任何账号")
        backend.set_character_game_profession(server, character, profession)
        if (self.active_character().get("server") == server
                and self.active_character().get("name") == character):
            self._config.setdefault("game", {})["game_profession"] = profession
        self._save_account_file()

    def add_account(
        self, name: str, account: str, password: str,
        server: str, character_name: str, security_key: str,
    ) -> None:
        backend = _require_backend("新增账号")
        backend.add_account(
            name, account, password, server, character_name, security_key,
            self._mgr.global_cfg, write_json_atomic,
        )

    def delete_account(self, name: str) -> None:
        backend = _require_backend("删除账号")
        backend.delete_account(name, self.current_account(), self._mgr.global_cfg)

    def add_character(self, server: str, character_name: str) -> None:
        backend = _require_backend("添加角色")
        if not self.current_account():
            raise ValueError("当前没有加载任何账号")
        backend.add_character(server, character_name)
        self._save_account_file()

    def delete_character(self, server: str, character_name: str) -> None:
        backend = _require_backend("删除角色")
        if not self.current_account():
            raise ValueError("当前没有加载任何账号")
        if (self.active_character().get("server") == server
                and self.active_character().get("name") == character_name):
            raise ValueError("不能删除当前正在使用的角色")
        backend.delete_character(server, character_name)
        self._save_account_file()

    def __str__(self):
        return json.dumps(self._config, ensure_ascii=False, indent=4)


cfg_manager = ConfigManager()
cfg = AutoConfig()
cfg.load_config()
atexit.register(lambda: cfg.save_config(quiet=True))
