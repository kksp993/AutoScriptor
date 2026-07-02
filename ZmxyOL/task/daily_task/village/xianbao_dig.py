from ZmxyOL import *
from AutoScriptor import *


@register_task(
    path_cn="每日任务/村庄/仙宝挖掘",
    description="自动进行两个遗迹的仙宝挖掘。",
    task_doc="必须解锁仙宝挖掘，会自动进行两个地的挖掘。",
)
def daily_fxiang_task():
    ensure_in("法相")
    sleep(2)
    click(T("法宝"))
    click(T("获取仙宝"))
    sleep(1)
    click(T("遗迹"), until=lambda: ui_T(T("混沌遗迹")))
    click(B(300,250,250,350))
    sleep(2)    
    wait_for_appear(T("每日"))
    click(B(500,300,300,200))
    sleep(1)
    click(B(727,432,135,79))
    while ui_F(T("合成")):
        click(B(20,20,30,30))
        sleep(0.5)
    click(T("遗迹"))
    click(T("魔神遗迹"))
    wait_for_appear(T("魔神遗迹"))
    click(B(750,250,250,350))
    sleep(2)
    wait_for_appear(T("每日"))
    click(B(500,300,300,200))
    sleep(1)
    click(B(727,432,135,79))
    while ui_F(T("合成")):
        click(B(20,20,30,30))
        sleep(0.5)
    click(B(1200,30,30,30))
