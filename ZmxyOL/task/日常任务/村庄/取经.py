import traceback
from ZmxyOL.task.task_register import register_task
from ZmxyOL import *
from AutoScriptor import *
@register_task
def daily_qujing_task():
    ensure_in("村庄")
    logger.info("====取经====")
    click(B(10,10,10,10))
    click(I("导航-挑战"))
    click(I("挑战-取经"))
    wait_for_appear(T("刷新"))
    if ui_F(T("取经-立即完成")):
        if ui_T(T("领取奖励")):
            click(T("领取奖励"))
            click(I("取经-取经"))
            click(I("取经-开始取经"))
        else:
            click(I("取经-立即完成"))
            click(T("确定"))
    sleep(2)
    click(B(35,620,60,60))
    wait_for_appear(I("挑战-取经"))
    sleep(0.5)
    click(B(1200,30,30,30))


if __name__ == "__main__":
    try:
        daily_qujing_task()
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)


