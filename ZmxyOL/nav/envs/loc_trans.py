from re import U
from AutoScriptor import *
from ZmxyOL.nav import mm
from ZmxyOL.nav import path
from ZmxyOL.nav.envs.decorators import *


@path(LOC_ENV, "法相")
def way():
    click(I("导航-菜单"))
    click(I("菜单-个人资料"),delay=0.5); sleep(1)
    if get_colors(B(31,639,194,63))[0] != "蓝色": 
        click(T("法相", box=Box(0,0,500,140)), delay=1, until=lambda: ui_T(T("属性")))
    mm.set_loc("法相")

@path("法相", LOC_ENV)
def way():
    click(T("角色"))
    locate(T("伤害率"))
    sleep(0.5)
    click(B(1200,30,30,30))
    sleep(1)
    click(B(1200,30,30,30))
    click(B(0,0))
    mm.set_loc(mm.get_region()[0])

@path("极北#-1", "幽冥冰窟")
def way():
    click(I("冰霜遗迹"),delay=1)
    click(T("幽冥冰窟",box=Box(993,272,115,104)))
    click(T("进入"), delay=1)
    click(T("确定"), timeout=1, if_exist=True)
    wait_for_appear(T("虚空裂缝"))
    mm.set_loc("幽冥冰窟")
    
@path("幽冥冰窟", LOC_ENV)
def way():
    click(I("冰窟-返回"),delay=0.5)
    wait_for_disappear(I("极北-加载中"))
    mm.set_loc(mm.get_region()[0])

@path("炼器师", LOC_ENV)
def way():
    click(B(896,42,64,56))
    sleep(0.5)
    click(B(1123,54,66,58))
    sleep(1)
    click(B(0,0))

@path(LOC_ENV, "炼器师")
def way():
    idx = ui_idx((T('莫邪'),T("副职业宗师"),T('仙器培养')),timeout=2)
    if idx == 0:
        click(T('莫邪'),offset=(-230,80),resize=(0,0))
    elif idx == 1:
        click(T("副职业宗师"))
    elif idx == 2:
        click(T('仙器培养'),offset=(-525,80),resize=(0,0))
    else:
        from ZmxyOL.nav.api import ensure_in
        ensure_in("极北")
        ensure_in("炼器师")
    click(T('炼器师'),until=lambda:ui_T(T("+", box=Box(259,374,101,112).margin())))
    

@path("背包", LOC_ENV)
def way():
    click(B(1200,30,30,30))
    sleep(1)
    click(B(1200,30,30,30), until=lambda:ui_F(T("背包")), interval=1)
    mm.set_loc(mm.get_region()[0])

@path(LOC_ENV, "背包")
def way():
    click(I("导航-菜单")); sleep(1)
    if ui_F(I("菜单-背包")): click(I("导航-菜单")); sleep(1)
    click(I("菜单-背包"),delay=0.5)
    wait_for_appear(I("背包背景"))
    mm.set_loc("背包")

"=======================    荒古万界    ======================="
@path(LOC_ENV, "荒古万界")
def way():
    click(T("古万界"),offset=(180,0))
    wait_for_appear(T("万界穿梭"))
    mm.set_loc("荒古万界")
    sleep(1)

@path("荒古万界", LOC_ENV)
def way():
    click(B(30,30,30,30))
    # 如果打完荒古副本，出来返回会直接去村庄，否则返回去荒古遗境，欸，官方就是搞
    from ZmxyOL.nav.api import ensure_in
    ensure_in("洪荒遗境")

def travel_to_dst_loc(target_env: str):
    click(T("万界穿梭"))
    click(T(target_env[:2]))
    click(T("确定"))
    wait_for_appear(T(target_env))

available_dst_locs = ["外域区域", "边缘区域"]


for dst_loc in available_dst_locs:
    for src_loc in available_dst_locs:
        if src_loc == dst_loc: continue
        def way(dst_loc: str):
            if ui_T(T(dst_loc)): return mm.set_loc(dst_loc)
            travel_to_dst_loc(dst_loc)
            mm.set_loc(dst_loc)
        path(src_loc, dst_loc)(partial(way, dst_loc=dst_loc))
    path("荒古万界", dst_loc)(partial(way, dst_loc=dst_loc))
    path(dst_loc, "荒古万界")(lambda: mm.set_loc(mm.get_region()[0]))


"=======================    荒古村庄    ======================="
@path(LOC_ENV, "荒古村庄")
def way():
    click(T("回家", box=Box(29,656,77,54).margin()))
    mm.set_loc("荒古村庄")

def way(env_name: str):
    click(I("导航-世界地图"), until=lambda: ui_T(I("世界地图-极北")))
    mm.paths["世界地图", env_name]()

for env_name in SHIJIEDITU_CANTO:
    path("荒古村庄", env_name)(partial(way, env_name=env_name))
