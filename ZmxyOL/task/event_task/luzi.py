from AutoScriptor import *
from ZmxyOL import *

from AutoScriptor.utils.logger import logger

@register_task
def task(battle_loop: int = 1000, battle_flow: BattleFlowName = DEFAULT_BATTLE_FLOW):
    from AutoScriptor.battle_character.hero import h
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
