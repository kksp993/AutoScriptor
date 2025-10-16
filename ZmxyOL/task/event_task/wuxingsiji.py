import traceback
from ZmxyOL.task.task_register import register_task
from AutoScriptor import *
from ZmxyOL import *

from logzero import logger

@register_task
def task(battle_loop: int = 1000):
    from ZmxyOL.battle.character.hero import h
    h.set(has_cd=False, speed_x=3)
    h.kunlunshan_task(battle_loop=battle_loop)

if __name__ == "__main__":
    try:
        task(battle_loop=7)
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)