import traceback
from ZmxyOL.task.task_register import register_task
from AutoScriptor import *
from ZmxyOL import *

from logzero import logger

@register_task
def task():
    from ZmxyOL.battle.character.hero import h
    from ZmxyOL.battle.tasks import JIYUAN_TASK_TABLE
    TASK_TABLE_LIST = [
        "龙宫",
        # "九重天",
        # "南天王殿·精英",
        "南天王殿·终",
        # "西天王殿·精英",
        # "西天王殿·终",
        "北天王殿·终",
        # "彩虹楼",
        # "东天王殿", 
        # "朝会殿",
        "凌霄宝殿",
    ]
    h.battle_tasks(task_table=list(set(TASK_TABLE_LIST).union(set(JIYUAN_TASK_TABLE))))

if __name__ == "__main__":
    try:
        task()
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)