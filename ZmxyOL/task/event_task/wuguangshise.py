import traceback
from ZmxyOL.task.task_register import register_task
from AutoScriptor import *
from ZmxyOL import *

tasks =[
    "九重天",
    "凌霄宝殿",
    "玲珑塔·李天王",
    "龙宫",
    "白虎之森·终",
    "转轮殿·普通",
    "九重天",
]

@register_task
def task():
    from ZmxyOL.battle.character.hero import h
    h.battle_tasks(task_table=tasks[0])

if __name__ == "__main__":
    try:
        task()
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)