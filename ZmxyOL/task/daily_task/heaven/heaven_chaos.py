import traceback
from ZmxyOL import *
from AutoScriptor import *
from ZmxyOL.battle.character.hero import h


@register_task(description="依次通关天庭混沌噩梦：火焰山、五指山、盘丝洞。")
def daily_chaos_task(battle_flow: BattleFlowName = DEFAULT_BATTLE_FLOW):
    h.task(task_name="混沌火焰山·噩梦")
    h.task(task_name="混沌五指山·噩梦")
    h.task(task_name="混沌盘丝洞·噩梦")


if __name__ == "__main__":
    try:
        daily_chaos_task()
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)
