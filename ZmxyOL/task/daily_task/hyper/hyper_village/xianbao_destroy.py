
from AutoScriptor.control.NemuIpc.device.method.nemu_ipc import RequestHumanTakeover
from ZmxyOL import *
from AutoScriptor import *

def destroy_item(item_box):
    click(B(item_box))
    sleep(0.5)
    click(T("选择", color="红色"))
    click(T("确定", box=Box(733,606,137,65).margin()))
    click(T("炼化", box=Box(416,581,164,69)), delay=1)
    click(T("确定"))  # 炼化
    click(T("+", box=Box(259,374,101,112).margin()))
    sleep(0.5)


def make_more_for_destroy(nums: int=1):
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
    click(T("+", box=Box(259,374,101,112).margin()))
    sleep(0.5)
    


@register_task(
    description="执行仙宝炼化 A/B。",
    task_doc="材料不够会自行合成。",
    path_cn="每日任务/极北/极北村庄/仙宝炼化",
)
def lianqishi_destroy():
    ensure_in("炼器师")
    res = extract_info(B(1000,430,130,42), lambda x: x)
    cur, limit = int(res.split("/")[0]), int(res.split("/")[1][:-1])
    click(T("+", box=Box(259,374,101,112).margin()))
    if ui_T(T("没有可以选择的仙器法宝", box=Box(393,336,494,45).margin()), timeout=2):
        make_more_for_destroy((limit-cur)*2)
    else:
        wait_for_appear(T("选择仙器法宝"))
    while cur < limit:
        item_box = locate((I("A"), I("B")), timeout=2)
        if item_box:
            destroy_item(item_box)
            cur += 1
        else:
            make_more_for_destroy((limit-cur)*2)
    click(B(890,50,30,30))

