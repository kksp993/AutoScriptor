from typing import Dict, List, Any
from agno.tools import tool

_TOOL_REGISTRY: Dict[str, Any] = {}

def register_tool(*, name: str, description: str):
    """
    只支持 @register_tool(name="my_tool", description="...") 这一种用法，
    直接用 Agno 原生 tool 装饰器，并自动加入注册表。
    """
    def decorator(func):
        registered_tool = tool(name=name, description=description)(func)
        _TOOL_REGISTRY[name] = registered_tool
        return registered_tool
    return decorator

def load_toolkits() -> List[Any]:
    """
    返回所有已注册的工具。
    """
    # 如果注册表为空，则动态导入本目录下所有以"_tools.py"结尾的工具模块
    if not _TOOL_REGISTRY:
        import os
        import importlib

        tools_dir = os.path.dirname(__file__)
        for fname in os.listdir(tools_dir):
            if fname.endswith("_tools.py") and fname != os.path.basename(__file__):
                mod_name = f"{__package__}.{fname[:-3]}" if __package__ else fname[:-3]
                importlib.import_module(mod_name)
    return _TOOL_REGISTRY

def get_tool(name: str) -> Any:
    """
    获取已注册的工具。
    """
    return _TOOL_REGISTRY.get(name)

def get_tools(names:List[str]) -> List[Any]:
    """
    获取已注册的工具列表。
    """
    return [_TOOL_REGISTRY.get(name) for name in names]