import traceback
from ZmxyOL.task.task_register import register_task
from ZmxyOL import *
from AutoScriptor import *
from logzero import logger

@register_task
def task():
    ensure_in("极北",-1)
    click(B(40,400,40,40))
    wait_for_appear(I("一键碾压-月"))
    click(B(190,155,10,10))
    click(I("一键碾压-一键碾压"))
    sleep(1)
    if ui_F(I("一键碾压-一键碾压")):
        click(T("不使用祝福"), until=lambda: ui_T(T("碾压奖励")))
        click(B(1040,170,30,30), until= lambda: ui_F(I("暂无可以碾压的关卡")))
    ensure_in("极北",-1)


if __name__ == "__main__":
    try:
        task()
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)