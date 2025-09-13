from AutoScriptor import *
from ZmxyOL.nav import mm
from ZmxyOL.nav import path
from ZmxyOL.nav.envs.decorators import *


@path(LOC_ENV, "法相")
def way():
    click(T("菜单"))
    click(I("菜单-个人资料"),delay=0.5)
    click(T("法相"))
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

@path(LOC_ENV, "炼器师")
def way():
    if ui_idx((T('莫邪'),T("欧冶子")),30)==0:
        click(T('莫邪'),offset=(-230,100),resize=(80,120))
    else:
        click(T('欧冶子'),offset=(-480,100),resize=(80,120))
    click(T('炼器师'))
    mm.set_loc("炼器师")

@path("背包", LOC_ENV)
def way():
    click(B(1200,30,30,30))
    sleep(1)
    click(B(1200,30,30,30))
    mm.set_loc(mm.get_region()[0])

@path(LOC_ENV, "背包")
def way():
    click(T("菜单"))
    click(I("菜单-背包"),delay=0.5)
    wait_for_appear(I("背包背景"))
    mm.set_loc("背包")
