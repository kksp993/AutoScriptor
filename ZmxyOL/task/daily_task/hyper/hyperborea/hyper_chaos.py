import traceback

from ZmxyOL.battle.procedure.chaos import DEFAULT_LINGQI_PRIORITY_VALUES, sort_stage_lingqi_pairs
from ZmxyOL.battle.tasks import JIBEI_CHAOS_TABLE, get_task_table
from ZmxyOL import *
from AutoScriptor import *
from AutoScriptor.utils.logger import logger

@register_task
def task(
    battle_flow: BattleFlowName = DEFAULT_BATTLE_FLOW,
):
    ensure_in("极北",-1)
    Weather = h.check_linggen()
    logger.info(f"当前灵气: {Weather}")
    JIBEI_CHAOS  = []
    for name in JIBEI_CHAOS_TABLE:
        if first(get_colors(get_task_table(name)["target"]))=="紫色": 
            JIBEI_CHAOS.append(name)
    logger.info(f"今日极北混沌关卡: {JIBEI_CHAOS}")
    if not JIBEI_CHAOS: return
    same_linggen_chaos, stage_lingqi_pairs = h.chaos_select(
        task_list=JIBEI_CHAOS, Weather=Weather, task_type="极北"
    )
    logger.info(f"关卡↔灵气映射: {stage_lingqi_pairs}")
    logger.info(f"与当前灵气匹配的关卡: {same_linggen_chaos}")
    if same_linggen_chaos:
        cur_task = same_linggen_chaos
    else:
        sorted_by_prio = sort_stage_lingqi_pairs(stage_lingqi_pairs, priority=DEFAULT_LINGQI_PRIORITY_VALUES)
        cur_task = sorted_by_prio[0][0] if sorted_by_prio else JIBEI_CHAOS[0]
        logger.info(f"无灵气匹配，按默认灵气优先级 fallback: {cur_task}")
    remains = h.task_way_to_diff(task=cur_task, expect_difficulty="灵狱", task_type="极北")
    if remains > 0:
        click(T("开始挑战"))
        h.set(has_cd=True,speed_x=3).battle_task(crash_suddenly=True)
    else:
        click(B(1200,30,30,30))
        wait_for_appear(T("回家", box=Box(29,613,77,88).margin()))

if __name__ == "__main__":
    try:
        task()
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)