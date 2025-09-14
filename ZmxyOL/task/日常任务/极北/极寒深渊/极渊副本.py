import traceback
from ZmxyOL.task.task_register import register_task
from ZmxyOL import *
from AutoScriptor import *
from logzero import logger

@register_task
def task():
    from ZmxyOL.battle.tasks import JHSY_CHAOS_TABLE, get_task_table
    logger.info("====极寒深渊====")
    ensure_in("极寒深渊")
    Weather = h.check_linggen()
    logger.info(f"当前灵气: {Weather}")
    same_linggen_chaos = h.chaos_select(task_list=JHSY_CHAOS_TABLE, Weather=Weather)
    logger.info(f"找到与灵气相同的混沌关卡: {same_linggen_chaos}")
    cur_task = same_linggen_chaos if same_linggen_chaos else JHSY_CHAOS_TABLE[0]
    remains = h.task_way_to_diff(task=cur_task, expect_difficulty="灵狱")
    if remains > 0:
        logger.info(f"开始挑战: {cur_task}")
        bonus_x = extract_info(B(290,570,100,30), lambda x: 1 if x.strip() == "普通" else int(x.strip()[-1]))
        repeat = (3 - bonus_x) % 3
        click(B(430,570,30,30), repeat=repeat)
        click(T("开始挑战"))
        h.set(has_cd=True,speed_x=3).battle_task(crash_suddenly=True, bonus_x=3)
    else:
        click(B(1200,30,30,30))
        wait_for_appear(T("回家", box=Box(18,607,87,109)))

    logger.info("====极寒深渊-噩梦====")
    for name in JHSY_CHAOS_TABLE:
        if name == cur_task: continue
        remains = h.task_way_to_diff(task=name, expect_difficulty="噩梦")
        if remains > 0:
            logger.info(f"开始挑战: {name}")
            bonus_x = extract_info(B(290,570,100,30), lambda x: 1 if x.strip() == "普通" else int(x.strip()[-1]))
            repeat = (3 - bonus_x) % 3
            click(B(430,570,30,30), repeat=repeat) 
            click(T("开始挑战"))
            h.set(has_cd=True,speed_x=3).battle_task(bonus_x=3, has_loading_after_battle=True, exit_loc=get_task_table(name)["exit_loc"])
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