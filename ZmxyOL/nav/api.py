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
from ZmxyOL.nav.envs.decorators import LOC_ENV
from .map_manager import mm



def check_loc_exists(loc_name: str) -> bool:
    """检查loc中是否存在目标标示物"""
    loc = mm.locs.get(loc_name)
    print(loc, loc.identifier)
    return ui_T(loc.identifier)

def check_env_exists(env_name: str) -> bool:
    """检查环境是否为当前环境"""
    env = mm.envs.get(env_name)
    return ui_T(env.identifier)

def locate_region(cnt = 0) -> tuple[str, str]:
    """
        按优先级检查当前位置
    """
    cur_env, cur_loc = mm.get_region()
    logger.info("# 1.1 检查当前ctx中的loc")
    if cur_loc and check_loc_exists(cur_loc):
        return mm.set_region(cur_env, cur_loc)
    
    logger.info("# 1.2 检查当前ctx中的env")
    if cur_env and check_env_exists(cur_env):
        return mm.set_region(cur_env)
    
    logger.info("# 1.3 检查所有env")
    for env_name in mm.envs:
        if check_env_exists(env_name):
            return mm.set_region(env_name)
    
    logger.info("# 1.4 检查所有loc")
    for loc_name in mm.locs:
        if check_loc_exists(loc_name):
            loc = mm.locs[loc_name]
            return mm.set_region(loc.envs[0].name, loc_name)
    if cnt % 3 == 0:
        try_close_via_x()
    if cnt > 20:
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
    ]
    
    # 等待消失目标列表
    wait_for_disappear_targets = [
        I("加载中"),
        I("极北-加载中"),
    ]
    
    click(B(0,0,))
    found = True
    while found:
        found = False
        for target, click_target in close_targets:
            if ui_T(target):
                click(click_target, if_exist=True)
                found = True
                sleep(0.5)
        for target in wait_for_disappear_targets:
            while(ui_T(target)): 
                time.sleep(0.5) 
                found = True
    
    return True 