import traceback
from AutoScriptor.utils.logger import logger
from AutoScriptor.utils.cancel import check_cancel_raise
from ZmxyOL.nav.api import locate_region
from ZmxyOL import *
from AutoScriptor import *
from ZmxyOL.battle.character.hero import h
from time import time


def bonus_callback():
    click(B(1015, 85))
    logger.info("打地鼠开始！！！")
    start = time()
    # 与 battle_loop 一致：try_exit 为 True 时退出；未设置时 .signal(..., False) 为 False，应继续打地鼠
    while not bg.signal("try_exit", False) and time() - start < 120:
        box = locate(I("地鼠", color="蓝色"), timeout=0, assure_stable=False)
        if box:
            click(B(box), save_screenshot=False)


_SETTLE_IDF = (
    T("继续挑战"),
    T("通关成功", box=Box(275, 114, 733, 490).margin()),
    T("今日还可购买"),
)

_FAIL_IDF = (
    T("198点券"),
    T("159点券"),
    T("复活"),
    T("重新挑战")
)


def _stop_battle():
    bg.set_signal("Pause_battle", True)
    bg.set_signal("try_exit", True)


def _handle_settlement() -> str:
    """主线程顺序处理结算/失败界面。返回 'done'（任务结束）或 'continue'（继续下一波）。"""
    switch_base("mumu")

    if ui_T(T("重新挑战"), 1):
        click(T("重新挑战"))
        if ui_T(I("加载中"), 0.5):
            wait_for_disappear(I("加载中"))
        return "continue"

    if ui_T((T("198点券"), T("159点券"), T("复活")), 1):
        click(T("取消"), delay=4, repeat=3)
        return "done"

    if ui_T((T("通关成功", box=Box(275, 114, 733, 490).margin()), T("继续挑战")), 1):
        click(T("继续挑战"), if_exist=True, timeout=5)
        if ui_T(T("购买"), 2):
            click(T("取消"), if_exist=True)
            sleep(0.5)
            click(T("确认", color="蓝色"))
            return "done"
        else:
            click(T("确定"), if_exist=True)
            if ui_T(I("加载中"), 0.5):
                wait_for_disappear(I("加载中"))
            return "continue"

    return "continue"


# tasks=[
#     B(50,83),
#     B(15,410),
#     B(235,250),
#     B(400,550),
#     B(570,360),
#     B(840,550),
#     B(900,250),
#     B(1200,90),
#     B(1210,400),
# ]

# hg_tasks=[
#     "荒古-普通-0",
#     "荒古-精英-0",
#     "荒古-奖励-0",
#     "荒古-普通-1",
#     "荒古-精英-1",
#     "荒古-奖励-1",
# ]


@register_task
def task2(battle_flow: BattleFlowName = DEFAULT_BATTLE_FLOW):
    task(battle_flow=battle_flow)
    task(battle_flow=battle_flow)


def task(
    battle_flow: BattleFlowName = DEFAULT_BATTLE_FLOW,
):
    ensure_in("外域区域")
    click(T("信标定位", box=Box(1045,654,113,54).margin()), until=lambda: ui_T(T("定位完成")))
    click(B(630, 360))
    wait_for_appear(T("总灵根值"))
    click(B(960, 510, 90, 90))

    if locate((T("本次登录不再提醒"), T("都已通关")), timeout=3):
        click(B(560, 415))
        sleep(0.5)
        click(T("确定"))

    if locate(T("购买"), timeout=3):
        click(T("取消"))
        click(B(1225, 150), until=lambda: ui_T(T("定位完成")))
        click(T("关闭定位"))
        logger.info("当前免费任务已经完成，荒古挑战结束")
        return

    while not bg.signal("all_task_done", False):
        if ui_T(I("加载中"), timeout=3):
            wait_for_disappear(I("加载中"))

        bg.set_signal("try_exit", False)
        bg.set_signal("Pause_battle", False)
        bg.add(name="hgwj_settle", identifier=_SETTLE_IDF, callback=_stop_battle)
        bg.add(name="hgwj_fail", identifier=_FAIL_IDF, callback=_stop_battle)

        try:
            if ui_T(T("规则", box=Box(551, 43, 144, 56).margin()), 2):
                bonus_callback()
                continue
            h.set(True, 3).battle_loop()
        finally:
            bg.remove("hgwj_settle")
            bg.remove("hgwj_fail")

        if _handle_settlement() == "done":
            bg.set_signal("all_task_done", True)
            
    click(B(30, 30, 30, 30), until=lambda: ui_T((T("荒古万界"), I("导航-菜单"), T("世界地图"))))
    click(B(1200, 30, 30, 30))
    bg.clear(clear_signals=True)
    locate_region()


if __name__ == "__main__":
    try:
        init()
        task()
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)
