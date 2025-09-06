import traceback
from ZmxyOL.task.task_register import register_task
from ZmxyOL import *
from AutoScriptor import *

@register_task
def task():
    ensure_in("村庄")
    click(I("导航-战令"))
    wait_for_appear(T("购买等级"))
    click(B(105,244,34,124))
    sleep(1)
    while ui_T(T("完成",color="绿色")):
        click(T("完成",color="绿色"),if_exist=True)
        sleep(0.5)
    click(B(1200,30,30,30))


if __name__ == "__main__":
    try:
        task()
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)

