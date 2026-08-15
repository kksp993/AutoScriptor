from AutoScriptor.utils.logger import logger
from AutoScriptor import *
from ZmxyOL.nav.map_manager import mm, path
from .login import login
from ZmxyOL.nav.envs.decorators import *

"=======================    世界地图    ======================="


@path(HAS_SHIJIEDITU, "世界地图")
def way():
    logger.debug(f"当前区域: {mm.get_region()}==>{mm.get_region()[0]}")
    from ZmxyOL.nav.api import ensure_in
    ensure_in(mm.get_region()[0])
    logger.debug(f"当前区域: {mm.get_region()[0]}==>世界地图")
    click(I("导航-世界地图"), until=lambda: ui_T(I("世界地图-极北")))
    # mm.set_region("世界地图")

def way(env_name: str):
    click(SHIJIEDITU_CANTO_DICT[env_name])
    click(T("确定"))
    wait_for_appear(mm.envs[env_name].identifier)
    sleep(1)
    mm.set_region(env_name)

for env_name in SHIJIEDITU_CANTO:
    path("世界地图", env_name)(partial(way, env_name=env_name))


"=======================    天庭    ======================="
@path("仙盟", "天庭")
def way():
    click(I("导航-挑战"))
    while ui_F(I("挑战-昆仑山")):
        swipe(B(1000, 300), B(700, 300), duration_s=0.5)
        sleep(0.5)
    click(I("挑战-昆仑山"))
    wait_for_disappear(I("加载中"))
    wait_for_appear(T("夺回昆仑山"))
    click(B(1200, 30, 30, 30))
    mm.set_region("天庭")

    
"=======================    登录    ======================="
@path(HAS_SHEZHI, "登录")
def way():
    click(I("导航-菜单"))
    click(I("菜单-设置"))
    click(T("开始界面"))
    click(T("确定",color="绿色"))

"=======================    极北    ======================="
@path("极北", "极北村庄")
def way():
    click(T("回家", box=Box(29,656,77,54).margin()),until=lambda:ui_T(I("加载中")))
    wait_for_disappear(I("加载中"))
    wait_for_appear(I("极北村庄背景"))
    sleep(2)
    mm.set_region("极北村庄")

"=======================  极寒深渊  ======================="
@path("极北", "极寒深渊")
def way():
    swipe(B(640, 650, 10, 10), B(640, 350, 10, 10), duration_s=1)
    click(I("极寒深渊"))
    wait_for_appear(I("极寒深渊背景"))
    mm.set_region("极寒深渊")
    sleep(1)

@path("极寒深渊", "极北")
def way():
    wait_for_appear(I("极寒深渊背景"))
    click(B(70,460))
    wait_for_disappear(I("加载中"))
    mm.set_region("极北")
    sleep(1)

"=======================    村庄    ======================="
@path(["天庭", "地狱"], "村庄")
def way():
    click(T("回家", box=Box(29,656,77,54).margin()))
    wait_for_disappear(I("加载中"))
    mm.set_region("村庄")
    sleep(1)

@path("仙盟", "村庄")
def way():
    click(I("导航-菜单"), delay=0.5)
    sleep(2)
    click(I("菜单-设置"), delay=0.5)
    click(T("村庄",box=Box(964,542,94,120)), delay=1)
    wait_for_disappear(I("加载中"))
    sleep(3)
    mm.set_region("村庄")

@path("登录", "村庄")
def way():
    login(
        cfg["game"].get("account", None), 
        cfg["game"].get("password", None), 
        cfg["game"].get("character_name", None)
    )
    mm.set_region("村庄")


"=======================    仙盟    ======================="
@path(["村庄"], "仙盟")
def way():
    while ui_F(T("仙盟",box=Box(16,30,130,400)), 3):
        click(I("导航-按钮收缩"))
        if ui_T(T("精彩活动"), 2): click(B(1100, 40, 40, 40))
        sleep(2)
    click(T("仙盟",box=Box(16,30,130,400)))
    sleep(1)
    click(I("仙盟-驻地"), until=lambda: ui_T(I("加载中")), interval=1)
    wait_for_disappear(I("加载中"))
    mm.set_region("仙盟")
    sleep(1)


"=======================    联盟    ======================="
@path("仙盟", "联盟")
def way():
    click(I("仙盟-联盟"))
    wait_for_appear(T("魔渊之界"))
    mm.set_region("联盟")

@path("联盟", "村庄")
def way():
    click(T("返回村庄", box=Box(1130,600,150,120)), assure_stable=True, until=lambda: ui_T((I("加载中"))))
    wait_for_disappear(I("加载中"))
    sleep(3)
    mm.set_region("村庄")


LR_ENVS = ["极寒深渊", "联盟"]

"=======================    导航    ======================="
for env_name in mm.envs.keys():
    if env_name in LR_ENVS: LOC_INDEX_TRAV(env_name, swipe_left_right)
    else: LOC_INDEX_TRAV(env_name, swipe_up_down)
