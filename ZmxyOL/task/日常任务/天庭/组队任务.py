
import traceback
from ZmxyOL.task.task_register import register_task
from ZmxyOL import *
from AutoScriptor import *



@register_task
def zudui_task():
    ensure_in("天庭",-1)
    click(ui["彩虹楼"].i)
    click(T("东天王殿"),delay=0.5)
    click(T("普通难度"))
    click(T("组队挑战"))
    wait_for_appear(T("队伍列表"))
    click(T("快速加入"), until=lambda: ui_T(T("我的队伍")))
    start_battle = False
    while not start_battle:
        cnt = 0
        while not start_battle:
            cnt += 1
            if cnt % 5 == 0 :
                click(B(1050,50,30,30),delay=1.5)
                click(T("快速加入"), until=lambda: ui_T(T("我的队伍")))
            click((T("开始"),T("准备")), if_exist=True, timeout=1)
            sleep(1)
            start_battle = ui_T(I("加载中"))
    h.set(True,1).heaven_battle(exit_loc=get_task_table("东天王殿")["exit_loc"])
    click(B(1050,50,30,30),delay=1.5)
    click(B(1200,30,30,30))
    wait_for_disappear(I("加载中"))


if __name__ == "__main__":
    try:
        zudui_task()
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)