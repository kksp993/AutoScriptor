import traceback
from ZmxyOL import *
from AutoScriptor import *


@register_task
def daily_hell_chaos_task(battle_flow: BattleFlowName = DEFAULT_BATTLE_FLOW):
    from ZmxyOL.battle.character.hero import h
    h.task(task_name="混沌地狱官邸·噩梦")




if __name__ == "__main__":
    try:
        daily_hell_chaos_task()
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)
