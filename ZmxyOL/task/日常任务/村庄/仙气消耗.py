import traceback
from ZmxyOL.task.task_register import register_task
from ZmxyOL import *
from AutoScriptor import *
from logzero import logger

@register_task
def task():
    ensure_in("仙盟")
    ensure_in("村庄")
    click(I("村庄-小仙女"),offset=(0,60))
    wait_for_appear(T("立即刷新"))
    click((I("战功"),I("仙气")),offset=(0,50))
    if ui_F(T("确定"),2):
        swipe(B(624,624,1,1), B(624,324,1,1))
        click((I("战功"),I("仙气")),offset=(0,50))
    price = extract_info(B(523,300,300,60), lambda res: int(res))
    repeat = 28888//price
    click(B(820,400,40,40), repeat=repeat)
    click(T("确定"))
    sleep(3)
    click(B(1200,30,30,30))

if __name__ == "__main__":
    try:
        task()
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)