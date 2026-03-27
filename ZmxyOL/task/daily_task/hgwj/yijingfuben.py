from calendar import weekday
import datetime
import enum
import traceback

from AutoScriptor.utils.logger import logger

from ZmxyOL.nav.api import locate_region
from ZmxyOL.task.task_register import register_task
from ZmxyOL import *
from AutoScriptor import *
from ZmxyOL.battle.character.hero import h


class YijingNandu(str, enum.Enum):
    不打 = "不打"
    初难 = "初难"
    灾厄 = "灾厄"
    浩劫 = "浩劫"




@register_task
def task(
    HuShenZhiYa:YijingNandu=YijingNandu.不打,
    CangLongYouGu:YijingNandu=YijingNandu.不打,
    MingHaiZhiYuan:YijingNandu=YijingNandu.不打,
    cancel_on_failed:bool=True,
):
    task_list={
        "虎神之崖":(T("虎神之崖", box=Box(106,389,94,37).margin()), HuShenZhiYa),
        "苍龙幽谷":(T("苍龙幽谷", box=Box(183,598,116,73).margin()), CangLongYouGu),
        "溟海之渊":(T("溟海之渊", box=Box(557,332,218,95).margin()), MingHaiZhiYuan),
    }
    diff_list={
        "初难":1,
        "灾厄":2,
        "浩劫":3,
    }
    for name, (task, nandu) in task_list.items():
        if nandu == YijingNandu.不打:
            logger.info(f"{name} 不打")
            continue
        for _ in range(2):
            ensure_in("洪荒遗境")
            click(task)

            remains = extract_info(B(853,390,220,51), post_process=lambda s: int(s.strip()[-2]), ensure_not_empty=True)
            if remains == 0: continue
            
            diff = extract_info(B(220,474,230,62), post_process=lambda s: s.strip(), ensure_not_empty=True)
            diff_repeat = (diff_list[nandu] - diff_list[diff]) % 3
            click(B(401,494,31,29), repeat=diff_repeat)

            bonus_x = extract_info(B(241,592,103,53), post_process=lambda s: 1 if s.strip() == "普通" else int(s.strip()[-1]), ensure_not_empty=True)
            bonus_repeat = (remains - bonus_x) % 3
            click(B(344,577,73,81), repeat=bonus_repeat)
            bonus_x = extract_info(B(241,592,103,53), post_process=lambda s: 1 if s.strip() == "普通" else int(s.strip()[-1]), ensure_not_empty=True)

            click(T("开始挑战", box=Box(928,589,170,73).margin()))
            h.set(has_cd=True,speed_x=3).battle_task(crash_suddenly=True, bonus_x=bonus_x, cancel_on_failed=cancel_on_failed)
        


if __name__ == "__main__":
    try:
        task()
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)
