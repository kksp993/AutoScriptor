from AutoScriptor import *
from ZmxyOL import *

from AutoScriptor.utils.logger import logger

@register_task
def task(battle_loop: int = 1000, battle_flow: BattleFlowName = DEFAULT_BATTLE_FLOW, equipment: str = "诛仙剑阵"):
    from AutoScriptor.battle_character.hero import h
    h.set(has_cd=False, speed_x=3)
    h.kunlunshan_task(battle_loop=battle_loop, equipment=equipment)
