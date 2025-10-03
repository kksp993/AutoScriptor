import traceback
from ZmxyOL.task.task_register import register_task
from ZmxyOL import *
from AutoScriptor import *
from logzero import logger

@register_task
def daily_qianghua_task():
    ensure_in("村庄")
    if ui_T(T("仙盟",box=Box(16,30,924,400)), 3):
        click(B(40,40,60,60))
        sleep(4)
    click(B(0,0),until=lambda:ui_T(T("云中子")))
    click(T("云中子"), offset=(0,60))
    click(T("进阶"),repeat=2)
    click(T(key="炼丹炉-进阶"))
    while ui_F(I("法宝-戮仙剑")):
        click(I("炼丹炉-进阶-右"))
        sleep(1)
    swipe(I("法宝-戮仙剑"),I("炼丹炉-进阶-添加装备"),duration_s=1)
    sleep(1)
    click(I("炼丹炉-批量进阶"))
    sleep(0.5)
    click(I("炼丹炉-选择全部"))
    sleep(0.5)
    click(T("确定进阶"))
    sleep(1)
    click(T("确定",color="绿色"))
    while ui_F(I("炼丹炉-启灵-添加装备")):
        click(T(key="炼丹炉-启灵"))
    click(B(1200,30,30,30))
    click(I("菜单"))


if __name__ == "__main__":
    try:
        daily_qianghua_task()
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)