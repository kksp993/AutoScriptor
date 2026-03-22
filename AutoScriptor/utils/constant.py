import atexit
import copy
import datetime
import getpass
import glob
import os
import json
import shutil

from AutoScriptor.utils.logger import logger
from AutoScriptor.crypto.config_manager import ConfigManager

class AutoConfig:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not hasattr(self, '_initialized'):
            self.CONFIG_PATH = os.path.join(os.getcwd(), "config.json")
            self._initialized = True
    
    def load_config(self, pwd=""):
        """加载配置文件"""
            # 加载其他非敏感配置
        with open(self.CONFIG_PATH, 'r', encoding='utf-8') as f:
            self._config = loaded_config = json.load(f)
            self._update_dict(self._config, loaded_config)
        config_manager = ConfigManager(self.CONFIG_PATH)
        decrypted_data = config_manager.decrypt_config(pwd)
        
        self._config['game']={}
        if decrypted_data:
            self._config['game']['account'] = decrypted_data.get('account', '')
            self._config['game']['password'] = decrypted_data.get('password', '')
            self._config['game']['character_name'] = decrypted_data.get('character_name',"")
        cfg["year"]=datetime.datetime.now().year
        cfg["month"]=datetime.datetime.now().month
        cfg["day"]=datetime.datetime.now().day
        cfg["weekday"]=datetime.datetime.now().weekday()+1


    def _update_dict(self, d, u):
        """递归更新字典"""
        for k, v in u.items():
            if isinstance(v, dict) and k in d:
                self._update_dict(d[k], v)
            else:
                d[k] = v
    
    def save_config(self):
        """保存配置到文件，并同步到当前档案文件"""
        os.makedirs(os.path.dirname(self.CONFIG_PATH), exist_ok=True)
        safe_config = copy.deepcopy(self._config)
        rkeys = ["game","year","month","day","weekday"]
        for key in rkeys:
            safe_config.pop(key, None)
        
        if 'tasks' in safe_config and isinstance(safe_config['tasks'], dict):
            self._clean_tasks_for_saving(safe_config['tasks'])

        safe_config.pop("profiles", None)
        
        with open(self.CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(safe_config, f, ensure_ascii=False, indent=4)

        self._sync_to_profile()

    def _sync_to_profile(self):
        """将 config.json 同步回当前档案文件（如果存在）"""
        try:
            profile_path = self._profile_path(self._config.get("current_profile", "default"))
            if os.path.exists(profile_path):
                shutil.copy2(self.CONFIG_PATH, profile_path)
        except Exception:
            pass

    def _clean_tasks_for_saving(self, data):
        """递归清理 tasks 字典中残留的不可序列化字段（防御性）。"""
        if isinstance(data, dict):
            data.pop('fn', None)
            data.pop('order', None)
            for key, value in data.items():
                self._clean_tasks_for_saving(value)

    # 添加 __setitem__ 方法以支持通过 cfg[...] 赋值
    def __setitem__(self, key, value):
        """支持通过 config["xxx"] = value 更新配置"""
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

    # 添加 __getitem__ 方法以支持通过 cfg[...] 获取值
    def __getitem__(self, key):
        """支持通过 config["xxx"] 或 config["xxx.yyy"] 获取配置"""
        if isinstance(key, str) and '.' in key:
            parts = key.split('.')
            value = self._config
            for part in parts:
                # 逐层深入字典查找
                value = value[part]
            return value
        else:
            return self._config[key]
    
    def get(self, key, default=None):
        """支持通过 cfg.get("xxx") 或 cfg.get("xxx.yyy", default) 获取配置，如果不存在则返回默认值"""
        try:
            logger.info(f"配置已获取: {key} = {self.__getitem__(key)}")
            return self.__getitem__(key)
        except (KeyError, TypeError):
            logger.info(f"配置未获取: {key} = {default}")
            return default
    
    def set(self, key, value):
        """支持通过 cfg.set("xxx", value) 或 cfg.set("xxx.yyy", value) 设置配置并自动保存
        如果键不存在，会自动创建所需的嵌套结构"""
        self.__setitem__(key, value)
        self.save_config()
        logger.info(f"配置已更新: {key} = {value}")
            
    # ── 多账号档案管理（文件级） ──

    def _profile_path(self, name: str) -> str:
        return os.path.join(os.path.dirname(self.CONFIG_PATH), f"config_{name}.json")

    def list_profiles(self) -> list:
        """扫描 config_*.json 文件，返回档案名列表"""
        pattern = os.path.join(os.path.dirname(self.CONFIG_PATH), "config_*.json")
        names = []
        for f in glob.glob(pattern):
            basename = os.path.basename(f)
            name = basename[7:-5]  # "config_xxx.json" → "xxx"
            if name:
                names.append(name)
        return sorted(names)

    def current_profile(self) -> str:
        return self._config.get("current_profile", "default")

    def switch_profile(self, target: str, security_key: str = ""):
        """切换档案：保存当前 → 复制目标到 config.json → 重新加载"""
        target_path = self._profile_path(target)
        if not os.path.exists(target_path):
            raise KeyError(f"档案 '{target}' 不存在")

        current = self.current_profile()
        self.save_config()
        shutil.copy2(self.CONFIG_PATH, self._profile_path(current))

        shutil.copy2(target_path, self.CONFIG_PATH)
        self.load_config(security_key)
        self._config["current_profile"] = target
        self.save_config()
        logger.info(f"已切换到档案: {target}")

    def add_profile(self, name: str, account: str, password: str,
                    character_name: str, security_key: str):
        """创建新档案文件：基于当前配置，使用新的账号数据加密"""
        safe_config = copy.deepcopy(self._config)
        for key in ("game", "year", "month", "day", "weekday", "profiles"):
            safe_config.pop(key, None)
        if "tasks" in safe_config and isinstance(safe_config["tasks"], dict):
            self._clean_tasks_for_saving(safe_config["tasks"])

        sensitive = {"account": account, "password": password, "character_name": character_name}
        safe_config["encryption"] = ConfigManager.encrypt_data(sensitive, security_key)
        safe_config["current_profile"] = name

        target_path = self._profile_path(name)
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(safe_config, f, ensure_ascii=False, indent=4)
        logger.info(f"已创建档案: {name}")

    def delete_profile(self, name: str):
        """删除档案文件"""
        if name == self.current_profile():
            raise ValueError("不能删除当前正在使用的档案")
        target_path = self._profile_path(name)
        if os.path.exists(target_path):
            os.remove(target_path)
            logger.info(f"已删除档案: {name}")

    def __str__(self):
        return json.dumps(self._config, ensure_ascii=False, indent=4)

# 创建全局单例配置实例
global cfg
cfg = AutoConfig()
cfg.load_config()

def _sync_on_exit():
    """程序退出时同步 config.json 到当前档案文件"""
    try:
        cfg.save_config()
    except Exception:
        pass

atexit.register(_sync_on_exit)
