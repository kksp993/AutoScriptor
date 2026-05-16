import traceback
from time import time
from ZmxyOL import *
from AutoScriptor import *
from AutoScriptor.utils.logger import logger

def battle():
    wait_for_disappear(I("加载中"))
    from ZmxyOL.battle.character.hero import h
    sleep(0.5)
    h.skill(4, 0.95)
    h.zhenling()
    h.huashen()
    h.prop()
    h.sleep(0.5)
    h.skill(6)
    cnt = 1
    bg.set_signal("try_exit", False)
    deadline = time() + 120
    with bg.scope("每日梵天塔") as scope:
        scope.add(
            name="战斗结束",
            identifier=(T("确认"),T("入劫")),
            callback=lambda: bg.set_signal("try_exit", True)
        )
        while not bg.signal("try_exit"):
            if time() >= deadline:
                raise TimeoutError("每日梵天塔战斗等待结束超时")
            if cnt % 2 == 0:
                h.skill(6)
            else:
                h.skill(5,5)
            cnt += 1
    click(T("确认"))
    wait_for_disappear(I("加载中"))

def FTT_battle_one_round():
    final = False
    while not final:
        final = ui_T(T("终劫"))
        if final: logger.info(f"本关是终劫，final={final}")
        while ui_F(T("烦恼")):
            click(T("更替"))
            sleep(0.5)
            click(T("确定"))
            sleep(2)
        click(T("烦恼"))
        click(T("入劫"),until=lambda: ui_T(I("加载中")))
        battle()
        wait_for_appear(T("入劫"))


@register_task
def fanTianTa(
    battle_times=1,
    claim_past=True,
    battle_flow: BattleFlowName = DEFAULT_BATTLE_FLOW,
):
    """claim_past：每日领取时是否也点「过去」；账号未解锁过去时设为 False。"""
    ensure_in("极北",-1)
    click(B(0,120,90,100))
    for diff in (["现在", "过去"] if claim_past else ["现在"]):
        click(T(diff),offset=(0,100))
        sleep(3)
        click(T("确认"), if_exist=True)
        sleep(1)
        click(B(30,30,30,30))
    click(T("现在"),offset=(0,100))
    sleep(3)
    click(T("确认"), if_exist=True)
    sleep(1)
    for _ in range(battle_times):
        if not ui_T(T("碾压")):
            FTT_battle_one_round()
        else:
            click(T("碾压"))
            wait_for_appear(T("优先级"))
            remains = extract_info(B(341,505,310,57), post_process=lambda s: int(s.strip()[-2]), ensure_not_empty=True)
            if remains > 0:
                click(T("烦恼"))
                click(T("立即碾压"))
                click(T("空白处"))
            else:
                click(B(1011,49,57,52))
        sleep(3)
    click(B(30,30,30,30))
    sleep(1)
    click(B(30,30,30,30))



if __name__ == "__main__":
    try:
        fanTianTa()
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)
