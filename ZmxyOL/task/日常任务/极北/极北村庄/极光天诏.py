import traceback
from ZmxyOL.task.task_register import register_task
from ZmxyOL import *
from AutoScriptor import *

@register_task
def task():
    ensure_in("极北村庄")
    sleep(3)
    click(I("极北-极光天诏"))
    wait_for_appear(I("青莲炎"))
    click(B(149,594,98,89))
    click(I("诏令任务-每日任务"))
    click(B(835,185,90,45),repeat=20)
    click(B(970,70,30,30))
    wait_for_appear(I("青莲炎"))
    click(B(60,605,30,30))
    ensure_in("极北村庄")


if __name__ == "__main__":
    try:
        task()
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)