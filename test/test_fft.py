from AutoScriptor import *
from ZmxyOL.nav import *
import traceback

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
        callback=lambda: [bg.set_signal("try_exit", True),bg.remove("FTT_battle")]
    )
    cnt = 1
    while not bg.signal("try_exit",False):
        if cnt % 5 == 0:
            h.skill(6)
        else:
            h.skill(5,1)
        cnt += 1
    click(T("确认"))
    wait_for_disappear(I("加载中"))

def control():
    final = False
    while not final:
        final = ui_T(T("终劫"))
        while ui_F(T("烦恼")):
            click(T("更替"))
            sleep(0.5)
            click(T("确定"))
            sleep(2)
        click(T("烦恼"))
        click(T("入劫"))
        battle()
        
if __name__ == "__main__":
    try:
        control()
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)