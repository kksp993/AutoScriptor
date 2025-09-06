import traceback
from ZmxyOL.battle.tasks import JIBEI_CHAOS_TABLE
from ZmxyOL.task.task_register import register_task
from ZmxyOL import *
from AutoScriptor import *

@register_task
def task():
    ensure_in("极北",-1)
    Weather = h.check_linggen()
    logger.info(f"当前灵气: {Weather}")
    JIBEI_CHAOS  = []
    for name in JIBEI_CHAOS_TABLE:
        if first(get_colors(get_task_table(name)["target"]))=="紫色": 
            JIBEI_CHAOS.append(name)
    logger.info(f"今日极北混沌关卡: {JIBEI_CHAOS}")
    if not JIBEI_CHAOS: return
    same_linggen_chaos = h.chaos_select(task_list=JIBEI_CHAOS, Weather=Weather)
    logger.info(f"找到与灵气相同的混沌关卡: {same_linggen_chaos}")
    # TODO: 可以按照优先级排序
    cur_task = same_linggen_chaos if same_linggen_chaos else JIBEI_CHAOS[0]
    remains = h.task_way_to_diff(task=cur_task, expect_difficulty="灵狱")
    if remains > 0:
        click(T("开始挑战"))
        h.set(has_cd=True,speed_x=3).battle_task(crash_suddenly=True)
    else:
        click(B(1200,30,30,30))
        wait_for_appear(T("回家", box=Box(18,607,87,109)))

if __name__ == "__main__":
    try:
        task()
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)