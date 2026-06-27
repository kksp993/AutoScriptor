
from AutoScriptor.control.MumuAdaptor.constant import AndroidKey
from ZmxyOL.task.task_register import register_task
from AutoScriptor import *


@register_task(
    path_cn="自定义任务/操作设置",
    description="在操作按钮设置页面运行此程序，可以自动配置按钮位置",
    task_doc=(
        "在操作按钮设置页面运行此程序，可以自动配置按钮位置"
    ),
    debug_mode=True,
)
def test_task():
    click(T("清理数据", box=Box(360,22,147,56).margin()), timeout=3)
    click(T("重置", box=Box(548,9,125,77).margin()))
    swipe(B(979,565),B(1085,306))
    swipe(B(134,482),B(224,480))
    swipe(B(138,362),B(524,361))
    click(B(416,156,15,13))
    swipe(B(493,361),B(400,660))
    click(T("保存", box=Box(663,3,136,79).margin()), timeout=3)
    click(T("确定", box=Box(661,369,132,96).margin()), if_exist=True)
    return True