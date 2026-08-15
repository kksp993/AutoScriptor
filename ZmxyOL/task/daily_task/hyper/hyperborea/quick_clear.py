from ZmxyOL import *
from AutoScriptor import *


@register_task(
    description="执行极北一键碾压。",
    task_doc="【bug】注意不会消耗祝福，如果有需求不要开启。",
    path_cn="每日任务/极北/极北地区/一键碾压",
)
def task():
    ensure_in("极北",-1)
    click(B(40,400,40,40))
    wait_for_appear(I("一键碾压-月"))
    click(B(190,155,10,10))
    click(I("一键碾压-一键碾压"))
    sleep(1)
    if ui_F(I("一键碾压-一键碾压")):
        click(T("不使用祝福"), until=lambda: ui_T(T("碾压奖励")))
        if ui_T(I("暂无可以碾压的关卡"), timeout=2):
            click(B(1040,170,30,30))
        else:
            click(B(1040,170,30,30), until=lambda: ui_F(T("碾压奖励")))
    ensure_in("极北",-1)
