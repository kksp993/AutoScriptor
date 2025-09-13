import traceback
from AutoScriptor.core.api import _locate_all
from ZmxyOL.task.task_register import register_task
from ZmxyOL import *
from AutoScriptor import *

def reset_task():
    if extract_info(B(1053,581,213,48), lambda x: int(x.strip()[-1])==0):
        logger.info("今日天选阁已通关")
        return False
    click(T("重置"))
    click(T("确定"),if_exist=True,timeout=2)
    sleep(2)
    return True

@register_task
def task():
    print(cfg["weekday"])
    if cfg["weekday"] in [1,2,3,4]:
        logger.info(f"今日{cfg['weekday']}为周一至周四，不进行天选阁任务")
        return
    ensure_in("村庄")
    click(T("挑战"))
    click(T("天选阁"))
    wait_for_appear(T("回家", box=Box(18,607,87,109)))
    sleep(1)
    not_finish = True
    task_idx = -1
    while not_finish:
        if task_idx == -1:
            task_arr = []
            task_arr.extend(simple(get_colors((T(f"第{i}关") for i in (1,2,3)), offset=(120,120), resize=(80,80))))
            swipe(B(800,300,),B(200,300))
            task_arr.extend(simple(get_colors((T(f"第{i}关") for i in (4,5)), offset=(120,120), resize=(80,80))))
            swipe(B(200,300,),B(800,300))
            task_idx = 1
            logger.info(f"当前关卡状态: {task_arr}")
            if "灰色" in task_arr:
                task_idx = task_arr.index("灰色")
            else:
                task_idx = len(task_arr)
        else:
            task_idx += 1
        logger.info(f"准备开始第{task_idx}关")
        swipe(B(800,300,),B(200,300)) if task_idx>3 else None
        sleep(2)
        click(T(f"第{task_idx}关"))
        if task_idx==5 and ui_F(I("加载中"),2):
            if not reset_task(): break
            not_finish = False
            continue
        bg.add(
            name="天选战斗结束",
            identifier=(T("胜利"),T("确定")),
            callback=lambda : [
                logger.info("战斗结束"),
                bg.set_signal("try_exit", True),
                bg.set_signal("failed", True),
                click(T("确定"),repeat=2),
                h.heaven_draw_card_exit(),
                bg.clear(),
            ]
        )
        h.set(True,3).battle_task(crash_suddenly=True)
        if ui_T(T("恭喜本次通关，请重置或等待"),timeout=3):
            click(T("确定"))
            sleep(1)
            if not reset_task(): break
            not_finish = False
    click(T("回家", box=Box(18,607,87,109)))
    wait_for_appear(T("天选阁"))
    sleep(0.5)
    click(B(1200,30,30,30))



if __name__ == "__main__":
    try:
        task()
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)

