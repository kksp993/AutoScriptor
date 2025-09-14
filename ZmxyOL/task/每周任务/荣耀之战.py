import traceback
from ZmxyOL.task.task_register import register_task
from ZmxyOL import *
from AutoScriptor import *
from logzero import logger

@register_task
def task():
    ensure_in("村庄")
    click(I("导航-挑战"))
    while ui_F(T("荣耀之战")):
        swipe(B(1000, 300), B(700, 300), duration_s=0.5)
    click(T("荣耀之战"))
    for i in range(5):
        wait_for_appear(T("荣耀之战",box=Box(510, 0, 250, 80)))
        sleep(3)
        if first(get_colors(T("挑战",box=Box(894,569,190,72))))=="灰色":
            break
        click(T("挑战",box=Box(894,569,190,72)))
        bg.add(
            name="try_exit",
            identifier=T("确定"),
            callback=lambda: [
                bg.set_signal("try_exit", True),
                bg.clear(),
                click(T("确定"))
            ]
        )
        h.set(True,1).battle_loop(battle_weight=100)
        click(B(1090,25,30,30))
    sleep(2)
    click(B(1200,30,30,30))
    wait_for_appear(I("挑战-取经"))
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