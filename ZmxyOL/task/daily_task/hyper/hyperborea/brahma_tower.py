import traceback
from ZmxyOL.task.task_register import register_task
from ZmxyOL import *
from AutoScriptor import *
from logzero import logger

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
    bg.add(
        name="FTT_battle",
        identifier=T("确认"),
        callback=lambda: [
            bg.set_signal("try_exit", True),
            bg.clear(),
        ]
    )
    cnt = 1
    bg.set_signal("try_exit", False)
    while not bg.signal("try_exit"):
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
        click(T("入劫"))
        battle()
        wait_for_appear(T("入劫"))


@register_task
def fanTianTa(battle_times=1):
    ensure_in("极北",-1)
    click(B(0,120,90,100))
    sleep(3)
    click(T("现在"),offset=(0,100))
    sleep(3)
    click(T("确认"), if_exist=True)
    sleep(5)
    for _ in range(battle_times):
        FTT_battle_one_round()
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