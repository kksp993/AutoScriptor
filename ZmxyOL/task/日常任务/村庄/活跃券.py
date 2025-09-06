import traceback
from ZmxyOL.task.task_register import register_task
from ZmxyOL import *
from AutoScriptor import *

def buy_item(item_name: str):
    if first(get_colors(T("购买", box=locate(T(item_name),timeout=10)+(0,240))))=="绿色":
        click(T(item_name),offset=(0,240),delay=0.5)
        sleep(4)

@register_task
def task():
    logger.info("====活跃券====")
    ensure_in(["村庄"])
    click(I("导航-菜单"))
    click(I("菜单-荣誉勋章"))
    click(T("荣誉商店"))
    buy_item("至尊成长礼包")
    switch_base("nemu")
    for i in range(3):
        swipe(B(600,450,10,10), B(600,100,10,10), duration_s=1)
    sleep(1)
    buy_item("活跃福利券")
    click(B(1200,30,30,30))
    sleep(1)
    click(B(1200,30,30,30))
    click(ui["菜单-背包"].i)
    sleep(1)
    click(B(430,630,30,30))
    click(I("活跃券"), if_exist=True, delay=0.5, timeout=3)
    click(T("使用"), if_exist=True, delay=0.5, timeout=2)
    click(B(1200,30,30,30))
    click(B(1200,30,30,30))


if __name__ == "__main__":
    try:
        task()
        # buy_item("至尊成长礼包")
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)

