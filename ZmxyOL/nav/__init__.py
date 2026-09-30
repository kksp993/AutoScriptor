"""
新的导航系统
基于图论的动态导航，支持env.loc概念
"""

from .map_manager import MapManager, Loc, Env, mm, path 
from .api import ensure_in, try_close_via_x
from .envs import *
from .envs.decorators import LOC_ENV


def _register_error_context_providers() -> None:
    """Contribute navigation state to AutoScriptor error archives.

    The archive keeps the ``mm_current_region`` / ``locate_region_result`` keys
    so existing error.log files stay readable; the values come from here rather
    than AutoScriptor importing the nav layer.
    """
    from AutoScriptor.logging.log_archiver import register_context_provider

    def current_region() -> dict:
        cur_env, cur_loc = mm.get_region()
        return {"env": cur_env, "loc": cur_loc}

    def locate_region_result():
        from ZmxyOL.nav.api import locate_region

        # cnt=1 跳过冷启动分支：归档诊断不该顺手启动游戏并 sleep 2 秒。
        result = locate_region(cnt=1, check_only=True)
        if isinstance(result, tuple) and len(result) == 2:
            detected_env, detected_loc = result
            return {"env": detected_env, "loc": detected_loc}
        return f"unresolved: {result}"

    register_context_provider("mm_current_region", current_region)
    register_context_provider("locate_region_result", locate_region_result)


_register_error_context_providers()

__all__ = [
    # 核心类
    'MapManager',
    'Loc', 
    'Env',
    
    # 全局实例
    'mm',
    
    # 装饰器
    'path', 
    "LOC_ENV",
    
    # 核心服务函数
    'ensure_in',
    'try_close_via_x',
    'LoginClient',
    'login',
]
