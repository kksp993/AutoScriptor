import atexit
import copy
import datetime
import glob
import os
import json
import shutil

from AutoScriptor.utils.logger import logger
from AutoScriptor.crypto.config_manager import ConfigManager


# Keys that live only in memory, never serialized to config.json
_RUNTIME_KEYS = ("game", "year", "month", "day", "weekday", "profiles")

# Keys that belong to the global config.json (not per-account)
_GLOBAL_KEYS = (
    "app", "ocr", "emulator", "llm", "deploy", "notify",
    "update", "remote_access",
)


class AutoConfig:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, '_initialized'):
            self.CONFIG_PATH = os.path.join(os.getcwd(), "config.json")
            self.ACCOUNTS_DIR = os.path.join(os.path.dirname(self.CONFIG_PATH), "accounts")
            self._account_data = {}
            self._initialized = True

    # ── load / save ──

    def load_config(self, pwd=""):
        """Load global config + current account + active character."""
        with open(self.CONFIG_PATH, 'r', encoding='utf-8') as f:
            new_cfg = json.load(f)
        # 先补全默认键再一次性赋值，避免多线程下「已替换 _config 但尚未 setdefault」时 cfg['tasks'] 竞态 KeyError
        new_cfg.setdefault('tasks', {})
        new_cfg.setdefault('status', {})
        new_cfg.setdefault('game', {})
        self._config = new_cfg

        account_name = self._config.get("current_account", "")
        if account_name:
            self._load_account(account_name, pwd)

        self._config["year"] = datetime.datetime.now().year
        self._config["month"] = datetime.datetime.now().month
        self._config["day"] = datetime.datetime.now().day
        self._config["weekday"] = datetime.datetime.now().weekday() + 1

    def _load_account(self, name: str, pwd: str = ""):
        """Load an account file, decrypt credentials, and activate its current character."""
        path = self._account_path(name)
        if not os.path.exists(path):
            logger.warning(f"账号文件不存在: {path}")
            return

        with open(path, 'r', encoding='utf-8') as f:
            self._account_data = json.load(f)

        self._config['game'] = {}
        enc = self._account_data.get("encryption", {})
        if pwd and enc.get("encrypted_data"):
            try:
                decrypted = ConfigManager.decrypt_data(enc, pwd)
                self._config['game']['account'] = decrypted.get('account', '')
                self._config['game']['password'] = decrypted.get('password', '')
            except Exception as e:
                logger.error(f"解密账号失败: {e}")

        ac = self._account_data.get("active_character", {})
        server = ac.get("server", "")
        char_name = ac.get("name", "")
        self._config['game']['character_name'] = char_name

        chars = self._account_data.get("characters", {})
        char_node = chars.get(server, {}).get(char_name, {})
        self._config['tasks'] = char_node.get("tasks", {})
        self._config['status'] = char_node.get("status", {})

    def save_config(self):
        """Save global settings to config.json and character data back to account file."""
        os.makedirs(os.path.dirname(self.CONFIG_PATH), exist_ok=True)

        self._sync_character_to_account()

        safe_config = {}
        for k in _GLOBAL_KEYS:
            if k in self._config:
                safe_config[k] = copy.deepcopy(self._config[k])
        safe_config["current_account"] = self._config.get("current_account", "")

        with open(self.CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(safe_config, f, ensure_ascii=False, indent=4)

        self._save_account_file()

    def _sync_character_to_account(self):
        """Write current character's tasks/status back into account_data."""
        account_name = self._config.get("current_account", "")
        if not account_name or not self._account_data:
            return
        ac = self._account_data.get("active_character", {})
        server = ac.get("server", "")
        char_name = ac.get("name", "")
        if not server or not char_name:
            return

        chars = self._account_data.setdefault("characters", {})
        server_node = chars.setdefault(server, {})
        char_node = server_node.setdefault(char_name, {})

        tasks_copy = copy.deepcopy(self._config.get("tasks", {}))
        self._clean_tasks_for_saving(tasks_copy)
        char_node["tasks"] = tasks_copy
        char_node["status"] = copy.deepcopy(self._config.get("status", {}))

    def _save_account_file(self):
        """Persist current account data to its JSON file."""
        account_name = self._config.get("current_account", "")
        if not account_name or not self._account_data:
            return
        try:
            os.makedirs(self.ACCOUNTS_DIR, exist_ok=True)
            path = self._account_path(account_name)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(self._account_data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            logger.error(f"保存账号文件失败: {e}")

    def _clean_tasks_for_saving(self, data):
        """递归清理 tasks 字典中残留的不可序列化字段（防御性）。"""
        if isinstance(data, dict):
            data.pop('fn', None)
            data.pop('order', None)
            for key, value in data.items():
                self._clean_tasks_for_saving(value)

    def _update_dict(self, d, u):
        """递归更新字典"""
        for k, v in u.items():
            if isinstance(v, dict) and k in d:
                self._update_dict(d[k], v)
            else:
                d[k] = v

    # ── dict-like access ──

    def __setitem__(self, key, value):
        if isinstance(key, str) and '.' in key:
            parts = key.split('.')
            cfg_dict = self._config
            for part in parts[:-1]:
                if part not in cfg_dict or not isinstance(cfg_dict[part], dict):
                    cfg_dict[part] = {}
                cfg_dict = cfg_dict[part]
            cfg_dict[parts[-1]] = value
        else:
            self._config[key] = value

    def __getitem__(self, key):
        if isinstance(key, str) and '.' in key:
            parts = key.split('.')
            value = self._config
            for part in parts:
                value = value[part]
            return value
        else:
            return self._config[key]

    def get(self, key, default=None):
        try:
            return self.__getitem__(key)
        except (KeyError, TypeError):
            return default

    def set(self, key, value):
        """Set a config value and auto-save."""
        self.__setitem__(key, value)
        self.save_config()
        logger.info(f"配置已更新: {key} = {value}")

    # ── account file helpers ──

    def _account_path(self, name: str) -> str:
        return os.path.join(self.ACCOUNTS_DIR, f"{name}.json")

    # ── account management ──

    def list_accounts(self) -> list:
        """Return sorted list of account names from accounts/ directory."""
        if not os.path.isdir(self.ACCOUNTS_DIR):
            return []
        names = []
        for f in os.listdir(self.ACCOUNTS_DIR):
            if f.endswith('.json'):
                names.append(f[:-5])
        return sorted(names)

    def current_account(self) -> str:
        return self._config.get("current_account", "")

    def active_character(self) -> dict:
        """Return {'server': ..., 'name': ...} for the active character."""
        return self._account_data.get("active_character", {})

    def list_characters(self) -> dict:
        """Return the full characters tree { server: { char: {...} } } for current account."""
        return self._account_data.get("characters", {})

    def switch_account(self, target: str, security_key: str = ""):
        """Switch to another account: save current, load target, decrypt."""
        target_path = self._account_path(target)
        if not os.path.exists(target_path):
            raise KeyError(f"账号 '{target}' 不存在")

        self.save_config()

        self._config["current_account"] = target
        self._load_account(target, security_key)

        self._config["year"] = datetime.datetime.now().year
        self._config["month"] = datetime.datetime.now().month
        self._config["day"] = datetime.datetime.now().day
        self._config["weekday"] = datetime.datetime.now().weekday() + 1

        self.save_config()
        logger.info(f"已切换到账号: {target}")

    def switch_character(self, server: str, character: str):
        """Switch to a different character within the current account (no password needed)."""
        account_name = self.current_account()
        if not account_name:
            raise ValueError("当前没有加载任何账号")

        chars = self._account_data.get("characters", {})
        if server not in chars or character not in chars[server]:
            raise KeyError(f"角色 '{server}/{character}' 不存在")

        self._sync_character_to_account()

        self._account_data["active_character"] = {"server": server, "name": character}

        char_node = chars[server][character]
        self._config['tasks'] = char_node.get("tasks", {})
        self._config['status'] = char_node.get("status", {})
        self._config['game']['character_name'] = character

        self.save_config()
        logger.info(f"已切换到角色: {server}/{character}")

    def add_account(self, name: str, account: str, password: str,
                    server: str, character_name: str, security_key: str):
        """Create a new account file with encrypted credentials and one initial character."""
        if not name:
            raise ValueError("账号名称不能为空")
        if os.path.exists(self._account_path(name)):
            raise ValueError(f"账号 '{name}' 已存在")

        sensitive = {"account": account, "password": password}
        encryption = ConfigManager.encrypt_data(sensitive, security_key)

        server = server or "默认服务器"
        character_name = character_name or "默认角色"

        account_data = {
            "encryption": encryption,
            "active_character": {"server": server, "name": character_name},
            "characters": {
                server: {
                    character_name: {
                        "tasks": {},
                        "status": {}
                    }
                }
            }
        }

        os.makedirs(self.ACCOUNTS_DIR, exist_ok=True)
        with open(self._account_path(name), "w", encoding="utf-8") as f:
            json.dump(account_data, f, ensure_ascii=False, indent=4)
        logger.info(f"已创建账号: {name}")

    def delete_account(self, name: str):
        """Delete an account file."""
        if name == self.current_account():
            raise ValueError("不能删除当前正在使用的账号")
        target_path = self._account_path(name)
        if os.path.exists(target_path):
            os.remove(target_path)
            logger.info(f"已删除账号: {name}")

    def add_character(self, server: str, character_name: str):
        """Add a new character under the current account."""
        if not self.current_account():
            raise ValueError("当前没有加载任何账号")
        if not server or not character_name:
            raise ValueError("服务器名和角色名不能为空")

        chars = self._account_data.setdefault("characters", {})
        server_node = chars.setdefault(server, {})
        if character_name in server_node:
            raise ValueError(f"角色 '{server}/{character_name}' 已存在")

        server_node[character_name] = {"tasks": {}, "status": {}}
        self._save_account_file()
        logger.info(f"已添加角色: {server}/{character_name}")

    def delete_character(self, server: str, character_name: str):
        """Delete a character from the current account."""
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

        self._save_account_file()
        logger.info(f"已删除角色: {server}/{character_name}")

    # ── legacy compatibility ──

    def current_profile(self) -> str:
        """Legacy alias for current_account()."""
        return self.current_account()

    def list_profiles(self) -> list:
        """Legacy alias for list_accounts()."""
        return self.list_accounts()

    # ── migration from old profile system ──

    def _migrate_old_profiles(self):
        """Auto-migrate old config_*.json profile files to accounts/ directory."""
        config_dir = os.path.dirname(self.CONFIG_PATH)
        pattern = os.path.join(config_dir, "config_*.json")
        old_files = glob.glob(pattern)
        if not old_files:
            return

        os.makedirs(self.ACCOUNTS_DIR, exist_ok=True)
        migrated = []

        for fpath in old_files:
            basename = os.path.basename(fpath)
            profile_name = basename[7:-5]  # "config_xxx.json" -> "xxx"
            if not profile_name:
                continue

            try:
                with open(fpath, 'r', encoding='utf-8') as f:
                    old_config = json.load(f)

                encryption = old_config.get("encryption", {})
                tasks = old_config.get("tasks", {})
                status = old_config.get("status", {})

                char_name = profile_name

                account_data = {
                    "encryption": encryption,
                    "active_character": {"server": "默认服务器", "name": char_name},
                    "characters": {
                        "默认服务器": {
                            char_name: {
                                "tasks": tasks,
                                "status": status,
                            }
                        }
                    }
                }

                dest = self._account_path(profile_name)
                if not os.path.exists(dest):
                    with open(dest, 'w', encoding='utf-8') as f:
                        json.dump(account_data, f, ensure_ascii=False, indent=4)

                backup_dir = os.path.join(config_dir, "_old_profiles_backup")
                os.makedirs(backup_dir, exist_ok=True)
                shutil.move(fpath, os.path.join(backup_dir, basename))
                migrated.append(profile_name)

            except Exception as e:
                logger.error(f"迁移档案 '{profile_name}' 失败: {e}")

        if migrated:
            logger.info(f"已迁移旧档案到 accounts/ 目录: {migrated}")

        old_profile = self._config.get("current_profile", "")
        if old_profile and not self._config.get("current_account"):
            if os.path.exists(self._account_path(old_profile)):
                self._config["current_account"] = old_profile
            self._config.pop("current_profile", None)

    # ── also migrate current config.json if it has old-style encryption+tasks ──

    def _migrate_current_config(self):
        """Migrate config.json data to an account file if not yet linked.

        Handles two cases:
        - Old-style config with encryption block (account+password+character_name encrypted)
        - Config with task data but no encryption (user hasn't set credentials yet)
        """
        if self._config.get("current_account"):
            return

        enc = self._config.get("encryption", {})
        tasks = self._config.get("tasks", {})
        status = self._config.get("status", {})

        has_encryption = bool(enc.get("encrypted_data"))
        has_data = bool(tasks)
        if not has_encryption and not has_data:
            return

        profile_name = self._config.get("current_profile", "default")
        char_name = profile_name

        account_data = {
            "encryption": enc if has_encryption else {},
            "active_character": {"server": "默认服务器", "name": char_name},
            "characters": {
                "默认服务器": {
                    char_name: {
                        "tasks": tasks,
                        "status": status,
                    }
                }
            }
        }

        os.makedirs(self.ACCOUNTS_DIR, exist_ok=True)
        dest = self._account_path(profile_name)
        if not os.path.exists(dest):
            with open(dest, 'w', encoding='utf-8') as f:
                json.dump(account_data, f, ensure_ascii=False, indent=4)

        self._config["current_account"] = profile_name
        self._config.pop("current_profile", None)
        self._config.pop("encryption", None)

        self._account_data = account_data
        logger.info(f"已迁移当前配置到账号: {profile_name}")

    def __str__(self):
        return json.dumps(self._config, ensure_ascii=False, indent=4)


# Create global singleton
global cfg
cfg = AutoConfig()

# First load to populate _config
cfg.load_config()

# Run migrations (they need _config to be loaded first)
cfg._migrate_old_profiles()
cfg._migrate_current_config()

# Reload if migrations changed things
if cfg._config.get("current_account") and not cfg._account_data:
    cfg.load_config()


def _sync_on_exit():
    """程序退出时同步数据"""
    try:
        cfg.save_config()
    except Exception:
        pass

atexit.register(_sync_on_exit)
