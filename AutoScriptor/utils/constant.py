import copy
import datetime
import getpass
import os
import json
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
        """
        2. 新增的辅助方法：递归清理 tasks 字典。
        它会遍历所有嵌套的字典，并从中删除 'fn' 键。
        """
        # 如果当前数据是字典
        if isinstance(data, dict):
            # 关键：先删除当前层的 'fn'，因为它不会有子节点
            data.pop('fn', None)
            data.pop('order', None)
            # 然后，对自己所有的子节点（value）递归调用此函数
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
            
    def __str__(self):
        return json.dumps(self._config, ensure_ascii=False, indent=4)

# 创建全局单例配置实例
global cfg
cfg = AutoConfig()
cfg.load_config()
