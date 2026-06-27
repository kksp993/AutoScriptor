from ZmxyOL import *
from AutoScriptor import *
from AutoScriptor.battle_character.hero import h


@register_task
def daily_chaos_task(battle_flow: BattleFlowName = DEFAULT_BATTLE_FLOW):
    h.task(task_name="混沌火焰山·噩梦")
    h.task(task_name="混沌五指山·噩梦")
    h.task(task_name="混沌盘丝洞·噩梦")
