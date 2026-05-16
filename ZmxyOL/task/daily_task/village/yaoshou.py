import traceback
from ZmxyOL import *
from AutoScriptor import *
from AutoScriptor.utils.logger import logger

@register_task(sched_window_hours=(10, 22))
def task(
    battle_flow: BattleFlowName = DEFAULT_BATTLE_FLOW,
):
    global cfg
    if cfg["weekday"] in [1,2,3,4]:
        logger.info(f"今日{cfg['weekday']}为周一至周四，不进行妖兽任务")
        return
    ensure_in("村庄")
    click(ui["导航-挑战"].i)
    click(ui["挑战-妖兽"].i)
    sleep(1)
    swipe(B(800,450,10,10), B(300,450,10,10), duration_s=2)
    sleep(3)
    click(B(881,528,39,15))
    click(B(621,525,51,19))
    click(B(364,525,45,19))
    click(T("取消"), if_exist=True, timeout=1)
    if ui_F(T("讨伐目标"), 3):
        click(B(1060,45,30,30))
    elif ui_F(T("进入",color="绿色"), 3):
        logger.info("当前妖兽任务已结束")
    else:
        click(T("进入",color="绿色"))
        sleep(1)
        wait_for_disappear(ui["加载中"].i)
        with bg.scope("妖兽") as scope:
            scope.add(
                name="战斗结束",
                identifier=(T("退出副本"),T("确定")),
                callback=lambda: [
                    logger.info("妖兽突发事件"),
                    sleep(0.03),
                    bg.set_signal("failed", True),
                    bg.set_signal("try_exit", True),
                ],
            )
            h.set(has_cd=False,speed_x=1).battle_loop(battle_weight=100000)
        click((T("退出副本"),T("确定")), delay=2)
        wait_for_appear(ui["导航-奇闻录"].i)



if __name__ == "__main__":
    try:
        task()
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)

