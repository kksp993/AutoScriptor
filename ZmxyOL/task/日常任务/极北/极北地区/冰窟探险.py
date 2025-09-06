import traceback
from ZmxyOL.task.task_register import register_task
from ZmxyOL import *
from AutoScriptor import *
@register_task
def bingkuTanXian():
    ensure_in("极北",-1)
    click(I("冰霜遗迹"),delay=1)
    sleep(1)
    ice_cave_energy = extract_info(B(970,500,100,22), lambda res: int(res.split("/")[0]) if res else 0)
    if ice_cave_energy>14:
        click(T("进入"))
        click(I("冰窟-一键扫荡"),delay=0.5)
        sleep(3),
        click(B(925,240,30,30))
        click(B(925,340,30,30))
        click(B(925,440,30,30))
        click(B(575,340,30,30))
        click(T("立即扫荡"))
        click(T("确定"))
        sleep(1)
        click(B(1100,30,30,30))
        wait_for_disappear(I("加载中"))
    else:
        click(B(1122,34,30,30))


if __name__ == "__main__":
    try:
        bingkuTanXian()
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)










