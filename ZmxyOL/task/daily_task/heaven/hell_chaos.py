from ZmxyOL import *
from AutoScriptor import *


@register_task
def daily_hell_chaos_task(battle_flow: BattleFlowName = DEFAULT_BATTLE_FLOW):
    from AutoScriptor.battle_character.hero import h
    h.task(task_name="混沌地狱官邸·噩梦")
