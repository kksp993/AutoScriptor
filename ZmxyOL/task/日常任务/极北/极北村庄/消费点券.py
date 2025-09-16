import traceback
from enum import Enum
from ZmxyOL.task.task_register import register_task
from ZmxyOL import *
from AutoScriptor import *
from logzero import logger

class Method(Enum):
    """消费点券的方法"""
    # 符印之匙
    YAOSHI = "符印之匙"
    # 唤灵之心
    QILING = "唤灵之心"

@register_task
def task(method:Method=Method.YAOSHI):
    if method == Method.YAOSHI:
        ensure_in("极北村庄")
        click(T("寻宝"))
        wait_for_appear(T("符印寻宝"))
        click(B(1043,39,54,56))
        click(T("确定"))
        wait_for_disappear(T("购买数量"))
        sleep(1)
        click(B(1200,30,30,30))
    elif method == Method.QILING:
        ensure_in("极北村庄")
        click(T("器灵"))
        click(T("普通召唤"))
        click(B(1224,43,23,22))
        click(T("确定"))
        wait_for_disappear(T("购买数量"))
        sleep(1)
        click(B(24,31,69,55))
    else:
        raise ValueError(f"不支持的方法: {method}")



if __name__ == "__main__":
    try:
        task()
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)