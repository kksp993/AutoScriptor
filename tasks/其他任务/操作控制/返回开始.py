from ZmxyOL import *
from AutoScriptor import *

@register_task(
    ensure_in="登录",
    description="从当前游戏状态返回开始界面。",
)
def task():
    ensure_in("登录")
