import traceback
from enum import Enum
from ZmxyOL.task.task_register import register_task
from ZmxyOL import *
from AutoScriptor import *
from AutoScriptor.utils.logger import logger

class Method(Enum):
    """消费点券的完成方式（WebUI 下拉展示为 value，配置中仍保存成员名）"""
    YAOSHI = "购买符印之匙"
    QILING = "购买唤灵之心"
    JINFAYIN = "购买金法印"
    MUFAYIN = "购买木法印"
    # SHUIFAYIN = "购买水法印"
    # HUOFAYIN = "购买火法印"
    # TUFAYIN = "购买土法印"

@register_task
def task(method:Method=Method.YAOSHI):
    if method == Method.YAOSHI:
        ensure_in("极北村庄")
        click(I("导航-寻宝"))
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
    elif method == Method.JINFAYIN or method == Method.MUFAYIN:
        target_item = "金法印制作书" if method == Method.JINFAYIN else "木法印制作书"
        ensure_in("法相")
        click(T("法相", box=Box(312,11,95,49).margin()))
        click(T("法宝", box=Box(76,238,78,72).margin()))
        click(T("获取仙宝", box=Box(894,525,202,77).margin()))
        click(T("冶炼", box=Box(116,16,95,67).margin()))
        click(T("荒古商店", box=Box(1148,594,122,105).margin()))
        wait_for_appear(T("荒古商店", box=Box(553,0,251,102).margin()))
        swipe(B(637,605,1,1), B(637,210,1,1))
        swipe(B(637,605,1,1), B(637,210,1,1))
        click(T(target_item, box=Box(286,238,185,42).margin()), offset=(30,230))
        wait_for_appear(T(target_item, box=Box(516,107,269,39).margin()))
        click(B(820,383,67,69), repeat=3)
        click(T("确定", box=Box(713,514,158,75).margin()))
        wait_for_appear(T("荒古商店", box=Box(553,0,251,102).margin()))
        click(B(1044,52,97,78))
        wait_for_appear(T("冶炼", box=Box(116,16,95,67).margin()))
        click(B(1199,25,58,49))
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