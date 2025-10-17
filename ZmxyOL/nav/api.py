"""
导航服务
提供ensure_in、try_get_region、way_to_region等核心导航功能

新版本特点：
- 使用函数式调用替代TaskBuilder模式
- 直接使用AutoScriptor核心API
- 简化参数传递，移除ctx上下文依赖
- 保持核心功能不变，提高代码可读性
"""

import time
from AutoScriptor import *
from AutoScriptor.core.api import ui_idx
from ZmxyOL.nav.envs.decorators import LOC_ENV
from .map_manager import mm
from logzero import logger
from typing import Any, Callable

def _flatten_identifiers(idfs: list[Any]) -> tuple[list[Any], list[list[Any]]]:
    """将混合单个或序列的 identifier 展平，并记录分组"""
    groups: list[list[Any]] = []
    flat: list[Any] = []
    for idf in idfs:
        items = list(idf) if isinstance(idf, (list, tuple)) else [idf]
        groups.append(items)
        flat.extend(items)
    return flat, groups

def _restore_flat_idx(flat_idx: int, groups: list[list[Any]]) -> int:
    """将展平索引映射回原始列表索引"""
    cum = 0
    for idx, group in enumerate(groups):
        if flat_idx < cum + len(group):
            return idx
        cum += len(group)
    return -1

def _check_idx(get_identifier: Callable[[str], Any], names: list[str]) -> int:
    """通用索引查找：展平 identifiers，定位，再还原原始索引"""
    idfs = [get_identifier(name) for name in names]
    flat, groups = _flatten_identifiers(idfs)
    flat_idx = ui_idx(flat)
    if flat_idx < 0: return -1
    res = _restore_flat_idx(flat_idx, groups)
    return res

def check_loc_idx(loc_list: list[str]) -> int:
    """检查多个位置：扁平化 identifier 并映射原始位置索引"""
    return _check_idx(lambda name: mm.locs.get(name).identifier, loc_list)

def check_env_idx(env_list: list[str]) -> int:
    """检查多个环境：扁平化 identifier 并映射原始环境索引"""
    return _check_idx(lambda name: mm.envs.get(name).identifier, env_list)


def locate_region(cnt = 0) -> tuple[str, str]:
    """
        按优先级检查当前位置
    """
    cur_env, cur_loc = mm.get_region()
    logger.info("# 1.1 检查当前ctx中的loc")
    if cur_loc and check_loc_idx([cur_loc]) >= 0:
        return mm.set_region(cur_env, cur_loc)
    
    logger.info("# 1.2 检查当前ctx中的env")
    if cur_env and check_env_idx([cur_env]) >= 0:
        return mm.set_region(cur_env)
    
    logger.info("# 1.3 检查所有env")
    idx = check_env_idx(mm.envs.keys())
    if idx >= 0:
        return mm.set_region(list(mm.envs.keys())[idx])
    
    logger.info("# 1.4 检查所有loc")
    idx = check_loc_idx(mm.locs.keys())
    if idx >= 0:
        loc = mm.locs[list(mm.locs.keys())[idx]]
        return mm.set_region(loc.envs[0].name, loc.name)
    if cnt % 2 == 0:
        try_close_via_x()
    if cnt > 10:
        raise ValueError("无法找到当前位置，请检查环境是否正确")
    return locate_region(cnt + 1)

def ensure_in(tar_loc: str|list[str], idx:int|None|list[int]=None):
    """
    根据当前的env.loc，和目标位置的env.loc
    利用导航工具组装path，到达目的地
    """
    if tar_loc == LOC_ENV:
        tar_loc = mm.get_region()[0]
    elif idx is not None: 
        if isinstance(idx, list):
            assert len(idx) == len(tar_loc), "idx和tar_loc长度不一致"
            tar_loc = [tar_loc[i] + "#" + str(idx[i])  if idx[i] else tar_loc[i] for i in range(len(tar_loc))]
        else:
            tar_loc = tar_loc + "#" + str(idx) if idx else tar_loc
    cur_env, cur_loc = locate_region()
    tar_loc = mm.get_nearest_env(tar_loc)
    assert cur_env and cur_loc, "当前位置未设置，无法导航"
    tar_env = mm.locs[tar_loc].env().name
    mm.navigate_to(cur_env,cur_loc,tar_env,tar_loc)


def try_close_via_x():
    """
    尝试关闭各种弹窗和等待加载完成
    """
    # 关闭目标列表
    close_targets = [
        (I("极北之地-取消"), I("极北之地-取消")),
        (I("x"), I("x")),
        (I("x-in"), B(1061,178,39,47)),
        (I("菜单-宠物"), B(10,10)),
        (T("回家",box=Box(18,607,87,109)), T("回家",box=Box(18,607,87,109))),
        (T("确认"), T("确认")),
        (T("返回地图"), T("返回地图")),
        (T("返回大厅"), T("返回大厅")),
        (T("我的队伍",box=Box(434,15,439,119)), B(1060,30,30,30)),
    ]
    
    # 等待消失目标列表
    wait_for_disappear_targets = [
        I("加载中"),
        I("极北-加载中"),
        I("进入游戏中")
    ]
    
    click(B(0,0,))
    found = True
    while found:
        found = False
        tgts = tuple(target for target, _ in close_targets)
        idx = ui_idx(tgts)
        if idx > 0:
            click(close_targets[idx][1], if_exist=True)
            found = True
            sleep(0.5)
        for target in wait_for_disappear_targets:
            while(ui_T(target)): 
                time.sleep(0.5) 
                found = True
    
    return True 