import traceback

from logzero import logger
from ZmxyOL.nav.api import locate_region
from ZmxyOL.task.task_register import register_task
from ZmxyOL import *
from AutoScriptor import *
from ZmxyOL.battle.character.hero import h
from time import time

def bonus_callback():
    click(B(1015,85))
    start = time()
    while bg.signal("try_exit") and time() - start < 120:
        click(I("地鼠", color="蓝色"), if_exist=True, save_screenshot=False)

def battle_callback(cancel_on_failed:bool=True):
    from ZmxyOL.battle.character.hero import h
    def failed_callback():
        bg.clear()
        bg.set_signal("try_exit", True)
        bg.set_signal("bonus_x", 0)
        bg.set_signal("failed", True)
    bg.add(
        name="战斗失败",
        identifier=((T("198点券"),T("159点券"),T("复活"))),
        callback=lambda : [
            switch_base("mumu"),
            logger.info("战斗结束"),
            bg.set_signal("failed", True),
            switch_base("mumu"),
            click(T("取消" if cancel_on_failed else "确定"),delay=4,repeat=3),
            failed_callback() if cancel_on_failed else None,
        ]
    )
    bg.add(
        name="通关失败",
        identifier=(T("重新挑战")),
        callback=lambda : [
            switch_base("mumu"),
            logger.info("战斗结束"),
            bg.set_signal("Failed", True),
            switch_base("mumu"),
            click(T("重新挑战")),
            failed_callback(),
        ]
    )
    wait_for_disappear(I("加载中"))
    h.set(True,3).battle_loop()


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
def task2():
    task()
    task()

def task():
    ensure_in("外域区域")
    click(T("信标定位",box=Box(1040,600,110,-1)))
    wait_for_appear(T("定位完成"))
    click(B(630,360))
    wait_for_appear(T("总灵根值"))
    click(B(960,510,90,90))
    if tgt:=locate((T("本次登录不再提醒"), T("都已通关")), timeout=3): 
        click(B(560,415))
        sleep(0.5)
        click(T("确定"))
    if tgt:=locate(T("购买"), timeout=3): 
        click(T("取消"))
        click(B(1225,150),until=lambda: ui_T(T("定位完成")))
        click(T("关闭定位"))
        logger.info("当前免费任务已经完成，荒古挑战结束")
        return
    if ui_T(I("加载中"), timeout=0.5):
        wait_for_disappear(I("加载中"))
    
    bg.set_signal("task_done", False)
    def callback():
        bg.set_signal("Pause_battle", True)
        bg.set_signal("try_exit", True)
        click(T("继续挑战"),delay=1)
        if ui_T(T("购买"),2):
            click(T("取消"),if_exist=True)
            sleep(0.5)
            click(T("确认",color="蓝色"))
            bg.set_signal("task_done", True)
            bg.clear()
        else:
            click(T("确定"),if_exist=True)
            if ui_T(I("加载中"), timeout=0.5):
                wait_for_disappear(I("加载中"))
            bg.set_signal("Pause_battle", False)


    while not bg.signal("task_done"):
        bg.add(
            name="try_pause",
            identifier=(T("继续挑战"),I("荒古-通关成功")),
            callback=callback,
        )
        if bg.signal("Pause_battle"): sleep(1);continue
        if ui_T(T("土行孙"),1): bonus_callback()
        else: battle_callback()
    click(B(30,30,30,30),until=lambda: ui_T((T("荒古万界"),I("导航-菜单"),T("世界地图"))))
    click(B(1200,30,30,30))
    bg.clear(clear_signals=True)
    locate_region()





if __name__ == "__main__":
    try:
        task()
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)
