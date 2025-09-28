import traceback

from AutoScriptor.control.NemuIpc.device.method.nemu_ipc import RequestHumanTakeover
from ZmxyOL.task.task_register import register_task
from ZmxyOL import *
from AutoScriptor import *
from logzero import logger

def destory_item():
    click((I("A"), I("B")))
    sleep(0.5)
    click(T("选择", color="红色"))
    click(T("炼化", box=Box(416,581,164,69)), delay=1)
    click(T("确定"))  # 炼化
    click(I("炼器炉"))
    sleep(0.5)


def make_more_for_destory(nums: int=1):
    Material_not_sufficent=False
    click(B(890,50,30,30))
    ensure_in("法相")
    sleep(1)  
    click(T("法宝"))
    click(T("获取仙宝"))
    click(B(706,566,40,40), repeat=nums)
    click(T("合成", box=Box(579,627,173,63)))
    sleep(0.5)
    if ui_F(T("确定"),timeout=2): Material_not_sufficent=True
    else: click(T("确定"))
    sleep(5)
    click(B(0,0,0,0))
    sleep(0.5)
    click(B(1200,30,30,30))
    click(T("角色"))
    click(B(1200,30,30,30),repeat=2)
    if Material_not_sufficent: raise RequestHumanTakeover("材料不足，无法炼化")
    ensure_in("炼器师")
    click(I('炼器炉'))
    sleep(0.5)
    


@register_task
def lianqishi_destory():
    ensure_in("炼器师")
    remains = extract_info(B(1000,430,130,42), lambda x: int(x.split("/")[1][:-1])-int(x.split("/")[0]))
    click(I('炼器炉'))
    wait_for_appear(T("选择仙器法宝"))
    while remains > 0:
        if ui_T((I("A"), I("B")),2):
            destory_item()
            remains -= 1
        else:
            make_more_for_destory(remains*2)
    click(B(890,50,30,30))


if __name__ == "__main__":
    try:
        # lianqishi_destory()
        locate(I("A"))
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)



