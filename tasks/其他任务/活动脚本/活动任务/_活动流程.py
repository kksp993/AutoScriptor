"""活动页的公共流程：从村庄进入活动、滑到目标、执行、退出。

活动任务共用同一个入口，差异只在找到入口之后，所以进入和退出收在这里。
本模块不是任务，注册表不会为它生成任务项。
"""
from AutoScriptor import *
from ZmxyOL import *


def run_activity(name: str, entry, do_task) -> None:
    """进入 ``entry`` 指定的活动，执行 ``do_task``，无论成败都退出活动页。"""
    ensure_in("村庄")

    # 仙盟面板展开时会盖住“活动”入口，先收起来
    while ui_F(T("仙盟", box=Box(16, 30, 130, 400)), 3):
        click(I("导航-按钮收缩"))
        if ui_T(T("精彩活动"), 2):
            click(B(1100, 40, 40, 40))
        sleep(2)

    click(T("活动", box=Box(255, 127, 103, 101).margin()))
    for _ in range(10):
        if ui_T(entry):
            break
        swipe(B(989, 170), B(345, 160), duration_s=1)

    sleep(1)
    click(entry)
    logger.info("找到目标: %s", entry)

    try:
        do_task()
        logger.info("任务完成: %s", name)
    finally:
        sleep(1)
        click(B(1092, 25, 44, 48))
        logger.info("%s 流程结束，退出活动界面。", name)
