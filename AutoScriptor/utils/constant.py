import copy
import datetime
import getpass
import os
import json

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
        """保存配置到文件"""
        os.makedirs(os.path.dirname(self.CONFIG_PATH), exist_ok=True)
        safe_config = copy.deepcopy(self._config)
        rkeys = ["game","year","month","day","weekday"]
        for key in rkeys:
            safe_config.pop(key, None)
        
        # 如果副本中存在 'tasks' 字典，就对其进行清理
        if 'tasks' in safe_config and isinstance(safe_config['tasks'], dict):
            self._clean_tasks_for_saving(safe_config['tasks'])
        
        with open(self.CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(safe_config, f, ensure_ascii=False, indent=4)

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
            
    # ── 多账号档案管理 ──

    def list_profiles(self) -> list:
        """返回所有档案名称列表"""
        profiles = self._config.get("profiles", {})
        return list(profiles.get("list", {}).keys())

    def current_profile(self) -> str:
        return self._config.get("profiles", {}).get("current", "default")

    def switch_profile(self, name: str):
        """切换当前档案，将档案字段写入 game 段"""
        profiles = self._config.get("profiles", {}).get("list", {})
        if name not in profiles:
            raise KeyError(f"档案 '{name}' 不存在")
        profile = profiles[name]
        if "game" not in self._config:
            self._config["game"] = {}
        for k in ("account", "password", "character_name", "character_index"):
            if k in profile:
                self._config["game"][k] = profile[k]
        self._config["profiles"]["current"] = name
        self.save_config()
        logger.info(f"已切换到档案: {name}")

    def add_profile(self, name: str, data: dict):
        """新建档案"""
        if "profiles" not in self._config:
            self._config["profiles"] = {"current": "default", "list": {}}
        self._config["profiles"]["list"][name] = data
        self.save_config()

    def delete_profile(self, name: str):
        """删除档案"""
        profiles = self._config.get("profiles", {}).get("list", {})
        if name in profiles:
            del profiles[name]
            if self._config.get("profiles", {}).get("current") == name:
                self._config["profiles"]["current"] = next(iter(profiles), "default")
            self.save_config()

    def __str__(self):
        return json.dumps(self._config, ensure_ascii=False, indent=4)

# 创建全局单例配置实例
global cfg
cfg = AutoConfig()
cfg.load_config()
