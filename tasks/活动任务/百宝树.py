"""百宝树：领取宝树奖励，并处理宝树护理。

护理分支在“数量不足”时调用 ``_补充宝树``，该流程尚未实现——命中该分支会记一条
warning 并结束，不会中断其他活动任务。
"""
from AutoScriptor import *
from ZmxyOL import *

from tasks.活动任务._活动流程 import run_activity


@register_task(description="领取百宝树的宝树奖励与宝树护理")
def task():
    def claim_rewards():
        swipe(B(713, 600), B(713, 286), duration_s=1)
        swipe(B(734, 618), B(734, 305), duration_s=1)
        click(T("宝树任务", box=Box(796, 362, 216, 55).margin()))
        for _ in range(3):
            click_all(T("领取", box=Box(909, 418, 119, 216).margin()), if_exist=True)
            swipe(B(845, 590), B(847, 300), duration_s=1)

        click(B(464, 272, 48, 52))
        sleep(1)
        swipe(B(713, 600), B(713, 286), duration_s=1)
        swipe(B(734, 618), B(734, 305), duration_s=1)
        click(T("宝树护理", box=Box(796, 427, 215, 58).margin()))
        swipe(B(713, 600), B(713, 286), duration_s=1)
        swipe(B(734, 618), B(734, 305), duration_s=1)

        status_box = locate(T("当前异常状态"))
        if not status_box:
            logger.warning("当前尚未种植宝树，跳过护理")
            return
        status = extract_info(
            status_box + (80, 0),
            post_process=lambda s: s.replace("：", ":").split(":")[1].strip(),
            ensure_not_empty=True,
            mode="text",
        )
        click(T("确认", box=status_box + (Box(929, 521, 85, 50) - Box(555, 543, 137, 29))))
        click(T("确定", box=Box(658, 374, 144, 84).margin()))
        if ui_T(T("数量不足", box=Box(617, 322, 236, 83).margin())):
            logger.warning("宝树护理材料不足（%s），跳过补充流程", status)

    run_activity("百宝树", T("百宝树", box=Box(220, 90, 834, 127).margin()), claim_rewards)
