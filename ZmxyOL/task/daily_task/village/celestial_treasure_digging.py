import traceback
from ZmxyOL.task.task_register import register_task
from ZmxyOL import *
from AutoScriptor import *
from logzero import logger

@register_task
def daily_fxiang_task():
    ensure_in("法相")
    sleep(2)
    click(T("法宝"))
    click(T("获取仙宝"))
    click(T("遗迹"))
    wait_for_appear(T("混沌遗迹"))
    click(B(300,250,250,350))
    sleep(2)
    wait_for_appear(T("每日"))
    click(B(500,300,300,200))
    sleep(1)
    click(B(727,432,135,79))
    while ui_F(T("合成")):click(B(20,20,30,30))
    click(T("遗迹"))
    click(T("魔神遗迹"))
    wait_for_appear(T("魔神遗迹"))
    click(B(750,250,250,350))
    sleep(2)
    wait_for_appear(T("每日"))
    click(B(500,300,300,200))
    sleep(1)
    click(B(727,432,135,79))
    while ui_F(T("合成")):click(B(20,20,30,30))
    click(B(1200,30,30,30))


if __name__ == "__main__":
    try:
         daily_fxiang_task()
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)