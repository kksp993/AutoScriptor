import traceback
from ZmxyOL.task.task_register import register_task
from AutoScriptor import *
from ZmxyOL import *

from AutoScriptor.utils.logger import logger

@register_task
def task():
    ensure_in("村庄")
    while ui_T(T("仙盟",box=Box(16,30,924,400))):
        click(I("导航-按钮展开"))
        sleep(2)
    if (tgt:=locate(I("腾蛇飞升",box=Box(0,0,640,360))))is None: return
    click(B(*tgt))
    click(T("辉月之路"))
    for ii in range(3):
        click(B(425+225*ii,495))
        click(B(600,300))
    swipe(B(970,495,30,30), B(200,495,30,30))
    sleep(1)
    for ii in range(1,3):
        click(B(425+225*ii,495))
        click(B(600,300))
    click(B(1200,30,30,30))
    wait_for_appear(T("天赋晋升"))
    click(B(1200,30,30,30))

if __name__ == "__main__":

    try:
        task()
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)