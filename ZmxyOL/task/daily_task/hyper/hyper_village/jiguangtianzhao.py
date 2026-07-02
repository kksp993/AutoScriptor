from ZmxyOL import *
from AutoScriptor import *

@register_task(
    description="领取极光天诏任务奖励。",
    path_cn="每日任务/极北/极北村庄/极光天诏",
)
def task():
    ensure_in("极北村庄")
    while(ui_F((I("青莲炎"),T("青莲炎")))):
        click(I("导航-极光天诏"), if_exist=True)
        sleep(0.5)
    click(B(10,10,10,10))
    click(B(149,594,98,89))
    click(I("诏令任务-每日任务"))
    click(B(835,185,90,45),repeat=20,interval=0.25)
    click(B(970,70,30,30))
    wait_for_appear(I("青莲炎"))
    click(B(60,605,30,30))
    ensure_in("极北村庄")
