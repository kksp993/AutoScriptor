"""账号 / 角色 / 凭据存储（游戏业务层）。

拥有 ``data/accounts/*.json``：角色树、每个角色的 ``tasks``/``status``、加密凭据、
跨角色调度队列。通过 ``AutoScriptor.utils.app_config.set_account_backend()`` 注册进
通用配置层，因此 AutoScriptor 自身**不导入 ZmxyOL**。

通用配置（``data/config.json`` 的 app/ocr/emulator/... 段）由 AutoScriptor 负责；
本模块只负责账号域，并在需要时把账号数据叠加进拍平配置。
"""
from __future__ import annotations

import copy
import datetime
import json
import os
import shutil
from pathlib import Path
from typing import Any

from AutoScriptor.logging.logger import logger
from ZmxyOL.paths import get_accounts_dir, get_editable_data_root
from ZmxyOL.crypto.config_manager import ConfigManager as CryptoConfigManager
from ZmxyOL.game_profession import DEFAULT_GAME_PROFESSION, normalize_game_profession


_DECRYPT_ERRORS = getattr(
    CryptoConfigManager,
    "DECRYPT_ERRORS",
    (KeyError, TypeError, ValueError),
)
_SECURITY_KEY_CHECK_ERRORS = (OSError, AttributeError) + _DECRYPT_ERRORS

# 测试任务路径：不得写进真实账号/全局配置，避免开发期任务树外泄到运行时数据。
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


