import functools
import traceback
from AutoScriptor import *
from ZmxyOL import *

from AutoScriptor.utils.logger import logger

from ZmxyOL.task.event_task.hd_registry import HD_TASK_TABLE
from ZmxyOL.task.event_task.hd_details import *





@register_task
def task():
    assert HD_TASK_TABLE, "No HD tasks found"
    print(f"Found {len(HD_TASK_TABLE)} HD tasks")
    print(HD_TASK_TABLE)
    idfs = [idf for idf in HD_TASK_TABLE.keys()]
    bxs = locate(idfs)
    print(bxs)
    task_dict = {B(*bxs[i]): HD_TASK_TABLE[idfs[i]] for i in range(len(bxs)) if bxs[i] is not None}
    print(task_dict)
    raise ValueError("Stop here")
    ensure_in("村庄")
    click(I("导航-活动"))
    wait_for_appear(T("签到"))
    for i in range(4):
        swipe(B(1000,150,0,0), B(350,150,0,0), duration_s=1)
        locate(HD_TASK_TABLE.keys())




if __name__ == "__main__":

    try:
        task()
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)