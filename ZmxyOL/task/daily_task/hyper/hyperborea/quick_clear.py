from ZmxyOL import *
from AutoScriptor import *


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
