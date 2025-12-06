from ZmxyOL.nav import *

from AutoScriptor.vlm.tools.toolkits import register_tool
from ZmxyOL.nav.api import locate_region

@register_tool(name="check_region", description="""
检查并返回当前位置信息

Returns:
    tuple[str, str]: 当前位置信息 (env, loc)
""")
def check_region_tool():
    return locate_region(check_only=True)

@register_tool(name="ensure_in", description="""
根据当前的env.loc和目标位置的env.loc，利用导航工具组装path，到达目的地
当env或loc不满足instruction且instruction中包含env或loc时，请优先调用本工具，不要使用其他工具。
Args:
    tar_loc: 目标位置的env.loc，可以是单个位置，也可以是列表
        当tar_loc为LOC_ENV时，表示目标位置为当前位置为ENV=LOC=当前所在ENV名称
        当tar_loc为列表时，表示列表中的任意位置均可（优先最近的）
    idx: 目标位置的idx，可以是单个idx，也可以是列表
        当idx为None时，表示不使用idx, 默认使用0号idx
Returns:
    None
""")
def ensure_in_tool(tar_loc: str|list[str], idx:int|None|list[int]=None):
    if not mm.get_region()[0] or not mm.get_region()[1]:
        return "当前位置未设置，无法导航，请先调用check_region工具"
    ensure_in(tar_loc, idx)
    return "__Screenshot_Required__"

@register_tool(name="get_envs_and_locs", description="""
获取当前所有环境(Env)和位置(Loc)

Args:
    None
Returns:
    envs: 所有环境(Env)的名称列表
    locs: 所有位置(Loc)的名称列表
""")
def get_envs_and_locs_tool():
    return mm.envs, mm.locs