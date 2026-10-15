from ZmxyOL.nav.api import locate_region
from ZmxyOL.nav.envs.decorators import HAS_SHEZHI
from ZmxyOL import *
from AutoScriptor import *
from ZmxyOL.character.hero import h


@register_task(
    description="完成本命空间每日流程，领取任务奖励，合成本命法宝。",
    reschedule="daily",
)
def task(clear_all=False, lianbao=False):
    ensure_in(HAS_SHEZHI)
    while ui_F(T("仙盟",box=Box(16,30,924,400)), 3):
        click(I("导航-按钮收缩"))
        sleep(4)
    # 搜索区必须够高：仙盟面板展开时图标会多出一整行，把「本命空间」那行挤到 y≈426，
    # 而原来的 Box(25,15,882,328) 只覆盖到 y≈363，正好差几十像素，于是永远找不到。
    # 2026-10-02 的失败帧里 OCR 其实读到了它（合并成「本命空间穆王西行灵兽商店」），
    # 只是落在搜索区外；按字符等比例切分后点击点落在标签正中，不必绕开粘连。
    click(T("本命空间", box=Box(25,15,882,480).margin()))
    wait_for_appear(T("升级"))
    click(T("空间任务"))
    click(B(860,250,60,60),repeat=3)
    click(B(300,100))
    if clear_all and (tgt:=locate(T("一键完成",box=Box(579,591,136,55),color="绿色"), timeout=3)):
        click(B(*tgt))
        sleep(2)
        click(T("确定"), until=lambda: ui_F(T("确定")))
        sleep(1)
    click(B(1200,30,30,30))
    if lianbao:
        click(T("本命法宝"))
        tgt = wait_for_appear(T("炼宝", box=Box(580,610,130,85)))
        click(B(795,545,30,30))
        click(B(*tgt))
        sleep(2)
        click(T("确定"), if_exist=True)
    # TODO: 这里有概率 T("空间任务") 检测不到，看看跳到哪个界面了优化下
    click(B(50,30,30,30),until=lambda: ui_T(T("空间任务")))
    click(T("回家"))
    locate_region()
