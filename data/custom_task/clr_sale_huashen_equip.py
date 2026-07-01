
from AutoScriptor.control.MumuAdaptor.constant import AndroidKey
from ZmxyOL.nav.api import ensure_in
from ZmxyOL.nav.envs.decorators import HAS_SHEZHI
from ZmxyOL.task.task_register import register_task
from AutoScriptor import *


@register_task(
    path_cn="自定义任务/背包清空/出售化身装备",
    description="一键清空化身装备背包",
    task_doc=(
        "【特别注意】：在使用此功能前，请先确认化身装备背包中没有需要保留的装备，否则会被清空！"
    ),
    debug_mode=True,
)
def test_task():
    ensure_in(HAS_SHEZHI)
    click(I("导航-菜单"), delay=1)
    click(T("身外化身", box=Box(294,21,98,119).margin()))
    click(T("化身背包", box=Box(118,614,119,96).margin()))
    click(T("装备", box=Box(296,37,150,96).margin()))
    while True:
        info = extract_info(B(234,630,150,48), post_process=lambda s: int(s.strip().split("/")[1]), ensure_not_empty=True)
        # 当1/1时额外触发一轮
        click(T("批量出售", box=Box(808,613,114,65).margin()))
        click(T("全选", box=Box(529,602,136,87).margin()))
        click(T("键出售", box=Box(808,613,113,65).margin()))
        click(T("确定", box=Box(964,568,165,87).margin()), if_exist= (info == 1) );sleep(1)
        if info == 1: break
    click(B(1199,10,51,68));sleep(1)
    click(B(1165,12,83,63));sleep(1)
    click(I("导航-菜单"), delay=1)
    return True