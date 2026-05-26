"""自定义任务调试探针。

data/custom_task 下必须在 @register_task 中传入 path_cn（cfg 中的中文路径，斜杠分隔）。
"""

from AutoScriptor.control.MumuAdaptor.constant import AndroidKey
from ZmxyOL.task.task_register import register_task
from AutoScriptor import *


def add_friend(user_id):
    click(T("好友", box=Box(832,90,53,26).margin()))
    sleep(1)
    click(T("加好友", box=Box(817,578,126,69).margin()))
    click(T("输入好友呢称", box=Box(452,299,228,72).margin()))
    input(user_id)
    key_event(AndroidKey.KEYCODE_ENTER)
    sleep(2)
    click(T("确定", box=Box(576,423,126,71).margin()))
    sleep(3)
    click(B(910,197,43,46));sleep(1)
    click(B(979,67,1,1))

# def check_



@register_task(
    path_cn="自定义任务/调试/添加好友",
    description="不操作游戏，用于验证自定义任务加载、参数注入和 debug 直跑链路。",
    task_doc=(
        "这是一个安全的自定义任务调试探针。默认只写日志，不点击、不截图、不改变游戏状态；"
        "打开 fail 可主动抛错，用来验证 debug_mode 下失败不会关闭或重启游戏。"
    ),
    debug_mode=True,
)
def test_task():
    add_friend("兽神峰:青颖飞帆")
    # fail = True