from AutoScriptor import *
from ZmxyOL.nav.map_manager import mm, path
from .login import login
import time
from ZmxyOL.nav.envs.decorators import *



"=======================    天庭    ======================="
@path("仙盟", "天庭")
def way():
    click(I("导航-挑战"))
    while ui_F(I("挑战-昆仑山")):
        swipe(B(1000, 300), B(700, 300), duration_s=0.5)
    click(I("挑战-昆仑山"))
    while ui_T(I("加载中"), 1):
        time.sleep(0.5)
    wait_for_appear(T("夺回昆仑山"))
    click(B(1200, 30, 30, 30))
    mm.set_region("天庭")

@path(HAS_SHIJIEDITU, "天庭")
def way():
    click(I("导航-世界地图"))
    click(I("世界地图-天庭"))
    click(T("确定"))
    wait_for_appear(T("神兽森林"))
    mm.set_region("天庭")
    
"=======================    登录    ======================="
@path(HAS_SHEZHI, "登录")
def way():
    click(T("菜单"))
    click(I("菜单-设置"))
    click(T("开始界面"))
    click(T("确定",color="绿色"))

"=======================    极北    ======================="
@path("极北", "极北村庄")
def way():
    click(T("回家",box=Box(18,607,87,109)))
    # 等待加载中消失
    while ui_T(I("加载中"), 1):
        time.sleep(0.5)
    mm.set_region("极北村庄")
    time.sleep(1)

"=======================  极寒深渊  ======================="
@path("极北", "极寒深渊")
def way():
    swipe(B(640, 650, 10, 10), B(640, 350, 10, 10), duration_s=1)
    click(I("极寒深渊"))
    wait_for_appear(I("极寒深渊背景"))
    mm.set_region("极寒深渊")
    time.sleep(1)

"=======================    地狱    ======================="
@path(HAS_SHIJIEDITU, "地狱")
def way():
    click(I("导航-世界地图"))
    click(I("世界地图-炼狱"))
    click(T("确定"))
    wait_for_appear(I("地狱鬼城"))
    mm.set_region("地狱")
    time.sleep(1)

"=======================    极北    ======================="
@path(HAS_SHIJIEDITU, "极北")
def way():
    click(I("导航-世界地图"))
    click(I("世界地图-极北"))
    click(T("确定"))
    wait_for_appear(I("极北背景"))
    mm.set_region("极北")
    time.sleep(1)

@path("极寒深渊", "极北")
def way():
    click(B(10, 490, 134, 110))
    # 等待加载中消失
    while ui_T(I("加载中"), 1):
        time.sleep(0.5)
    mm.set_region("极北")
    time.sleep(1)

"=======================    村庄    ======================="
@path(["天庭", "地狱"], "村庄")
def way():
    click(T("回家",box=Box(18,607,87,109)))
    # 等待加载中消失
    while ui_T(I("加载中"), 1):
        time.sleep(0.5)
    mm.set_region("村庄")
    time.sleep(1)

@path("仙盟", "村庄")
def way():
    click(T("菜单"), delay=0.5)
    time.sleep(2)
    click(I("菜单-设置"), delay=0.5)
    click(T("村庄",box=Box(964,542,94,120)), delay=1)
    # 等待加载中消失
    while ui_T(I("加载中"), 1):
        time.sleep(0.5)
    mm.set_region("村庄")

@path("登录", "村庄")
def way():
    login(
        cfg["game"].get("account", None), 
        cfg["game"].get("password", None), 
        cfg["game"].get("character_name", None)
    )

@path(["极北村庄","极北","极寒深渊"], "村庄")
def way():
    click(I("导航-世界地图"))
    click(T("村庄"))
    click(T("确定"))
    # 等待加载中消失
    while ui_T(I("加载中"), 1):
        time.sleep(0.5)
    mm.set_region("村庄")
    time.sleep(1)

"=======================    仙盟    ======================="
@path(["村庄", "极北村庄"], "仙盟")
def way():
    while ui_F(T("仙盟",box=Box(16,30,924,400)), 3):
        click(I("导航-按钮收缩"))
        sleep(4)
    click(T("仙盟",box=Box(16,30,924,400)))
    sleep(1)
    click(I("仙盟-驻地"))
    sleep(1)
    # 等待加载中消失
    while ui_T(I("加载中"), 1):
        sleep(0.5)
    mm.set_region("仙盟")
    sleep(1)

for env_name in mm.envs.keys():
    LOC_INDEX_TRAV(env_name, swipe_up_down)