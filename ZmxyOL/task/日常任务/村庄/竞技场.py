import traceback
from ZmxyOL.task.task_register import register_task
from ZmxyOL import *
from AutoScriptor import *
from logzero import logger


@register_task
def daily_arena_task():
    ensure_in(["村庄","仙盟"])
    logger.info("====斗兽场====")
    click(I("导航-竞技"), delay=0.5)
    click(I("竞技-斗兽场"))
    click(T("加成"),delay=1)
    click(T("选择加成"))
    click(B(280,210,170,290))
    click(B(520,210,170,290))
    click(B(760,210,170,290))
    click(B(1030,110,40,40))
    click(I("斗兽场-挑战"))
    click(T("认输"))
    click(T("确定"))
    sleep(0.5)
    click(B(1210,20,40,40))
    logger.info("====竞技场====")
    click(I("竞技-决斗场"))
    click(T("决斗场"))
    click(B(970,230,80,80))
    while(ui_T(I("加载中"))): sleep(0.5)
    sleep(2)
    bg.add(
        name="try_exit",
        identifier=T("决斗场"),
        callback=lambda: bg.set_signal("try_exit", True),
    )
    h.set(True,1).jjc_battle()
    click(B(1210,20,40,40))



if __name__ == "__main__":
    try:
        daily_arena_task()
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)