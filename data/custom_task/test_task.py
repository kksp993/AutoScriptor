"""自定义任务调试探针。

data/custom_task 下必须在 @register_task 中传入 path_cn（cfg 中的中文路径，斜杠分隔）。
"""

from ZmxyOL.task.task_register import register_task
from AutoScriptor import *


def task_1():
    equipment = "万千花篮"
    from AutoScriptor.utils.logger import logger
    if ui_F(T("须弥鼎", box=Box(1153,184,126,50).margin())):
        click(T("菜单", box=Box(1151,24,98,77).margin()))
    click(T("须弥鼎", box=Box(1153,184,126,50).margin()), offset=(0,-20))
    while ui_F(I(equipment)):
        click(I("炼丹炉-进阶-右"),if_exist=True)
        sleep(1)
    swipe(I(equipment),I("炼丹炉-进阶-添加装备"),duration_s=1)
    sleep(1)
    click(I("炼丹炉-批量进阶"))
    sleep(0.5)
    click(I("炼丹炉-选择全部"))
    sleep(0.5)
    click(T("确定进阶"))
    sleep(1)
    click(T("确定",color="绿色"))
    click(B(1204,21,47,42),until=lambda:ui_T(T("菜单", box=Box(1151,24,98,77).margin())),interval=1)
    sleep(1)
    click(T("菜单", box=Box(1151,24,98,77).margin()))
    




@register_task(
    path_cn="自定义任务/调试/测试1",
    description="不操作游戏，用于验证自定义任务加载、参数注入和 debug 直跑链路。",
    task_doc=(
        "这是一个安全的自定义任务调试探针。默认只写日志，不点击、不截图、不改变游戏状态；"
        "打开 fail 可主动抛错，用来验证 debug_mode 下失败不会关闭或重启游戏。"
    ),
    debug_mode=True,
)
def test_task():
    for i in range(5):
        task_1()
        sleep(1)
    # fail = True