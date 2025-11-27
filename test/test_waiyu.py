from calendar import c
import time
from AutoScriptor import *
from ZmxyOL.nav import *
import traceback


def bonus_callback():
    click(B(1015,85))
    bg.set_signal("exit_bonus", False)
    t = time.time()
    while time.time() - t < 47: click(I("地鼠"), if_exist=True)

def battle_callback():
    from ZmxyOL.battle.character.hero import h
    h.set(True,3)
    h.battle_loop(battle_weight=2)


tasks=[
    B(50,83),
    B(15,410),
    B(235,250),
    B(400,550),
    B(570,360),
    B(840,550),
    B(900,250),
    B(1200,90),
    B(1210,400),
]

hg_tasks=[
    "荒古-普通-0",
    "荒古-精英-0",
    "荒古-奖励-0",
    "荒古-普通-1",
    "荒古-精英-1",
    "荒古-奖励-1",
]

if __name__ == "__main__":
    try:
        ensure_in("外域区域")
        click(T("信标定位"))
        wait_for_appear(T("定位完成"))
        click(B(630,360))
        wait_for_appear(T("总灵根值"))
        click(B(960,510,90,90))
        if tgt:=locate(T("本次登录不再提醒"), timeout=1): 
            click(B(560,415))
            sleep(0.5)
            click(T("确定"))
        if ui_T(I("加载中"), timeout=0.5):
            wait_for_disappear(I("加载中"))
        
        bg.set_signal("task_done", False)
        def callback():
            bg.set_signal("Pause_battle", True)
            click(T("继续挑战"))
            if ui_T(T("购买"),2):
                bg.set_signal("try_exit", True)
                click(T("取消"),if_exist=True)
                sleep(0.5)
                click(T("确定",color="蓝色"))
                bg.set_signal("task_done", True)
                bg.clear()
            else:
                click(T("确定"),if_exist=True)
                if ui_T(I("加载中"), timeout=0.5):
                    wait_for_disappear(I("加载中"))
                bg.set_signal("try_exit", True)

        bg.add(
            name="try_pause",
            identifier=T("继续挑战"),
            callback=callback,
            once=False
        )

        while not bg.signal("task_done"):
            if ui_T(T("土行孙"),1): bonus_callback()
            else: battle_callback()



    except InterruptedError:
        bg.remove("try_pause")
        bg.clear()
        exit(0)
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)