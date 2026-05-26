import traceback
from AutoScriptor import *
from ZmxyOL import *

from AutoScriptor.utils.logger import logger

@register_task
def task(battle_flow: BattleFlowName = DEFAULT_BATTLE_FLOW):
    from ZmxyOL.battle.character.hero import h
    from ZmxyOL.battle.tasks import JIYUAN_TASK_TABLE
    h.battle_tasks(task_table=JIYUAN_TASK_TABLE)

if __name__ == "__main__":
    try:
        task()
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)