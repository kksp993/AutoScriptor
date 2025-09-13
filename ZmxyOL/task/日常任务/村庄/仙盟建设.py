import traceback
from ZmxyOL.task.task_register import register_task
from ZmxyOL import *
from AutoScriptor import *


@register_task
def daily_alliance_task():
    logger.info("====仙盟贡献====")
    ensure_in("仙盟")
    sleep(1)
    click(B(544,340,240,140))
    click(T("议事"))
    click(B(925,220,120,40))
    click(T("确定",color="绿色"))
    wait_for_appear(T("优秀建设"))
    click(B(1200,30,30,30))
    logger.info("====日常任务====")
    sleep(2)
    click(I("导航-任务"))
    click(T("经典任务"))
    click(T("日常任务"))
    cnt = 0
    while ui_F(T("仙盟建设1")) and cnt<5:
        swipe(B(315,600),B(315,230),duration_s=0.3)
        sleep(0.2)
        cnt += 1
    if ui_T(T("仙盟建设1")):
        click(T("仙盟建设1"))
        click(T("领取奖励"))
    while ui_F(T("翡翠灵签任务")):
        click(T("限时任务"))
    click(B(1200,30,30,30))
    wait_for_appear(T("活跃任务"))
    click(B(1200,30,30,30))

if __name__ == "__main__":
    try:
        daily_alliance_task()
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)

