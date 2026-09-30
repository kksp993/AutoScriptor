"""成长活动：领取开服冲级、冲战力、飞升三档奖励。"""
from AutoScriptor import *
from ZmxyOL import *

from tasks.活动任务._活动流程 import run_activity


@register_task(description="领取成长活动的冲级、战力、飞升奖励")
def task():
    def claim_rewards():
        for entry_text, entry_box, scrolls in (
            ("开服冲级迎大礼", Box(203, 269, 250, 66), 10),
            ("冲战力赢奖励", Box(187, 339, 238, 87), 6),
            ("飞升奖励", Box(214, 446, 203, 70), 2),
        ):
            click(T(entry_text, box=entry_box.margin()))
            for _ in range(scrolls):
                click_all(T("领取", box=Box(879, 302, 190, 367).margin()), if_exist=True)
                swipe(B(845, 590), B(847, 300), duration_s=1)

    run_activity("成长活动", T("成长活动", box=Box(220, 90, 834, 127).margin()), claim_rewards)
