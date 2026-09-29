
from ZmxyOL import *
from AutoScriptor import *

@register_task(
    path_cn="每日任务/村庄/星之结晶消耗",
    description="购买灵力滴液和灵力真酿",
    task_doc="购买灵力滴液和灵力真酿(100星之结晶/天)",
)
def task(购买灵力滴液=True, 购买灵力真酿=True):
    ensure_in("村庄")
    while ui_F(T("仙盟",box=Box(16,30,130,400)), 3):
        click(I("导航-按钮收缩"))
        if ui_T(T("精彩活动"), 2): click(B(1100, 40, 40, 40))
        sleep(2)
    click(T("活动", box=Box(255,127,103,101).margin()))
    for _ in range(10):
        if ui_T(T("兑换豪礼", box=Box(0,112,1280,100).margin())): break
        swipe(B(989,170), B(345,160), duration_s=0.1)
    click(T("兑换豪礼", box=Box(0,112,1280,100).margin()))
    click(T("星之结晶", box=Box(202,280,217,306).margin()))
    for _ in range(6):swipe(B(763,639), B(764,269), duration_s=0.1);sleep(1)
    buylist = []
    if 购买灵力滴液:
        buylist.append(1)
    if 购买灵力真酿:
        buylist.append(2)

    for _ in [1,2]:
        click(B(528,482+(_-1)*130))
        temp=ui_T(T("于培养灵识之体升级", box=Box(600,200,350,400).margin()), timeout=2)
        click(B(763,130))
        if temp:
            click(B(985,456+(_-1)*130))
            click(T("确定", box=Box(569,513,140,79).margin()),if_exist=True)
        sleep(1)
    click(B(1092,25,44,48))

