from ZmxyOL import *
from AutoScriptor import *

@register_task(
    path_cn="一般任务/返回开始",
    description="从当前游戏状态返回开始界面。",
)
def task():
    ensure_in("登录")
