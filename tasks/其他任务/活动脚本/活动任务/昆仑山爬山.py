from AutoScriptor import *
from ZmxyOL import *

from AutoScriptor.logging.logger import logger

@register_task(
    ensure_in="天庭#1",
    description="执行活动版昆仑山爬山流程。",
    reschedule="daily",
    params_doc={"battle_loop": "战斗循环次数", "battle_flow": "战斗招式", "equipment": "须弥鼎进阶装备"},
)
def task(battle_loop: int = 1000, battle_flow: BattleFlowName = DEFAULT_BATTLE_FLOW, equipment: str = "诛仙剑阵"):
    """【未完成】执行活动版昆仑山爬山流程。"""
    from ZmxyOL.character.hero import h
    h.set(has_cd=False, speed_x=3)
    h.kunlunshan_task(battle_loop=battle_loop, equipment=equipment, entry_ready=True)
