from AutoScriptor import *
from ZmxyOL import *

@register_task
def task(
    speed_x:int=3,
    has_cd:bool=True,
    battle_flow: BattleFlowName = DEFAULT_BATTLE_FLOW,
):
    from AutoScriptor.battle_character.hero import h
    flow_name = getattr(battle_flow, "value", battle_flow)
    h.set(has_cd, speed_x).battle_loop(flow_name=flow_name)