class AccountStore:
    """账号域实现；由 AutoConfig 通过 backend 契约调用。"""

    def __init__(self) -> None:
        self.data_root = Path(get_editable_data_root())
        self.default_accounts_dir = Path(get_accounts_dir())
        self.current_acc: Account | None = None

    # ── 目录 ──

    @staticmethod
    def _is_under_path(child: Path, parent: Path) -> bool:
        try:
            child.resolve().relative_to(parent.resolve())
            return True
        except (OSError, ValueError):
            return False

    def _force_default_accounts_dir(self) -> bool:
        return bool(os.environ.get("AUTOSCRIPTOR_DATA_DIR"))

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

    def normalize_accounts_dir(self, global_cfg: dict[str, Any]) -> None:
        accounts = global_cfg.setdefault("accounts", {})
        raw = str((accounts or {}).get("dir") or "").strip()
        if not raw:
            return
        p = Path(raw)
        if p.is_absolute() and self._force_default_accounts_dir() and not self._is_under_path(p, self.data_root):
            self._migrate_external_accounts_dir(p)
            accounts["dir"] = ""
            logger.warning("账号目录已切回 dataRoot/accounts: %s -> %s", p, self.default_accounts_dir)

    def resolved_accounts_dir(self, global_cfg: dict[str, Any]) -> Path:
        raw = (global_cfg.get("accounts") or {}).get("dir") or ""
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

    def account_path(self, name: str, global_cfg: dict[str, Any]) -> Path:
        return self.resolved_accounts_dir(global_cfg) / f"{name}.json"

    # ── 账号文件 ──

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

    def load_account(self, name: str, pwd: str, global_cfg: dict[str, Any], writer) -> None:
        acc_dir = self.resolved_accounts_dir(global_cfg)
        path = acc_dir / f"{name}.json"
        if not path.exists():
            acc_dir.mkdir(parents=True, exist_ok=True)
            writer(path, self._default_account_payload(name))
            logger.info("已创建默认账号文件: %s", path)
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        self.current_acc = Account(name, data)
        self.current_acc.decrypt_credentials(pwd)

    def load(self, name: str, pwd: str, global_cfg: dict[str, Any], writer) -> None:
        if name:
            self.load_account(name, pwd, global_cfg, writer)
        else:
            self.current_acc = None

    def save_account_file(self, global_cfg: dict[str, Any], writer) -> None:
        if not self.current_acc:
            return
        self.current_acc.prepare_for_save(None)
        _assert_no_testing_tasks_in_account(self.current_acc.root)
        acc_dir = self.resolved_accounts_dir(global_cfg)
        writer(acc_dir / f"{self.current_acc.account_name}.json", self.current_acc.to_persist_dict())

    def save(self, flat: dict[str, Any], global_cfg: dict[str, Any], writer) -> None:
        _assert_no_testing_tasks_in_production(flat)
        if self.current_acc:
            self.current_acc.prepare_for_save(flat)
            _assert_no_testing_tasks_in_account(self.current_acc.root)
            acc_dir = self.resolved_accounts_dir(global_cfg)
            writer(acc_dir / f"{self.current_acc.account_name}.json", self.current_acc.to_persist_dict())

    # ── 叠加 ──

    @property
    def account_data(self) -> dict[str, Any]:
        return self.current_acc.root if self.current_acc else {}

    def flat_overlay(self) -> dict[str, Any]:
        char = self.current_acc.get_active_character() if self.current_acc else None
        if self.current_acc and char:
            return {
                "tasks": char.tasks,
                "status": char.status,
                "game": {
                    **self.current_acc.credentials,
                    "character_name": char.name,
                    "server_name": char.server,
                    "game_profession": char.profession,
                },
            }
        return {"tasks": {}, "status": {}, "game": {}}

    # ── 查询 ──

    def list_accounts(self, global_cfg: dict[str, Any]) -> list[str]:
        acc_dir = self.resolved_accounts_dir(global_cfg)
        if not acc_dir.is_dir():
            return []
        return sorted(f[:-5] for f in os.listdir(acc_dir) if f.endswith(".json"))

    def verify_security_key(self, name: str, security_key: str, global_cfg: dict[str, Any]) -> bool:
        name = (name or "").strip()
        security_key = (security_key or "").strip()
        if not name or not security_key:
            return False
        path = self.account_path(name, global_cfg)
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

    # ── 写入 ──

    def switch_account(self, target: str, security_key: str, global_cfg: dict[str, Any], writer) -> None:
        if not self.account_path(target, global_cfg).exists():
            raise KeyError(f"账号 '{target}' 不存在")
        global_cfg["current_account"] = target
        self.load_account(target, security_key, global_cfg, writer)
        logger.info("已切换到账号: %s", target)

    def add_account(
        self,
        name: str,
        account: str,
        password: str,
        server: str,
        character_name: str,
        security_key: str,
        global_cfg: dict[str, Any],
        writer,
    ) -> None:
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
        path = self.account_path(name, global_cfg)
        if os.path.exists(path):
            raise ValueError(f"账号 '{name}' 已存在")
        enc = CryptoConfigManager.encrypt_data(
            {"account": account, "password": password}, security_key
        )
        account_data = {
            "encryption": enc,
            "active_character": {"server": server, "name": character_name},
            "characters": {
                server: {
                    character_name: {
                        "tasks": {},
                        "status": {},
                        "game_profession": DEFAULT_GAME_PROFESSION,
                    }
                }
            },
        }
        writer(path, account_data)
        logger.info("已创建账号: %s", name)

    def delete_account(self, name: str, current_account: str, global_cfg: dict[str, Any]) -> None:
        if name == current_account:
            raise ValueError("不能删除当前正在使用的账号")
        path = self.account_path(name, global_cfg)
        if os.path.exists(path):
            os.remove(path)
            logger.info("已删除账号: %s", name)

    def update_credentials(self, account: str, password: str, security_key: str, saver) -> None:
        self.account_data["encryption"] = CryptoConfigManager.encrypt_data(
            {"account": account, "password": password}, security_key
        )
        saver()

    def rebind_characters(self) -> None:
        if self.current_acc:
            self.current_acc.rebind_characters()

    def switch_character(self, server: str, character: str) -> None:
        acc = self.current_acc
        if acc is None:
            raise ValueError("当前没有加载任何账号")
        acc.active_info = {"server": server, "name": character}

    def set_character_game_profession(self, server: str, character: str, profession: str) -> None:
        chars = self.account_data.get("characters", {})
        if server not in chars or character not in chars[server]:
            raise KeyError(f"角色 '{server}/{character}' 不存在")
        chars[server][character]["game_profession"] = normalize_game_profession(profession)

    def add_character(self, server: str, character_name: str) -> None:
        server = (server or "").strip()
        character_name = (character_name or "").strip()
        if not server or not character_name:
            raise ValueError("服务器名和角色名不能为空")
        chars = self.account_data.setdefault("characters", {})
        server_node = chars.setdefault(server, {})
        if character_name in server_node:
            raise ValueError(f"角色 '{server}/{character_name}' 已存在")
        server_node[character_name] = {
            "tasks": {},
            "status": {},
            "game_profession": DEFAULT_GAME_PROFESSION,
        }
        self.rebind_characters()
        logger.info("已添加角色: %s/%s", server, character_name)

    def delete_character(self, server: str, character_name: str) -> None:
        chars = self.account_data.get("characters", {})
        server_node = chars.get(server, {})
        if character_name not in server_node:
            raise KeyError(f"角色 '{server}/{character_name}' 不存在")
        del server_node[character_name]
        if not server_node:
            del chars[server]
        self.rebind_characters()
        logger.info("已删除角色: %s/%s", server, character_name)

    def restore_credentials(self, credentials: dict[str, Any] | None) -> None:
        if self.current_acc:
            self.current_acc.restore_credentials(credentials)

    def clear_credentials(self) -> None:
        if self.current_acc:
            self.current_acc.credentials = {"account": "", "password": ""}

    def current_credentials(self) -> dict[str, Any]:
        return copy.deepcopy(self.current_acc.credentials) if self.current_acc else {}


account_store = AccountStore()


def _register_backend() -> None:
    """Attach this account domain to the generic config layer."""
    from AutoScriptor.utils.app_config import set_account_backend

    set_account_backend(account_store)


_register_backend()
