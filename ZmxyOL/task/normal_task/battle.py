from AutoScriptor import *
from ZmxyOL import *
import traceback

@register_task
def task(
    speed_x:int=3,
    has_cd:bool=True,
    battle_weight:int=3,
    battle_flow: BattleFlowName = DEFAULT_BATTLE_FLOW,
):
    from ZmxyOL.battle.character.hero import h
    h.set(has_cd, speed_x).battle_loop(battle_weight=battle_weight)


