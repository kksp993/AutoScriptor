from AutoScriptor import *
from ZmxyOL import *

from AutoScriptor.utils.logger import logger

@register_task(
    path_cn="活动任务/昆仑山爬山",
    description="执行活动版昆仑山爬山流程。",
    task_doc="【未完成】执行活动版昆仑山爬山流程。",
)
def task(battle_loop: int = 1000, battle_flow: BattleFlowName = DEFAULT_BATTLE_FLOW, equipment: str = "诛仙剑阵"):
    from AutoScriptor.battle_character.hero import h
    h.set(has_cd=False, speed_x=3)
    h.kunlunshan_task(battle_loop=battle_loop, equipment=equipment)
