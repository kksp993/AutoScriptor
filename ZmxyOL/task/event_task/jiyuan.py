from AutoScriptor import *
from ZmxyOL import *

from AutoScriptor.utils.logger import logger

@register_task
def task(battle_flow: BattleFlowName = DEFAULT_BATTLE_FLOW):
    from AutoScriptor.battle_character.hero import h
    from ZmxyOL.battle.tasks import JIYUAN_TASK_TABLE
    h.battle_tasks(task_table=JIYUAN_TASK_TABLE)
