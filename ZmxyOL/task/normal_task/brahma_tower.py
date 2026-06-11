from enum import Enum
import traceback

from numpy import arange
from AutoScriptor.utils import box
from ZmxyOL import *
from AutoScriptor import *
from AutoScriptor.utils.logger import logger
class FFT_difficulty(Enum):
    past = "过去"
    now = "现在"

class FFT_preference(Enum):
    yellow = "烦恼"
    purple = "恶意"
    red = "恶语"


def battle():
    bg.set_signal("short_cut", False)
    wait_for_disappear(I("加载中"))
    from ZmxyOL.battle.character.hero import h
    sleep(0.5)
    with bg.scope("梵天塔") as scope:
        scope.add(
            name="战斗结束",
            identifier=(T("确认"),T("前往新一层")),
            callback=lambda: bg.set_signal("try_exit", True)
        )
        scope.add(
            name="捷径",
            identifier=T("入劫"),
            callback=lambda: [
                bg.set_signal("try_exit", True),
                bg.set_signal("short_cut", True),
            ]
        )
        h.battle_loop(max_duration=180)
    if not bg.signal("short_cut"):
        click((T("确认"),T("前往新一层")))
        wait_for_disappear(I("加载中"))

def FTT_battle_one_round(preference:list[FFT_preference], conquer_TianMo:bool):
    if first(get_colors(B(94,623,2,3)))!="灰色" and conquer_TianMo: 
        return logger.info("可以挑战天魔，跳过轮回轮次")
    preference_list = [T(p.value) for p in preference]
    preference_list.append(T("终劫"))
    preference_list = tuple(preference_list)
    while True:
        while ui_F(preference_list):
            click(T("更替"))
            sleep(0.5)
            click(T("确定"))
            sleep(2)
        final = ui_T(T("终劫"))
        click(T("终劫") if final else preference_list)
        click(T("入劫"))
        battle()
        wait_for_appear(T("入劫"))
        if final and ui_F(T("终劫")):
            break

def FTT_TianMo():
    while ui_F(T("天魔禁忌",box=Box(732,342,77,27))):
        click(B(94,623,2,3))
    sleep(0.5)
    click(I("梵天塔-天魔挑战"))
    battle()
    wait_for_appear(T("入劫"))

@register_task
def fanTianTa(
    battle_times=50, 
    difficulty=FFT_difficulty.past, 
    preference=(FFT_preference.purple,FFT_preference.yellow),
    conquer_TianMo=False,
    battle_flow: BattleFlowName = BattleFlowName["梵天塔循环"],
):
    ensure_in("极北",-1)
    click(B(0,120,90,100))
    sleep(3)
    for diff in ["现在", "过去"]:
        click(T(diff),offset=(0,100))
        sleep(3)
        click(T("确认"), if_exist=True)
        sleep(3)
        click(B(30,30,30,30))
    click(T(difficulty.value),offset=(0,100))
    sleep(3)
    for _ in range(battle_times):
        FTT_battle_one_round(preference, conquer_TianMo)
        sleep(3)
        if conquer_TianMo: FTT_TianMo()
        sleep(3)
    click(B(30,30,30,30))
    sleep(1)
    click(B(30,30,30,30))



if __name__ == "__main__":
    try:
        fanTianTa(
            battle_times=50, 
            difficulty=FFT_difficulty.now, 
            preference=(FFT_preference.yellow,),
            conquer_TianMo=False
        )
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)
