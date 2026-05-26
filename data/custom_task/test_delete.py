"""自定义任务调试探针。

data/custom_task 下必须在 @register_task 中传入 path_cn（cfg 中的中文路径，斜杠分隔）。
"""

from ZmxyOL.task.task_register import register_task
from AutoScriptor import *


def delete_friend(num=50):
    click(T("好友", box=Box(832,90,53,26).margin()))
    for _ in range(num):
        sleep(1)
        swipe(B(930,235,1,1), B(930,483,1,1))
        click(B(853,468,1,1))
        click(T("删除", box=Box(727,249,131,61).margin()))
        click(T("确定", box=Box(658,374,142,80).margin()))
        sleep(2)
    sleep(1)
    click(B(979,67,1,1))

# def check_



@register_task(
    path_cn="自定义任务/调试/删除好友",
    description="不操作游戏，用于验证自定义任务加载、参数注入和 debug 直跑链路。",
    task_doc=(
        "这是一个安全的自定义任务调试探针。默认只写日志，不点击、不截图、不改变游戏状态；"
        "打开 fail 可主动抛错，用来验证 debug_mode 下失败不会关闭或重启游戏。"
    ),
    debug_mode=True,
)
def test_task():
    for i in range(1):
        sleep(1)
    # fail = True