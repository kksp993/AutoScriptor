"""
新的导航系统
基于图论的动态导航，支持env.loc概念
"""

from .map_manager import MapManager, Loc, Env, mm, path 
from .api import ensure_in, try_close_via_x
from .envs import *

__all__ = [
    # 核心类
    'MapManager',
    'Loc', 
    'Env',
    
    # 全局实例
    'mm',
    
    # 装饰器
    'path', 
    
    # 核心服务函数
    'ensure_in',
    'try_close_via_x',
] 