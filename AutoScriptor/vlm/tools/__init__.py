from AutoScriptor.vlm.tools.toolkits import register_tool, get_tool, get_tools
from AutoScriptor.vlm.tools.toolkits import load_toolkits as _load_toolkits_dict

# 自动导入所有工具模块以触发注册
# 新增工具文件时，请在此处添加导入
from AutoScriptor.vlm.tools import *


def load_toolkits() -> list:
    """
    返回所有已注册的工具列表（Agno 兼容格式）。
    """
    return list(_load_toolkits_dict().values())

print(load_toolkits())

__all__ = [
    "register_tool",
    "load_toolkits",
    "get_tool",
    "get_tools",
]
