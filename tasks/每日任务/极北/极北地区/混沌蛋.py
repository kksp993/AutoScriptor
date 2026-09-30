from ZmxyOL import *
from AutoScriptor import *
from AutoScriptor.logging.logger import logger
# """
@register_task(
    description="扫荡极北混沌蛋。",
    reschedule="daily",
)
def scan_chaos_egg():
    """目前只能扫 170w 的蛋。"""
    ensure_in("极北")
    logger.info("====混沌蛋_lv_170====")
    for _ in range(3):
        if ui_T(I(key="一键扫荡"),2): 
            click(B(820,155,110,20))
            click(T("确定"))
            sleep(4)
