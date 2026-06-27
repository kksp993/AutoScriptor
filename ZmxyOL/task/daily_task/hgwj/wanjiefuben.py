from AutoScriptor.utils.logger import logger
from AutoScriptor.utils.cancel import check_cancel_raise
from ZmxyOL.nav.api import locate_region
from ZmxyOL import *
from AutoScriptor import *
from AutoScriptor.battle_character.hero import h
from time import time


_BONUS_SIGNAL = "hgwj_bonus"
_BONUS_RULE_IDF = T("规则", box=Box(551, 43, 144, 56).margin())
_BONUS_ACTIVE_IDF = I("地鼠", color="蓝色")


def bonus_callback(start_game: bool = True) -> str:
    if start_game:
        click(B(1015, 85))
    logger.info("打地鼠开始！！！")
    start = time()
    last_state_check = 0.0
    hit_count = 0
    # 与 battle_loop 一致：try_exit 为 True 时退出；未设置时 .signal(..., False) 为 False，应继续打地鼠
    while not bg.signal("try_exit", False) and time() - start < 120:
        check_cancel_raise()
        now = time()
        if now - last_state_check >= 0.8:
            last_state_check = now
            if ui_T(_SETTLE_IDF + _FAIL_IDF, 0):
                _stop_battle()
                logger.info("打地鼠检测到结算/失败界面，准备进入结算处理")
                return "settlement"
        box = locate(I("地鼠", color="蓝色"), timeout=0, assure_stable=False)
        if box:
            hit_count += 1
            click(B(box), save_screenshot=False)
        else:
            sleep(0.03)
    if bg.signal("try_exit", False):
        logger.info("打地鼠结束：收到退出信号，命中 %d 次", hit_count)
        return "settlement"
    logger.warning("打地鼠超时退出，命中 %d 次，准备检查结算界面", hit_count)
    return "timeout"


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


def _stop_for_bonus(kind: str):
    bg.set_signal(_BONUS_SIGNAL, kind)
    _stop_battle()


def _handle_settlement(wait_timeout: float = 0) -> str:
    """主线程顺序处理结算/失败界面。返回 'done'、'continue' 或 'unknown'。"""
    switch_base("mumu")
    deadline = time() + max(wait_timeout, 0)
    first_probe = True

    while True:
        probe_timeout = 1 if first_probe and wait_timeout <= 0 else 0.5

        if ui_T(T("重新挑战"), probe_timeout):
            click(T("重新挑战"))
            if ui_T(I("加载中"), 0.5):
                wait_for_disappear(I("加载中"))
            return "continue"

        if ui_T((T("198点券"), T("159点券"), T("复活")), probe_timeout):
            click(T("取消"), delay=4, repeat=3)
            return "done"

        if ui_T((T("通关成功", box=Box(275, 114, 733, 490).margin()), T("继续挑战")), probe_timeout):
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

        if wait_timeout <= 0 or time() >= deadline:
            return "unknown"
        first_probe = False
        sleep(0.3)


def _run_bonus_and_handle_settlement(start_game: bool = True) -> str:
    bonus_result = bonus_callback(start_game=start_game)
    result = _handle_settlement(wait_timeout=12)
    if result == "unknown":
        if bonus_result == "timeout":
            raise RuntimeError("打地鼠超时后仍未识别到结算/失败界面")
        logger.warning("打地鼠结束后暂未识别到结算界面，将回到外层重新判断")
        return "continue"
    return result


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

    bg.set_signal("all_task_done", False)
    while not bg.signal("all_task_done", False):
        if ui_T(I("加载中"), timeout=3):
            wait_for_disappear(I("加载中"))

        round_result = "unknown"
        bg.set_signal(_BONUS_SIGNAL, False)
        bg.set_signal("try_exit", False)
        bg.set_signal("Pause_battle", False)
        with bg.scope("荒古万界") as scope:
            scope.add(name="settle", identifier=_SETTLE_IDF, callback=_stop_battle)
            scope.add(name="fail", identifier=_FAIL_IDF, callback=_stop_battle)
            if ui_T(_BONUS_RULE_IDF, 8):
                logger.info("检测到打地鼠规则页，进入打地鼠分支")
                round_result = _run_bonus_and_handle_settlement(start_game=True)
            elif bg.signal("try_exit", False):
                round_result = _handle_settlement(wait_timeout=3)
            else:
                scope.add(
                    name="bonus_rule",
                    identifier=_BONUS_RULE_IDF,
                    callback=lambda: _stop_for_bonus("rule"),
                    priority=1000,
                )
                scope.add(
                    name="bonus_active",
                    identifier=_BONUS_ACTIVE_IDF,
                    callback=lambda: _stop_for_bonus("active"),
                    priority=1000,
                )
                h.set(True, 3).battle_loop()
                bonus_state = bg.signal(_BONUS_SIGNAL, False)
                if bonus_state:
                    logger.info("战斗循环中检测到打地鼠界面，切换到打地鼠分支 (%s)", bonus_state)
                    round_result = _run_bonus_and_handle_settlement(start_game=(bonus_state != "active"))
                else:
                    round_result = _handle_settlement()

        if round_result == "done":
            bg.set_signal("all_task_done", True)
            
    click(B(30, 30, 30, 30), until=lambda: ui_T((T("荒古万界"), I("导航-菜单"), T("世界地图"))))
    click(B(1200, 30, 30, 30))
    bg.clear(clear_signals=True)
    locate_region()
