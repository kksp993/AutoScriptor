import traceback
from ZmxyOL.task.task_register import register_task
from ZmxyOL import *
from AutoScriptor import *
@register_task
def fanTianTa():
    ensure_in("极北",-1)
    click(B(0,120,90,100))
    sleep(3)
    click(B(30,30,30,30))
    sleep(3)
    click(B(30,30,30,30))



if __name__ == "__main__":
    try:
        fanTianTa()
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)