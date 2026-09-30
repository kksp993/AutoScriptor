from AutoScriptor import *
from ZmxyOL import *

from AutoScriptor.logging.logger import logger

_KLS_DEFAULT_FLOW = BattleFlowName["昆仑山循环"]

@register_task(
    description="挑战夺回昆仑山并领取奖励。",
    reschedule="daily",
)
def task(battle_loop: int = 7, battle_flow: BattleFlowName = _KLS_DEFAULT_FLOW, equipment: str = "万千花篮"):
    """目前可能无法进入玉虚殿，请需要时手动检查该步骤。"""
    from ZmxyOL.character.hero import h
    h.set(has_cd=False, speed_x=3)
    h.kunlunshan_task(battle_loop=battle_loop, equipment=equipment)
