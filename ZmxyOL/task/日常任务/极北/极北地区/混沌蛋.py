import traceback
from ZmxyOL.task.task_register import register_task
from ZmxyOL import *
from AutoScriptor import *
# """
@register_task
def scan_chaos_egg():
    ensure_in("极北")
    logger.info("====混沌蛋_lv_170====")
    for _ in range(3):
        if ui_T(I(key="一键扫荡"),2): 
            click(B(820,155,110,20))
            click(T("确定"))
            sleep(4)


if __name__ == "__main__":
    try:
        scan_chaos_egg()
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)