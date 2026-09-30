
from ZmxyOL import *
from AutoScriptor import *


@register_task(
    description="购买灵力滴液和灵力真酿",
    task_doc="用星之结晶兑换灵力滴液与灵力真酿（每日约 100 星之结晶）。",
)
def task(buy_spirit_liquid=True, buy_spirit_brew=True):
    """在兑换豪礼页购买灵力滴液、灵力真酿。"""
    ensure_in("村庄")

    # 仙盟面板展开时先收起，否则“活动”入口被遮挡
    while ui_F(T("仙盟", box=Box(16, 30, 130, 400)), 3):
        click(I("导航-按钮收缩"))
        if ui_T(T("精彩活动"), 2):
            click(B(1100, 40, 40, 40))
        sleep(2)

    click(T("活动", box=Box(255, 127, 103, 101).margin()))
    for _ in range(10):
        if ui_T(T("兑换豪礼", box=Box(0, 112, 1280, 100).margin())):
            break
        swipe(B(989, 170), B(345, 160), duration_s=0.1)
    click(T("兑换豪礼", box=Box(0, 112, 1280, 100).margin()))
    click(T("星之结晶", box=Box(202, 280, 217, 306).margin()))

    # 列表滚到顶，让两行商品位置固定
    for _ in range(6):
        swipe(B(763, 639), B(764, 269), duration_s=0.1)
        sleep(1)

    # 第 1 行是灵力滴液，第 2 行是灵力真酿
    rows = []
    if buy_spirit_liquid:
        rows.append(1)
    if buy_spirit_brew:
        rows.append(2)

    for row in rows:
        click(B(528, 482 + (row - 1) * 130))
        already_upgraded = ui_T(
            T("于培养灵识之体升级", box=Box(600, 200, 350, 400).margin()),
            timeout=2,
        )
        click(B(763, 130))
        if already_upgraded:
            click(B(985, 456 + (row - 1) * 130))
            click(T("确定", box=Box(569, 513, 140, 79).margin()), if_exist=True)
        sleep(1)

    click(B(1092, 25, 44, 48))
