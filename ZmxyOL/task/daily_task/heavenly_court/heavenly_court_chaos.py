import traceback
from ZmxyOL.task.task_register import register_task
from ZmxyOL import *
from AutoScriptor import *



@register_task
def daily_chaos_task():
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
