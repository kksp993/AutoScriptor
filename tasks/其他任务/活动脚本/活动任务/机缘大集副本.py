from AutoScriptor import *
from ZmxyOL import *

from AutoScriptor.logging.logger import logger

@register_task(
    description="挑战机缘大集活动副本。",
    reschedule="daily",
)
def task(battle_flow: BattleFlowName = DEFAULT_BATTLE_FLOW):
    """【未完成】挑战机缘大集活动副本。"""
    from ZmxyOL.character.hero import h
    from ZmxyOL.battle.tasks import JIYUAN_TASK_TABLE
    h.battle_tasks(task_table=JIYUAN_TASK_TABLE)
