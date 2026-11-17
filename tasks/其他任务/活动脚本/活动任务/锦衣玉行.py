

"""锦衣玉行：领取见闻奖励，分次种植和收获灵脉异种。"""
from AutoScriptor import *
from ZmxyOL import *

from tasks.其他任务.活动脚本.活动任务._活动流程 import run_activity


@register_task(
    ensure_in="村庄",
    description="领取锦衣玉行奖励，每隔三分钟继续种植和收获",
    reschedule="daily",
)
def task():
    def claim_rewards():
        seq_click([T("锦衣玉行", box=Box(678,166,110,44).margin()) ])

        click(T("仙游见闻", box=Box(202,370,155,36).margin()))
        click(T("领取", box=Box(927,236,155,363).margin()), if_exist=True, until=lambda x: ui_F(T("领取", box=Box(927,236,155,363).margin())))
        swipe(B(731,526), B(731,294), duration_s=1)
        click(T("领取", box=Box(927,236,155,363).margin()), if_exist=True, until=lambda x: ui_F(T("领取", box=Box(927,236,155,363).margin())))

        click(T("灵脉异种", box=Box(204,424,221,92).margin()))
        info_1=info_2=0
        if ui_T(T("收获", box=Box(702,552,119,55).margin())):
            click(T("收获", box=Box(702,552,119,55).margin(), color="绿色"))
            click(T("确定", box=Box(653,373,172,102).margin()))
        info_1 = extract_info(B(665,600,147,39), post_process=postnum, ensure_not_empty=True, mode="text")
        if info_1>0:
            click(T("种植", box=Box(702,552,119,55).margin()))


        if ui_T(T("收获", box=Box(904,551,114,47).margin())):
            click(T("收获", box=Box(904,551,114,47).margin(), color="绿色"))
            click(T("确定", box=Box(653,373,172,102).margin()))
        info_2 = extract_info(B(882,603,136,34), post_process=postnum, ensure_not_empty=True, mode="text")
        if info_2>0:
            click(T("种植", box=Box(904,551,114,47).margin()))
        finish_all = info_1 == 0 and info_2 == 0
        if not finish_all:
            set_task_next_run(3 * 60)

    run_activity("锦衣玉行", T("锦衣玉行", box=Box(220, 90, 834, 127).margin()), claim_rewards)
