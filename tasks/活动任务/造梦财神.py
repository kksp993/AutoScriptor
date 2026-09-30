"""造梦财神：领取财神任务奖励。"""
from AutoScriptor import *
from ZmxyOL import *

from tasks.活动任务._活动流程 import run_activity


@register_task(description="领取造梦财神的财神任务奖励")
def task():
    def claim_rewards():
        swipe(B(713, 600), B(713, 286), duration_s=1)
        swipe(B(734, 618), B(734, 305), duration_s=1)
        click(T("财神任务", box=Box(796, 362, 216, 55).margin()))
        for _ in range(6):
            click_all(T("领取", box=Box(909, 418, 119, 216).margin()), if_exist=True)
            swipe(B(845, 590), B(847, 300), duration_s=1)

    run_activity("造梦财神", T("造梦财神", box=Box(220, 90, 834, 127).margin()), claim_rewards)
