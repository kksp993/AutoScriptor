from AutoScriptor import *
from ZmxyOL import *

from AutoScriptor.utils.logger import logger

@register_task(
    path_cn="活动任务/机缘大集副本",
    description="挑战机缘大集活动副本。",
    task_doc="【未完成】挑战机缘大集活动副本。",
)
def task(battle_flow: BattleFlowName = DEFAULT_BATTLE_FLOW):
    from AutoScriptor.battle_character.hero import h
    from ZmxyOL.battle.tasks import JIYUAN_TASK_TABLE
    h.battle_tasks(task_table=JIYUAN_TASK_TABLE)
