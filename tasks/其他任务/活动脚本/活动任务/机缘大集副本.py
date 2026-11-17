from AutoScriptor import *
from ZmxyOL import *

from AutoScriptor.logging.logger import logger

@register_task(
    ensure_in="天庭#4",
    description="挑战机缘大集活动副本。",
    reschedule="daily",
    params_doc={"battle_flow": "战斗招式"},
)
def task(battle_flow: BattleFlowName = DEFAULT_BATTLE_FLOW):
    """【未完成】挑战机缘大集活动副本。"""
    from ZmxyOL.character.hero import h
    from ZmxyOL.battle.tasks import JIYUAN_TASK_TABLE
    h.battle_tasks(task_table=JIYUAN_TASK_TABLE, entry_ready=True)
