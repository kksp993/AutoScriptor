import traceback
from ZmxyOL.task.task_register import register_task
from ZmxyOL import *
from AutoScriptor import *
from logzero import logger

def buy(item):
    tgt = T("购买",box=locate(T(item),timeout=10)+(-20,262,180,44),color="青色")
    if ui_T(tgt,2):
        click(tgt)
        swipe(B(472,415),B(800,415))
        click(T("确定"))
        sleep(4)


@register_task
def task():
    ensure_in("幽冥冰窟")

    click(T("奖励",box=Box(37,232,84,89)))
    click(T("领取奖励"))
    sleep(1)
    click(B(898,18,67,66))

    click(T("商店"))
    click(B(276,149,125,48))
    buy("符印之匙")
    swipe(B(640,500),B(640,220))
    sleep(1)
    buy("天陨星晶")
    swipe(B(640,220),B(640,500))
    sleep(1)
    buy("精刻符")

    click(B(395,149,130,48))
    buy("随机初级灵晶礼包")
    buy("下品仙玉")
    buy("玉髓")
    swipe(B(640,500),B(640,220))
    swipe(B(640,500),B(640,220))
    sleep(1)
    buy("随机一级环境药剂")
    buy("随机二级万灵药剂")
    buy("随机三级环境药剂")

    click(B(523,158,121,39))
    buy("符印之匙")

    sleep(1)
    click(B(1200,30,30,30))

if __name__ == "__main__":
    try:
        task()
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)










