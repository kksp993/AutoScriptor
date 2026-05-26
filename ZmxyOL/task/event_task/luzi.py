import traceback
from AutoScriptor import *
from ZmxyOL import *

from AutoScriptor.utils.logger import logger

@register_task
def task(battle_loop: int = 1000, battle_flow: BattleFlowName = DEFAULT_BATTLE_FLOW):
    from ZmxyOL.battle.character.hero import h
    TASK_TABLE_LIST = [
        "龙宫",
        # "九重天",
        # "南天王殿·精英",
        "南天王殿·终",
        "西天王殿·精英",
        # "西天王殿·终",
        # "北天王殿·终",
        # "彩虹楼",
        # "东天王殿", 
        # "朝会殿",
        "凌霄宝殿",
    ]
    h.battle_tasks(task_table=TASK_TABLE_LIST)

if __name__ == "__main__":
    try:
        task(battle_loop=7)
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)