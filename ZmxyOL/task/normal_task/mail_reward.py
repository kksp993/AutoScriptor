"""一般任务：领取邮件奖励。"""

from AutoScriptor import *
from ZmxyOL import *


@register_task(
    path_cn="一般任务/领取邮件",
    description="进入村庄后打开邮件并点击一键领取。",
    debug_mode=True,
)
def task():
    ensure_in("村庄")
    click(T("邮件", box=Box(33, 45, 868, 74).margin()))
    click(T("键领取", box=Box(532, 551, 214, 90).margin()))
    sleep(3)
    click(B(981, 73, 1, 1))
