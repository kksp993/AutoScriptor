from AutoScriptor import *
from ZmxyOL import *
import traceback
from ZmxyOL.task.task_register import register_task

@register_task
def task(speed_x:int=3, has_cd:bool=True, battle_weight:int=99):
    from ZmxyOL.battle.character.hero import h
    h.set(has_cd, speed_x).battle_loop(battle_weight=battle_weight)


if __name__ == "__main__":
    try:
        task()
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)
