"""自定义任务调试探针。

data/custom_task 下必须在 @register_task 中传入 path_cn（cfg 中的中文路径，斜杠分隔）。
"""

from AutoScriptor.control.MumuAdaptor.constant import AndroidKey
from ZmxyOL.nav.api import ensure_in
from ZmxyOL.task.task_register import register_task
from AutoScriptor import *





@register_task(
    path_cn="自定义任务/调试/异兽入侵",
    description="不操作游戏，用于验证自定义任务加载、参数注入和 debug 直跑链路。",
    task_doc=(
        "这是一个安全的自定义任务调试探针。默认只写日志，不点击、不截图、不改变游戏状态；"
        "打开 fail 可主动抛错，用来验证 debug_mode 下失败不会关闭或重启游戏。"
    ),
    debug_mode=True,
)
def test_task():
    ensure_in("荒古万界")
    click(T("万界穿梭"));sleep(1)
    click(T("荒古巨兽"),until=lambda: ui_T(T("荒古灵机",box=Box(118,113,123,32).margin())))
    click(T("异兽入侵", box=Box(192,657,110,52).margin()), timeout=3)