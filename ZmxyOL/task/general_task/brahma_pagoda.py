from enum import Enum
import traceback

from numpy import arange
from AutoScriptor.utils import box
from ZmxyOL.task.task_register import register_task
from ZmxyOL import *
from AutoScriptor import *
from logzero import logger
class FFT_difficulty(Enum):
    past = "过去"
    now = "现在"

class FFT_preference(Enum):
    yellow = "烦恼"
    purple = "恶意"
    red = "恶语"


def battle():
    wait_for_disappear(I("加载中"))
    from ZmxyOL.battle.character.hero import h
    sleep(0.5)
    h.zhenwu()
    h.huashen()
    h.skill(4, 0.95)
    h.prop()
    h.zhenling()
    h.zhenling()
    h.zhenling()
    h.sleep(1.5)
    h.skill(6)
    bg.add(
        name="FTT_battle",
        identifier=(T("确认"),T("前往新一层")),
        callback=lambda: [bg.set_signal("try_exit", True),bg.clear()]
    )
    bg.set_signal("try_exit", False)
    while not bg.signal("try_exit"):
        for cnt in range(5):
            h.prop()
            if cnt % 2 == 0: h.skill(6)
            else: h.skill(5,4)
        h.zhenling()
        h.battle_loop(battle_weight=99)
    click((T("确认"),T("前往新一层")))
    wait_for_disappear(I("加载中"))

def FTT_battle_one_round(preference:list[FFT_preference], conquer_TianMo:bool):
    if first(get_colors(B(94,623,2,3)))!="灰色" and conquer_TianMo: 
        return logger.info("可以挑战天魔，跳过轮回轮次")
    final = False
    preference_list = [T(p.value) for p in preference]
    preference_list.append(T("终劫"))
    preference_list = tuple(preference_list)
    while not final:
        final = ui_T(T("终劫"))
        if final: logger.info(f"本关是终劫，final={final}")
        while ui_F(preference_list):
            click(T("更替"))
            sleep(0.5)
            click(T("确定"))
            sleep(2)
        click(preference_list)
        click(T("入劫"))
        battle()
        wait_for_appear(T("入劫"))

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
    conquer_TianMo=False
):
    ensure_in("极北",-1)
    click(B(0,120,90,100))
    sleep(3)
    click(T(difficulty.value),offset=(0,100))
    sleep(3)
    click(T("确认"), if_exist=True)
    sleep(5)
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